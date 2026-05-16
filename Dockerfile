FROM python:3.11-slim

WORKDIR /app

# Install deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy ALL source files in one layer — avoids Railway Metal builder cache-key bug
COPY . .

# Verify src module is present (fail fast if missing)
RUN python -c "import os; assert os.path.exists('src/__init__.py'), 'src/__init__.py missing!'"

CMD ["python", "main.py"]
