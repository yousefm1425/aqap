# Debian لأن تصدير النموذج الرسمي يشغّل LibreOffice عبر UNO، وحزمة python3-uno مبنية لبايثون النظام
FROM debian:bookworm-slim
ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-uno libreoffice-calc-nogui fonts-noto-core fonts-noto-ui-core libpango-1.0-0 libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*
# --system-site-packages ليصل التطبيق إلى وحدة uno المثبتة مع النظام
RUN python3 -m venv --system-site-packages /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY frontend ./frontend
COPY scripts ./scripts
COPY db ./db
RUN useradd --create-home --uid 10001 aqap && chown -R aqap /srv
USER aqap
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
