FROM python:3.12-slim
ARG WORKER
ENV WORKER=${WORKER}
WORKDIR /app
ENV PYTHONPATH=/app
COPY workers/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY workers/${WORKER} workers/${WORKER}
COPY workers/interface.py workers/interface.py
COPY common common
COPY logger logger
COPY storage storage
COPY coordinator coordinator
CMD python workers/$WORKER/entrypoint.py