web: gunicorn --bind 0.0.0.0:$PORT --workers 3 --timeout 120 grants_aggregator.wsgi:application
celery: celery -A grants_aggregator worker -l info
scraper: cd python_scraper && uvicorn app.main:app --host 0.0.0.0 --port $PORT

