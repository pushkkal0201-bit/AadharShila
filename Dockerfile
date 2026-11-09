FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
WORKDIR /app
COPY requirements.txt pyproject.toml ./
COPY src ./src
COPY web ./web
COPY policies ./policies
COPY docs ./docs
COPY data ./data
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-deps -e . && useradd -m -u 10001 app && mkdir -p /app/var/documents && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn aadharshila.main:app --host 0.0.0.0 --port 8000"]
