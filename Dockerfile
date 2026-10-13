FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AVELORA_ONLINE=1 AVELORA_DATA_DIR=/data PORT=8080
WORKDIR /app
COPY server.py rules.py offline_data.json ./
COPY static ./static
EXPOSE 8080
CMD ["python","server.py","--no-browser"]
