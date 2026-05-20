"""
Synthetic sales data generator.

Generates realistic sales records and uploads them as a CSV to MinIO.
No pandas required — uses only stdlib csv + boto3.

Usage:
    python generate_data.py              # 500 records (default)
    python generate_data.py --rows 1000
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import random
import string
from datetime import datetime, timedelta

import boto3
from botocore.exceptions import ClientError

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS   = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET   = os.getenv("MINIO_SECRET_KEY", "minioadmin")
BUCKET         = "sales-data"

FIELDNAMES = [
    "order_id", "customer_id", "customer_name", "product_id", "product_name",
    "category", "quantity", "unit_price", "total_amount", "order_date",
    "region", "status",
]

PRODUCTS = [
    ("P001", "Laptop Pro 15",       "Electronics", 1299.99),
    ("P002", "Wireless Headphones", "Electronics",  199.99),
    ("P003", "Office Chair",        "Furniture",    449.99),
    ("P004", "Standing Desk",       "Furniture",    699.99),
    ("P005", "Coffee Maker",        "Appliances",    89.99),
    ("P006", "Notebook Set",        "Stationery",    24.99),
    ("P007", "USB-C Hub",           "Electronics",   49.99),
    ("P008", "Ergonomic Mouse",     "Electronics",   79.99),
    ("P009", "Desk Lamp",           "Furniture",     59.99),
    ("P010", "Water Bottle",        "Accessories",   29.99),
    ("P011", "Mechanical Keyboard", "Electronics",  149.99),
    ('P012', 'Monitor 27"',         "Electronics",  349.99),
]

CUSTOMER_NAMES = [
    "Alice Johnson", "Bob Smith",     "Carol Williams", "David Brown",
    "Eve Davis",     "Frank Miller",  "Grace Wilson",   "Henry Moore",
    "Ivy Taylor",    "Jack Anderson", "Kate Thomas",    "Liam Jackson",
    "Mia Garcia",    "Noah Martinez", "Olivia Lee",     "Paul Harris",
]

REGIONS  = ["North", "South", "East", "West", "Central"]
STATUSES = ["completed", "completed", "completed", "pending", "cancelled", "refunded"]


def _order_id() -> str:
    return "ORD-" + "".join(random.choices(string.digits, k=8))


def _customer_id() -> str:
    return "CUST-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


def generate_rows(num_rows: int = 500) -> list[dict]:
    base_date = datetime.now() - timedelta(days=30)
    rows = []
    for _ in range(num_rows):
        pid, pname, category, unit_price = random.choice(PRODUCTS)
        qty = random.randint(1, 10)
        order_date = base_date + timedelta(days=random.randint(0, 30), hours=random.randint(0, 23))
        rows.append({
            "order_id":      _order_id(),
            "customer_id":   _customer_id(),
            "customer_name": random.choice(CUSTOMER_NAMES),
            "product_id":    pid,
            "product_name":  pname,
            "category":      category,
            "quantity":      qty,
            "unit_price":    unit_price,
            "total_amount":  round(qty * unit_price, 2),
            "order_date":    order_date.strftime("%Y-%m-%d"),
            "region":        random.choice(REGIONS),
            "status":        random.choice(STATUSES),
        })
    return rows


def generate_and_upload(num_rows: int = 500) -> str:
    """Generate data, upload to MinIO, and return the object key."""
    rows = generate_rows(num_rows)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDNAMES)
    writer.writeheader()
    writer.writerows(rows)

    s3 = boto3.client(
        "s3",
        endpoint_url=f"http://{MINIO_ENDPOINT}",
        aws_access_key_id=MINIO_ACCESS,
        aws_secret_access_key=MINIO_SECRET,
    )

    try:
        s3.head_bucket(Bucket=BUCKET)
    except ClientError:
        s3.create_bucket(Bucket=BUCKET)

    key = f"sales_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=buf.getvalue().encode("utf-8"),
        ContentType="text/csv",
    )

    print(f"Uploaded {len(rows)} records -> s3://{BUCKET}/{key}")
    return key


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate and upload synthetic sales data.")
    parser.add_argument("--rows", type=int, default=500, help="Number of records to generate")
    args = parser.parse_args()
    generate_and_upload(args.rows)
