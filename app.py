import os
import json
import time
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
import psycopg2
import psycopg2.extras

BASE_DIR = Path(__file__).parent
app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")

DATABASE_URL = os.environ.get("DATABASE_URL", "")


def get_conn():
    # Render's internal Postgres URLs sometimes start with postgres:// -- psycopg2 wants postgresql://
    url = DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return psycopg2.connect(url)


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS app_state (
                    id INTEGER PRIMARY KEY,
                    customers JSONB NOT NULL,
                    entries JSONB NOT NULL,
                    expenses JSONB NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL
                )
                """
            )
            cur.execute("SELECT COUNT(*) FROM app_state WHERE id = 1")
            (count,) = cur.fetchone()
            if count == 0:
                customers = json.loads((BASE_DIR / "initial_customers.json").read_text(encoding="utf-8"))
                entries = json.loads((BASE_DIR / "initial_entries.json").read_text(encoding="utf-8"))
                cur.execute(
                    """
                    INSERT INTO app_state (id, customers, entries, expenses, updated_at)
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


@app.route("/")
def index():
    return send_from_directory(str(BASE_DIR), "index.html")


@app.route("/api/state", methods=["GET"])
def get_state():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT customers, entries, expenses, updated_at FROM app_state WHERE id = 1")
            row = cur.fetchone()
    if not row:
        return jsonify({"customers": [], "entries": [], "expenses": [], "updated_at": 0})
    return jsonify(dict(row))


@app.route("/api/state", methods=["POST"])
def save_state():
    data = request.get_json(force=True, silent=True) or {}
    customers = data.get("customers", [])
    entries = data.get("entries", [])
    expenses = data.get("expenses", [])
    now = time.time()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE app_state
                SET customers = %s, entries = %s, expenses = %s, updated_at = %s
                WHERE id = 1
                """,
                (json.dumps(customers), json.dumps(entries), json.dumps(expenses), now),
            )
        conn.commit()
    return jsonify({"ok": True, "updated_at": now})


@app.route("/api/admin/restore-seed")
def restore_seed():
    """One-off recovery: re-loads the original customers/entries baked into the
    repo (initial_customers.json / initial_entries.json) into the database.
    Does NOT touch expenses. Safe to call more than once."""
    customers = json.loads((BASE_DIR / "initial_customers.json").read_text(encoding="utf-8"))
    entries = json.loads((BASE_DIR / "initial_entries.json").read_text(encoding="utf-8"))
    now = time.time()
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE app_state SET customers = %s, entries = %s, updated_at = %s WHERE id = 1",
                (json.dumps(customers), json.dumps(entries), now),
            )
        conn.commit()
    return jsonify({"ok": True, "restored_customers": len(customers), "restored_entries": len(entries)})


@app.route("/api/health")
def health():
    return jsonify({"ok": True})


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
