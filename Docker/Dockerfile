FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY Docker/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY proxy.py .

EXPOSE 8765

RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

CMD ["python", "proxy.py"]
