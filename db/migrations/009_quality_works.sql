-- أعمال الجودة: جدول مهام متابعة الجودة الأسبوعي وربطها بالمعايير الفرعية والمتطلبات. آمن للتكرار.
BEGIN;
SET search_path = aqap, public;

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

COMMIT;
