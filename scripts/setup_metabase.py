#!/usr/bin/env python3
"""
Metabase provisioning — first-time setup, DB connection, KPI cards, and dashboard
via the Metabase REST API. Safe to re-run (idempotent).
"""

import os
import sys
import time
import requests
from dotenv import load_dotenv

# Load .env from the project root regardless of where the script is invoked from
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_root, ".env"))

_REQUIRED = [
    "METABASE_URL", "METABASE_ADMIN_EMAIL", "METABASE_ADMIN_PASSWORD",
    "DATAPLATFORM_DB", "DATAPLATFORM_USER", "DATAPLATFORM_PASSWORD",
]
_missing = [v for v in _REQUIRED if not os.getenv(v)]
if _missing:
    sys.exit(f"ERROR: missing required environment variables: {', '.join(_missing)}\n"
             f"       Ensure .env exists at the project root and defines them.")

METABASE_URL = os.getenv("METABASE_URL")
ADMIN_EMAIL = os.getenv("METABASE_ADMIN_EMAIL")
ADMIN_PASSWORD = os.getenv("METABASE_ADMIN_PASSWORD")
SITE_NAME = "Mini Data Platform"
DASHBOARD_NAME = "Sales KPI Dashboard"

DB_HOST = os.getenv("METABASE_DB_HOST", "postgres")
DB_PORT = int(os.getenv("METABASE_DB_PORT", "5432"))
DB_NAME = os.getenv("DATAPLATFORM_DB")
DB_USER = os.getenv("DATAPLATFORM_USER")
DB_PASS = os.getenv("DATAPLATFORM_PASSWORD")

# ── KPI card definitions ───────────────────────────────────────────────────────
# Layout grid: 18 columns wide; size_x/size_y in grid units
KPI_CARDS = [
    # Row 0 — scalar KPIs
    {
        "name": "Total Completed Revenue",
        "sql": (
            "SELECT CONCAT('RWF ', TO_CHAR(SUM(total_amount), 'FM999,999,999,999.00')) AS total_revenue "
            "FROM sales WHERE status = 'completed'"
        ),
        "display": "scalar",
        "viz": {},
        "col": 0, "row": 0, "size_x": 6, "size_y": 4,
    },
    {
        "name": "Total Orders",
        "sql": "SELECT COUNT(*) AS total_orders FROM sales",
        "display": "scalar",
        "viz": {},
        "col": 6, "row": 0, "size_x": 6, "size_y": 4,
    },
    {
        "name": "Average Order Value",
        "sql": (
            "SELECT CONCAT('RWF ', TO_CHAR(ROUND(AVG(total_amount), 2), 'FM999,999,999,999.00')) AS avg_order_value "
            "FROM sales WHERE status = 'completed'"
        ),
        "display": "scalar",
        "viz": {},
        "col": 12, "row": 0, "size_x": 6, "size_y": 4,
    },
    # Row 4 — region + status
    {
        "name": "Revenue by Region",
        "sql": (
            "SELECT region, SUM(total_amount) AS revenue "
            "FROM sales WHERE status = 'completed' "
            "GROUP BY region ORDER BY revenue DESC"
        ),
        "display": "bar",
        "viz": {
            "graph.dimensions": ["region"],
            "graph.metrics": ["revenue"],
            "graph.x_axis.title_text": "Region",
            "graph.y_axis.title_text": "Revenue ($)",
        },
        "col": 0, "row": 4, "size_x": 9, "size_y": 8,
    },
    {
        "name": "Order Status Breakdown",
        "sql": "SELECT status, COUNT(*) AS order_count FROM sales GROUP BY status",
        "display": "pie",
        "viz": {},
        "col": 9, "row": 4, "size_x": 9, "size_y": 8,
    },
    # Row 12 — daily trend (full width)
    {
        "name": "Daily Order & Revenue Trend",
        "sql": (
            "SELECT order_date, COUNT(*) AS orders, SUM(total_amount) AS revenue "
            "FROM sales GROUP BY order_date ORDER BY order_date"
        ),
        "display": "line",
        "viz": {
            "graph.dimensions": ["order_date"],
            "graph.metrics": ["orders", "revenue"],
            "graph.x_axis.title_text": "Date",
        },
        "col": 0, "row": 12, "size_x": 18, "size_y": 8,
    },
    # Row 20 — product + category
    {
        "name": "Top 5 Products by Revenue",
        "sql": (
            "SELECT product_name, SUM(total_amount) AS revenue "
            "FROM sales WHERE status = 'completed' "
            "GROUP BY product_name ORDER BY revenue DESC LIMIT 5"
        ),
        "display": "bar",
        "viz": {
            "graph.dimensions": ["product_name"],
            "graph.metrics": ["revenue"],
            "graph.x_axis.title_text": "Product",
            "graph.y_axis.title_text": "Revenue (RWF)",
        },
        "col": 0, "row": 20, "size_x": 9, "size_y": 8,
    },
    {
        "name": "Revenue by Category",
        "sql": (
            "SELECT category, SUM(total_amount) AS revenue "
            "FROM sales WHERE status = 'completed' "
            "GROUP BY category ORDER BY revenue DESC"
        ),
        "display": "bar",
        "viz": {
            "graph.dimensions": ["category"],
            "graph.metrics": ["revenue"],
            "graph.x_axis.title_text": "Category",
            "graph.y_axis.title_text": "Revenue (RWF)",
        },
        "col": 9, "row": 20, "size_x": 9, "size_y": 8,
    },
    # Row 28 — monthly trend (full width)
    {
        "name": "Monthly Revenue Trend",
        "sql": (
            "SELECT DATE_TRUNC('month', order_date)::date AS month, "
            "SUM(total_amount) AS revenue "
            "FROM sales WHERE status = 'completed' "
            "GROUP BY month ORDER BY month"
        ),
        "display": "line",
        "viz": {
            "graph.dimensions": ["month"],
            "graph.metrics": ["revenue"],
            "graph.x_axis.title_text": "Month",
            "graph.y_axis.title_text": "Revenue (RWF)",
        },
        "col": 0, "row": 28, "size_x": 18, "size_y": 8,
    },
]


