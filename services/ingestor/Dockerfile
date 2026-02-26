FROM python:3.12-slim

RUN groupadd --system appuser && useradd --system --gid appuser --create-home appuser

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY config ./config
RUN chown -R appuser:appuser /app

USER appuser
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8092"]
