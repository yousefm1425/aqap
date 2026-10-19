-- =====================================================================
--  AQAP — منصة إدارة الجودة والاعتماد الأكاديمي
--  مخطط قاعدة البيانات (PostgreSQL 15+)
--  مبني على هيكل "نموذج العمل الشامل لجودة التدريب – المستوى الثاني"
--  ويدعم أطر اعتماد متعددة (TVTC / NCAAA / ISO)
-- =====================================================================
BEGIN;

CREATE SCHEMA IF NOT EXISTS aqap;
SET search_path = aqap, public;

-- ---------------------------------------------------------------------
-- 1) الأنواع المعدّدة
-- ---------------------------------------------------------------------
CREATE TYPE rating_t            AS ENUM ('met','partial','not_met','na');               -- متحقق / جزئي / غير متحقق / لا ينطبق
CREATE TYPE adequacy_t          AS ENUM ('suitable','unsuitable','insufficient');       -- مناسب / غير مناسب / غير كافٍ
-- حكم المقيّم الخارجي على صحة التقييم الذاتي، كما في النموذج الرسمي: منطبق / غير منطبق / غير كافٍ
CREATE TYPE ext_verdict_t       AS ENUM ('conforms','not_conforming','insufficient');
CREATE TYPE cycle_status_t      AS ENUM ('planning','open','external_review','closed','archived');
CREATE TYPE assessment_status_t AS ENUM ('draft','submitted','returned','hod_approved','under_audit','audited','final');
CREATE TYPE role_t              AS ENUM ('system_admin','quality_dean','quality_auditor','hod','dept_coordinator','faculty','external_reviewer');
CREATE TYPE evidence_kind_t     AS ENUM ('file','link','image','form');
CREATE TYPE action_status_t     AS ENUM ('draft','submitted','revision','approved','completed','verified','cancelled');
-- مسودة / مرفوعة للمقيّم / معادة للقسم / معتمدة وقيد التنفيذ / منجزة بانتظار التحقق / مغلقة بعد التحقق / ملغاة
CREATE TYPE req_scope_t         AS ENUM ('department','institution');                  -- متطلب على مستوى القسم أو المنشأة

-- ---------------------------------------------------------------------
-- 2) دوال مساعدة عامة
-- ---------------------------------------------------------------------
CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at := now(); RETURN NEW; END $$;

CREATE FUNCTION current_actor() RETURNS bigint LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('aqap.user_id', true), '')::bigint $$;

-- ---------------------------------------------------------------------
-- 3) الهيكل التنظيمي والمستخدمون
-- ---------------------------------------------------------------------
CREATE TABLE institution (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code        text NOT NULL UNIQUE,
  name_ar     text NOT NULL,
  name_en     text,
  city        text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE department (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  institution_id  bigint NOT NULL REFERENCES institution(id),
  code            text NOT NULL,
  name_ar         text NOT NULL,
  name_en         text,
  is_general_studies boolean NOT NULL DEFAULT false,   -- له قواعد «لا ينطبق» خاصة (متطلبات النجمة الواحدة)
  trainer_count   int CHECK (trainer_count >= 0),
  trainee_count   int CHECK (trainee_count >= 0),
  is_active       boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (institution_id, code)
);

CREATE TABLE app_user (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  institution_id  bigint REFERENCES institution(id),       -- NULL للمقيّم الخارجي
  sso_subject     text UNIQUE,                              -- معرّف الدخول الموحّد
  email           text NOT NULL,
  full_name_ar    text NOT NULL,
  full_name_en    text,
  is_active       boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ux_app_user_email ON app_user (lower(email));

-- ---------------------------------------------------------------------
-- 4) أطر الاعتماد: إطار ← معيار ← معيار فرعي ← متطلب
-- ---------------------------------------------------------------------
CREATE TABLE framework (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  code        text NOT NULL UNIQUE,
  name_ar     text NOT NULL,
  name_en     text,
  issuer      text,
  version     text,
  is_active   boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE standard (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  framework_id  bigint NOT NULL REFERENCES framework(id),
  code          text NOT NULL,
  title_ar      text NOT NULL,
  title_en      text,
  weight        numeric(6,3) NOT NULL DEFAULT 1 CHECK (weight > 0),
  sort_order    int NOT NULL DEFAULT 0,
  UNIQUE (framework_id, code)
);

CREATE TABLE sub_standard (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  standard_id  bigint NOT NULL REFERENCES standard(id),
  code         text NOT NULL,
  title_ar     text NOT NULL,
  title_en     text,
  weight       numeric(6,3) NOT NULL DEFAULT 1 CHECK (weight > 0),
  sort_order   int NOT NULL DEFAULT 0,
  UNIQUE (standard_id, code)
);

CREATE TABLE requirement (
  id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sub_standard_id       bigint NOT NULL REFERENCES sub_standard(id),
  code                  text NOT NULL,
  text_ar               text NOT NULL,
  text_en               text,
  guidance_ar           text,                 -- إرشادات للمقيّم
  expected_evidence_ar  text,                 -- الشواهد المتوقعة
  scope                 req_scope_t NOT NULL DEFAULT 'department',
  weight                numeric(6,3) NOT NULL DEFAULT 1 CHECK (weight > 0),
  evidence_required     boolean NOT NULL DEFAULT true,
  -- متى يُقبل «لا ينطبق»: 0 لا يُقبل، 1 لقسم الدراسات العامة فقط (*)، 2 لأي قسم (**)
  na_scope              smallint NOT NULL DEFAULT 0 CHECK (na_scope BETWEEN 0 AND 2),
  is_active             boolean NOT NULL DEFAULT true,
  sort_order            int NOT NULL DEFAULT 0,
  UNIQUE (sub_standard_id, code)
);

-- قيم التقدير الرقمية (قابلة للتعديل). "لا ينطبق" بلا قيمة = تُستبعد من المقام
CREATE TABLE rating_score (
  rating    rating_t PRIMARY KEY,
  score     numeric(4,3),
  label_ar  text NOT NULL,
  CHECK ((rating = 'na') = (score IS NULL)),
  CHECK (score IS NULL OR score BETWEEN 0 AND 1)
);

-- ---------------------------------------------------------------------
-- 5) دورات التقييم
-- ---------------------------------------------------------------------
CREATE TABLE assessment_cycle (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  institution_id  bigint NOT NULL REFERENCES institution(id),
  framework_id    bigint NOT NULL REFERENCES framework(id),
  title_ar        text NOT NULL,
  academic_year   text NOT NULL,                 -- مثال: 1447
  starts_on       date NOT NULL,
  ends_on         date NOT NULL,
  status          cycle_status_t NOT NULL DEFAULT 'planning',
  closed_at       timestamptz,
  closed_by       bigint REFERENCES app_user(id),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (ends_on >= starts_on),
  UNIQUE (institution_id, framework_id, academic_year)
);

CREATE TABLE cycle_department (
  cycle_id       bigint NOT NULL REFERENCES assessment_cycle(id) ON DELETE CASCADE,
  department_id  bigint NOT NULL REFERENCES department(id),
  PRIMARY KEY (cycle_id, department_id)
);

-- الأدوار: نطاق القسم اختياري (NULL = كل الأقسام)، ونطاق الدورة اختياري
CREATE TABLE user_role (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id        bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  role           role_t NOT NULL,
  department_id  bigint REFERENCES department(id),
  cycle_id       bigint REFERENCES assessment_cycle(id),
  valid_from     date NOT NULL DEFAULT current_date,
  valid_to       date,
  CHECK (valid_to IS NULL OR valid_to >= valid_from),
  CHECK (role NOT IN ('hod','dept_coordinator','faculty') OR department_id IS NOT NULL),
  CHECK (role <> 'external_reviewer' OR (valid_to IS NOT NULL AND cycle_id IS NOT NULL))
);
CREATE UNIQUE INDEX ux_user_role ON user_role (user_id, role, COALESCE(department_id,0), COALESCE(cycle_id,0));

-- ---------------------------------------------------------------------
-- 6) التقديرات (قلب النظام): قسم × متطلب × دورة
-- ---------------------------------------------------------------------
CREATE TABLE assessment (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id            bigint NOT NULL REFERENCES assessment_cycle(id),
  department_id       bigint REFERENCES department(id),    -- NULL لمتطلبات المنشأة
  requirement_id      bigint NOT NULL REFERENCES requirement(id),
  -- التقييم الذاتي
  self_rating         rating_t,
  self_adequacy       adequacy_t,
  self_notes          text,
  self_by             bigint REFERENCES app_user(id),
  self_at             timestamptz,
  -- التقييم الخارجي / التدقيق
  ext_verdict         ext_verdict_t,
  ext_recommendation  text,
  ext_by              bigint REFERENCES app_user(id),
  ext_at              timestamptz,
  -- سير العمل
  status              assessment_status_t NOT NULL DEFAULT 'draft',
  assigned_to         bigint REFERENCES app_user(id),
  due_date            date,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (cycle_id, department_id, requirement_id)
);
CREATE INDEX ix_assessment_cycle_dept ON assessment (cycle_id, department_id);
CREATE INDEX ix_assessment_status     ON assessment (status);

-- ---------------------------------------------------------------------
-- 7) بنك الشواهد: شاهد واحد يُربط بعدة متطلبات، مع نسخ غير قابلة للتعديل
-- ---------------------------------------------------------------------
CREATE TABLE evidence (
  id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  institution_id       bigint NOT NULL REFERENCES institution(id),
  department_id        bigint REFERENCES department(id),
  title_ar             text NOT NULL,
  description_ar       text,
  kind                 evidence_kind_t NOT NULL,
  url                  text,
  current_version_no   int,
  confidentiality      smallint NOT NULL DEFAULT 1 CHECK (confidentiality BETWEEN 1 AND 3), -- 1 عام، 2 داخلي، 3 سري
  is_archived          boolean NOT NULL DEFAULT false,
  created_by           bigint REFERENCES app_user(id),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  CHECK (kind <> 'link' OR url IS NOT NULL)
);
CREATE INDEX ix_evidence_dept ON evidence (department_id);

CREATE TABLE evidence_version (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  evidence_id  bigint NOT NULL REFERENCES evidence(id) ON DELETE RESTRICT,
  version_no   int NOT NULL,
  storage_key  text NOT NULL,              -- مفتاح الكائن في MinIO
  file_name    text,
  mime_type    text,
  size_bytes   bigint CHECK (size_bytes >= 0),
  sha256       char(64),
  change_note  text,
  uploaded_by  bigint REFERENCES app_user(id),
  uploaded_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (evidence_id, version_no)
);

CREATE TABLE assessment_evidence (
  assessment_id      bigint NOT NULL REFERENCES assessment(id) ON DELETE CASCADE,
  evidence_id        bigint NOT NULL REFERENCES evidence(id),
  pinned_version_no  int,                  -- يُثبَّت تلقائياً عند إغلاق الدورة
  note               text,
  linked_by          bigint REFERENCES app_user(id),
  linked_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (assessment_id, evidence_id)
);
CREATE INDEX ix_ae_evidence ON assessment_evidence (evidence_id);

-- ---------------------------------------------------------------------
-- 8) اللجان والاجتماعات
-- ---------------------------------------------------------------------
CREATE TABLE committee (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  institution_id  bigint NOT NULL REFERENCES institution(id),
  department_id   bigint REFERENCES department(id),
  name_ar         text NOT NULL,
  mandate_ar      text,
  formed_on       date,
  dissolved_on    date,
  is_active       boolean NOT NULL DEFAULT true
);

CREATE TABLE committee_member (
  committee_id  bigint NOT NULL REFERENCES committee(id) ON DELETE CASCADE,
  user_id       bigint NOT NULL REFERENCES app_user(id),
  member_role   text NOT NULL DEFAULT 'member' CHECK (member_role IN ('chair','secretary','member')),
  PRIMARY KEY (committee_id, user_id)
);

CREATE TABLE meeting (
  id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  committee_id          bigint NOT NULL REFERENCES committee(id),
  held_on               date NOT NULL,
  location              text,
  decisions_ar          text,
  minutes_evidence_id   bigint REFERENCES evidence(id)   -- المحضر يُحفظ كشاهد
);

-- ---------------------------------------------------------------------
-- 9) خطط التحسين
-- ---------------------------------------------------------------------
CREATE TABLE improvement_action (
  id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id                bigint NOT NULL REFERENCES assessment_cycle(id),
  assessment_id           bigint REFERENCES assessment(id),
  department_id           bigint REFERENCES department(id),
  source                  text NOT NULL DEFAULT 'auto'
                          CHECK (source IN ('auto','self_assessment','external_review','internal_audit','kpi','other')),
  title_ar                text NOT NULL,
  -- يعبّئه القسم (أعمدة النموذج: الإجراءات التحسينية، المسؤول عن التنفيذ، تاريخ اكتمال التنفيذ)
  action_ar               text,
  owner_id                bigint REFERENCES app_user(id),
  owner_label             text,
  priority                smallint NOT NULL DEFAULT 2 CHECK (priority BETWEEN 1 AND 3),
  due_date                date,
  -- يحكم عليه المقيّم (عمود: ملائمة الإجراءات، ملاحظات)
  adequacy                adequacy_t,
  adequacy_by             bigint REFERENCES app_user(id),
  adequacy_at             timestamptz,
  reviewer_notes          text,
  -- التنفيذ والإغلاق (عمود: شواهد التحسين)
  status                  action_status_t NOT NULL DEFAULT 'draft',
  progress_pct            smallint NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
  completion_evidence_id  bigint REFERENCES evidence(id),
  completed_on            date,
  completed_by            bigint REFERENCES app_user(id),
  verified_by             bigint REFERENCES app_user(id),
  verified_at             timestamptz,
  verification_note       text,
  created_by              bigint REFERENCES app_user(id),
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now(),
  CHECK (status NOT IN ('approved','completed','verified') OR adequacy = 'suitable'),
  CHECK (status NOT IN ('completed','verified')
         OR (completion_evidence_id IS NOT NULL AND completed_on IS NOT NULL AND progress_pct = 100)),
  CHECK (status <> 'verified' OR verified_by IS NOT NULL)
);
CREATE UNIQUE INDEX ux_action_auto ON improvement_action (assessment_id) WHERE source = 'auto';
CREATE INDEX ix_action_cycle_dept ON improvement_action (cycle_id, department_id);
CREATE INDEX ix_action_owner_status ON improvement_action (owner_id, status);

