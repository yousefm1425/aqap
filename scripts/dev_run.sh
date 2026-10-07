#!/usr/bin/env bash
# تشغيل المنصة في الخلفية على المنفذ 8000 (Codespaces يفتحه تلقائياً)
cd "$(dirname "$0")/.."
pkill -f "uvicorn app.main:app" 2>/dev/null || true
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers > /tmp/aqap.log 2>&1 &
echo "✓ المنصة تعمل: افتح المنفذ 8000 (السجل: /tmp/aqap.log)"
