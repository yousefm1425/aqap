-- مكتبة الأدلة وتدقيق إدارة المستخدمين. آمن للتكرار.
BEGIN;
SET search_path = aqap, public;

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
COMMIT;
