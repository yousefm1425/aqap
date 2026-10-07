#!/usr/bin/env bash
# تجهيز قاعدة بيانات التطوير: المخطط + بيانات العرض (مرة واحدة)، واستيراد النموذج الرسمي إن وُضع في templates/
set -euo pipefail
cd "$(dirname "$0")/.."
DB_URL="${AQAP_DATABASE_URL:-postgresql://aqap:aqap@localhost:5432/aqap}"

echo "⏳ انتظار قاعدة البيانات…"
for _ in $(seq 1 60); do psql "$DB_URL" -qc 'SELECT 1' >/dev/null 2>&1 && break; sleep 1; done

if psql "$DB_URL" -tAc "SELECT to_regclass('aqap.assessment')" | grep -q assessment; then
  echo "✓ المخطط موجود مسبقاً"
else
  psql "$DB_URL" -q -v ON_ERROR_STOP=1 -f db/schema.sql
  if [ -f templates/model.xlsb ]; then
    echo "✓ استيراد النموذج الرسمي من templates/model.xlsb"
    psql "$DB_URL" -q -v ON_ERROR_STOP=1 <<'SQL'
SET search_path = aqap;
INSERT INTO institution(code, name_ar) VALUES ('YNB', 'الكلية التقنية التطبيقية بينبع');
INSERT INTO app_user(institution_id, email, full_name_ar) VALUES (1, 'dean@ynb', 'وكيل الجودة');
INSERT INTO user_role(user_id, role) VALUES (1, 'quality_dean');
INSERT INTO assessment_cycle(institution_id, framework_id, title_ar, academic_year, starts_on, ends_on, status)
  VALUES (1, 1, 'التقييم الذاتي 1447هـ', '1447', '2026-09-01', '2027-05-31', 'open');
SQL
    python scripts/import_xlsb.py templates/model.xlsb --dsn "$DB_URL" --institution-id 1 --cycle-id 1 --actor-id 1
  else
    echo "✓ تحميل بيانات العرض (نصوص تجريبية)"
    python scripts/seed_demo.py "$DB_URL"
  fi
fi
