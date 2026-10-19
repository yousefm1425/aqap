-- المتدربون المستمرون والبرامج: تقرير ST06 من رايات (صف لكل قسم/برنامج/فترة). آمن للتكرار.
-- لقطتان لكل فصل: «بداية الفصل» (أول رفع، للمقارنة) و«الأحدث» (يستبدله كل رفع جديد). أعداد إجمالية فقط.
BEGIN;
SET search_path = aqap, public;

CREATE TABLE IF NOT EXISTS enrollment_upload (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id      bigint NOT NULL REFERENCES assessment_cycle(id) ON DELETE CASCADE,
  slot          text NOT NULL CHECK (slot IN ('baseline', 'latest')),
  term_label    text,
  file_name     text,
  uploaded_by   bigint REFERENCES app_user(id),
  uploaded_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (cycle_id, slot)
);

CREATE TABLE IF NOT EXISTS enrollment_row (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  upload_id     bigint NOT NULL REFERENCES enrollment_upload(id) ON DELETE CASCADE,
  dept_name     text NOT NULL,          -- كما في رايات؛ يُطابق بأقسام المنصة عند القراءة
  program       text NOT NULL,
  stage         text,
  shift         text,
  trainees      int NOT NULL CHECK (trainees >= 0)
);
CREATE INDEX IF NOT EXISTS ix_enrollment_row_upload ON enrollment_row (upload_id);

DROP TRIGGER IF EXISTS t_audit_enrollment_upload ON enrollment_upload;
CREATE TRIGGER t_audit_enrollment_upload AFTER INSERT OR DELETE ON enrollment_upload FOR EACH ROW EXECUTE FUNCTION trg_audit();
COMMIT;
