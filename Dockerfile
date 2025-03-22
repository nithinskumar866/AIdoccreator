# ✅ Use Python 3.10 base image
FROM python:3.10-slim

# ✅ Install system dependencies required for dlib
RUN apt-get update && apt-get install -y \
    cmake \
    python3-dev \
    g++ \
    libx11-dev \
    libgtk-3-dev \
    libboost-python-dev

# ✅ Set the working directory inside the container
WORKDIR /app

# ✅ Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ✅ Install dlib separately using pre-built wheels
RUN pip install dlib==19.22.99

# ✅ Copy all app files into the Docker container
COPY . .

# ✅ Expose the port used by Flask
EXPOSE 10000

# ✅ Start the Flask app using Gunicorn
CMD ["gunicorn", "app:app"]
