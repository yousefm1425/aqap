#!/usr/bin/env bash
# تشغيل المنصة في الخلفية على المنفذ 8000 (Codespaces يفتحه تلقائياً)
# setsid يفصل الخادم عن جلسة أمر التشغيل حتى لا يُغلق عند انتهائها
cd "$(dirname "$0")/.."
pkill -f "uvicorn app.main:app" 2>/dev/null || true
setsid nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers > /tmp/aqap.log 2>&1 < /dev/null &
for _ in $(seq 1 20); do
  curl -sf -o /dev/null http://localhost:8000/api/v1/health 2>/dev/null && { echo "✓ المنصة تعمل: افتح المنفذ 8000"; exit 0; }
  curl -s -o /dev/null http://localhost:8000/ 2>/dev/null && { echo "✓ المنصة تعمل: افتح المنفذ 8000"; exit 0; }
  sleep 1
done
echo "✗ لم يبدأ الخادم — آخر سطور السجل (/tmp/aqap.log):"
tail -30 /tmp/aqap.log
