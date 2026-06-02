FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer — only rebuilds when requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Make the entrypoint executable
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

# Entrypoint seeds the DB on first run, then starts uvicorn
ENTRYPOINT ["./docker-entrypoint.sh"]
