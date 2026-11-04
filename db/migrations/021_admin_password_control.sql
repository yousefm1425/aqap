-- لوحة تحكم مدير النظام بالحسابات: كلمة مرور مؤقتة يجب تغييرها عند أول دخول. آمن للتكرار.
BEGIN;
SET search_path = aqap, public;
ALTER TABLE user_credential ADD COLUMN IF NOT EXISTS must_change boolean NOT NULL DEFAULT false;
COMMIT;
