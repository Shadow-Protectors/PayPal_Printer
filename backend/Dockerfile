FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN groupadd --gid 10001 achuppori \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin achuppori
COPY requirements.txt ./requirements.txt
RUN python -m pip install -r requirements.txt
COPY --chown=10001:10001 app/ ./app/
COPY --chown=10001:10001 deployment_check.py ./deployment_check.py
USER 10001:10001
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=127.0.0.1"]