-- ---------------------------------------------------------------------
-- 10) سير العمل وسجل التدقيق
-- ---------------------------------------------------------------------
CREATE TABLE workflow_rule (
  from_status  assessment_status_t NOT NULL,
  to_status    assessment_status_t NOT NULL,
  role         role_t NOT NULL,
  PRIMARY KEY (from_status, to_status, role)
);

CREATE TABLE assessment_transition (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  assessment_id  bigint NOT NULL REFERENCES assessment(id) ON DELETE CASCADE,
  from_status    assessment_status_t NOT NULL,
  to_status      assessment_status_t NOT NULL,
  actor_id       bigint NOT NULL REFERENCES app_user(id),
  comment        text,
  at             timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_transition_assessment ON assessment_transition (assessment_id);

CREATE TABLE audit_log (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  table_name  text NOT NULL,
  row_key     text,
  action      text NOT NULL,
  old_data    jsonb,
  new_data    jsonb,
  actor_id    bigint,
  at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_audit_table_row ON audit_log (table_name, row_key);

-- ---------------------------------------------------------------------
-- 11) المشغّلات (Triggers)
-- ---------------------------------------------------------------------
-- updated_at
CREATE TRIGGER t_upd_institution BEFORE UPDATE ON institution        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER t_upd_department  BEFORE UPDATE ON department         FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER t_upd_app_user    BEFORE UPDATE ON app_user           FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER t_upd_cycle       BEFORE UPDATE ON assessment_cycle   FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER t_upd_assessment  BEFORE UPDATE ON assessment         FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER t_upd_evidence    BEFORE UPDATE ON evidence           FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER t_upd_action      BEFORE UPDATE ON improvement_action FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- قواعد النموذج الرسمي (أعمدة Y و R في ورقة المنهجية)
CREATE FUNCTION na_allowed(p_requirement bigint, p_department bigint) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT CASE r.na_scope WHEN 2 THEN true
                         WHEN 1 THEN COALESCE((SELECT d.is_general_studies FROM department d WHERE d.id = p_department), false)
                         ELSE false END
    FROM requirement r WHERE r.id = p_requirement
$$;

-- ---------------------------------------------------------------------
-- نطاق انطباق المتطلبات على القسم: متطلب خارج اختصاص القسم (مثل الإرشاد أو المشروع لقسم الدراسات العامة)
-- يقرره وكيل الجودة بمسوّغ موثّق؛ يُستبعد من التقديرات والمؤشرات والنماذج وخطط التحسين.
-- القرار دائم للقسم، ولا يغيّر نتائج دورة مغلقة (يُحتسب بحسب وقت الإغلاق).
-- ---------------------------------------------------------------------
CREATE TABLE requirement_exclusion (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  department_id      bigint NOT NULL REFERENCES department(id),
  requirement_id     bigint NOT NULL REFERENCES requirement(id),
  reason_ar          text NOT NULL CHECK (length(btrim(reason_ar)) >= 5),
  within_model_rule  boolean NOT NULL,           -- يسمح به شرط النجمة في النموذج الرسمي؟
  decided_by         bigint REFERENCES app_user(id),
  decided_at         timestamptz NOT NULL DEFAULT clock_timestamp(),
  revoked_at         timestamptz,
  revoked_by         bigint REFERENCES app_user(id),
  CHECK (revoked_at IS NULL OR revoked_at >= decided_at)
);
CREATE UNIQUE INDEX ux_requirement_exclusion_active ON requirement_exclusion (department_id, requirement_id) WHERE revoked_at IS NULL;

CREATE FUNCTION is_excluded(p_requirement bigint, p_department bigint, p_cycle bigint) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT p_department IS NOT NULL AND EXISTS (
    SELECT 1 FROM requirement_exclusion e, assessment_cycle c
     WHERE c.id = p_cycle AND e.department_id = p_department AND e.requirement_id = p_requirement
       AND e.decided_at <= COALESCE(c.closed_at, 'infinity')
       AND (e.revoked_at IS NULL OR e.revoked_at > COALESCE(c.closed_at, 'infinity')))
$$;

-- التقدير الفعلي: الذاتي ما لم يحكم المقيّم بعدم الانطباق؛ «لا ينطبق» بلا شرط يُعد «غير متحقق»
CREATE FUNCTION effective_rating(p_self rating_t, p_verdict ext_verdict_t, p_na_ok boolean) RETURNS rating_t
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN p_self IS NULL THEN NULL
              WHEN p_verdict = 'not_conforming' THEN 'not_met'::rating_t
              WHEN p_verdict = 'insufficient' THEN 'partial'::rating_t
              WHEN p_self = 'na' AND NOT p_na_ok THEN 'not_met'::rating_t
              ELSE p_self END
$$;

-- حماية التقديرات: الدورة المغلقة مجمّدة، والحالة لا تتغير إلا عبر دالة الانتقال،
-- والتقييم الذاتي يُعدّل في (مسودة/معاد) فقط، والخارجي أثناء التدقيق فقط
CREATE FUNCTION trg_assessment_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  v_cycle_id bigint;
  v_cstatus  cycle_status_t;
  v_sys      boolean := COALESCE(current_setting('aqap.system_op', true), '') = 'on';
BEGIN
  v_cycle_id := CASE WHEN TG_OP = 'DELETE' THEN OLD.cycle_id ELSE NEW.cycle_id END;
  SELECT status INTO v_cstatus FROM assessment_cycle WHERE id = v_cycle_id;

  IF v_cstatus IN ('closed','archived') THEN
    RAISE EXCEPTION 'الدورة % مغلقة؛ لا يمكن تعديل التقديرات', v_cycle_id;
  END IF;

  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  IF TG_OP = 'INSERT' THEN NEW.status := 'draft'; RETURN NEW; END IF;

  IF NEW.status IS DISTINCT FROM OLD.status AND NOT v_sys THEN
    RAISE EXCEPTION 'تغيير حالة التقدير يتم عبر aqap.transition_assessment فقط';
  END IF;

  IF (NEW.self_rating, NEW.self_adequacy, NEW.self_notes)
     IS DISTINCT FROM (OLD.self_rating, OLD.self_adequacy, OLD.self_notes) THEN
    IF OLD.status NOT IN ('draft','returned') AND NOT v_sys THEN
      RAISE EXCEPTION 'التقييم الذاتي يُعدّل فقط في حالة المسودة أو المعاد';
    END IF;
    IF NEW.self_rating = 'na' AND NOT v_sys AND NOT na_allowed(NEW.requirement_id, NEW.department_id) THEN
      RAISE EXCEPTION '«لا ينطبق» غير مقبول لهذا المتطلب في هذا القسم وفق النموذج؛ قيّمه بمستوى تحققه الفعلي';
    END IF;
    NEW.self_by := COALESCE(current_actor(), NEW.self_by);
    NEW.self_at := now();
  END IF;

  IF (NEW.ext_verdict, NEW.ext_recommendation)
     IS DISTINCT FROM (OLD.ext_verdict, OLD.ext_recommendation) THEN
    IF OLD.status <> 'under_audit' AND NOT v_sys THEN
      RAISE EXCEPTION 'التقييم الخارجي يُدخل فقط أثناء مرحلة التدقيق';
    END IF;
    NEW.ext_by := COALESCE(current_actor(), NEW.ext_by);
    NEW.ext_at := now();
  END IF;

  RETURN NEW;
END $$;
CREATE TRIGGER t_assessment_guard BEFORE INSERT OR UPDATE OR DELETE ON assessment
  FOR EACH ROW EXECUTE FUNCTION trg_assessment_guard();

-- ربط الشواهد مسموح فقط عندما يكون التقدير في مسودة/معاد والدورة مفتوحة
CREATE FUNCTION trg_assessment_evidence_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  v_aid     bigint := CASE WHEN TG_OP = 'DELETE' THEN OLD.assessment_id ELSE NEW.assessment_id END;
  v_astatus assessment_status_t;
  v_cstatus cycle_status_t;
BEGIN
  IF COALESCE(current_setting('aqap.system_op', true), '') = 'on' THEN
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
  END IF;
  SELECT a.status, c.status INTO v_astatus, v_cstatus
    FROM assessment a JOIN assessment_cycle c ON c.id = a.cycle_id WHERE a.id = v_aid;
  IF v_cstatus IN ('closed','archived') THEN
    RAISE EXCEPTION 'الدورة مغلقة؛ لا يمكن تعديل ربط الشواهد';
  END IF;
  IF v_astatus NOT IN ('draft','returned') THEN
    RAISE EXCEPTION 'لا يمكن تعديل الشواهد بعد رفع التقدير (الحالة: %)', v_astatus;
  END IF;
  IF TG_OP = 'INSERT' THEN NEW.linked_by := COALESCE(NEW.linked_by, current_actor()); END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END $$;
CREATE TRIGGER t_ae_guard BEFORE INSERT OR UPDATE OR DELETE ON assessment_evidence
  FOR EACH ROW EXECUTE FUNCTION trg_assessment_evidence_guard();

-- ترقيم النسخ تلقائياً، ومنع تعديل أو حذف أي نسخة
CREATE FUNCTION trg_evidence_version_before() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'نسخ الشواهد غير قابلة للتعديل أو الحذف؛ ارفع نسخة جديدة';
  END IF;
  PERFORM 1 FROM evidence WHERE id = NEW.evidence_id FOR UPDATE;
  SELECT COALESCE(max(version_no), 0) + 1 INTO NEW.version_no
    FROM evidence_version WHERE evidence_id = NEW.evidence_id;
  NEW.uploaded_by := COALESCE(NEW.uploaded_by, current_actor());
  RETURN NEW;
END $$;
CREATE TRIGGER t_ev_before BEFORE INSERT OR UPDATE OR DELETE ON evidence_version
  FOR EACH ROW EXECUTE FUNCTION trg_evidence_version_before();

CREATE FUNCTION trg_evidence_version_after() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  UPDATE evidence SET current_version_no = NEW.version_no WHERE id = NEW.evidence_id;
  RETURN NULL;
END $$;
CREATE TRIGGER t_ev_after AFTER INSERT ON evidence_version
  FOR EACH ROW EXECUTE FUNCTION trg_evidence_version_after();

-- سجل تدقيق عام
CREATE FUNCTION trg_audit() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_old jsonb; v_new jsonb; v_row jsonb;
BEGIN
  IF TG_OP <> 'INSERT' THEN v_old := to_jsonb(OLD); END IF;
  IF TG_OP <> 'DELETE' THEN v_new := to_jsonb(NEW); END IF;
  v_row := COALESCE(v_new, v_old);
  INSERT INTO audit_log (table_name, row_key, action, old_data, new_data, actor_id)
  VALUES (TG_TABLE_NAME,
          COALESCE(v_row->>'id', (v_row->>'assessment_id') || ':' || (v_row->>'evidence_id')),
          TG_OP, v_old, v_new, current_actor());
  RETURN NULL;
END $$;
CREATE TRIGGER t_audit_assessment AFTER INSERT OR UPDATE OR DELETE ON assessment          FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER t_audit_ae         AFTER INSERT OR UPDATE OR DELETE ON assessment_evidence FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER t_audit_evidence   AFTER INSERT OR UPDATE OR DELETE ON evidence            FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER t_audit_action     AFTER INSERT OR UPDATE OR DELETE ON improvement_action  FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER t_audit_user_role  AFTER INSERT OR UPDATE OR DELETE ON user_role           FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER t_audit_cycle      AFTER INSERT OR UPDATE OR DELETE ON assessment_cycle    FOR EACH ROW EXECUTE FUNCTION trg_audit();

-- ---------------------------------------------------------------------
-- 12) الإجراءات (Functions)
-- ---------------------------------------------------------------------
-- هل يملك المستخدم دوراً فعّالاً ضمن النطاق؟
CREATE FUNCTION has_role(p_user bigint, p_role role_t, p_dept bigint, p_cycle bigint)
RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT EXISTS (
    SELECT 1 FROM user_role ur
    WHERE ur.user_id = p_user AND ur.role = p_role
      AND (ur.department_id IS NULL OR ur.department_id = p_dept)
      AND (ur.cycle_id IS NULL OR ur.cycle_id = p_cycle)
      AND current_date BETWEEN ur.valid_from AND COALESCE(ur.valid_to, 'infinity'::date))
$$;

-- توليد سجلات التقدير لدورة: كل قسم مشارك × كل متطلب قسم، + متطلبات المنشأة مرة واحدة
CREATE FUNCTION generate_cycle_assessments(p_cycle_id bigint) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE v_fw bigint; v_n integer;
BEGIN
  SELECT framework_id INTO v_fw FROM assessment_cycle WHERE id = p_cycle_id;
  IF v_fw IS NULL THEN RAISE EXCEPTION 'الدورة % غير موجودة', p_cycle_id; END IF;

  INSERT INTO assessment (cycle_id, department_id, requirement_id)
  SELECT p_cycle_id, cd.department_id, r.id
    FROM cycle_department cd
    CROSS JOIN requirement r
    JOIN sub_standard ss ON ss.id = r.sub_standard_id
    JOIN standard s      ON s.id  = ss.standard_id
   WHERE cd.cycle_id = p_cycle_id AND s.framework_id = v_fw
     AND r.scope = 'department' AND r.is_active
     AND NOT EXISTS (SELECT 1 FROM requirement_exclusion e
                      WHERE e.department_id = cd.department_id AND e.requirement_id = r.id AND e.revoked_at IS NULL)
  UNION ALL
  SELECT p_cycle_id, NULL, r.id
    FROM requirement r
    JOIN sub_standard ss ON ss.id = r.sub_standard_id
    JOIN standard s      ON s.id  = ss.standard_id
   WHERE s.framework_id = v_fw AND r.scope = 'institution' AND r.is_active
  ON CONFLICT DO NOTHING;

  GET DIAGNOSTICS v_n = ROW_COUNT;
  RETURN v_n;
END $$;

-- الانتقال بين حالات سير العمل مع التحقق من الصلاحية والاكتمال
CREATE FUNCTION transition_assessment(p_assessment_id bigint, p_to assessment_status_t,
                                      p_actor bigint, p_comment text DEFAULT NULL)
