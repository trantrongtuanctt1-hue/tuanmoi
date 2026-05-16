FROM python:3.11-slim

WORKDIR /app

# Install deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy ALL source files in one layer — avoids Railway Metal builder cache-key bug
COPY . .


CMD ["python", "main.py"]
