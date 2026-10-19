-- سير العملية التدريبية: تقرير التحضير الأسبوعي SO09 من رايات (صف لكل شعبة) وربط المدربين بالأقسام. آمن للتكرار.
-- لا تُخزَّن بيانات شخصية للمتدربين؛ الملف إحصائي على مستوى الشعبة.
BEGIN;
SET search_path = aqap, public;

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
COMMIT;