RETURNS assessment_status_t LANGUAGE plpgsql AS $$
DECLARE
  a        assessment%ROWTYPE;
  v_cstat  cycle_status_t;
  v_evreq  boolean;
BEGIN
  SELECT * INTO a FROM assessment WHERE id = p_assessment_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'التقدير % غير موجود', p_assessment_id; END IF;

  SELECT status INTO v_cstat FROM assessment_cycle WHERE id = a.cycle_id;
  IF v_cstat NOT IN ('open','external_review') THEN
    RAISE EXCEPTION 'الدورة ليست مفتوحة (الحالة: %)', v_cstat;
  END IF;

  IF NOT EXISTS (
       SELECT 1 FROM workflow_rule w
        WHERE w.from_status = a.status AND w.to_status = p_to
          AND has_role(p_actor, w.role, a.department_id, a.cycle_id)) THEN
    RAISE EXCEPTION 'انتقال غير مسموح من % إلى % لهذا المستخدم', a.status, p_to;
  END IF;

  IF p_to = 'submitted' THEN
    IF a.self_rating IS NULL THEN
      RAISE EXCEPTION 'لا يمكن الرفع قبل إدخال التقييم الذاتي';
    END IF;
    SELECT evidence_required INTO v_evreq FROM requirement WHERE id = a.requirement_id;
    IF v_evreq AND a.self_rating <> 'na'
       AND NOT EXISTS (SELECT 1 FROM assessment_evidence WHERE assessment_id = a.id) THEN
      RAISE EXCEPTION 'هذا المتطلب يستلزم ربط شاهد واحد على الأقل';
    END IF;
  ELSIF p_to = 'audited' AND a.ext_verdict IS NULL THEN
    RAISE EXCEPTION 'يجب إدخال حكم التقييم الخارجي قبل إنهاء التدقيق';
  ELSIF p_to = 'returned' AND COALESCE(btrim(p_comment), '') = '' THEN
    RAISE EXCEPTION 'الإعادة تتطلب ذكر السبب';
  END IF;

  PERFORM set_config('aqap.user_id',   p_actor::text, true);
  PERFORM set_config('aqap.system_op', 'on', true);
  UPDATE assessment SET status = p_to WHERE id = a.id;
  PERFORM set_config('aqap.system_op', 'off', true);

  INSERT INTO assessment_transition (assessment_id, from_status, to_status, actor_id, comment)
  VALUES (a.id, a.status, p_to, p_actor, p_comment);

  RETURN p_to;
END $$;

-- إغلاق الدورة: تثبيت نسخ الشواهد المرتبطة ثم التجميد
CREATE FUNCTION close_cycle(p_cycle_id bigint, p_actor bigint) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE v_open integer;
BEGIN
  IF NOT (has_role(p_actor, 'quality_dean', NULL, p_cycle_id)
          OR has_role(p_actor, 'system_admin', NULL, p_cycle_id)) THEN
    RAISE EXCEPTION 'إغلاق الدورة من صلاحية وكيل الجودة فقط';
  END IF;

  SELECT count(*) INTO v_open FROM assessment
   WHERE cycle_id = p_cycle_id AND status <> 'final' AND NOT is_excluded(requirement_id, department_id, cycle_id);
  IF v_open > 0 THEN
    RAISE EXCEPTION 'لا يمكن الإغلاق: % تقديرات لم تصل للحالة النهائية', v_open;
  END IF;

  PERFORM set_config('aqap.user_id',   p_actor::text, true);
  PERFORM set_config('aqap.system_op', 'on', true);
  UPDATE assessment_evidence ae
     SET pinned_version_no = e.current_version_no
    FROM evidence e, assessment a
   WHERE ae.evidence_id = e.id AND ae.assessment_id = a.id
     AND a.cycle_id = p_cycle_id AND ae.pinned_version_no IS NULL;
  PERFORM set_config('aqap.system_op', 'off', true);

  UPDATE assessment_cycle
     SET status = 'closed', closed_at = now(), closed_by = p_actor
   WHERE id = p_cycle_id;
END $$;

-- ---------------------------------------------------------------------
-- 13) قواعد الحساب (Views) — مطابقة لصيغ النموذج الرسمي
--   متحقق (ذاتي)  = ذاتي «متحقق»                               (العمود U)
--   متحقق (خارجي) = ذاتي «متحقق» + حكم «منطبق»                  (العمود V)
--   لا ينطبق مقبول = ذاتي «لا ينطبق» + شرط النجمة [+ «منطبق»]     (W / X)
--   نسبة الاستيفاء = المتحقق ÷ (المتطلبات − لا ينطبق المقبول)     (ورقة القوائم: K ÷ (J − M))
--   يحتاج تحسيناً = جزئي/غير متحقق، أو «لا ينطبق» بلا شرط، أو حكم «غير منطبق/غير كافٍ» (R)
--   القيم في rating_score (متحقق 1، والباقي 0) قابلة للتعديل لأطر أخرى.
-- ---------------------------------------------------------------------
CREATE VIEW v_assessment_scored AS
WITH base AS (
  SELECT a.*, r.code AS requirement_code, r.weight AS requirement_weight, r.evidence_required,
         na_allowed(a.requirement_id, a.department_id) AS na_ok,
         ss.id AS sub_standard_id, ss.code AS sub_standard_code, ss.title_ar AS sub_standard_title,
         s.id AS standard_id, s.code AS standard_code, s.title_ar AS standard_title
    FROM assessment a
    JOIN requirement r   ON r.id  = a.requirement_id
    JOIN sub_standard ss ON ss.id = r.sub_standard_id
    JOIN standard s      ON s.id  = ss.standard_id
   WHERE NOT is_excluded(a.requirement_id, a.department_id, a.cycle_id)
)
SELECT b.id AS assessment_id, b.cycle_id, b.department_id, b.status,
       b.standard_id, b.standard_code, b.standard_title, b.sub_standard_id, b.sub_standard_code, b.sub_standard_title,
       b.requirement_id, b.requirement_code, b.requirement_weight, b.evidence_required, b.na_ok,
       b.self_rating, b.ext_verdict,
       effective_rating(b.self_rating, b.ext_verdict, b.na_ok) AS eff_rating,
       -- NULL = غير مقدّر أو «لا ينطبق» مقبول (يُستبعد من المقام)
       CASE WHEN b.self_rating IS NULL OR (b.self_rating = 'na' AND b.na_ok) THEN NULL
            ELSE COALESCE(rs_self.score, 0) END AS self_score,
       CASE WHEN b.ext_verdict IS NULL OR b.self_rating IS NULL THEN NULL
            WHEN b.ext_verdict = 'conforms' AND b.self_rating = 'na' AND b.na_ok THEN NULL
            WHEN b.ext_verdict = 'conforms' THEN COALESCE(rs_self.score, 0)
            ELSE 0 END AS ext_score,
       CASE WHEN effective_rating(b.self_rating, b.ext_verdict, b.na_ok) IS NULL
              OR effective_rating(b.self_rating, b.ext_verdict, b.na_ok) = 'na' THEN NULL
            ELSE COALESCE(rs_eff.score, 0) END AS eff_score
  FROM base b
  LEFT JOIN rating_score rs_self ON rs_self.rating = b.self_rating
  LEFT JOIN rating_score rs_eff  ON rs_eff.rating  = effective_rating(b.self_rating, b.ext_verdict, b.na_ok);

-- النسبة في كل مستوى = Σ(وزن × قيمة) ÷ Σ(أوزان المقدّر غير المستبعد) مباشرة من المتطلبات، كما يحسبها القالب
CREATE VIEW v_substandard_compliance AS
SELECT cycle_id, department_id, standard_id, standard_code, sub_standard_id, sub_standard_code, sub_standard_title,
       count(*)                                                AS total_requirements,
       count(*) FILTER (WHERE eff_rating = 'met')              AS met_count,
       count(*) FILTER (WHERE eff_rating = 'partial')          AS partial_count,
       count(*) FILTER (WHERE eff_rating = 'not_met')          AS not_met_count,
       count(*) FILTER (WHERE eff_rating = 'na')               AS na_count,
       count(*) FILTER (WHERE eff_rating IS NULL)              AS unrated_count,
       100 * sum(requirement_weight * self_score) / NULLIF(sum(requirement_weight) FILTER (WHERE self_score IS NOT NULL), 0) AS self_pct,
       100 * sum(requirement_weight * ext_score)  / NULLIF(sum(requirement_weight) FILTER (WHERE ext_score  IS NOT NULL), 0) AS ext_pct,
       100 * sum(requirement_weight * eff_score)  / NULLIF(sum(requirement_weight) FILTER (WHERE eff_score  IS NOT NULL), 0) AS eff_pct
  FROM v_assessment_scored
 GROUP BY cycle_id, department_id, standard_id, standard_code, sub_standard_id, sub_standard_code, sub_standard_title;

CREATE VIEW v_standard_compliance AS
SELECT cycle_id, department_id, standard_id, standard_code,
       count(*)                                   AS total_requirements,
       count(*) FILTER (WHERE eff_rating IS NULL) AS unrated_count,
       count(*) FILTER (WHERE ext_verdict IS NULL AND self_rating IS NOT NULL) AS awaiting_external,
       100 * sum(requirement_weight * self_score) / NULLIF(sum(requirement_weight) FILTER (WHERE self_score IS NOT NULL), 0) AS self_pct,
       100 * sum(requirement_weight * ext_score)  / NULLIF(sum(requirement_weight) FILTER (WHERE ext_score  IS NOT NULL), 0) AS ext_pct,
       100 * sum(requirement_weight * eff_score)  / NULLIF(sum(requirement_weight) FILTER (WHERE eff_score  IS NOT NULL), 0) AS eff_pct
  FROM v_assessment_scored
 GROUP BY cycle_id, department_id, standard_id, standard_code;

-- ملخص القسم (يطابق التقرير التقييمي النهائي في النموذج)
CREATE VIEW v_department_compliance AS
SELECT v.cycle_id, v.department_id,
       COALESCE(d.name_ar, 'متطلبات المنشأة') AS department_name,
       round(100 * sum(v.requirement_weight * v.self_score) / NULLIF(sum(v.requirement_weight) FILTER (WHERE v.self_score IS NOT NULL), 0), 1) AS self_pct,
       round(100 * sum(v.requirement_weight * v.ext_score)  / NULLIF(sum(v.requirement_weight) FILTER (WHERE v.ext_score  IS NOT NULL), 0), 1) AS ext_pct,
       round(100 * sum(v.requirement_weight * v.eff_score)  / NULLIF(sum(v.requirement_weight) FILTER (WHERE v.eff_score  IS NOT NULL), 0), 1) AS eff_pct,
       count(*)                                                   AS total_requirements,
       count(*) FILTER (WHERE v.eff_rating = 'met')               AS met_count,
       count(*) FILTER (WHERE v.eff_rating = 'na')                AS na_count,
       count(*) FILTER (WHERE v.eff_rating IN ('partial','not_met')) AS needs_improvement_count,
       count(*) FILTER (WHERE v.eff_rating IS NULL)               AS unrated_count,
       round(100.0 * count(*) FILTER (WHERE v.eff_rating IS NOT NULL) / count(*), 1) AS rating_coverage_pct,
       round(100.0 * count(*) FILTER (WHERE v.status = 'final') / count(*), 1)       AS workflow_completion_pct
  FROM v_assessment_scored v LEFT JOIN department d ON d.id = v.department_id
 GROUP BY v.cycle_id, v.department_id, d.name_ar;

-- مستوى الاجتياز لكل معيار رئيسي (العمود AI في ورقة القوائم):
-- «مجتاز» إذا لم تقل نسبة أي قسم في المعيار عن 89.5% بعد اكتمال التقييم الخارجي
CREATE VIEW v_pass_level AS
SELECT cycle_id, standard_id, standard_code,
       round(min(ext_pct), 1)                       AS lowest_department_pct,
       sum(awaiting_external)                       AS awaiting_external,
       sum(unrated_count)                           AS unrated,
       CASE WHEN sum(awaiting_external) + sum(unrated_count) > 0 THEN NULL
            ELSE bool_and(COALESCE(ext_pct, 0) >= 89.5) END AS passed
  FROM v_standard_compliance
 WHERE department_id IS NOT NULL
 GROUP BY cycle_id, standard_id, standard_code;

-- أفضل وأضعف المعايير الفرعية على مستوى المنشأة
CREATE VIEW v_substandard_ranking AS
WITH agg AS (
  SELECT cycle_id, sub_standard_id, sub_standard_code, sub_standard_title,
         100 * sum(requirement_weight * eff_score) / NULLIF(sum(requirement_weight) FILTER (WHERE eff_score IS NOT NULL), 0) AS eff_pct
    FROM v_assessment_scored
   GROUP BY cycle_id, sub_standard_id, sub_standard_code, sub_standard_title
)
SELECT cycle_id, sub_standard_id, sub_standard_code, sub_standard_title,
       round(eff_pct, 1) AS eff_pct,
       rank() OVER (PARTITION BY cycle_id ORDER BY eff_pct DESC NULLS LAST) AS best_rank,
       rank() OVER (PARTITION BY cycle_id ORDER BY eff_pct ASC  NULLS LAST) AS worst_rank
  FROM agg;

-- أحكام خارجية بعدم الانطباق: حيث لم يصمد التقييم الذاتي أمام المقيّم
CREATE VIEW v_self_external_gap AS
SELECT assessment_id, cycle_id, department_id, requirement_code, sub_standard_code, self_rating, ext_verdict, eff_rating
  FROM v_assessment_scored
 WHERE ext_verdict IN ('not_conforming','insufficient');

-- «لا ينطبق» غير مقبول وفق شرط النجمة
CREATE VIEW v_invalid_na AS
SELECT assessment_id, cycle_id, department_id, requirement_code
  FROM v_assessment_scored WHERE self_rating = 'na' AND NOT na_ok;

-- متطلبات بلا شواهد (عدا «لا ينطبق» المقبول)
CREATE VIEW v_missing_evidence AS
SELECT v.assessment_id, v.cycle_id, v.department_id, v.requirement_code, v.eff_rating, v.status
  FROM v_assessment_scored v
 WHERE v.evidence_required
   AND v.eff_rating IS DISTINCT FROM 'na'
   AND NOT EXISTS (SELECT 1 FROM assessment_evidence ae WHERE ae.assessment_id = v.assessment_id);

