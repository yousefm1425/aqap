-- الشواهد بالروابط ومجلدات OneDrive/SharePoint. آمن للتكرار.
BEGIN;
SET search_path = aqap, public;

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
COMMIT;
