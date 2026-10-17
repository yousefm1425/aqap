-- ترحيل قاعدة قائمة: محرّك النماذج الإلكترونية (الخطط والتقارير). آمن للتكرار.
BEGIN;
SET search_path = aqap, public;
-- ---------------------------------------------------------------------
-- النماذج الإلكترونية (الخطط والتقارير): محرّك موحّد تعرّفه قوالب JSON لكل متطلب
--   بيانات التخطيط (plan_data) تُعدّل في المسودة أو بعد الإعادة فقط؛
--   وبيانات المتابعة (follow_data: المتحقق وحالة التنفيذ والمعوقات وخطط التحسين) تبقى مفتوحة
--   بعد الاعتماد طوال الدورة، ولا تُعدّل والنموذج بانتظار قرار رئيس القسم أو بعد إغلاق الدورة.
-- ---------------------------------------------------------------------
DO $$ BEGIN CREATE TYPE form_status_t AS ENUM ('draft','submitted','returned','approved'); EXCEPTION WHEN duplicate_object THEN NULL; END $$;   -- مسودة/مرفوع/معاد/معتمد

CREATE TABLE IF NOT EXISTS form_template (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  framework_code    text NOT NULL,
  requirement_code  text NOT NULL,
  kind              text NOT NULL CHECK (kind IN ('plan','report')),
  title_ar          text NOT NULL,
  schema            jsonb NOT NULL,                 -- الأقسام والجداول والأعمدة والصيغ (تعرّفها طبقة التطبيق)
  guidance_ar       text,
  is_provisional    boolean NOT NULL DEFAULT false, -- نموذج مبدئي بانتظار النموذج الرسمي
  sort_order        int NOT NULL DEFAULT 0,
  version           int NOT NULL DEFAULT 1,
  updated_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (framework_code, requirement_code)
);

CREATE TABLE IF NOT EXISTS form_record (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id       bigint NOT NULL REFERENCES assessment_cycle(id),
  department_id  bigint NOT NULL REFERENCES department(id),
  template_id    bigint NOT NULL REFERENCES form_template(id),
  plan_data      jsonb NOT NULL DEFAULT '{}',
  follow_data    jsonb NOT NULL DEFAULT '{}',
  summary        jsonb NOT NULL DEFAULT '{}',       -- مؤشرات محسوبة للقوائم واللوحات
  status         form_status_t NOT NULL DEFAULT 'draft',
  return_reason  text,
  submitted_by   bigint REFERENCES app_user(id),
  submitted_at   timestamptz,
  approved_by    bigint REFERENCES app_user(id),
  approved_at    timestamptz,
  evidence_id    bigint REFERENCES evidence(id),    -- النسخة المؤرشفة (PDF)
  created_by     bigint REFERENCES app_user(id),
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (cycle_id, department_id, template_id)     -- نموذج واحد لكل قسم في الدورة
);

CREATE TABLE IF NOT EXISTS form_transition (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  form_id     bigint NOT NULL REFERENCES form_record(id) ON DELETE CASCADE,
  from_status form_status_t NOT NULL,
  to_status   form_status_t NOT NULL,
  actor_id    bigint NOT NULL REFERENCES app_user(id),
  comment     text,
  at          timestamptz NOT NULL DEFAULT now()
);

DROP TRIGGER IF EXISTS t_upd_form ON form_record;
CREATE TRIGGER t_upd_form BEFORE UPDATE ON form_record FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS t_audit_form ON form_record;
CREATE TRIGGER t_audit_form AFTER INSERT OR UPDATE OR DELETE ON form_record FOR EACH ROW EXECUTE FUNCTION trg_audit();

