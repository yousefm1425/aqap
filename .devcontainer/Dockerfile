FROM mcr.microsoft.com/devcontainers/base:bookworm
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip python3-uno libreoffice-calc-nogui fonts-noto-core postgresql-client libpango-1.0-0 libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv --system-site-packages /opt/venv && chown -R vscode /opt/venv
ENV PATH=/opt/venv/bin:$PATH
