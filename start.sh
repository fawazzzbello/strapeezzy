#!/bin/bash
set -e
PORT=${PORT:-8000}
echo "Starting Strapeezzy on port $PORT"
exec python -m uvicorn main:app --host 0.0.0.0 --port "$PORT"
