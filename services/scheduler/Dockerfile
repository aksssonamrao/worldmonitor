FROM python:3.11-slim

WORKDIR /app

COPY services/backend_api/requirements.txt /tmp/backend_requirements.txt
RUN pip install --no-cache-dir -r /tmp/backend_requirements.txt

COPY services/backend_api/app /app/app
COPY services/scheduler/main.py /app/main.py

CMD ["python", "main.py"]
