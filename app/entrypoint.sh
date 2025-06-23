#!/bin/bash
cd /app
python -m app.init_db
sleep 5
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 8 --proxy-headers --no-access-log