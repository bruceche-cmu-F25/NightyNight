FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app


COPY langgraph/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY langgraph/ /app
COPY sounds/ /sounds

# Critical: let Python import from src/
ENV PYTHONPATH=/app/src
ENV SOUNDS_DIR=/sounds

EXPOSE 8000
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8000"]