CREATE VIEW v_improvement_tracker AS
SELECT ia.*,
       r.code AS requirement_code, r.text_ar AS requirement_text,
       a.ext_recommendation, effective_rating(a.self_rating, a.ext_verdict, na_allowed(a.requirement_id, a.department_id)) AS eff_rating,
       (ia.status IN ('draft','submitted','revision','approved') AND ia.due_date < current_date) AS is_overdue,
       CASE WHEN ia.status IN ('draft','submitted','revision','approved') AND ia.due_date < current_date
            THEN current_date - ia.due_date END AS days_overdue
  FROM improvement_action ia
  LEFT JOIN assessment a  ON a.id = ia.assessment_id
  LEFT JOIN requirement r ON r.id = a.requirement_id;

-- ملخص خطط التحسين لكل قسم: نسبة الإغلاق = المغلقة بعد التحقق ÷ غير الملغاة
CREATE VIEW v_improvement_summary AS
SELECT cycle_id, department_id,
       count(*) FILTER (WHERE status <> 'cancelled')                     AS total,
       count(*) FILTER (WHERE status IN ('draft','revision'))            AS with_department,
       count(*) FILTER (WHERE status = 'submitted')                      AS under_review,
       count(*) FILTER (WHERE status = 'approved')                       AS in_progress,
       count(*) FILTER (WHERE status = 'completed')                      AS awaiting_verification,
       count(*) FILTER (WHERE status = 'verified')                       AS verified,
       count(*) FILTER (WHERE is_overdue)                                AS overdue,
       round(100.0 * count(*) FILTER (WHERE status = 'verified')
             / NULLIF(count(*) FILTER (WHERE status <> 'cancelled'), 0), 1) AS closure_pct
  FROM v_improvement_tracker
 GROUP BY cycle_id, department_id;

-- ---------------------------------------------------------------------
-- 14) الاستيراد من ملف النموذج (xlsb → CSV → staging)
-- ---------------------------------------------------------------------
CREATE TABLE import_requirement_staging (
  standard_code          text NOT NULL,
  standard_title_ar      text NOT NULL,
  standard_order         int,
  sub_standard_code      text NOT NULL,
  sub_standard_title_ar  text NOT NULL,
  sub_standard_order     int,
  requirement_code       text NOT NULL,
  requirement_text_ar    text NOT NULL,
  requirement_order      int,
  scope                  req_scope_t NOT NULL DEFAULT 'department',
  evidence_required      boolean NOT NULL DEFAULT true,
  na_scope               smallint NOT NULL DEFAULT 0
);

CREATE FUNCTION import_framework_from_staging(p_framework_code text) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE v_fw bigint; v_n integer;
BEGIN
  SELECT id INTO v_fw FROM framework WHERE code = p_framework_code;
  IF v_fw IS NULL THEN RAISE EXCEPTION 'الإطار % غير موجود', p_framework_code; END IF;

  INSERT INTO standard (framework_id, code, title_ar, sort_order)
  SELECT DISTINCT ON (standard_code) v_fw, standard_code, standard_title_ar, COALESCE(standard_order, 0)
    FROM import_requirement_staging ORDER BY standard_code
  ON CONFLICT (framework_id, code) DO UPDATE
     SET title_ar = EXCLUDED.title_ar, sort_order = EXCLUDED.sort_order;

  INSERT INTO sub_standard (standard_id, code, title_ar, sort_order)
  SELECT DISTINCT ON (st.standard_code, st.sub_standard_code)
         s.id, st.sub_standard_code, st.sub_standard_title_ar, COALESCE(st.sub_standard_order, 0)
    FROM import_requirement_staging st
    JOIN standard s ON s.framework_id = v_fw AND s.code = st.standard_code
   ORDER BY st.standard_code, st.sub_standard_code
  ON CONFLICT (standard_id, code) DO UPDATE
     SET title_ar = EXCLUDED.title_ar, sort_order = EXCLUDED.sort_order;

  INSERT INTO requirement (sub_standard_id, code, text_ar, sort_order, scope, evidence_required, na_scope)
  SELECT DISTINCT ON (st.standard_code, st.sub_standard_code, st.requirement_code)
         ss.id, st.requirement_code, st.requirement_text_ar, COALESCE(st.requirement_order, 0),
         st.scope, st.evidence_required, st.na_scope
    FROM import_requirement_staging st
    JOIN standard s      ON s.framework_id = v_fw AND s.code = st.standard_code
    JOIN sub_standard ss ON ss.standard_id = s.id AND ss.code = st.sub_standard_code
   ORDER BY st.standard_code, st.sub_standard_code, st.requirement_code
  ON CONFLICT (sub_standard_id, code) DO UPDATE
     SET text_ar = EXCLUDED.text_ar, sort_order = EXCLUDED.sort_order,
         scope = EXCLUDED.scope, evidence_required = EXCLUDED.evidence_required, na_scope = EXCLUDED.na_scope;

  GET DIAGNOSTICS v_n = ROW_COUNT;
  TRUNCATE import_requirement_staging;
  RETURN v_n;
END $$;

-- ---------------------------------------------------------------------
-- 15) وحدة خطط التحسين
--   تتولد خطة لكل متطلب يُعتمد نهائياً بتقدير "جزئي" أو "غير متحقق"،
--   يعبّئها القسم، ويحكم المقيّم على ملاءمتها، ثم تُنفَّذ، ولا تُغلق إلا بتحقق مستقل.
-- ---------------------------------------------------------------------
CREATE TABLE action_workflow_rule (
  from_status  action_status_t NOT NULL,
  to_status    action_status_t NOT NULL,
  role         text NOT NULL,          -- دور من role_t، أو 'owner' = المسؤول عن التنفيذ نفسه
  PRIMARY KEY (from_status, to_status, role)
);

CREATE TABLE action_transition (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  action_id   bigint NOT NULL REFERENCES improvement_action(id) ON DELETE CASCADE,
  from_status action_status_t NOT NULL,
  to_status   action_status_t NOT NULL,
  actor_id    bigint NOT NULL REFERENCES app_user(id),
  comment     text,
  at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_action_transition ON action_transition (action_id);

-- عضوية القسم: أساس قاعدة الفصل بين المهام
CREATE FUNCTION is_department_member(p_user bigint, p_dept bigint) RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT p_dept IS NOT NULL AND EXISTS (
    SELECT 1 FROM user_role ur
     WHERE ur.user_id = p_user AND ur.department_id = p_dept
       AND ur.role IN ('hod','dept_coordinator','faculty')
       AND current_date BETWEEN ur.valid_from AND COALESCE(ur.valid_to, 'infinity'::date))
$$;

CREATE FUNCTION trg_action_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  v_sys   boolean := COALESCE(current_setting('aqap.system_op', true), '') = 'on';
  v_actor bigint  := current_actor();
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NOT v_sys THEN
      NEW.status := 'draft';
      NEW.adequacy := NULL; NEW.adequacy_by := NULL; NEW.adequacy_at := NULL;
      NEW.verified_by := NULL; NEW.verified_at := NULL; NEW.completed_by := NULL;
    END IF;
    NEW.created_by := COALESCE(NEW.created_by, v_actor);
    RETURN NEW;
  END IF;
  IF v_sys THEN RETURN NEW; END IF;

  IF NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'تغيير حالة الخطة يتم عبر aqap.transition_action فقط';
  END IF;
  IF (NEW.adequacy, NEW.adequacy_by, NEW.adequacy_at, NEW.verified_by, NEW.verified_at, NEW.verification_note,
      NEW.completed_by, NEW.cycle_id, NEW.assessment_id, NEW.department_id, NEW.source)
     IS DISTINCT FROM
     (OLD.adequacy, OLD.adequacy_by, OLD.adequacy_at, OLD.verified_by, OLD.verified_at, OLD.verification_note,
      OLD.completed_by, OLD.cycle_id, OLD.assessment_id, OLD.department_id, OLD.source) THEN
    RAISE EXCEPTION 'هذه الحقول تُسجَّل عبر مسار اعتماد الخطة فقط';
  END IF;
  IF (NEW.title_ar, NEW.action_ar, NEW.owner_id, NEW.owner_label, NEW.priority)
     IS DISTINCT FROM (OLD.title_ar, OLD.action_ar, OLD.owner_id, OLD.owner_label, OLD.priority)
     AND OLD.status NOT IN ('draft','revision') THEN
    RAISE EXCEPTION 'محتوى الخطة يُعدّل فقط قبل رفعها أو بعد إعادتها للقسم';
  END IF;
  IF NEW.due_date IS DISTINCT FROM OLD.due_date AND OLD.status NOT IN ('draft','revision')
     AND NOT (has_role(v_actor, 'quality_dean', OLD.department_id, OLD.cycle_id)
              OR has_role(v_actor, 'quality_auditor', OLD.department_id, OLD.cycle_id)
              OR has_role(v_actor, 'hod', OLD.department_id, OLD.cycle_id)) THEN
    RAISE EXCEPTION 'تعديل الموعد بعد رفع الخطة من صلاحية رئيس القسم أو الجودة';
  END IF;
  IF (NEW.progress_pct, NEW.completion_evidence_id) IS DISTINCT FROM (OLD.progress_pct, OLD.completion_evidence_id)
     AND OLD.status <> 'approved' THEN
    RAISE EXCEPTION 'نسبة الإنجاز وشاهد التحسين يُحدَّثان أثناء التنفيذ فقط';
  END IF;
  IF NEW.completed_on IS DISTINCT FROM OLD.completed_on AND OLD.status <> 'approved' THEN
    RAISE EXCEPTION 'تاريخ الإنجاز يُسجَّل أثناء التنفيذ فقط';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER t_action_guard BEFORE INSERT OR UPDATE ON improvement_action
  FOR EACH ROW EXECUTE FUNCTION trg_action_guard();

CREATE FUNCTION transition_action(p_action_id bigint, p_to action_status_t, p_actor bigint,
                                  p_comment text DEFAULT NULL, p_adequacy adequacy_t DEFAULT NULL)
RETURNS action_status_t LANGUAGE plpgsql AS $$
DECLARE
  x improvement_action%ROWTYPE;
  v_comment text := NULLIF(btrim(COALESCE(p_comment, '')), '');
BEGIN
  SELECT * INTO x FROM improvement_action WHERE id = p_action_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'الخطة % غير موجودة', p_action_id; END IF;

  IF NOT EXISTS (
       SELECT 1 FROM action_workflow_rule w
        WHERE w.from_status = x.status AND w.to_status = p_to
          AND ((w.role = 'owner' AND x.owner_id = p_actor)
               OR (w.role <> 'owner' AND has_role(p_actor, w.role::role_t, x.department_id, x.cycle_id)))) THEN
    RAISE EXCEPTION 'انتقال غير مسموح من % إلى % لهذا المستخدم', x.status, p_to;
  END IF;

  PERFORM set_config('aqap.user_id',   p_actor::text, true);
  PERFORM set_config('aqap.system_op', 'on', true);

  IF p_to = 'submitted' THEN
    IF COALESCE(btrim(x.action_ar), '') = '' THEN RAISE EXCEPTION 'اكتب الإجراءات التحسينية قبل رفع الخطة'; END IF;
    IF x.owner_id IS NULL AND COALESCE(btrim(x.owner_label), '') = '' THEN
      RAISE EXCEPTION 'حدّد المسؤول عن التنفيذ قبل رفع الخطة';
    END IF;
    IF x.due_date IS NULL THEN RAISE EXCEPTION 'حدّد تاريخ اكتمال التنفيذ قبل رفع الخطة'; END IF;
    UPDATE improvement_action SET status = p_to WHERE id = x.id;

  ELSIF p_to IN ('approved', 'revision') AND x.status = 'submitted' THEN
    IF is_department_member(p_actor, x.department_id) THEN
      RAISE EXCEPTION 'لا يحكم على ملاءمة خطة قسم ينتمي إليه (الفصل بين المهام)';
    END IF;
    IF p_to = 'revision' THEN
      IF p_adequacy IS NULL OR p_adequacy = 'suitable' THEN
        RAISE EXCEPTION 'الإعادة تتطلب حكم «غير مناسب» أو «غير كافٍ»';
      END IF;
      IF v_comment IS NULL THEN RAISE EXCEPTION 'الإعادة تتطلب ملاحظات للقسم'; END IF;
    END IF;
    UPDATE improvement_action
       SET status = p_to,
           adequacy = CASE WHEN p_to = 'approved' THEN 'suitable'::adequacy_t ELSE p_adequacy END,
           adequacy_by = p_actor, adequacy_at = now(),
           reviewer_notes = v_comment
     WHERE id = x.id;

  ELSIF p_to = 'completed' THEN
    IF x.completion_evidence_id IS NULL THEN
      RAISE EXCEPTION 'إعلان الإنجاز يتطلب ربط شاهد التحسين';
    END IF;
    UPDATE improvement_action
       SET status = p_to, progress_pct = 100, completed_on = COALESCE(completed_on, current_date),
           completed_by = p_actor
     WHERE id = x.id;

  ELSIF p_to = 'verified' THEN
    IF p_actor IN (x.owner_id, x.completed_by) OR is_department_member(p_actor, x.department_id) THEN
      RAISE EXCEPTION 'التحقق من الإنجاز يتم من طرف مستقل عن القسم والمنفّذ (الفصل بين المهام)';
    END IF;
    UPDATE improvement_action
       SET status = p_to, verified_by = p_actor, verified_at = now(), verification_note = v_comment
     WHERE id = x.id;

  ELSIF p_to = 'approved' AND x.status = 'completed' THEN
    IF v_comment IS NULL THEN RAISE EXCEPTION 'رفض التحقق يتطلب ذكر ما ينقص'; END IF;
    IF is_department_member(p_actor, x.department_id) THEN
      RAISE EXCEPTION 'التحقق من الإنجاز يتم من طرف مستقل عن القسم (الفصل بين المهام)';
    END IF;
    UPDATE improvement_action
       SET status = p_to, completed_on = NULL, completed_by = NULL, verification_note = v_comment
     WHERE id = x.id;

  ELSIF p_to = 'cancelled' THEN
    IF v_comment IS NULL THEN RAISE EXCEPTION 'الإلغاء يتطلب ذكر السبب'; END IF;
    UPDATE improvement_action SET status = p_to WHERE id = x.id;

  ELSE
    UPDATE improvement_action SET status = p_to WHERE id = x.id;
  END IF;

  PERFORM set_config('aqap.system_op', 'off', true);
  INSERT INTO action_transition (action_id, from_status, to_status, actor_id, comment)
  VALUES (x.id, x.status, p_to, p_actor, v_comment);
  RETURN p_to;
END $$;

-- توليد الخطط: متطلب نهائي بتقدير "جزئي" أو "غير متحقق" بلا خطة تلقائية
CREATE FUNCTION generate_improvement_actions(p_cycle_id bigint) RETURNS integer
LANGUAGE plpgsql AS $$
DECLARE v_n integer;
BEGIN
  INSERT INTO improvement_action (cycle_id, assessment_id, department_id, source, title_ar)
  SELECT a.cycle_id, a.id, a.department_id, 'auto', 'خطة تحسين المتطلب ' || r.code
    FROM assessment a JOIN requirement r ON r.id = a.requirement_id
   WHERE a.cycle_id = p_cycle_id AND a.status = 'final'
     AND NOT is_excluded(a.requirement_id, a.department_id, a.cycle_id)
     AND (effective_rating(a.self_rating, a.ext_verdict, na_allowed(a.requirement_id, a.department_id)) IN ('partial','not_met')
          OR (r.evidence_required
              AND effective_rating(a.self_rating, a.ext_verdict, na_allowed(a.requirement_id, a.department_id)) <> 'na'
              AND NOT EXISTS (SELECT 1 FROM assessment_evidence ae WHERE ae.assessment_id = a.id)))
  ON CONFLICT (assessment_id) WHERE source = 'auto' DO NOTHING;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  RETURN v_n;
END $$;

CREATE FUNCTION trg_assessment_final_action() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.status = 'final' AND OLD.status IS DISTINCT FROM 'final'
     AND effective_rating(NEW.self_rating, NEW.ext_verdict, na_allowed(NEW.requirement_id, NEW.department_id)) IS DISTINCT FROM 'na' THEN
    -- خطة تحسين: المتطلب غير منفذ/منفذ جزئياً، أو الشاهد المطلوب غير متوفر
    INSERT INTO improvement_action (cycle_id, assessment_id, department_id, source, title_ar)
    SELECT NEW.cycle_id, NEW.id, NEW.department_id, 'auto', 'خطة تحسين المتطلب ' || r.code
      FROM requirement r WHERE r.id = NEW.requirement_id
       AND NOT is_excluded(NEW.requirement_id, NEW.department_id, NEW.cycle_id)
       AND (effective_rating(NEW.self_rating, NEW.ext_verdict, na_allowed(NEW.requirement_id, NEW.department_id)) IN ('partial','not_met')
            OR (r.evidence_required AND NOT EXISTS (SELECT 1 FROM assessment_evidence ae WHERE ae.assessment_id = NEW.id)))
    ON CONFLICT (assessment_id) WHERE source = 'auto' DO NOTHING;
  END IF;
  RETURN NULL;
END $$;
CREATE TRIGGER t_assessment_final_action AFTER UPDATE OF status ON assessment
  FOR EACH ROW EXECUTE FUNCTION trg_assessment_final_action();

INSERT INTO action_workflow_rule (from_status, to_status, role) VALUES
  ('draft',     'submitted', 'dept_coordinator'), ('draft',     'submitted', 'faculty'), ('draft', 'submitted', 'hod'),
  ('revision',  'submitted', 'dept_coordinator'), ('revision',  'submitted', 'faculty'), ('revision', 'submitted', 'hod'),
  ('submitted', 'approved',  'quality_auditor'),  ('submitted', 'approved',  'external_reviewer'),
  ('submitted', 'revision',  'quality_auditor'),  ('submitted', 'revision',  'external_reviewer'),
  ('approved',  'completed', 'owner'),            ('approved',  'completed', 'dept_coordinator'), ('approved', 'completed', 'hod'),
  ('completed', 'verified',  'quality_auditor'),  ('completed', 'verified',  'quality_dean'), ('completed', 'verified', 'external_reviewer'),
  ('completed', 'approved',  'quality_auditor'),  ('completed', 'approved',  'quality_dean'), ('completed', 'approved', 'external_reviewer'),
  ('draft',     'cancelled', 'quality_dean'),     ('submitted', 'cancelled', 'quality_dean'),
  ('revision',  'cancelled', 'quality_dean'),     ('approved',  'cancelled', 'quality_dean');

-- ---------------------------------------------------------------------
-- 16) البيانات المرجعية الأساسية
-- ---------------------------------------------------------------------
INSERT INTO rating_score (rating, score, label_ar) VALUES
  ('met',     1.0, 'متحقق'),
  ('partial', 0.0, 'متحقق جزئي'),        -- النموذج الرسمي يحسب «متحقق» فقط
  ('not_met', 0.0, 'غير متحقق'),
  ('na',      NULL, 'لا ينطبق');