# ── helpers ────────────────────────────────────────────────────────────────────

def _ok(label, msg=""):
    print(f"  [OK]  {label}" + (f" — {msg}" if msg else ""), flush=True)


def _info(msg):
    print(f"  ...   {msg}", flush=True)


def wait_for_metabase(timeout=180):
    _info("Waiting for Metabase to be healthy...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{METABASE_URL}/api/health", timeout=5)
            if r.status_code == 200 and r.json().get("status") == "ok":
                _ok("Metabase is healthy")
                return
        except requests.RequestException:
            pass
        time.sleep(6)
    sys.exit("ERROR: Metabase did not become ready within the timeout.")


def _get_setup_token():
    r = requests.get(f"{METABASE_URL}/api/session/properties", timeout=10)
    r.raise_for_status()
    return r.json().get("setup-token")


def first_time_setup():
    token = _get_setup_token()
    if not token:
        _ok("Metabase already set up — skipping initial configuration")
        return

    _info("Running first-time setup (creating admin user + DB connection)...")
    payload = {
        "token": token,
        "user": {
            "first_name": "Admin",
            "last_name": "User",
            "email": ADMIN_EMAIL,
            "password": ADMIN_PASSWORD,
            "site_name": SITE_NAME,
        },
        "database": {
            "engine": "postgres",
            "name": "Mini Data Platform",
            "details": {
                "host": DB_HOST,
                "port": DB_PORT,
                "dbname": DB_NAME,
                "user": DB_USER,
                "password": DB_PASS,
            },
        },
        "prefs": {
            "site_name": SITE_NAME,
            "allow_tracking": False,
        },
    }
    r = requests.post(f"{METABASE_URL}/api/setup", json=payload, timeout=30)
    if r.status_code == 403:
        _ok("Metabase already set up — skipping initial configuration")
        return
    r.raise_for_status()
    _ok("First-time setup complete")
    time.sleep(3)  # let Metabase settle after setup


