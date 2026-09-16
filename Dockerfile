FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py runtime_settings.py unified_routes.py ./
COPY admin.html portal.html portal.js portal.css shared.js brand.png ./
COPY quality ./quality

ENV MIELL_DATA_DIR=/data
VOLUME ["/data"]

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}"]