INSERT INTO workflow_rule (from_status, to_status, role) VALUES
  ('draft',        'submitted',    'dept_coordinator'),
  ('draft',        'submitted',    'faculty'),
  ('returned',     'submitted',    'dept_coordinator'),
  ('returned',     'submitted',    'faculty'),
  ('submitted',    'hod_approved', 'hod'),
  ('submitted',    'returned',     'hod'),
  ('hod_approved', 'under_audit',  'quality_auditor'),
  ('hod_approved', 'under_audit',  'quality_dean'),
  ('under_audit',  'audited',      'quality_auditor'),
  ('under_audit',  'audited',      'external_reviewer'),
  ('under_audit',  'returned',     'quality_auditor'),
  ('audited',      'final',        'quality_dean'),
  ('audited',      'returned',     'quality_dean'),
  ('final',        'under_audit',  'quality_dean');   -- إعادة فتح قبل إغلاق الدورة

INSERT INTO framework (code, name_ar, name_en, issuer, version) VALUES
  ('TVTC-TQ-L2', 'نموذج العمل الشامل لجودة التدريب في المنشآت التدريبية – المستوى الثاني',
   'Comprehensive Work Model for Training Quality – Level 2', 'TVTC', '1.0');

-- المعايير والمعايير الفرعية والمتطلبات الرسمية تُستورد من ملف النموذج:
--   python scripts/import_xlsb.py <ملف.xlsb> --dsn ...

-- ---------------------------------------------------------------------
-- 17) وحدة المحاضر: نموذج رقمي موحّد لمحاضر الاجتماعات في متطلبات النموذج
--   محضر ← محاور ← توصيات (مسؤول، فترة) + الحضور + اعتماد رئيس القسم + متابعة تنفيذ التوصيات.
--   عند الاعتماد يُقفل المحضر ويُؤرشف PDF شاهداً للمتطلب (من طبقة التطبيق).
-- ---------------------------------------------------------------------
CREATE TYPE minutes_status_t AS ENUM ('draft','submitted','returned','approved');   -- مسودة/مرفوع/معاد/معتمد
CREATE TYPE minutes_fu_t     AS ENUM ('done','partial','not_done');                  -- مُنفذ/مُنفذ جزئي/لم يُنفذ

-- نماذج عامة لكل متطلب من نوع «محضر» (بلا بيانات أي قسم)؛ تُربط بالمتطلب برمزه داخل الإطار
CREATE TABLE minutes_template (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  framework_code    text NOT NULL,
  requirement_code  text NOT NULL,
  title_ar          text NOT NULL,                  -- اسم الاجتماع الافتراضي
  suggested_agenda  jsonb NOT NULL DEFAULT '[]',    -- محاور مقترحة قابلة للتعديل
  guidance_ar       text,
  sort_order        int NOT NULL DEFAULT 0,
  UNIQUE (framework_code, requirement_code)
);

