FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir -e . && pip install --no-cache-dir fastapi uvicorn
COPY . .

CMD ["uvicorn", "src.web.server:app", "--host", "0.0.0.0", "--port", "8080"]
