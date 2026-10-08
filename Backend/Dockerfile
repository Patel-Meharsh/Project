FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg2 + cairo (for xhtml2pdf PDF generation)
RUN apt-get update && apt-get install -y \
    libpq-dev gcc \
    libcairo2-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x start.sh
EXPOSE 8000

CMD ["./start.sh"]
