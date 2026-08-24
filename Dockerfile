FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN useradd --create-home --uid 10001 plata

COPY requirements.txt .
RUN pip install --no-cache-dir -U -r requirements.txt

COPY . .

RUN chown -R plata:plata /app
USER plata

VOLUME ["/app/configs", "/app/logs", "/app/storage", "/app/plugins"]

CMD ["python", "main.py"]
