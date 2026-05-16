FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy explicitly để tránh Railway bỏ sót
COPY main.py .
COPY src/ ./src/

CMD ["python", "-u", "main.py"]