def get_session_token():
    r = requests.post(
        f"{METABASE_URL}/api/session",
        json={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["id"]


def get_or_create_database(session):
    headers = {"X-Metabase-Session": session}
    resp = requests.get(f"{METABASE_URL}/api/database", headers=headers, timeout=10)
    resp.raise_for_status()
    body = resp.json()
    db_list = body if isinstance(body, list) else body.get("data", [])

    for db in db_list:
        if db.get("engine") == "postgres" and db.get("details", {}).get("dbname") == DB_NAME:
            _ok("Database connection", f"'{db['name']}' already exists (ID {db['id']})")
            return db["id"]

    _info(f"Creating database connection for '{DB_NAME}'...")
    payload = {
        "engine": "postgres",
        "name": "Mini Data Platform",
        "details": {
            "host": DB_HOST,
            "port": DB_PORT,
            "dbname": DB_NAME,
            "user": DB_USER,
            "password": DB_PASS,
        },
    }
    r = requests.post(
        f"{METABASE_URL}/api/database",
        headers={**headers, "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    r.raise_for_status()
    db_id = r.json()["id"]
    _ok("Database connection", f"created with ID {db_id}")
    return db_id


def get_or_create_card(session, db_id, spec):
    headers = {"X-Metabase-Session": session}

    resp = requests.get(f"{METABASE_URL}/api/card?f=all", headers=headers, timeout=10)
    resp.raise_for_status()
    cards = resp.json()
    for card in (cards if isinstance(cards, list) else []):
        if card.get("name") == spec["name"]:
            return card["id"]

    payload = {
        "name": spec["name"],
        "dataset_query": {
            "database": db_id,
            "type": "native",
            "native": {"query": spec["sql"], "template-tags": {}},
        },
        "display": spec["display"],
        "visualization_settings": spec["viz"],
    }
    r = requests.post(
        f"{METABASE_URL}/api/card",
        headers={**headers, "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()["id"]


def get_or_create_dashboard(session):
    headers = {"X-Metabase-Session": session}

    resp = requests.get(f"{METABASE_URL}/api/dashboard", headers=headers, timeout=10)
    resp.raise_for_status()
    dashboards = resp.json()
    for dash in (dashboards if isinstance(dashboards, list) else []):
        if dash.get("name") == DASHBOARD_NAME:
            _ok("Dashboard", f"'{DASHBOARD_NAME}' already exists (ID {dash['id']})")
            return dash["id"], True

    r = requests.post(
        f"{METABASE_URL}/api/dashboard",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "name": DASHBOARD_NAME,
            "description": "Auto-provisioned KPI dashboard — sales metrics and trends",
        },
        timeout=10,
    )
    r.raise_for_status()
    dash_id = r.json()["id"]
    _ok("Dashboard", f"created '{DASHBOARD_NAME}' (ID {dash_id})")
    return dash_id, False


def populate_dashboard(session, dashboard_id, card_ids_with_spec):
    headers = {"X-Metabase-Session": session, "Content-Type": "application/json"}

    dashcards = []
    for idx, (card_id, spec) in enumerate(card_ids_with_spec):
        dashcards.append({
            "id": -(idx + 1),  # negative = new dashcard
            "card_id": card_id,
            "col": spec["col"],
            "row": spec["row"],
            "size_x": spec["size_x"],
            "size_y": spec["size_y"],
            "series": [],
            "visualization_settings": {},
            "parameter_mappings": [],
        })

    r = requests.put(
        f"{METABASE_URL}/api/dashboard/{dashboard_id}/cards",
        headers=headers,
        json={"cards": dashcards},
        timeout=30,
    )
    r.raise_for_status()
    _ok("Cards added", f"{len(dashcards)} cards placed on dashboard")


# ── main ───────────────────────────────────────────────────────────────────────

def main():
    print(f"\nProvisioning Metabase at {METABASE_URL}\n", flush=True)

    wait_for_metabase()
    first_time_setup()

    session = get_session_token()
    _ok("Session", "authenticated")

    db_id = get_or_create_database(session)

    print("\nCreating KPI cards...")
    card_ids_with_spec = []
    for spec in KPI_CARDS:
        card_id = get_or_create_card(session, db_id, spec)
        _ok(f"Card '{spec['name']}'", f"ID {card_id}")
        card_ids_with_spec.append((card_id, spec))

    print("\nCreating dashboard...")
    dashboard_id, already_existed = get_or_create_dashboard(session)

    if not already_existed:
        populate_dashboard(session, dashboard_id, card_ids_with_spec)

    print(f"\nDone — open your dashboard at {METABASE_URL}/dashboard/{dashboard_id}\n")


if __name__ == "__main__":
    main()
