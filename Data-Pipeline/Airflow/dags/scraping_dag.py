from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonVirtualenvOperator, PythonOperator
from airflow.utils.dates import days_ago
from airflow.exceptions import AirflowFailException
from airflow.providers.google.common.hooks.base_google import GoogleBaseHook
from airflow.hooks.base import BaseHook
import json
from google.cloud import storage
from airflow.models import Variable
import os
import subprocess
import logging

from src import Scrape_script

# from src import test_scraper

# 🛠 CONFIGURATION
SCRAPED_TEXT_DIR = "/opt/airflow/dags/src/scraped_texts"
SCRAPING_SCRIPT_PATH = "/opt/airflow/dags/src/Scrape_script.py"
UNITTEST_SCRIPT_PATH = "/opt/airflow/dags/src/test_scraper.py"
GCS_BUCKET_NAME = Variable.get("GCS_BUCKET_NAME")  # 🔹 Replace with actual GCS bucket


default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date": days_ago(1),
    "retries": 2,
}


# ✅ Function: Validate Scraped Text
def validate_scraped_text():
    """Checks if at least one .txt file is created after scraping."""
    files = [f for f in os.listdir(SCRAPED_TEXT_DIR) if f.endswith(".txt")]
    if not files:
        raise AirflowFailException("No .txt files found after scraping!")
    logging.info(f"✅ Scraped {len(files)} text files successfully.")


# ✅ Function: Version Control with DVC
def dvc_push_to_gcs():
    """Tracks new data with DVC and pushes changes to GCS."""
    try:

        # intialize DVC
        subprocess.run(["dvc", "init", "--no-scm", "-f"], check=True)

        # add remote storage
        subprocess.run(
            [
                "dvc",
                "remote",
                "add",
                "-d",
                "my_gcs",
                "$DVC_REMOTE",
            ],
            check=True,
        )

        # Track data with DVC
        subprocess.run(["dvc", "add", SCRAPED_TEXT_DIR], check=True)

        # Push to GCS
        subprocess.run(["dvc", "push"], check=True)

        logging.info("✅ DVC successfully tracked and pushed data to GCS.")
    except subprocess.CalledProcessError as e:
        raise AirflowFailException(f"❌ DVC push to GCS failed: {e}")


# ✅ Function: Upload Files to GCS using Airflow Stored Credentials
def upload_to_gcs():
    """Uploads text files to Google Cloud Storage (GCS) using Airflow stored credentials."""
    try:
        # 🔹 Fetch credentials from Airflow UI Connection
        gcp_hook = GoogleBaseHook(gcp_conn_id="gcp_service_account")
        credentials = gcp_hook.get_credentials()

        # 🔹 Initialize Google Cloud Storage Client with retrieved credentials
        storage_client = storage.Client(credentials=credentials)
        bucket = storage_client.bucket(GCS_BUCKET_NAME)

        for file_name in os.listdir(SCRAPED_TEXT_DIR):
            file_path = os.path.join(SCRAPED_TEXT_DIR, file_name)
            if os.path.isfile(file_path):
                blob = bucket.blob(f"scraped_texts/{file_name}")
                blob.upload_from_filename(file_path)
                logging.info(
                    f"✅ Uploaded {file_name} to GCS bucket: {GCS_BUCKET_NAME}"
                )

        logging.info("✅ All files uploaded successfully!")
    except Exception as e:
        raise AirflowFailException(f"❌ Failed to upload to GCS: {e}")


with open("/opt/airflow/dags/src/requirements.txt") as f:
    script_requirements = f.read().splitlines()

# 🏗 DAG Definition
with DAG(
    dag_id="scraping_pipeline_gcs",
    default_args=default_args,
    description="Automated web scraping DAG with validation, DVC, and GCS storage",
    schedule_interval="@daily",
    catchup=False,
) as dag:

    # ✅ Step 1: Run Unit Tests Before Scraping
    install_requirements = BashOperator(
        task_id="install_requirements",
        bash_command="pip install -r /opt/airflow/dags/src/requirements.txt",
        dag=dag,
    )

    set_gcs_vars = BashOperator(
        task_id="set_env_vars",
        bash_command="export GOOGLE_APPLICATION_CREDENTIALS=/opt/airflow/dags/src/gcs_creds.json",
        dag=dag,
    )

    set_dvc_vars = BashOperator(
        task_id="set_dvc_vars",
        bash_command=f"export DVC_REMOTE={GCS_BUCKET_NAME}",
        dag=dag,
    )

    run_unittests = BashOperator(
        task_id="run_unittests", bash_command=f"pytest {UNITTEST_SCRIPT_PATH}"
    )
    # task = PythonVirtualenvOperator(
    #     task_id="test_python_env",
    #     python_callable=src.test_scraper,
    #     requirements=script_requirements,  # Pass requirements dynamically
    # )

    # ✅ Step 2: Run Scraping Script
    extract_data = BashOperator(
        task_id="extract_data",
        bash_command=f"mkdir -p {SCRAPED_TEXT_DIR} && python {SCRAPING_SCRIPT_PATH} && true",
    )
    # extract_data = PythonOperator(
    #     task_id="extract_data",
    #     python_callable=Scrape_script,
    # )

    # ✅ Step 3: Validate Scraped Text Files
    validate_data = PythonOperator(
        task_id="validate_data",
        python_callable=validate_scraped_text,
    )

    # ✅ Step 4: Add and Push Data to DVC
    dvc_push = PythonOperator(
        task_id="dvc_push",
        python_callable=dvc_push_to_gcs,
    )

    # ✅ Step 5: Upload Scraped Data to GCS
    # upload_data = PythonOperator(
    #     task_id="upload_data",
    #     python_callable=upload_to_gcs,
    # )

    # ❌ Step 6: Send Alert if Failure Occurs
    alert_failure = BashOperator(
        task_id="alert_failure",
        bash_command="echo '❌ Scraping Failed! Check Airflow logs.'",
        trigger_rule="one_failed",
    )

    # DAG Task Execution Order
    (install_requirements >> run_unittests >> extract_data >> validate_data >> dvc_push)
    [run_unittests, extract_data, validate_data, dvc_push] >> alert_failure
