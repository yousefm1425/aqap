-- ترحيل قاعدة قائمة (أُنشئت قبل وحدة الشواهد الداعمة للمحاضر). آمن للتكرار.
-- psql "$AQAP_DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/001_minutes_attachments.sql
BEGIN;
SET search_path = aqap, public;
-- الشواهد والتقارير الداعمة للمحضر: من بنك شواهد القسم نفسه، وتُربط بالمتطلب مع المحضر عند اعتماده.
-- تُضاف في المسودة أو بعد الإعادة أو بعد الاعتماد (شواهد المتابعة)، ولا تُضاف والمحضر بانتظار قرار رئيس القسم.
-- وتُزال في المسودة أو بعد الإعادة فقط؛ الإزالة تفك الربط بالمحضر ولا تحذف الشاهد من البنك.
CREATE TABLE IF NOT EXISTS minutes_attachment (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  minutes_id   bigint NOT NULL REFERENCES minutes(id) ON DELETE CASCADE,
  evidence_id  bigint NOT NULL REFERENCES evidence(id),
  note         text,
  added_by     bigint REFERENCES app_user(id),
  added_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (minutes_id, evidence_id)
);
CREATE INDEX IF NOT EXISTS ix_minutes_attachment_ev ON minutes_attachment (evidence_id);

CREATE OR REPLACE FUNCTION trg_minutes_attachment_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  v_sys  boolean := COALESCE(current_setting('aqap.system_op', true), '') = 'on';
  m      minutes%ROWTYPE;
  v_dept bigint; v_inst bigint; v_conf smallint; v_cinst bigint;
BEGIN
  IF TG_OP = 'UPDATE' THEN RAISE EXCEPTION 'الشاهد الداعم يُضاف أو يُزال فقط'; END IF;
  IF TG_OP = 'DELETE' THEN
    SELECT * INTO m FROM minutes WHERE id = OLD.minutes_id;     -- حذف مسودة المحضر يمر بالتتابع (لا صف)
    IF FOUND AND NOT v_sys AND m.status NOT IN ('draft','returned') THEN
      RAISE EXCEPTION 'تُزال الشواهد الداعمة في المسودة أو بعد إعادة المحضر فقط';
    END IF;
    RETURN OLD;
  END IF;
  SELECT * INTO m FROM minutes WHERE id = NEW.minutes_id;
  IF m.status = 'submitted' AND NOT v_sys THEN
    RAISE EXCEPTION 'المحضر بانتظار قرار رئيس القسم؛ أضف الشواهد بعد الاعتماد أو الإعادة';
  END IF;
  SELECT department_id, institution_id, confidentiality INTO v_dept, v_inst, v_conf FROM evidence WHERE id = NEW.evidence_id;
  SELECT institution_id INTO v_cinst FROM assessment_cycle WHERE id = m.cycle_id;
  IF v_inst IS DISTINCT FROM v_cinst OR v_dept IS DISTINCT FROM m.department_id THEN
    RAISE EXCEPTION 'الشاهد الداعم يجب أن يكون من بنك شواهد القسم نفسه';
  END IF;
  IF v_conf = 3 THEN RAISE EXCEPTION 'الشواهد السرية لا تُرفق بالمحاضر'; END IF;
  NEW.added_by := COALESCE(current_actor(), NEW.added_by);
  NEW.added_at := now();
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS t_minutes_attachment_guard ON minutes_attachment;
CREATE TRIGGER t_minutes_attachment_guard BEFORE INSERT OR UPDATE OR DELETE ON minutes_attachment
  FOR EACH ROW EXECUTE FUNCTION trg_minutes_attachment_guard();
DROP TRIGGER IF EXISTS t_audit_minutes_attachment ON minutes_attachment;
CREATE TRIGGER t_audit_minutes_attachment AFTER INSERT OR DELETE ON minutes_attachment
  FOR EACH ROW EXECUTE FUNCTION trg_audit();
COMMIT;
