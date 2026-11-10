
redis-server --daemonize yes

cd /app/backend/src && taskiq scheduler background.worker:scheduler &
cd /app/backend/src && taskiq worker background.worker:broker &
cd /app/backend/src && uvicorn main:app --host 0.0.0.0 


