-- الدخول بالبريد وكلمة المرور واستعادتها بالبريد. آمن للتكرار.
-- كلمات المرور في جدول مستقل عن app_user حتى لا تدخل تجزئتها سجل التدقيق.
BEGIN;
SET search_path = aqap, public;
CREATE TABLE IF NOT EXISTS user_credential (
  user_id        bigint PRIMARY KEY REFERENCES app_user(id) ON DELETE CASCADE,
  password_hash  text NOT NULL,
  changed_at     timestamptz NOT NULL DEFAULT now(),
  failed_count   int NOT NULL DEFAULT 0,
  locked_until   timestamptz,
  last_login_at  timestamptz
);
-- روابط لمرة واحدة: استعادة كلمة المرور، ودعوة حساب جديد لتعيينها. تُحفظ بصمة الرمز فقط.
CREATE TABLE IF NOT EXISTS auth_token (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  purpose     text NOT NULL CHECK (purpose IN ('reset', 'invite')),
  token_hash  text NOT NULL UNIQUE,
  expires_at  timestamptz NOT NULL,
  used_at     timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_auth_token_user ON auth_token (user_id);
COMMIT;
