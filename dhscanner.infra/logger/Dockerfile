FROM python:3.12-slim
WORKDIR /app
COPY logger/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY common common
COPY logger logger
EXPOSE 8000
CMD ["uvicorn", "logger.server:app", "--host", "0.0.0.0", "--port", "8000"]