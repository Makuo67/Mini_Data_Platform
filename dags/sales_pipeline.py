"""
Sales data pipeline: MinIO (CSV) → clean/transform → PostgreSQL.

Schedule: every 5 minutes. Idempotent — already-processed files are
tracked in the `processed_files` table so re-runs are safe.
"""
from __future__ import annotations

import io
import logging
import os
from datetime import timedelta

import boto3
import pandas as pd
import psycopg2
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.utils.dates import days_ago
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

# ── connection config ──────────────────────────────────────────────────────────
MINIO_ENDPOINT  = os.getenv("MINIO_ENDPOINT",        "minio:9000")
MINIO_ACCESS    = os.getenv("MINIO_ACCESS_KEY",       "minioadmin")
MINIO_SECRET    = os.getenv("MINIO_SECRET_KEY",       "minioadmin")
SOURCE_BUCKET   = "sales-data"
ARCHIVE_BUCKET  = "processed-data"

PG = dict(
    host     = os.getenv("POSTGRES_HOST",         "postgres"),
    port     = int(os.getenv("POSTGRES_PORT",     "5432")),
    dbname   = os.getenv("DATAPLATFORM_DB",       "dataplatform"),
    user     = os.getenv("DATAPLATFORM_USER",     "dataplatform"),
    password = os.getenv("DATAPLATFORM_PASSWORD", "dataplatform"),
)

DEFAULT_ARGS = {
    "owner": "okeke",
    "retries": 2,
    "retry_delay": timedelta(minutes=3),
    "email_on_failure": False,
}


# ── helpers ───────────────────────────────────────────────────────────────────
def _s3():
    return boto3.client(
        "s3",
        endpoint_url=f"http://{MINIO_ENDPOINT}",
        aws_access_key_id=MINIO_ACCESS,
        aws_secret_access_key=MINIO_SECRET,
    )


def _pg():
    return psycopg2.connect(**PG)


def _already_processed() -> set[str]:
    with _pg() as conn, conn.cursor() as cur:
        cur.execute("SELECT filename FROM processed_files")
        return {row[0] for row in cur.fetchall()}


# ── task functions ─────────────────────────────────────────────────────────────
def detect_new_files(**context):
    """List CSVs in MinIO bucket, filter out already-processed ones."""
    s3 = _s3()
    try:
        resp = s3.list_objects_v2(Bucket=SOURCE_BUCKET)
    except ClientError as exc:
        log.warning("Could not list bucket %s: %s", SOURCE_BUCKET, exc)
        context["ti"].xcom_push(key="new_files", value=[])
        return []

    all_files = [
        obj["Key"]
        for obj in resp.get("Contents", [])
        if obj["Key"].endswith(".csv")
    ]
    processed = _already_processed()
    new_files  = [f for f in all_files if f not in processed]

    log.info("Found %d CSV(s) in bucket, %d new.", len(all_files), len(new_files))
    context["ti"].xcom_push(key="new_files", value=new_files)
    return new_files


def process_and_load(**context):
    """Download each new CSV, clean it, load into PostgreSQL, then archive."""
    new_files: list[str] = context["ti"].xcom_pull(
        key="new_files", task_ids="detect_new_files"
    )
    if not new_files:
        log.info("No new files — nothing to do.")
        return

    s3   = _s3()
    conn = _pg()
    cur  = conn.cursor()

    try:
        for filename in new_files:
            log.info("Processing %s …", filename)

            # ── download ───────────────────────────────────────────────────
            obj = s3.get_object(Bucket=SOURCE_BUCKET, Key=filename)
            df  = pd.read_csv(io.BytesIO(obj["Body"].read()))
            raw_count = len(df)

            # ── clean / transform ──────────────────────────────────────────
            df = df.dropna(subset=["order_id", "customer_id"])
            df["order_date"]   = pd.to_datetime(df["order_date"], errors="coerce").dt.date
            df["quantity"]     = pd.to_numeric(df["quantity"],   errors="coerce").fillna(0).astype(int)
            df["unit_price"]   = pd.to_numeric(df["unit_price"],  errors="coerce").fillna(0.0)
            df["total_amount"] = (df["quantity"] * df["unit_price"]).round(2)
            df["status"]       = df["status"].str.strip().str.lower()
            df = df[df["order_date"].notna()]

            clean_count = len(df)
            log.info("  %d rows raw → %d clean", raw_count, clean_count)

            # ── upsert into PostgreSQL ─────────────────────────────────────
            upsert_sql = """
                INSERT INTO sales (
                    order_id, customer_id, customer_name, product_id, product_name,
                    category, quantity, unit_price, total_amount, order_date, region, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (order_id) DO UPDATE SET
                    quantity     = EXCLUDED.quantity,
                    unit_price   = EXCLUDED.unit_price,
                    total_amount = EXCLUDED.total_amount,
                    status       = EXCLUDED.status
            """
            rows = [
                (
                    row["order_id"],      row["customer_id"],
                    row.get("customer_name"), row.get("product_id"),
                    row.get("product_name"),  row.get("category"),
                    int(row["quantity"]),     float(row["unit_price"]),
                    float(row["total_amount"]), row["order_date"],
                    row.get("region"),        row.get("status"),
                )
                for _, row in df.iterrows()
            ]
            cur.executemany(upsert_sql, rows)

            # ── mark as processed ──────────────────────────────────────────
            cur.execute(
                """
                INSERT INTO processed_files (filename, record_count)
                VALUES (%s, %s) ON CONFLICT (filename) DO NOTHING
                """,
                (filename, clean_count),
            )
            conn.commit()

            # ── archive ────────────────────────────────────────────────────
            s3.copy_object(
                CopySource={"Bucket": SOURCE_BUCKET, "Key": filename},
                Bucket=ARCHIVE_BUCKET,
                Key=filename,
            )
            s3.delete_object(Bucket=SOURCE_BUCKET, Key=filename)
            log.info("  Archived %s → %s", SOURCE_BUCKET, ARCHIVE_BUCKET)

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


# ── DAG definition ─────────────────────────────────────────────────────────────
with DAG(
    dag_id="sales_data_pipeline",
    default_args=DEFAULT_ARGS,
    description="ETL: MinIO CSV → transform → PostgreSQL",
    schedule_interval="*/5 * * * *",
    start_date=days_ago(1),
    catchup=False,
    tags=["etl", "sales", "minio", "postgres"],
) as dag:

    detect_task = PythonOperator(
        task_id="detect_new_files",
        python_callable=detect_new_files,
    )

    process_task = PythonOperator(
        task_id="process_and_load",
        python_callable=process_and_load,
    )

    detect_task >> process_task