CREATE OR REPLACE FUNCTION trg_form_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  v_sys   boolean := COALESCE(current_setting('aqap.system_op', true), '') = 'on';
  v_cycle cycle_status_t;
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NOT v_sys THEN NEW.status := 'draft'; END IF;
    NEW.created_by := COALESCE(NEW.created_by, current_actor());
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' AND NOT v_sys THEN RAISE EXCEPTION 'يُحذف النموذج في حالة المسودة فقط'; END IF;
    RETURN OLD;
  END IF;
  IF v_sys THEN RETURN NEW; END IF;
  IF NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'تغيير حالة النموذج يتم عبر aqap.transition_form فقط';
  END IF;
  IF (NEW.cycle_id, NEW.department_id, NEW.template_id) IS DISTINCT FROM (OLD.cycle_id, OLD.department_id, OLD.template_id) THEN
    RAISE EXCEPTION 'لا يُغيَّر قسم النموذج أو دورته أو قالبه';
  END IF;
  IF (NEW.approved_by, NEW.approved_at, NEW.submitted_by, NEW.submitted_at, NEW.evidence_id, NEW.return_reason)
     IS DISTINCT FROM (OLD.approved_by, OLD.approved_at, OLD.submitted_by, OLD.submitted_at, OLD.evidence_id, OLD.return_reason) THEN
    RAISE EXCEPTION 'حقول الاعتماد والأرشفة تُسجَّل عبر مسار النموذج فقط';
  END IF;
  IF (NEW.plan_data, NEW.follow_data) IS DISTINCT FROM (OLD.plan_data, OLD.follow_data) THEN
    SELECT status INTO v_cycle FROM assessment_cycle WHERE id = OLD.cycle_id;
    IF v_cycle IN ('closed','archived') THEN RAISE EXCEPTION 'الدورة مغلقة؛ لا يُعدّل النموذج'; END IF;
    IF OLD.status = 'submitted' THEN
      RAISE EXCEPTION 'النموذج بانتظار قرار رئيس القسم؛ يُعدّل بعد الاعتماد أو الإعادة';
    END IF;
  END IF;
  IF NEW.plan_data IS DISTINCT FROM OLD.plan_data AND OLD.status NOT IN ('draft','returned') THEN
    RAISE EXCEPTION 'بيانات التخطيط تُعدّل في المسودة أو بعد الإعادة فقط؛ بعد الاعتماد تُحدَّث المتابعة فقط';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS t_form_guard ON form_record;
CREATE TRIGGER t_form_guard BEFORE INSERT OR UPDATE OR DELETE ON form_record
  FOR EACH ROW EXECUTE FUNCTION trg_form_guard();

-- اكتمال المحتوى يُتحقق منه في طبقة التطبيق (حسب قالب النموذج) قبل استدعاء الرفع
CREATE OR REPLACE FUNCTION transition_form(p_id bigint, p_to form_status_t, p_actor bigint, p_comment text DEFAULT NULL)
RETURNS form_status_t LANGUAGE plpgsql AS $$
DECLARE
  f form_record%ROWTYPE;
  v_comment text := NULLIF(btrim(COALESCE(p_comment, '')), '');
  v_cycle cycle_status_t;
BEGIN
  SELECT * INTO f FROM form_record WHERE id = p_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'النموذج % غير موجود', p_id; END IF;
  SELECT status INTO v_cycle FROM assessment_cycle WHERE id = f.cycle_id;
  IF v_cycle IN ('closed','archived') THEN RAISE EXCEPTION 'الدورة مغلقة؛ لا يمكن تغيير حالة النموذج'; END IF;

  IF p_to = 'submitted' AND f.status IN ('draft','returned') THEN
    IF NOT (has_role(p_actor,'dept_coordinator',f.department_id,f.cycle_id) OR has_role(p_actor,'faculty',f.department_id,f.cycle_id)
            OR has_role(p_actor,'hod',f.department_id,f.cycle_id)) THEN
      RAISE EXCEPTION 'رفع النموذج من صلاحية منسوبي القسم';
    END IF;
    PERFORM set_config('aqap.system_op', 'on', true);
    UPDATE form_record SET status = p_to, submitted_by = p_actor, submitted_at = now(), return_reason = NULL WHERE id = f.id;
  ELSIF p_to IN ('approved','returned') AND f.status = 'submitted' THEN
    IF NOT (has_role(p_actor,'hod',f.department_id,f.cycle_id) OR has_role(p_actor,'quality_dean',f.department_id,f.cycle_id)) THEN
      RAISE EXCEPTION 'اعتماد النموذج من صلاحية رئيس القسم';
    END IF;
    IF p_to = 'returned' AND v_comment IS NULL THEN RAISE EXCEPTION 'الإعادة تتطلب ذكر السبب'; END IF;
    PERFORM set_config('aqap.system_op', 'on', true);
    IF p_to = 'approved' THEN
      UPDATE form_record SET status = p_to, approved_by = p_actor, approved_at = now() WHERE id = f.id;
    ELSE
      UPDATE form_record SET status = p_to, return_reason = v_comment WHERE id = f.id;
    END IF;
  ELSIF p_to = 'returned' AND f.status = 'approved' THEN
    IF NOT has_role(p_actor,'quality_dean',f.department_id,f.cycle_id) THEN
      RAISE EXCEPTION 'إعادة فتح نموذج معتمد من صلاحية وكيل الجودة';
    END IF;
    IF v_comment IS NULL THEN RAISE EXCEPTION 'إعادة الفتح تتطلب ذكر السبب'; END IF;
    PERFORM set_config('aqap.system_op', 'on', true);
    UPDATE form_record SET status = p_to, return_reason = v_comment, approved_by = NULL, approved_at = NULL WHERE id = f.id;
  ELSE
    RAISE EXCEPTION 'انتقال غير مسموح من % إلى %', f.status, p_to;
  END IF;

  PERFORM set_config('aqap.system_op', 'off', true);
  INSERT INTO form_transition (form_id, from_status, to_status, actor_id, comment) VALUES (f.id, f.status, p_to, p_actor, v_comment);
  RETURN p_to;
