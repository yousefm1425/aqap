-- الاستبيانات: ثلاثة استبيانات لكل دورة (المتدرب، المدرب، الخدمات للجميع) تُعبَّأ في Microsoft Forms المقيّد بحساب المؤسسة،
-- وتُرفع ردودها المصدَّرة (Excel) لحساب الإحصاءات. لا يُخزَّن البريد ولا الاسم من ملف الردود. آمن للتكرار.
BEGIN;
SET search_path = aqap, public;

CREATE TABLE IF NOT EXISTS survey (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cycle_id      bigint NOT NULL REFERENCES assessment_cycle(id) ON DELETE CASCADE,
  kind          text NOT NULL CHECK (kind IN ('trainee', 'trainer', 'services')),
  title_ar      text NOT NULL CHECK (length(title_ar) BETWEEN 3 AND 200),
  form_url      text,
  results_url   text,
  opens_on      date,
  closes_on     date,
  questions     jsonb NOT NULL DEFAULT '[]'::jsonb,
  source_name   text,
  uploaded_by   bigint REFERENCES app_user(id),
  uploaded_at   timestamptz,
  updated_by    bigint REFERENCES app_user(id),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (cycle_id, kind),
  CHECK (closes_on IS NULL OR opens_on IS NULL OR closes_on >= opens_on)
);

CREATE TABLE IF NOT EXISTS survey_response (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  survey_id     bigint NOT NULL REFERENCES survey(id) ON DELETE CASCADE,
  ext_id        text NOT NULL,
  submitted_at  timestamptz,
  answers       jsonb NOT NULL,
  UNIQUE (survey_id, ext_id)
);

DROP TRIGGER IF EXISTS t_audit_survey ON survey;
CREATE TRIGGER t_audit_survey AFTER INSERT OR UPDATE OR DELETE ON survey FOR EACH ROW EXECUTE FUNCTION trg_audit();
COMMIT;
