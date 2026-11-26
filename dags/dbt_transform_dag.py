"""
dbt Transform DAG
-----------------
Wait for the OpenSky ingestion DAG for the same logical date,
then run dbt deps, seed, run and test against PostgreSQL.

Scheduled runs are aligned with opensky_flights_to_postgres.
"""

from datetime import timedelta

import pendulum

from airflow.decorators import dag
from airflow.operators.bash import BashOperator
from airflow.sensors.external_task import ExternalTaskSensor


DBT_PROJECT_DIR = "/opt/airflow/dbt"
DBT_PROFILES_DIR = "/opt/airflow/dbt"
DBT_VENV_BIN = "/opt/dbt-venv/bin"

default_args = {
    "owner": "analytics-academy",
    "retries": 1,
    "retry_delay": timedelta(minutes=3),
}


@dag(
    dag_id="dbt_transform",
    default_args=default_args,
    description="Wait for OpenSky ingestion, then run dbt seed, models and tests",
    schedule="@daily",
    start_date=pendulum.datetime(2025, 3, 15, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["dbt", "postgres", "transform"],
)
def dbt_transform_dag():

    wait_for_opensky = ExternalTaskSensor(
        task_id="wait_for_opensky",
        external_dag_id="opensky_flights_to_postgres",
        external_task_id=None,
        allowed_states=["success"],
        failed_states=["failed"],
        check_existence=True,
        mode="reschedule",
        poke_interval=60,
        timeout=6 * 60 * 60,
        retries=0,
    )

    dbt_deps = BashOperator(
        task_id="dbt_deps",
        bash_command=(
            f"cd {DBT_PROJECT_DIR} && "
            f"{DBT_VENV_BIN}/dbt deps "
            f"--profiles-dir {DBT_PROFILES_DIR}"
        ),
    )

    dbt_seed = BashOperator(
        task_id="dbt_seed",
        bash_command=(
            f"cd {DBT_PROJECT_DIR} && "
            f"{DBT_VENV_BIN}/dbt seed "
            f"--profiles-dir {DBT_PROFILES_DIR}"
        ),
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=(
            f"cd {DBT_PROJECT_DIR} && "
            f"{DBT_VENV_BIN}/dbt run "
            f"--profiles-dir {DBT_PROFILES_DIR}"
        ),
    )

    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=(
            f"cd {DBT_PROJECT_DIR} && "
            f"{DBT_VENV_BIN}/dbt test "
            f"--profiles-dir {DBT_PROFILES_DIR}"
        ),
    )

    wait_for_opensky >> dbt_deps >> dbt_seed >> dbt_run >> dbt_test


dbt_transform_dag()
