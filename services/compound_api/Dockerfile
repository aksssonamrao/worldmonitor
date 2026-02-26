FROM python:3.12-slim

WORKDIR /app

RUN addgroup --system appuser \
    && adduser --system --ingroup appuser appuser

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN chown -R appuser:appuser /app

USER appuser
EXPOSE 8090

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090"]