END $$;

-- الشواهد الداعمة للنموذج (بنفس قواعد شواهد المحاضر)
CREATE TABLE IF NOT EXISTS form_attachment (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  form_id      bigint NOT NULL REFERENCES form_record(id) ON DELETE CASCADE,
  evidence_id  bigint NOT NULL REFERENCES evidence(id),
  note         text,
  added_by     bigint REFERENCES app_user(id),
  added_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (form_id, evidence_id)
);
CREATE INDEX IF NOT EXISTS ix_form_attachment_ev ON form_attachment (evidence_id);

CREATE OR REPLACE FUNCTION trg_form_attachment_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  v_sys  boolean := COALESCE(current_setting('aqap.system_op', true), '') = 'on';
  f      form_record%ROWTYPE;
  v_dept bigint; v_inst bigint; v_conf smallint; v_cinst bigint;
BEGIN
  IF TG_OP = 'UPDATE' THEN RAISE EXCEPTION 'الشاهد الداعم يُضاف أو يُزال فقط'; END IF;
  IF TG_OP = 'DELETE' THEN
    SELECT * INTO f FROM form_record WHERE id = OLD.form_id;
    IF FOUND AND NOT v_sys AND f.status NOT IN ('draft','returned') THEN
      RAISE EXCEPTION 'تُزال الشواهد الداعمة في المسودة أو بعد إعادة النموذج فقط';
    END IF;
    RETURN OLD;
  END IF;
  SELECT * INTO f FROM form_record WHERE id = NEW.form_id;
  IF f.status = 'submitted' AND NOT v_sys THEN
    RAISE EXCEPTION 'النموذج بانتظار قرار رئيس القسم؛ أضف الشواهد بعد الاعتماد أو الإعادة';
  END IF;
  SELECT department_id, institution_id, confidentiality INTO v_dept, v_inst, v_conf FROM evidence WHERE id = NEW.evidence_id;
  SELECT institution_id INTO v_cinst FROM assessment_cycle WHERE id = f.cycle_id;
  IF v_inst IS DISTINCT FROM v_cinst OR v_dept IS DISTINCT FROM f.department_id THEN
    RAISE EXCEPTION 'الشاهد الداعم يجب أن يكون من بنك شواهد القسم نفسه';
  END IF;
  IF v_conf = 3 THEN RAISE EXCEPTION 'الشواهد السرية لا تُرفق بالنماذج'; END IF;
  NEW.added_by := COALESCE(current_actor(), NEW.added_by);
  NEW.added_at := now();
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS t_form_attachment_guard ON form_attachment;
CREATE TRIGGER t_form_attachment_guard BEFORE INSERT OR UPDATE OR DELETE ON form_attachment
  FOR EACH ROW EXECUTE FUNCTION trg_form_attachment_guard();
DROP TRIGGER IF EXISTS t_audit_form_attachment ON form_attachment;
CREATE TRIGGER t_audit_form_attachment AFTER INSERT OR DELETE ON form_attachment
  FOR EACH ROW EXECUTE FUNCTION trg_audit();
COMMIT;
