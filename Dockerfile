FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PYTHONUNBUFFERED=1 DOCUMENTOR_DATA_DIR=/app/data
RUN useradd --create-home app && mkdir -p /app/data && chown -R app /app
USER app
VOLUME /app/data
EXPOSE 8080

# Binds inside the container only. Publish it as 127.0.0.1:10000:8080 (see the README).
# One worker keeps background tasks and the SQLite database in a single process.
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "--timeout", "120"]
