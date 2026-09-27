FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-api.txt ./
# CPU-only torch keeps the image ~1 GB smaller
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch && pip install -r requirements.txt -r requirements-api.txt
COPY src ./src
COPY backend ./backend
COPY configs ./configs
COPY alembic ./alembic
COPY alembic.ini ./
RUN useradd -m app && mkdir -p data results models mlruns && chown -R app /app
USER app
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
