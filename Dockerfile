FROM apache/airflow:2.10.4-python3.11

# Copia e installa le dipendenze Python globali
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

# Passa a root per creare l'ambiente virtuale di dbt e impostare i permessi
USER root
RUN python3 -m venv /opt/dbt-venv && \
    /opt/dbt-venv/bin/pip install --no-cache-dir dbt-snowflake==1.9.0 && \
    chown -R airflow:root /opt/dbt-venv

# Torna all'utente Airflow per la sicurezza
USER airflow

# Configura le variabili d'ambiente e copia il progetto dbt
ENV DBT_VENV_PATH=/opt/dbt-venv/bin
COPY dbt /opt/airflow/dbt

WORKDIR /opt/airflow