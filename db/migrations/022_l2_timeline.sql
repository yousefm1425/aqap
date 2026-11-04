-- الخط الزمني لتنفيذ متطلبات نظام الجودة (المستوى الثاني): أسابيع التقويم التدريبي، ومواعيد كل متطلب،
-- والمسؤول (Planner) لكل قسم، وإنجاز القسم لكل موعد مع ربط شاهده بتقدير المتطلب. آمن للتكرار.
BEGIN;
SET search_path = aqap, public;

-- أسابيع التقويم التدريبي للدورة (الإجازات لا تُحسب أسابيع)
CREATE TABLE IF NOT EXISTS training_week (
  cycle_id   bigint NOT NULL REFERENCES assessment_cycle(id) ON DELETE CASCADE,
  semester   smallint NOT NULL CHECK (semester IN (1, 2)),
  week_no    smallint NOT NULL CHECK (week_no BETWEEN 1 AND 22),
  starts_on  date NOT NULL,
  is_exam    boolean NOT NULL DEFAULT false,
  PRIMARY KEY (cycle_id, semester, week_no)
);

-- موعد تنفيذ متطلب: أسبوع محدد، أو موعد بلا أسبوع (مستمر / ملف موحد) week_no = NULL
CREATE TABLE IF NOT EXISTS l2_schedule (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id        bigint NOT NULL REFERENCES assessment_cycle(id) ON DELETE CASCADE,
  requirement_id  bigint NOT NULL REFERENCES requirement(id),
  semester        smallint NOT NULL CHECK (semester IN (1, 2)),
  week_no         smallint CHECK (week_no BETWEEN 1 AND 22),
  label_ar        text,
  created_by      bigint REFERENCES app_user(id),
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_l2_schedule ON l2_schedule (cycle_id, requirement_id, semester, COALESCE(week_no, 0));
CREATE INDEX IF NOT EXISTS ix_l2_schedule_req ON l2_schedule (requirement_id);

-- المسؤول عن المتطلب في القسم
CREATE TABLE IF NOT EXISTS l2_planner (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id        bigint NOT NULL REFERENCES assessment_cycle(id) ON DELETE CASCADE,
  requirement_id  bigint NOT NULL REFERENCES requirement(id),
  department_id   bigint NOT NULL REFERENCES department(id),
  owner_name_ar   text NOT NULL,
  updated_by      bigint REFERENCES app_user(id),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (cycle_id, requirement_id, department_id)
);
CREATE INDEX IF NOT EXISTS ix_l2_planner_dept ON l2_planner (department_id);

-- إنجاز القسم لموعد
CREATE TABLE IF NOT EXISTS l2_progress (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  schedule_id    bigint NOT NULL REFERENCES l2_schedule(id) ON DELETE CASCADE,
  department_id  bigint NOT NULL REFERENCES department(id),
  status         text NOT NULL CHECK (status IN ('done', 'na')),
  evidence_id    bigint REFERENCES evidence(id),
  note_ar        text,
  linked         boolean NOT NULL DEFAULT false,
  done_by        bigint REFERENCES app_user(id),
  done_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (schedule_id, department_id)
);
CREATE INDEX IF NOT EXISTS ix_l2_progress_dept ON l2_progress (department_id);
CREATE INDEX IF NOT EXISTS ix_l2_progress_evidence ON l2_progress (evidence_id);

DROP TRIGGER IF EXISTS t_audit_l2_schedule ON l2_schedule;
CREATE TRIGGER t_audit_l2_schedule AFTER INSERT OR UPDATE OR DELETE ON l2_schedule FOR EACH ROW EXECUTE FUNCTION trg_audit();
DROP TRIGGER IF EXISTS t_audit_l2_progress ON l2_progress;
CREATE TRIGGER t_audit_l2_progress AFTER INSERT OR UPDATE OR DELETE ON l2_progress FOR EACH ROW EXECUTE FUNCTION trg_audit();
DROP TRIGGER IF EXISTS t_audit_l2_planner ON l2_planner;
CREATE TRIGGER t_audit_l2_planner AFTER INSERT OR UPDATE OR DELETE ON l2_planner FOR EACH ROW EXECUTE FUNCTION trg_audit();
COMMIT;
