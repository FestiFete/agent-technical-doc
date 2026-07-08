FROM --platform=linux/arm64 python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py .
COPY instructions.md .
COPY docagent ./docagent

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV OTEL_PYTHON_DISABLED_INSTRUMENTATIONS="requests,urllib3"

EXPOSE 8080

CMD ["opentelemetry-instrument", "python", "agent.py"]
