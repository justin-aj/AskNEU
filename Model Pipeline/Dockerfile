FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY ["Model Pipeline/Model Evaluation/requirements.txt", "./requirements.txt"]
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY ["Model Pipeline/model.py", "./model.py"]
COPY ["Model Pipeline/config.py", "./config.py"]


# Run the application
ENV PYTHONPATH=/app
CMD ["python", "model.py"]