CREATE TABLE minutes (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id         bigint NOT NULL REFERENCES assessment_cycle(id),
  department_id    bigint NOT NULL REFERENCES department(id),
  template_id      bigint NOT NULL REFERENCES minutes_template(id),
  meeting_no       int NOT NULL,
  title_ar         text NOT NULL,
  semester         text NOT NULL DEFAULT 'الأول' CHECK (semester IN ('الأول','الثاني','الصيفي')),
  meeting_date     date,
  start_time       text,
  location_ar      text,
  follow_up_owner  text,                            -- مسؤول متابعة تنفيذ التوصيات
  status           minutes_status_t NOT NULL DEFAULT 'draft',
  return_reason    text,
  submitted_by     bigint REFERENCES app_user(id),
  submitted_at     timestamptz,
  approved_by      bigint REFERENCES app_user(id),
  approved_at      timestamptz,
  evidence_id      bigint REFERENCES evidence(id),  -- النسخة المؤرشفة (PDF)
  created_by       bigint REFERENCES app_user(id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (cycle_id, department_id, template_id, meeting_no)
);
CREATE INDEX ix_minutes_scope ON minutes (cycle_id, department_id, template_id);

CREATE TABLE minutes_agenda_item (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  minutes_id  bigint NOT NULL REFERENCES minutes(id) ON DELETE CASCADE,
  ord         int NOT NULL,
  title_ar    text NOT NULL,
  UNIQUE (minutes_id, ord)
);

CREATE TABLE minutes_recommendation (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  agenda_item_id  bigint NOT NULL REFERENCES minutes_agenda_item(id) ON DELETE CASCADE,
  ord             int NOT NULL,
  text_ar         text NOT NULL,
  responsible_ar  text,
  period_ar       text,
  fu_status       minutes_fu_t,
  fu_obstacles    text,
  fu_solutions    text,
  fu_by           bigint REFERENCES app_user(id),
  fu_at           timestamptz,
  UNIQUE (agenda_item_id, ord)
);

CREATE TABLE minutes_attendee (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  minutes_id    bigint NOT NULL REFERENCES minutes(id) ON DELETE CASCADE,
  ord           int NOT NULL,
  name_ar       text NOT NULL,
  role_ar       text,
  user_id       bigint REFERENCES app_user(id),
  confirmed_at  timestamptz,                         -- تأكيد الحضور إلكترونياً (بديل التوقيع)
  UNIQUE (minutes_id, ord)
);

CREATE TABLE minutes_transition (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  minutes_id  bigint NOT NULL REFERENCES minutes(id) ON DELETE CASCADE,
  from_status minutes_status_t NOT NULL,
  to_status   minutes_status_t NOT NULL,
  actor_id    bigint NOT NULL REFERENCES app_user(id),
  comment     text,
  at          timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER t_upd_minutes BEFORE UPDATE ON minutes FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER t_audit_minutes AFTER INSERT OR UPDATE OR DELETE ON minutes FOR EACH ROW EXECUTE FUNCTION trg_audit();
CREATE TRIGGER t_audit_minutes_rec AFTER UPDATE OR DELETE ON minutes_recommendation FOR EACH ROW EXECUTE FUNCTION trg_audit();

-- رقم الاجتماع التالي تلقائياً، وحماية رأس المحضر
CREATE FUNCTION trg_minutes_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_sys boolean := COALESCE(current_setting('aqap.system_op', true), '') = 'on';
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.meeting_no IS NULL OR NEW.meeting_no <= 0 THEN
      SELECT COALESCE(max(meeting_no), 0) + 1 INTO NEW.meeting_no FROM minutes
       WHERE cycle_id = NEW.cycle_id AND department_id = NEW.department_id AND template_id = NEW.template_id;
    END IF;
    IF NOT v_sys THEN NEW.status := 'draft'; END IF;
    NEW.created_by := COALESCE(NEW.created_by, current_actor());
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' AND NOT v_sys THEN RAISE EXCEPTION 'يُحذف المحضر في حالة المسودة فقط'; END IF;
    RETURN OLD;
  END IF;
  IF v_sys THEN RETURN NEW; END IF;
  IF NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'تغيير حالة المحضر يتم عبر aqap.transition_minutes فقط';
  END IF;
  IF (NEW.title_ar, NEW.semester, NEW.meeting_date, NEW.start_time, NEW.location_ar, NEW.meeting_no,
      NEW.cycle_id, NEW.department_id, NEW.template_id)
     IS DISTINCT FROM (OLD.title_ar, OLD.semester, OLD.meeting_date, OLD.start_time, OLD.location_ar, OLD.meeting_no,
      OLD.cycle_id, OLD.department_id, OLD.template_id)
     AND OLD.status NOT IN ('draft','returned') THEN
    RAISE EXCEPTION 'محتوى المحضر يُعدّل في المسودة أو بعد إعادته فقط';
  END IF;
  IF (NEW.approved_by, NEW.approved_at, NEW.submitted_by, NEW.submitted_at, NEW.evidence_id, NEW.return_reason)
     IS DISTINCT FROM (OLD.approved_by, OLD.approved_at, OLD.submitted_by, OLD.submitted_at, OLD.evidence_id, OLD.return_reason) THEN
    RAISE EXCEPTION 'حقول الاعتماد والأرشفة تُسجَّل عبر مسار المحضر فقط';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER t_minutes_guard BEFORE INSERT OR UPDATE OR DELETE ON minutes
  FOR EACH ROW EXECUTE FUNCTION trg_minutes_guard();

-- المحاور والتوصيات والحضور: تُعدّل مع المحضر فقط؛ وبعد الاعتماد تُفتح حقول المتابعة وتأكيد الحضور
CREATE FUNCTION minutes_editable(p_minutes bigint) RETURNS minutes_status_t LANGUAGE plpgsql AS $$
DECLARE v minutes_status_t;
BEGIN
  SELECT status INTO v FROM minutes WHERE id = p_minutes;
  IF v IS NOT NULL AND v NOT IN ('draft','returned')
     AND COALESCE(current_setting('aqap.system_op', true), '') <> 'on' THEN
    RAISE EXCEPTION 'محتوى المحضر يُعدّل في المسودة أو بعد إعادته فقط';
  END IF;
  RETURN v;
END $$;

CREATE FUNCTION trg_minutes_agenda_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN PERFORM minutes_editable(OLD.minutes_id); RETURN OLD; END IF;
  PERFORM minutes_editable(NEW.minutes_id);
  RETURN NEW;
END $$;

CREATE FUNCTION trg_minutes_rec_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  v_sys boolean := COALESCE(current_setting('aqap.system_op', true), '') = 'on';
  v_mid bigint;
  v_status minutes_status_t;
BEGIN
  IF v_sys THEN RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END; END IF;
  IF TG_OP = 'DELETE' THEN
    SELECT minutes_id INTO v_mid FROM minutes_agenda_item WHERE id = OLD.agenda_item_id;
    PERFORM minutes_editable(v_mid);
    RETURN OLD;
  END IF;
  SELECT minutes_id INTO v_mid FROM minutes_agenda_item WHERE id = NEW.agenda_item_id;
  IF TG_OP = 'UPDATE' THEN
    IF (NEW.agenda_item_id, NEW.ord, NEW.text_ar, NEW.responsible_ar, NEW.period_ar)
       IS NOT DISTINCT FROM (OLD.agenda_item_id, OLD.ord, OLD.text_ar, OLD.responsible_ar, OLD.period_ar) THEN
      SELECT status INTO v_status FROM minutes WHERE id = v_mid;
      IF v_status <> 'approved' THEN RAISE EXCEPTION 'متابعة تنفيذ التوصيات تبدأ بعد اعتماد المحضر'; END IF;
      NEW.fu_by := COALESCE(current_actor(), NEW.fu_by);
      NEW.fu_at := now();
      RETURN NEW;
    END IF;
  END IF;
  PERFORM minutes_editable(v_mid);
  IF NEW.fu_status IS NOT NULL OR NEW.fu_obstacles IS NOT NULL OR NEW.fu_solutions IS NOT NULL THEN
    RAISE EXCEPTION 'متابعة تنفيذ التوصيات تبدأ بعد اعتماد المحضر';
  END IF;
  RETURN NEW;
END $$;

CREATE FUNCTION trg_minutes_att_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  v_sys boolean := COALESCE(current_setting('aqap.system_op', true), '') = 'on';
  v_status minutes_status_t;
BEGIN
  IF v_sys THEN RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END; END IF;
  IF TG_OP = 'DELETE' THEN PERFORM minutes_editable(OLD.minutes_id); RETURN OLD; END IF;
  IF TG_OP = 'UPDATE' AND (NEW.minutes_id, NEW.ord, NEW.name_ar, NEW.role_ar, NEW.user_id)
                          IS NOT DISTINCT FROM (OLD.minutes_id, OLD.ord, OLD.name_ar, OLD.role_ar, OLD.user_id) THEN
    SELECT status INTO v_status FROM minutes WHERE id = NEW.minutes_id;
    IF v_status NOT IN ('submitted','approved') THEN RAISE EXCEPTION 'يُؤكَّد الحضور بعد رفع المحضر'; END IF;
    RETURN NEW;
  END IF;
  PERFORM minutes_editable(NEW.minutes_id);
  IF TG_OP = 'INSERT' THEN NEW.confirmed_at := NULL; END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER t_minutes_agenda_guard BEFORE INSERT OR UPDATE OR DELETE ON minutes_agenda_item
  FOR EACH ROW EXECUTE FUNCTION trg_minutes_agenda_guard();
CREATE TRIGGER t_minutes_rec_guard BEFORE INSERT OR UPDATE OR DELETE ON minutes_recommendation
  FOR EACH ROW EXECUTE FUNCTION trg_minutes_rec_guard();
CREATE TRIGGER t_minutes_att_guard BEFORE INSERT OR UPDATE OR DELETE ON minutes_attendee
  FOR EACH ROW EXECUTE FUNCTION trg_minutes_att_guard();

CREATE FUNCTION transition_minutes(p_id bigint, p_to minutes_status_t, p_actor bigint, p_comment text DEFAULT NULL)
RETURNS minutes_status_t LANGUAGE plpgsql AS $$
DECLARE
  m minutes%ROWTYPE;
  v_comment text := NULLIF(btrim(COALESCE(p_comment, '')), '');
  v_items int; v_empty int; v_recs int; v_noresp int; v_att int;
  v_cycle cycle_status_t;
BEGIN
  SELECT * INTO m FROM minutes WHERE id = p_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'المحضر % غير موجود', p_id; END IF;
  SELECT status INTO v_cycle FROM assessment_cycle WHERE id = m.cycle_id;
  IF v_cycle IN ('closed','archived') THEN RAISE EXCEPTION 'الدورة مغلقة؛ لا يمكن تغيير حالة المحضر'; END IF;

  IF p_to = 'submitted' AND m.status IN ('draft','returned') THEN
    IF NOT (has_role(p_actor,'dept_coordinator',m.department_id,m.cycle_id) OR has_role(p_actor,'faculty',m.department_id,m.cycle_id)
            OR has_role(p_actor,'hod',m.department_id,m.cycle_id)) THEN
      RAISE EXCEPTION 'رفع المحضر من صلاحية منسوبي القسم';
    END IF;
    IF m.meeting_date IS NULL THEN RAISE EXCEPTION 'حدّد تاريخ الاجتماع قبل الرفع'; END IF;
    SELECT count(*) INTO v_items FROM minutes_agenda_item WHERE minutes_id = m.id;
    IF v_items = 0 THEN RAISE EXCEPTION 'أضف محوراً واحداً على الأقل'; END IF;
    SELECT count(*) INTO v_empty FROM minutes_agenda_item ai
     WHERE ai.minutes_id = m.id AND NOT EXISTS (SELECT 1 FROM minutes_recommendation r WHERE r.agenda_item_id = ai.id);
    IF v_empty > 0 THEN RAISE EXCEPTION 'كل محور يحتاج توصية واحدة على الأقل (% محور بلا توصيات)', v_empty; END IF;
    SELECT count(*), count(*) FILTER (WHERE COALESCE(btrim(r.responsible_ar),'') = '') INTO v_recs, v_noresp
      FROM minutes_recommendation r JOIN minutes_agenda_item ai ON ai.id = r.agenda_item_id WHERE ai.minutes_id = m.id;
    IF v_noresp > 0 THEN RAISE EXCEPTION 'حدّد مسؤول التنفيذ لكل توصية (% توصية بلا مسؤول)', v_noresp; END IF;
    SELECT count(*) INTO v_att FROM minutes_attendee WHERE minutes_id = m.id;
    IF v_att < 2 THEN RAISE EXCEPTION 'سجّل الحضور (عضوان على الأقل)'; END IF;
    PERFORM set_config('aqap.system_op', 'on', true);
    UPDATE minutes SET status = p_to, submitted_by = p_actor, submitted_at = now(), return_reason = NULL WHERE id = m.id;

  ELSIF p_to IN ('approved','returned') AND m.status = 'submitted' THEN
    IF NOT (has_role(p_actor,'hod',m.department_id,m.cycle_id) OR has_role(p_actor,'quality_dean',m.department_id,m.cycle_id)) THEN
      RAISE EXCEPTION 'اعتماد المحضر من صلاحية رئيس القسم';
    END IF;
    IF p_to = 'returned' AND v_comment IS NULL THEN RAISE EXCEPTION 'الإعادة تتطلب ذكر السبب'; END IF;
    PERFORM set_config('aqap.system_op', 'on', true);
    IF p_to = 'approved' THEN
      UPDATE minutes SET status = p_to, approved_by = p_actor, approved_at = now() WHERE id = m.id;
    ELSE
      UPDATE minutes SET status = p_to, return_reason = v_comment WHERE id = m.id;
    END IF;

  ELSIF p_to = 'returned' AND m.status = 'approved' THEN
    IF NOT has_role(p_actor,'quality_dean',m.department_id,m.cycle_id) THEN
      RAISE EXCEPTION 'إعادة فتح محضر معتمد من صلاحية وكيل الجودة';
    END IF;
    IF v_comment IS NULL THEN RAISE EXCEPTION 'إعادة الفتح تتطلب ذكر السبب'; END IF;
    PERFORM set_config('aqap.system_op', 'on', true);
    UPDATE minutes SET status = p_to, return_reason = v_comment, approved_by = NULL, approved_at = NULL WHERE id = m.id;
    UPDATE minutes_recommendation r SET fu_status = NULL, fu_obstacles = NULL, fu_solutions = NULL, fu_by = NULL, fu_at = NULL
      FROM minutes_agenda_item ai WHERE ai.id = r.agenda_item_id AND ai.minutes_id = m.id;
    UPDATE minutes_attendee SET confirmed_at = NULL WHERE minutes_id = m.id;
  ELSE
    RAISE EXCEPTION 'انتقال غير مسموح من % إلى %', m.status, p_to;
  END IF;

  PERFORM set_config('aqap.system_op', 'off', true);
  INSERT INTO minutes_transition (minutes_id, from_status, to_status, actor_id, comment)
  VALUES (m.id, m.status, p_to, p_actor, v_comment);
  RETURN p_to;
END $$;

-- ملخص المحضر ونسبة تنفيذ التوصيات (صيغة نموذج المتابعة: مُنفذ ×1 + مُنفذ جزئي ×0.5 ÷ إجمالي التوصيات)
CREATE VIEW v_minutes_summary AS
SELECT m.id AS minutes_id, m.cycle_id, m.department_id, m.template_id, t.requirement_code, m.meeting_no, m.title_ar,
       m.semester, m.meeting_date, m.status, m.approved_at, m.evidence_id,
       (SELECT count(*) FROM minutes_agenda_item ai WHERE ai.minutes_id = m.id)            AS agenda_count,
       count(r.id)                                                                        AS rec_total,
       count(r.id) FILTER (WHERE r.fu_status = 'done')                                    AS rec_done,
       count(r.id) FILTER (WHERE r.fu_status = 'partial')                                 AS rec_partial,
       count(r.id) FILTER (WHERE r.fu_status = 'not_done')                                AS rec_not_done,
       count(r.id) FILTER (WHERE r.fu_status IS NULL)                                     AS rec_pending,
       round(100.0 * (count(r.id) FILTER (WHERE r.fu_status = 'done')
                      + 0.5 * count(r.id) FILTER (WHERE r.fu_status = 'partial')) / NULLIF(count(r.id), 0), 1) AS completion_pct,
       (SELECT count(*) FROM minutes_attendee a WHERE a.minutes_id = m.id)                AS attendee_count,
       (SELECT count(*) FROM minutes_attendee a WHERE a.minutes_id = m.id AND a.confirmed_at IS NOT NULL) AS confirmed_count
  FROM minutes m
  JOIN minutes_template t ON t.id = m.template_id
  LEFT JOIN minutes_agenda_item ai2 ON ai2.minutes_id = m.id
  LEFT JOIN minutes_recommendation r ON r.agenda_item_id = ai2.id
 GROUP BY m.id, t.requirement_code;

-- الشواهد والتقارير الداعمة للمحضر: من بنك شواهد القسم نفسه، وتُربط بالمتطلب مع المحضر عند اعتماده.
-- تُضاف في المسودة أو بعد الإعادة أو بعد الاعتماد (شواهد المتابعة)، ولا تُضاف والمحضر بانتظار قرار رئيس القسم.
-- وتُزال في المسودة أو بعد الإعادة فقط؛ الإزالة تفك الربط بالمحضر ولا تحذف الشاهد من البنك.
CREATE TABLE minutes_attachment (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  minutes_id   bigint NOT NULL REFERENCES minutes(id) ON DELETE CASCADE,
  evidence_id  bigint NOT NULL REFERENCES evidence(id),
  note         text,
  added_by     bigint REFERENCES app_user(id),
  added_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (minutes_id, evidence_id)
);
CREATE INDEX ix_minutes_attachment_ev ON minutes_attachment (evidence_id);

CREATE FUNCTION trg_minutes_attachment_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE TRIGGER t_minutes_attachment_guard BEFORE INSERT OR UPDATE OR DELETE ON minutes_attachment
  FOR EACH ROW EXECUTE FUNCTION trg_minutes_attachment_guard();
CREATE TRIGGER t_audit_minutes_attachment AFTER INSERT OR DELETE ON minutes_attachment
  FOR EACH ROW EXECUTE FUNCTION trg_audit();

-- نماذج المحاضر الثلاثة عشر في النموذج الرسمي (محاور مقترحة عامة يعدّلها القسم)
INSERT INTO minutes_template (framework_code, requirement_code, title_ar, suggested_agenda, guidance_ar, sort_order) VALUES
('TVTC-TQ-L2','1-1-1','اجتماع أعضاء القسم لمناقشة المبادرات التنفيذية',
 '["مراجعة المبادرات التنفيذية للقسم للفصل التدريبي","ربط المبادرات بالأهداف التشغيلية للمنشأة","توزيع مسؤوليات التنفيذ وآلية المتابعة"]',
 'يوثّق مناقشة أعضاء القسم لمبادراته التنفيذية، مع توصيات ومسؤول وفترة لكل منها.', 1),
('TVTC-TQ-L2','1-2-1','اجتماع مجلس القسم',
 '["متابعة توصيات الاجتماع السابق","موضوعات جدول أعمال المجلس","ما يستجد من أعمال"]',
 'محضر معتمد لمجلس القسم يتضمن التوصيات ومتابعة تنفيذها.', 2),
('TVTC-TQ-L2','1-3-1','اجتماع لجنة إعداد الجداول التدريبية',
 '["تهيئة الشعب التدريبية وفق أعداد المتدربين","توزيع المقررات على المدربين","معالجة التعارضات في الجداول"]',
 'يوثّق أعمال لجنة الجداول في القسم وتوصياتها.', 3),
('TVTC-TQ-L2','2-1-2','اجتماع مناقشة أعمال الإرشاد التدريبي وفاعليتها',
 '["متابعة حالات المتدربين المتعثرين","تقييم فاعلية أعمال الإرشاد التدريبي","مقترحات تحسين الإرشاد"]',
 'يناقش أعمال الإرشاد التدريبي في القسم ومدى فاعليتها.', 4),
('TVTC-TQ-L2','2-2-3','اجتماع مناقشة نتائج المتدربين وقياس جودة المخرجات',
 '["تحليل نتائج المتدربين في المقررات","المقررات ذات نسب الإخفاق المرتفعة","إجراءات تحسين جودة المخرجات"]',
 'يناقش نتائج المتدربين ومؤشرات جودة المخرجات.', 5),
('TVTC-TQ-L2','2-2-8','اجتماع مناقشة المشاريع التنفيذية لمقرر المشروع',
 '["اعتماد مقترحات مشاريع المتدربين","توزيع الإشراف على المشاريع","آلية تقييم المشاريع ومناقشتها"]',
 'يناقش المشاريع التنفيذية لمقرر المشروع وتوصياتها.', 6),
('TVTC-TQ-L2','3-1-1','اجتماع لجنة القياس والتقييم (الاختبارات)',
 '["جداول الاختبارات وتوزيع اللجان","مراجعة نماذج الاختبارات","ضوابط سير الاختبارات ورصد النتائج"]',
 'يوثّق أعمال لجنة القياس والتقييم في القسم.', 7),
('TVTC-TQ-L2','3-2-1','اجتماع لجنة مراجعة وتقييم الخطط التدريبية والمهارات',
 '["مراجعة الخطط التدريبية المعتمدة","ملاءمة المهارات لاحتياج سوق العمل","مقترحات التطوير"]',
 'يوثّق مراجعة الخطط التدريبية والمهارات وتقييمها.', 8),
('TVTC-TQ-L2','3-2-3','اجتماع مدربي المقررات المشتركة (نظري – عملي)',
 '["التنسيق بين الجزء النظري والعملي","توحيد آلية التقييم","توزيع المفردات زمنياً"]',
 'يوثّق التنسيق بين مدربي المقررات المشتركة.', 9),
('TVTC-TQ-L2','3-2-4','اجتماع مدربي المقرر الواحد',
 '["توحيد الخطة الزمنية للمفردات","توحيد أدوات التقييم ومعاييره","تبادل المواد التدريبية"]',
 'للمقرر الذي يدرّب عليه أكثر من مدرب.', 10),
('TVTC-TQ-L2','3-3-1','اجتماع مراجعة المحتوى التدريبي',
 '["مراجعة المحتوى المقدّم مقابل مفردات الخطة","المراجع العلمية المعتمدة","ملاحظات التحديث"]',
 'يراجع المحتوى التدريبي المقدّم من المدربين للمتدربين.', 11),
('TVTC-TQ-L2','4-1-1','اجتماع تصميم ومراجعة تطبيق استراتيجيات وتقنيات التدريب',
 '["الاستراتيجيات المطبقة في المقررات","توظيف التقنيات والمنصات الإلكترونية","تبادل الخبرات بين المدربين"]',
 'يوثّق تصميم ومراجعة تطبيق استراتيجيات وتقنيات متنوعة في التدريب حسب المقررات.', 12),
('TVTC-TQ-L2','4-3-2','اجتماع مناقشة ملاحظات تقرير سير العملية التدريبية',
 '["عرض ملاحظات تقرير سير العملية التدريبية","تحليل أسباب الملاحظات","الإجراءات التصحيحية"]',
 'يناقش ملاحظات تقرير سير العملية التدريبية والإجراءات التصحيحية.', 13);

-- ---------------------------------------------------------------------
-- النماذج الإلكترونية (الخطط والتقارير): محرّك موحّد تعرّفه قوالب JSON لكل متطلب
--   بيانات التخطيط (plan_data) تُعدّل في المسودة أو بعد الإعادة فقط؛
--   وبيانات المتابعة (follow_data: المتحقق وحالة التنفيذ والمعوقات وخطط التحسين) تبقى مفتوحة
--   بعد الاعتماد طوال الدورة، ولا تُعدّل والنموذج بانتظار قرار رئيس القسم أو بعد إغلاق الدورة.
-- ---------------------------------------------------------------------
CREATE TYPE form_status_t AS ENUM ('draft','submitted','returned','approved');   -- مسودة/مرفوع/معاد/معتمد

CREATE TABLE form_template (
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

CREATE TABLE form_record (
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

CREATE TABLE form_transition (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  form_id     bigint NOT NULL REFERENCES form_record(id) ON DELETE CASCADE,
  from_status form_status_t NOT NULL,
  to_status   form_status_t NOT NULL,
  actor_id    bigint NOT NULL REFERENCES app_user(id),
  comment     text,
  at          timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER t_upd_form BEFORE UPDATE ON form_record FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER t_audit_form AFTER INSERT OR UPDATE OR DELETE ON form_record FOR EACH ROW EXECUTE FUNCTION trg_audit();

CREATE FUNCTION trg_form_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE TRIGGER t_form_guard BEFORE INSERT OR UPDATE OR DELETE ON form_record
  FOR EACH ROW EXECUTE FUNCTION trg_form_guard();

-- اكتمال المحتوى يُتحقق منه في طبقة التطبيق (حسب قالب النموذج) قبل استدعاء الرفع
CREATE FUNCTION transition_form(p_id bigint, p_to form_status_t, p_actor bigint, p_comment text DEFAULT NULL)
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
CREATE TABLE form_attachment (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  form_id      bigint NOT NULL REFERENCES form_record(id) ON DELETE CASCADE,
  evidence_id  bigint NOT NULL REFERENCES evidence(id),
  note         text,
  added_by     bigint REFERENCES app_user(id),
  added_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (form_id, evidence_id)
);
CREATE INDEX ix_form_attachment_ev ON form_attachment (evidence_id);

CREATE FUNCTION trg_form_attachment_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
CREATE TRIGGER t_form_attachment_guard BEFORE INSERT OR UPDATE OR DELETE ON form_attachment
  FOR EACH ROW EXECUTE FUNCTION trg_form_attachment_guard();
CREATE TRIGGER t_audit_form_attachment AFTER INSERT OR DELETE ON form_attachment
  FOR EACH ROW EXECUTE FUNCTION trg_audit();

COMMIT;

CREATE TRIGGER t_audit_requirement_exclusion AFTER INSERT OR UPDATE ON requirement_exclusion
  FOR EACH ROW EXECUTE FUNCTION trg_audit();

-- ---------------------------------------------------------------------
-- تقويم الإنجاز: مواعيد يرفعها وكيل الجودة للمعايير الفرعية أو المتطلبات (لكل الأقسام أو لقسم)
-- الموعد الأخص يغلب: المتطلب على المعيار الفرعي، والقسم على «كل الأقسام»
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cycle_deadline (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id         bigint NOT NULL REFERENCES assessment_cycle(id) ON DELETE CASCADE,
  sub_standard_id  bigint REFERENCES sub_standard(id),
  requirement_id   bigint REFERENCES requirement(id),
  department_id    bigint REFERENCES department(id),          -- NULL = كل الأقسام
  starts_on        date,
  due_on           date NOT NULL,
  note_ar          text,
  created_by       bigint REFERENCES app_user(id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  CHECK ((sub_standard_id IS NULL) <> (requirement_id IS NULL)),
  CHECK (starts_on IS NULL OR starts_on <= due_on)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cycle_deadline ON cycle_deadline
  (cycle_id, COALESCE(sub_standard_id, 0), COALESCE(requirement_id, 0), COALESCE(department_id, 0));

-- الموعد الفعلي لكل تقدير
CREATE OR REPLACE VIEW v_assessment_deadline AS
SELECT a.id AS assessment_id, a.cycle_id, a.department_id, a.requirement_id, a.status, d.id AS deadline_id, d.starts_on, d.due_on
  FROM assessment a
  JOIN requirement r ON r.id = a.requirement_id
  JOIN LATERAL (
    SELECT cd.* FROM cycle_deadline cd
     WHERE cd.cycle_id = a.cycle_id
       AND (cd.requirement_id = a.requirement_id OR cd.sub_standard_id = r.sub_standard_id)
       AND (cd.department_id IS NULL OR cd.department_id IS NOT DISTINCT FROM a.department_id)
     ORDER BY (cd.requirement_id IS NOT NULL) DESC, (cd.department_id IS NOT NULL) DESC
     LIMIT 1) d ON true
 WHERE NOT is_excluded(a.requirement_id, a.department_id, a.cycle_id);

DROP TRIGGER IF EXISTS t_audit_cycle_deadline ON cycle_deadline;
CREATE TRIGGER t_audit_cycle_deadline AFTER INSERT OR UPDATE OR DELETE ON cycle_deadline
  FOR EACH ROW EXECUTE FUNCTION trg_audit();

-- ---------------------------------------------------------------------
-- الشواهد بالروابط: إعدادات المنشأة (طريقة الإرفاق، النطاقات المسموحة)، ومجلدات الشواهد، وفحص الروابط
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS institution_setting (
  institution_id        bigint PRIMARY KEY REFERENCES institution(id),
  attachment_mode       text NOT NULL DEFAULT 'both' CHECK (attachment_mode IN ('both','links','files')),
  allowed_link_domains  text[] NOT NULL DEFAULT '{}',          -- فارغة = أي نطاق
  updated_by            bigint REFERENCES app_user(id),
  updated_at            timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE evidence ADD COLUMN IF NOT EXISTS link_status text
  CHECK (link_status IN ('ok','restricted','broken','unreachable'));
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS link_http int;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS link_checked_at timestamptz;

-- هل الرابط من نطاق مسموح للمنشأة؟ (النطاق نفسه أو أي نطاق فرعي منه)
CREATE OR REPLACE FUNCTION link_allowed(p_institution bigint, p_url text) RETURNS boolean
LANGUAGE sql STABLE AS $$
  WITH s AS (SELECT allowed_link_domains AS d FROM institution_setting WHERE institution_id = p_institution),
       h AS (SELECT lower(substring(p_url from '^[a-zA-Z][a-zA-Z0-9+.-]*://([^/:?#]+)')) AS host)
  SELECT p_url ~* '^https://'
     AND (COALESCE((SELECT cardinality(d) FROM s), 0) = 0
          OR EXISTS (SELECT 1 FROM s, h, unnest(s.d) AS dom
                      WHERE h.host = lower(dom) OR h.host LIKE '%.' || lower(dom)))
$$;

CREATE OR REPLACE FUNCTION trg_evidence_link_policy() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v_mode text;
BEGIN
  IF NEW.kind = 'link' AND (TG_OP = 'INSERT' OR NEW.url IS DISTINCT FROM OLD.url) THEN
    SELECT attachment_mode INTO v_mode FROM institution_setting WHERE institution_id = NEW.institution_id;
    IF v_mode = 'files' THEN
      RAISE EXCEPTION 'إعدادات المنشأة تسمح برفع الملفات فقط ولا تقبل الروابط';
    END IF;
    IF NOT link_allowed(NEW.institution_id, NEW.url) THEN
      RAISE EXCEPTION 'الرابط ليس من النطاقات المعتمدة للمنشأة (مثل OneDrive أو SharePoint التابع للمؤسسة) أو لا يبدأ بـ https://';
    END IF;
    NEW.link_status := NULL; NEW.link_http := NULL; NEW.link_checked_at := NULL;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS t_evidence_link_policy ON evidence;
CREATE TRIGGER t_evidence_link_policy BEFORE INSERT OR UPDATE OF url, kind ON evidence
  FOR EACH ROW EXECUTE FUNCTION trg_evidence_link_policy();

-- مجلدات الشواهد: يحددها وكيل الجودة لكل قسم (المجلد العام، أو لمعيار، أو لمعيار فرعي) في كل دورة
CREATE TABLE IF NOT EXISTS evidence_folder (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id         bigint NOT NULL REFERENCES assessment_cycle(id) ON DELETE CASCADE,
  department_id    bigint NOT NULL REFERENCES department(id),
  standard_id      bigint REFERENCES standard(id),
  sub_standard_id  bigint REFERENCES sub_standard(id),
  url              text NOT NULL,
  created_by       bigint REFERENCES app_user(id),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  CHECK (standard_id IS NULL OR sub_standard_id IS NULL)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_evidence_folder ON evidence_folder
  (cycle_id, department_id, COALESCE(standard_id, 0), COALESCE(sub_standard_id, 0));

DROP TRIGGER IF EXISTS t_audit_evidence_folder ON evidence_folder;
CREATE TRIGGER t_audit_evidence_folder AFTER INSERT OR UPDATE OR DELETE ON evidence_folder
  FOR EACH ROW EXECUTE FUNCTION trg_audit();
DROP TRIGGER IF EXISTS t_audit_institution_setting ON institution_setting;
CREATE TRIGGER t_audit_institution_setting AFTER INSERT OR UPDATE ON institution_setting
  FOR EACH ROW EXECUTE FUNCTION trg_audit();

-- ---------------------------------------------------------------------
-- مكتبة الأدلة: أدلة ومراجع يرفع روابطها وكيل الجودة (OneDrive/SharePoint أو مواقع المؤسسة)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS guide_document (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  institution_id  bigint NOT NULL REFERENCES institution(id),
  title_ar        text NOT NULL CHECK (length(btrim(title_ar)) >= 3),
  description_ar  text,
  category        text NOT NULL DEFAULT 'دليل إجرائي',
  url             text NOT NULL CHECK (url ~* '^https?://'),
  sort_order      int NOT NULL DEFAULT 0,
  created_by      bigint REFERENCES app_user(id),
  created_at      timestamptz NOT NULL DEFAULT now()
);
DROP TRIGGER IF EXISTS t_audit_guide_document ON guide_document;
CREATE TRIGGER t_audit_guide_document AFTER INSERT OR UPDATE OR DELETE ON guide_document
  FOR EACH ROW EXECUTE FUNCTION trg_audit();
DROP TRIGGER IF EXISTS t_audit_app_user ON app_user;
CREATE TRIGGER t_audit_app_user AFTER INSERT OR UPDATE ON app_user
  FOR EACH ROW EXECUTE FUNCTION trg_audit();
DROP TRIGGER IF EXISTS t_audit_user_role ON user_role;
CREATE TRIGGER t_audit_user_role AFTER INSERT OR UPDATE OR DELETE ON user_role
  FOR EACH ROW EXECUTE FUNCTION trg_audit();

-- أعمال الجودة: جدول مهام متابعة الجودة الأسبوعي وربطها بالمعايير الفرعية والمتطلبات. آمن للتكرار.

CREATE TABLE IF NOT EXISTS quality_task (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id       bigint NOT NULL REFERENCES assessment_cycle(id) ON DELETE CASCADE,
  week_no        smallint NOT NULL CHECK (week_no BETWEEN 1 AND 30),
  title_ar       text NOT NULL,
  due_on         date,
  due_hint_ar    text,                       -- مثل: قبل نهاية الأسبوع السادس (الثلاثاء)
  condition_ar   text,                       -- مثل: في حال تطبيق أنماط التدريب في القسم
  notes_ar       text,
  sort_order     int NOT NULL DEFAULT 0,
  created_by     bigint REFERENCES app_user(id),
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_quality_task_cycle ON quality_task (cycle_id, week_no, sort_order);

-- ربط المهمة بمعيار فرعي (توافق عام) أو بمتطلب محدد (ينعكس عليه الشاهد تلقائياً)
CREATE TABLE IF NOT EXISTS quality_task_link (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  task_id          bigint NOT NULL REFERENCES quality_task(id) ON DELETE CASCADE,
  sub_standard_id  bigint REFERENCES sub_standard(id),
  requirement_id   bigint REFERENCES requirement(id),
  CHECK ((sub_standard_id IS NULL) <> (requirement_id IS NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_quality_task_link
  ON quality_task_link (task_id, COALESCE(sub_standard_id, 0), COALESCE(requirement_id, 0));

-- تسليم القسم للمهمة
CREATE TABLE IF NOT EXISTS quality_task_submission (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  task_id         bigint NOT NULL REFERENCES quality_task(id) ON DELETE CASCADE,
  department_id   bigint NOT NULL REFERENCES department(id),
  status          text NOT NULL CHECK (status IN ('submitted','approved','returned','na')),
  evidence_id     bigint REFERENCES evidence(id),
  note_ar         text,
  review_note_ar  text,
  linked_count    int NOT NULL DEFAULT 0,
  submitted_by    bigint REFERENCES app_user(id),
  submitted_at    timestamptz NOT NULL DEFAULT now(),
  reviewed_by     bigint REFERENCES app_user(id),
  reviewed_at     timestamptz,
  UNIQUE (task_id, department_id)
);

DROP TRIGGER IF EXISTS t_audit_quality_task ON quality_task;
CREATE TRIGGER t_audit_quality_task AFTER INSERT OR UPDATE OR DELETE ON quality_task FOR EACH ROW EXECUTE FUNCTION trg_audit();
DROP TRIGGER IF EXISTS t_audit_quality_sub ON quality_task_submission;
CREATE TRIGGER t_audit_quality_sub AFTER INSERT OR UPDATE OR DELETE ON quality_task_submission FOR EACH ROW EXECUTE FUNCTION trg_audit();


-- ربط مهام أعمال الجودة بنماذج المنصة (تُسلَّم المهمة من النموذج المعتمد دون رفع مكرر). آمن للتكرار.

ALTER TABLE quality_task ADD COLUMN IF NOT EXISTS form_code text;   -- رمز قالب النموذج (form_template.requirement_code)

-- المهام المحمّلة سابقاً: ربطها بالنماذج وتصحيح توافق ملف المدرب (المتطلب 4-1-3)
UPDATE quality_task SET form_code = CASE
    WHEN title_ar LIKE 'تقرير جاهزية%' THEN '3-1/جاهزية'
    WHEN title_ar LIKE 'تقرير تنفيذ الاختبار%' THEN '3-1/تنفيذ'
    WHEN title_ar LIKE '%تحليل نتائج المتدربين%' OR title_ar LIKE '%الإجراءات التحسينية لتحليل نتائج%'
      OR title_ar LIKE 'متابعة تنفيذ الخطط التحسينية%' THEN '2-2-2'
    WHEN title_ar LIKE 'متابعة تطبيق ورفع ملف المدرب%' THEN '4-1-3'
    WHEN title_ar LIKE 'تقرير خطط تحسين قياس جودة مخرجات%' THEN '2-2-1'
  END
 WHERE form_code IS NULL;

DELETE FROM quality_task_link l USING quality_task t, sub_standard ss
 WHERE l.task_id = t.id AND t.form_code = '4-1-3' AND ss.id = l.sub_standard_id AND ss.code IN ('3-3', '4-3');

-- النموذج المرتبط بمتطلب محدد: يُضاف المتطلب ومعياره الفرعي لتوافق المهمة
INSERT INTO quality_task_link (task_id, requirement_id)
SELECT t.id, r.id FROM quality_task t JOIN assessment_cycle c ON c.id = t.cycle_id
  JOIN standard s ON s.framework_id = c.framework_id JOIN sub_standard ss ON ss.standard_id = s.id
  JOIN requirement r ON r.sub_standard_id = ss.id AND r.code = t.form_code
 WHERE t.form_code IN ('2-2-2', '4-1-3', '2-2-1')
ON CONFLICT DO NOTHING;
INSERT INTO quality_task_link (task_id, sub_standard_id)
SELECT t.id, ss.id FROM quality_task t JOIN assessment_cycle c ON c.id = t.cycle_id
  JOIN standard s ON s.framework_id = c.framework_id JOIN sub_standard ss ON ss.standard_id = s.id
 WHERE t.form_code = '4-1-3' AND ss.code = '4-1'
ON CONFLICT DO NOTHING;


-- ربط مهام جودة المخرجات ومنصة المهارات بنماذجها. آمن للتكرار.
UPDATE quality_task SET form_code = '4-1/المهارات' WHERE form_code IS NULL AND title_ar LIKE '%منصة المهارات العملية%';
UPDATE quality_task SET form_code = '2-2/المخرجات' WHERE form_code IS NULL AND title_ar LIKE 'تقرير متطلبات وتهيئة المتدربين%';
UPDATE quality_task SET form_code = '2-2-1' WHERE form_code IS NULL AND title_ar LIKE 'تقرير تنفيذ قياس جودة مخرجات%';
INSERT INTO quality_task_link (task_id, requirement_id)
SELECT t.id, r.id FROM quality_task t JOIN assessment_cycle c ON c.id = t.cycle_id
  JOIN standard s ON s.framework_id = c.framework_id JOIN sub_standard ss ON ss.standard_id = s.id
  JOIN requirement r ON r.sub_standard_id = ss.id AND r.code = t.form_code
 WHERE t.form_code = '2-2-1'
ON CONFLICT DO NOTHING;

-- منهجية قياس أنماط التدريب: إطار اختياري لا يُفعَّل إلا باعتماد صاحب الصلاحية لنمط التدريب في الكلية.
-- جدول زيارات التقييم الخارجي، وارتباط مهام أعمال الجودة بتفعيل الأنماط. آمن للتكرار.

INSERT INTO framework (code, name_ar, issuer, version)
VALUES ('TVTC-PATTERNS', 'منهجية قياس أنماط التدريب', 'المؤسسة العامة للتدريب التقني والمهني', '2024')
ON CONFLICT (code) DO NOTHING;
TRUNCATE import_requirement_staging;
INSERT INTO import_requirement_staging VALUES
('1','التخطيط',1,'1-1','المسؤوليات والمهام',1,'1-1-1','شواهد اعتماد تطبيق أنماط التدريب المختلفة في المنشأة التدريبية',1,'institution',true,0),
('1','التخطيط',1,'1-1','المسؤوليات والمهام',1,'1-1-2','الخطة التنفيذية لتطبيق أنماط التدريب المختلفة',2,'institution',true,0),
('1','التخطيط',1,'1-1','المسؤوليات والمهام',1,'1-1-3','التصميم الموحد لملف المقرر التدريبي',3,'institution',true,0),
('2','التهيئة',2,'2-1','الجاهزية',1,'2-1-1','تقرير جاهزية المنشأة التدريبية لتطبيق أنماط التدريب',1,'institution',true,0),
('2','التهيئة',2,'2-2','التأهيل والمعرفة',2,'2-2-1','تقرير تأهيل وتهيئة المتدربين، والتوصيات وخطط التحسين',1,'institution',true,0),
('2','التهيئة',2,'2-2','التأهيل والمعرفة',2,'2-2-2','تقرير تأهيل وتهيئة المدربين، والتوصيات وخطط التحسين',2,'institution',true,0),
('3','التنفيذ',3,'3-1','المحتوى الإلكتروني',1,'3-1-1','توفر المحتوى الرئيسي للمقرر التدريبي والمصادر الإثرائية الداعمة',1,'institution',true,0),
('3','التنفيذ',3,'3-2','سهولة الوصول',2,'3-2-1','تقرير رضا المتدربين عن سهولة الوصول إلى المنصة الإلكترونية المعتمدة، والتوصيات وخطط التحسين',1,'institution',true,0),
('3','التنفيذ',3,'3-3','إدارة التواصل',3,'3-3-1','تقرير تفعيل وسائل التواصل مع المتدربين للرد على أسئلتهم واستفساراتهم بشكل مستمر باستخدام المنصات الإلكترونية المعتمدة',1,'institution',true,0),
('4','التقويم',4,'4-1','قياس الأثر',1,'4-1-1','تقرير رضا المتدربين عن فاعلية أنماط التدريب المختلفة، والتوصيات وخطط التحسين',1,'institution',true,0),
('4','التقويم',4,'4-1','قياس الأثر',1,'4-1-2','تقرير رضا المدربين عن فاعلية أنماط التدريب المختلفة، والتوصيات وخطط التحسين',2,'institution',true,0),
('4','التقويم',4,'4-1','قياس الأثر',1,'4-1-3','تحليل نتائج المتدربين في المقررات المطبق عليها أنماط التدريب المعتمدة (عن بعد - ذاتي)، والتوصيات وخطط التحسين',3,'institution',true,0);
SELECT import_framework_from_staging('TVTC-PATTERNS');

-- قرار اعتماد نمط التدريب للكلية في الدورة (دون قرار: الأنماط غير مفعّلة ومهامها «لا تنطبق»)
CREATE TABLE IF NOT EXISTS training_pattern_activation (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id           bigint NOT NULL REFERENCES assessment_cycle(id) ON DELETE CASCADE,   -- دورة نظام الجودة
  patterns_cycle_id  bigint REFERENCES assessment_cycle(id),                             -- دورة منهجية الأنماط المنشأة
  authority_ar       text NOT NULL,            -- صاحب الصلاحية
  decision_no        text,
  decision_date      date,
  patterns           text[] NOT NULL,          -- ذاتي / مدمج / عن بعد
  specialties        jsonb NOT NULL DEFAULT '[]',   -- التخصص، عدد المقررات، النمط، المستفيدون
  notes_ar           text,
  created_by         bigint REFERENCES app_user(id),
  created_at         timestamptz NOT NULL DEFAULT now(),
  revoked_at         timestamptz,
  revoke_reason_ar   text
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pattern_active ON training_pattern_activation (cycle_id) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS external_visit (
  id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id          bigint NOT NULL REFERENCES assessment_cycle(id) ON DELETE CASCADE,
  visit_date        date NOT NULL,
  program           text NOT NULL CHECK (program IN ('بكالوريوس','دبلوم','بكالوريوس ودبلوم')),
  supervisor_name   text,
  supervisor_phone  text,
  college_name      text,
  college_phone     text,
  executed          boolean,
  notes_ar          text,
  created_by        bigint REFERENCES app_user(id),
  created_at        timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE quality_task ADD COLUMN IF NOT EXISTS depends_on text CHECK (depends_on IN ('patterns'));
UPDATE quality_task SET depends_on = 'patterns' WHERE depends_on IS NULL AND condition_ar LIKE '%أنماط التدريب%';

DROP TRIGGER IF EXISTS t_audit_pattern_act ON training_pattern_activation;
CREATE TRIGGER t_audit_pattern_act AFTER INSERT OR UPDATE OR DELETE ON training_pattern_activation FOR EACH ROW EXECUTE FUNCTION trg_audit();
DROP TRIGGER IF EXISTS t_audit_ext_visit ON external_visit;
CREATE TRIGGER t_audit_ext_visit AFTER INSERT OR UPDATE OR DELETE ON external_visit FOR EACH ROW EXECUTE FUNCTION trg_audit();


-- منطقة المنشأة (تُكتب في ترويسة ملفات الإدارة). آمن للتكرار.
ALTER TABLE institution ADD COLUMN IF NOT EXISTS region_ar text;
UPDATE institution SET region_ar = 'المدينة المنورة' WHERE region_ar IS NULL AND name_ar LIKE '%ينبع%';

-- سير العملية التدريبية: تقرير التحضير الأسبوعي SO09 من رايات (صف لكل شعبة) وربط المدربين بالأقسام. آمن للتكرار.
-- لا تُخزَّن بيانات شخصية للمتدربين؛ الملف إحصائي على مستوى الشعبة.

CREATE TABLE IF NOT EXISTS attendance_upload (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id      bigint NOT NULL REFERENCES assessment_cycle(id) ON DELETE CASCADE,
  week_no       smallint NOT NULL CHECK (week_no BETWEEN 1 AND 30),
  period_from   date,
  period_to     date,
  file_name     text,
  row_count     int NOT NULL DEFAULT 0,
  uploaded_by   bigint REFERENCES app_user(id),
  uploaded_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (cycle_id, week_no)
);

CREATE TABLE IF NOT EXISTS attendance_section (
  id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  upload_id          bigint NOT NULL REFERENCES attendance_upload(id) ON DELETE CASCADE,
  trainer_no         text NOT NULL,
  trainer_name       text,
  section_ref        text,
  course_name        text,
  schedule_type      text,
  total              int, registered int, deprived int, withdrawn int,
  slots              int, present int, absent int, unlisted_active int, unlisted_inactive int,
  recording_pct      numeric(6,2)
);
CREATE INDEX IF NOT EXISTS ix_att_section_upload ON attendance_section (upload_id);

-- المدرب ← القسم (يُقترح تلقائياً من مقرراته ويؤكده وكيل الجودة مرة واحدة)
CREATE TABLE IF NOT EXISTS trainer_department (
  institution_id  bigint NOT NULL REFERENCES institution(id),
  trainer_no      text NOT NULL,
  trainer_name    text,
  department_id   bigint REFERENCES department(id),
  confirmed       boolean NOT NULL DEFAULT false,
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (institution_id, trainer_no)
);

DROP TRIGGER IF EXISTS t_audit_att_upload ON attendance_upload;
CREATE TRIGGER t_audit_att_upload AFTER INSERT OR DELETE ON attendance_upload FOR EACH ROW EXECUTE FUNCTION trg_audit();
