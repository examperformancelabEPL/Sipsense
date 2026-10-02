import os
import re
import json
import time
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, jsonify, request, send_from_directory
import pg8000.dbapi as pg8000

BASE_DIR = Path(__file__).parent
app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Where the app keeps its data. Defaults keep today's behaviour exactly
# (table "app_state" in DATABASE_URL). To live inside a shared database, set
# APP_STATE_TABLE (e.g. "sipsense_app_state") so it never touches other apps' tables.
STATE_TABLE = os.environ.get("APP_STATE_TABLE", "app_state")
if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", STATE_TABLE):
    raise RuntimeError("APP_STATE_TABLE must be a simple lowercase name")

# One-time move: if OLD_DATABASE_URL is set and the new table is still empty,
# the data is COPIED from the old database (which is never modified).
OLD_DATABASE_URL = os.environ.get("OLD_DATABASE_URL", "")


def get_conn(url=None):
    parsed = urlparse(url or DATABASE_URL)
    return pg8000.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        database=parsed.path.lstrip("/"),
    )


def row_to_dict(cur, row):
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
            id INTEGER PRIMARY KEY,
            customers JSONB NOT NULL,
            entries JSONB NOT NULL,
            expenses JSONB NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL
        )
        """
    )
    cur.execute(f"SELECT COUNT(*) FROM {STATE_TABLE} WHERE id = 1")
    (count,) = cur.fetchone()
    if count == 0 and OLD_DATABASE_URL:
        # Copy (never move) the live data from the old database.
        oconn = get_conn(OLD_DATABASE_URL)
        ocur = oconn.cursor()
        ocur.execute("SELECT customers, entries, expenses, updated_at FROM app_state WHERE id = 1")
        orow = ocur.fetchone()
        ocur.close()
        oconn.close()
        if not orow:
            # Refuse to start rather than quietly fall back to old seed data.
            raise RuntimeError("OLD_DATABASE_URL is set but it has no data to copy")
        customers, entries, expenses, updated_at = orow
        cur.execute(
            f"""
            INSERT INTO {STATE_TABLE} (id, customers, entries, expenses, updated_at)
            VALUES (1, %s, %s, %s, %s)
            """,
            (json.dumps(customers), json.dumps(entries), json.dumps(expenses), updated_at),
        )
        print(f"[sipsense] copied from old database: {len(customers)} customers, "
              f"{len(entries)} entries, {len(expenses)} expenses", flush=True)
    elif count == 0:
        customers = json.loads((BASE_DIR / "initial_customers.json").read_text(encoding="utf-8"))
        entries = json.loads((BASE_DIR / "initial_entries.json").read_text(encoding="utf-8"))
        cur.execute(
            f"""
            INSERT INTO {STATE_TABLE} (id, customers, entries, expenses, updated_at)
            VALUES (1, %s, %s, %s, %s)
            """,
            (
                json.dumps(customers),
                json.dumps(entries),
                json.dumps([]),
                time.time(),
            ),
        )
    conn.commit()
    cur.close()
    conn.close()


@app.route("/")
def index():
    return send_from_directory(str(BASE_DIR), "index.html")


@app.route("/api/state", methods=["GET"])
def get_state():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT customers, entries, expenses, updated_at FROM {STATE_TABLE} WHERE id = 1")
    row = cur.fetchone()
    if row:
        row = row_to_dict(cur, row)
    cur.close()
    conn.close()
    if not row:
        return jsonify({"customers": [], "entries": [], "expenses": [], "updated_at": 0})
    return jsonify(row)


@app.route("/api/state", methods=["POST"])
def save_state():
    data = request.get_json(force=True, silent=True) or {}
    customers = data.get("customers", [])
    entries = data.get("entries", [])
    expenses = data.get("expenses", [])
    now = time.time()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"""
        UPDATE {STATE_TABLE}
        SET customers = %s, entries = %s, expenses = %s, updated_at = %s
        WHERE id = 1
        """,
        (json.dumps(customers), json.dumps(entries), json.dumps(expenses), now),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True, "updated_at": now})


@app.route("/api/admin/restore-seed")
def restore_seed():
    """One-off recovery: re-loads the original customers/entries baked into the
    repo (initial_customers.json / initial_entries.json) into the database.
    Does NOT touch expenses. Safe to call more than once."""
    customers = json.loads((BASE_DIR / "initial_customers.json").read_text(encoding="utf-8"))
    entries = json.loads((BASE_DIR / "initial_entries.json").read_text(encoding="utf-8"))
    now = time.time()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE {STATE_TABLE} SET customers = %s, entries = %s, updated_at = %s WHERE id = 1",
        (json.dumps(customers), json.dumps(entries), now),
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"ok": True, "restored_customers": len(customers), "restored_entries": len(entries)})


@app.route("/api/health")
def health():
    return jsonify({"ok": True})


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
