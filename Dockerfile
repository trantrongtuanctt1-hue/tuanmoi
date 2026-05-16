FROM python:3.11-slim

WORKDIR /app

# Install deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source explicitly
COPY main.py .
COPY src/ ./src/

CMD ["python", "main.py"]
