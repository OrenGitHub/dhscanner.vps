FROM python:3.12-slim
WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app /app/app
COPY common common
COPY logger logger
COPY storage storage
COPY coordinator coordinator
EXPOSE 8000
COPY app/entrypoint.sh .
RUN chmod +x /app/entrypoint.sh
CMD ["app/entrypoint.sh"]