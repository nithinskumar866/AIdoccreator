# ✅ Use official Python image
FROM python:3.10-slim

# ✅ Set working directory
WORKDIR /app

# ✅ Install system dependencies
RUN apt-get update && \
    apt-get install -y \
    build-essential \
    python3-dev \
    libpq-dev \
    cmake \
    && rm -rf /var/lib/apt/lists/*

# ✅ Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ✅ Copy app files
COPY . .

# ✅ Set environment variables
ENV PYTHONUNBUFFERED=1

# ✅ Start the app
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8080"]
