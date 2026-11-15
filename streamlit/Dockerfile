FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir streamlit snowflake-connector-python pandas python-dotenv plotly

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "backfill_dashboard.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.enableCORS=false", "--server.enableXsrfProtection=false"]
