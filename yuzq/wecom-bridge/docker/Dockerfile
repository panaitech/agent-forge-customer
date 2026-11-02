# 职责：构建雨中情 WeCom Bridge 运行镜像（本地 dev 与腾讯云共用同一 Dockerfile）。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN useradd --create-home --uid 10001 bridge \
 && mkdir -p /app/data /app/config \
 && chown -R bridge:bridge /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY scripts /app/scripts
# 默认空例外表；生产通过 volume 挂载覆盖
COPY docker/exceptions.empty.json /app/config/exceptions.json

RUN chown -R bridge:bridge /app

USER bridge
EXPOSE 8787

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=12 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=2)"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8787"]
