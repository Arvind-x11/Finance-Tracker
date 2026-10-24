from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import csv
import io
import sqlite3
from datetime import date
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from flask import Flask, jsonify, render_template, request, Response
import os
import secrets
from functools import wraps
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    Response,
    redirect,
    url_for,
    session,
    flash,
)
from werkzeug.security import generate_password_hash, check_password_hash
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,  # Local HTTP development only
    PERMANENT_SESSION_LIFETIME=1800,
)

if not app.config.get("SECRET_KEY"):
    raise RuntimeError(
        "FLASK_SECRET_KEY is missing. Set it before starting the app."
    )

csrf = CSRFProtect(app)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[]
)

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "finance.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_columns(conn, table_name):
    rows = conn.execute(
        f"PRAGMA table_info({table_name})"
    ).fetchall()
    return {row["name"] for row in rows}


def init_db():
    with get_db() as conn:
        # Create tables if they do not exist.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                amount REAL NOT NULL,
                kind TEXT NOT NULL,
                category TEXT NOT NULL,
                txn_date TEXT,
                notes TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                amount REAL NOT NULL,
                month TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS recurring_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                amount REAL NOT NULL,
                kind TEXT NOT NULL,
                category TEXT NOT NULL,
                day_of_month INTEGER DEFAULT 1,
                start_month TEXT,
                active INTEGER DEFAULT 1
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS recurring_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_id INTEGER,
                entry_month TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(rule_id, entry_month),
                FOREIGN KEY(rule_id) REFERENCES recurring_rules(id)
                    ON DELETE SET NULL
            )
        """)

        # Migrate older recurring_entries table without deleting existing rows.
        entry_columns = table_columns(conn, "recurring_entries")

        if "recurring_id" in entry_columns and "rule_id" not in entry_columns:
            conn.execute("""
                ALTER TABLE recurring_entries
                RENAME COLUMN recurring_id TO rule_id
            """)
            entry_columns = table_columns(conn, "recurring_entries")

        if "month" in entry_columns and "entry_month" not in entry_columns:
            conn.execute("""
                ALTER TABLE recurring_entries
                RENAME COLUMN month TO entry_month
            """)
            entry_columns = table_columns(conn, "recurring_entries")

        if "created_at" not in entry_columns:
            conn.execute("""
                ALTER TABLE recurring_entries
                ADD COLUMN created_at TEXT
            """)
            entry_columns = table_columns(conn, "recurring_entries")

        # Older databases have a required transaction_id column. Keep it for
        # compatibility; new databases get the same column as nullable.
        if "transaction_id" not in entry_columns:
            conn.execute("""
                ALTER TABLE recurring_entries
                ADD COLUMN transaction_id INTEGER
            """)

        # Migrate older transactions table without deleting its data.
        tx_columns = table_columns(conn, "transactions")

        if "tx_date" in tx_columns and "txn_date" not in tx_columns:
            conn.execute("""
                ALTER TABLE transactions
                RENAME COLUMN tx_date TO txn_date
            """)
            tx_columns = table_columns(conn, "transactions")

        if "txn_date" not in tx_columns:
            conn.execute("""
                ALTER TABLE transactions ADD COLUMN txn_date TEXT
            """)
            tx_columns.add("txn_date")

        if "notes" not in tx_columns:
            conn.execute("""
                ALTER TABLE transactions ADD COLUMN notes TEXT DEFAULT ''
            """)

        # Fill dates only when the existing table has no usable date column.
        conn.execute("""
            UPDATE transactions
            SET txn_date = date('now')
            WHERE txn_date IS NULL OR txn_date = ''
        """)

        # Migrate older budgets table.
        budget_columns = table_columns(conn, "budgets")

        if "month" not in budget_columns:
            conn.execute("""
                ALTER TABLE budgets ADD COLUMN month TEXT
            """)

        # Assign existing month-less budgets to the current month.
        conn.execute("""
            UPDATE budgets
            SET month = strftime('%Y-%m', 'now')
            WHERE month IS NULL OR month = ''
        """)

        # Add any missing recurring columns.
        recurring_columns = table_columns(conn, "recurring_rules")

        recurring_additions = {
            "title": "TEXT DEFAULT ''",
            "amount": "REAL DEFAULT 0",
            "kind": "TEXT DEFAULT 'expense'",
            "category": "TEXT DEFAULT 'Other'",
            "day_of_month": "INTEGER DEFAULT 1",
            "start_month": "TEXT",
            "active": "INTEGER DEFAULT 1",
        }

        for column, column_type in recurring_additions.items():
            if column not in recurring_columns:
                conn.execute(
                    f"ALTER TABLE recurring_rules "
                    f"ADD COLUMN {column} {column_type}"
                )


def valid_month(value):
    try:
        date.fromisoformat(value + "-01")
        return len(value) == 7
    except (ValueError, TypeError):
        return False


def current_month():
    return date.today().strftime("%Y-%m")


@app.route("/register", methods=["GET", "POST"])
@limiter.limit("3 per hour", methods=["POST"])
def register():
    # Allow registration only when the first account does not exist.
    with get_db() as conn:
        user_count = conn.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

    if user_count > 0:
        flash("An account already exists. Please log in.", "error")
        return redirect(url_for("login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username or len(username) > 50:
            flash("Username must be between 1 and 50 characters.", "error")
            return render_template("register.html"), 400

        if len(password) < 12:
            flash("Password must be at least 12 characters long.", "error")
            return render_template("register.html"), 400

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("register.html"), 400

        try:
            with get_db() as conn:
                # Recheck inside the write transaction to prevent two
                # simultaneous registrations from creating separate accounts.
                conn.execute("BEGIN IMMEDIATE")
                user_count = conn.execute(
                    "SELECT COUNT(*) FROM users"
                ).fetchone()[0]

                if user_count > 0:
                    conn.rollback()
                    flash("An account already exists. Please log in.", "error")
                    return redirect(url_for("login"))

                conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, generate_password_hash(password))
                )

            flash("Account created successfully. Please log in.", "success")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            flash("Could not create this account. Try another username.", "error")
            return render_template("register.html"), 400

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with get_db() as conn:
            user = conn.execute(
                "SELECT id, username, password_hash FROM users WHERE username = ?",
                (username,)
            ).fetchone()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session.permanent = True
            return redirect(url_for("index"))

        flash("Invalid username or password.", "error")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.before_request
def require_login():
    # Public pages and static assets
    public_endpoints = {"login", "register", "static"}

    if request.endpoint in public_endpoints:
        return None

    # Allow logout only for authenticated users; it is POST-only.
    if request.endpoint == "logout":
        if session.get("user_id"):
            return None
        return redirect(url_for("login"))

    # Protect dashboard and every other route, including /api/*.
    if not session.get("user_id"):
        if request.path.startswith("/api/"):
            return jsonify({"error": "Authentication required. Please log in."}), 401

        return redirect(url_for("login"))

    return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/transactions", methods=["GET", "POST"])
def transactions():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}

        title = str(data.get("title", "")).strip()
        category = str(data.get("category", "Other")).strip() or "Other"
        kind = str(data.get("kind", "expense")).strip().lower()
        txn_date = str(data.get("txn_date") or data.get("tx_date") or date.today().isoformat())
        notes = str(data.get("notes", "")).strip()

        try:
            amount = float(data.get("amount", 0))
            date.fromisoformat(txn_date)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid amount or date"}), 400

        if not title or amount <= 0:
            return jsonify({"error": "Title and positive amount are required"}), 400

        if kind not in ("income", "expense"):
            return jsonify({"error": "Kind must be income or expense"}), 400

        with get_db() as conn:
            cursor = conn.execute("""
                INSERT INTO transactions
                    (title, amount, kind, category, txn_date, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (title, amount, kind, category, txn_date, notes))

            row = conn.execute(
                "SELECT * FROM transactions WHERE id = ?",
                (cursor.lastrowid,)
            ).fetchone()

        return jsonify(dict(row)), 201

    month = request.args.get("month", current_month())
    search = request.args.get("search", "").strip()
    kind = request.args.get("kind", "").strip()
    category = request.args.get("category", "").strip()

    if not valid_month(month):
        return jsonify({"error": "Month must be YYYY-MM"}), 400

    sql = """
        SELECT id, title, amount, kind, category, txn_date, notes
        FROM transactions
        WHERE substr(txn_date, 1, 7) = ?
    """
    params = [month]

    if search:
        sql += " AND (title LIKE ? OR notes LIKE ? OR category LIKE ?)"
        pattern = f"%{search}%"
        params.extend([pattern, pattern, pattern])

    if kind in ("income", "expense"):
        sql += " AND kind = ?"
        params.append(kind)

    if category:
        sql += " AND category = ?"
        params.append(category)

    sql += " ORDER BY txn_date DESC, id DESC"

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    return jsonify([dict(row) for row in rows])


@app.route("/api/transactions/<int:transaction_id>", methods=["PUT", "DELETE"])
def transaction_detail(transaction_id):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM transactions WHERE id = ?",
            (transaction_id,)
        ).fetchone()

        if not existing:
            return jsonify({"error": "Transaction not found"}), 404

        if request.method == "DELETE":
            conn.execute(
                "DELETE FROM transactions WHERE id = ?",
                (transaction_id,)
            )
            return jsonify({"message": "Transaction deleted"})

        data = request.get_json(silent=True) or {}

        title = str(data.get("title", existing["title"])).strip()
        category = str(data.get("category", existing["category"])).strip()
        kind = str(data.get("kind", existing["kind"])).strip().lower()
        notes = str(data.get("notes", existing["notes"] or "")).strip()
        txn_date = str(
            data.get("txn_date", existing["txn_date"] or date.today().isoformat())
        )

        try:
            amount = float(data.get("amount", existing["amount"]))
            date.fromisoformat(txn_date)
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid amount or date"}), 400

        if not title or not category or amount <= 0:
            return jsonify({"error": "Title, category and positive amount required"}), 400

        if kind not in ("income", "expense"):
            return jsonify({"error": "Kind must be income or expense"}), 400

        conn.execute("""
            UPDATE transactions
            SET title = ?, amount = ?, kind = ?, category = ?,
                txn_date = ?, notes = ?
            WHERE id = ?
        """, (title, amount, kind, category, txn_date, notes, transaction_id))

        row = conn.execute(
            "SELECT * FROM transactions WHERE id = ?",
            (transaction_id,)
        ).fetchone()

    return jsonify(dict(row))


@app.route("/api/summary")
def summary():
    month = request.args.get("month", current_month())

    if not valid_month(month):
        return jsonify({"error": "Month must be YYYY-MM"}), 400

    # Previous month calculate karo
    year, month_number = map(int, month.split("-"))

    if month_number == 1:
        previous_month = f"{year - 1}-12"
    else:
        previous_month = f"{year}-{month_number - 1:02d}"

    with get_db() as conn:
        # Current month totals
        totals = conn.execute("""
            SELECT
                COALESCE(SUM(
                    CASE WHEN kind = 'income' THEN amount ELSE 0 END
                ), 0) AS income,
                COALESCE(SUM(
                    CASE WHEN kind = 'expense' THEN amount ELSE 0 END
                ), 0) AS expenses,
                COUNT(*) AS transaction_count
            FROM transactions
            WHERE substr(txn_date, 1, 7) = ?
        """, (month,)).fetchone()

        # Previous month totals
        previous_totals = conn.execute("""
            SELECT
                COALESCE(SUM(
                    CASE WHEN kind = 'income' THEN amount ELSE 0 END
                ), 0) AS income,
                COALESCE(SUM(
                    CASE WHEN kind = 'expense' THEN amount ELSE 0 END
                ), 0) AS expenses
            FROM transactions
            WHERE substr(txn_date, 1, 7) = ?
        """, (previous_month,)).fetchone()

        # Current month expense categories
        categories = conn.execute("""
            SELECT category, SUM(amount) AS total
            FROM transactions
            WHERE substr(txn_date, 1, 7) = ?
              AND kind = 'expense'
            GROUP BY category
            ORDER BY total DESC
        """, (month,)).fetchall()

    income = totals["income"]
    expenses = totals["expenses"]
    previous_income = previous_totals["income"]
    previous_expenses = previous_totals["expenses"]

    result = dict(totals)
    result["balance"] = income - expenses
    result["categories"] = [dict(row) for row in categories]
    result["month"] = month

    result["savings_rate"] = (
        round((income - expenses) / income * 100, 2)
        if income > 0 else 0
    )

    # Previous month comparison
    result["previous_month"] = previous_month
    result["previous_income"] = previous_income
    result["previous_expenses"] = previous_expenses
    result["previous_balance"] = previous_income - previous_expenses

    result["income_change_percent"] = (
        round(
            (income - previous_income) / previous_income * 100, 2
        )
        if previous_income > 0 else None
    )

    result["expense_change_percent"] = (
        round(
            (expenses - previous_expenses) / previous_expenses * 100, 2
        )
        if previous_expenses > 0 else None
    )

    return jsonify(result)


@app.route("/api/monthly-trends")
def monthly_trends():
    from datetime import date

    today = date.today()
    months = []

    year = today.year
    month_number = today.month

    # Current month + previous 5 months
    for _ in range(6):
        month = f"{year}-{month_number:02d}"
        months.append(month)

        month_number -= 1
        if month_number == 0:
            month_number = 12
            year -= 1

    months.reverse()

    results = []

    with get_db() as conn:
        for month in months:
            row = conn.execute("""
                SELECT
                    COALESCE(SUM(CASE WHEN kind = 'income'
                        THEN amount ELSE 0 END), 0) AS income,
                    COALESCE(SUM(CASE WHEN kind = 'expense'
                        THEN amount ELSE 0 END), 0) AS expenses
                FROM transactions
                WHERE substr(txn_date, 1, 7) = ?
            """, (month,)).fetchone()

            income = float(row["income"])
            expenses = float(row["expenses"])

            results.append({
                "month": month,
                "income": income,
                "expenses": expenses,
                "savings": income - expenses
            })

    return jsonify(results)


@app.route("/api/budgets", methods=["GET", "POST"])
def budgets():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        category = str(data.get("category", "")).strip()
        month = str(data.get("month") or current_month())

        try:
            amount = float(data.get("amount", 0))
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid budget amount"}), 400

        if not category or amount <= 0 or not valid_month(month):
            return jsonify({"error": "Valid category, amount and month required"}), 400

        with get_db() as conn:
            existing = conn.execute("""
                SELECT id FROM budgets
                WHERE category = ? AND month = ?
            """, (category, month)).fetchone()

            if existing:
                conn.execute(
                    "UPDATE budgets SET amount = ? WHERE id = ?",
                    (amount, existing["id"])
                )
                budget_id = existing["id"]
            else:
                cursor = conn.execute("""
                    INSERT INTO budgets (category, amount, month)
                    VALUES (?, ?, ?)
                """, (category, amount, month))
                budget_id = cursor.lastrowid

            row = conn.execute(
                "SELECT * FROM budgets WHERE id = ?", (budget_id,)
            ).fetchone()

        return jsonify(dict(row)), 201

    month = request.args.get("month", current_month())

    if not valid_month(month):
        return jsonify({"error": "Month must be YYYY-MM"}), 400

    with get_db() as conn:
        rows = conn.execute("""
            SELECT
                b.id, b.category, b.amount, b.month,
                COALESCE(SUM(t.amount), 0) AS spent
            FROM budgets b
            LEFT JOIN transactions t
                ON t.category = b.category
                AND t.kind = 'expense'
                AND substr(t.txn_date, 1, 7) = b.month
            WHERE b.month = ?
            GROUP BY b.id
            ORDER BY b.category
        """, (month,)).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        item["remaining"] = item["amount"] - item["spent"]
        item["percent_used"] = (
            round(item["spent"] / item["amount"] * 100, 2)
            if item["amount"] else 0
        )
        result.append(item)

    return jsonify(result)


@app.route("/api/budgets/<int:budget_id>", methods=["DELETE"])
def delete_budget(budget_id):
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM budgets WHERE id = ?", (budget_id,)
        )

    if cursor.rowcount == 0:
        return jsonify({"error": "Budget not found"}), 404

    return jsonify({"message": "Budget deleted"})


@app.route("/api/recurring", methods=["GET", "POST"])
def recurring():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}

        title = str(data.get("title", "")).strip()
        category = str(data.get("category", "Other")).strip() or "Other"
        kind = str(data.get("kind", "expense")).strip().lower()
        start_month = str(data.get("start_month") or current_month())

        try:
            amount = float(data.get("amount", 0))
            day = int(data.get("day_of_month", 1))
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid amount or day"}), 400

        if not title or amount <= 0:
            return jsonify({"error": "Title and positive amount required"}), 400
        if kind not in ("income", "expense"):
            return jsonify({"error": "Kind must be income or expense"}), 400
        if not valid_month(start_month) or not 1 <= day <= 31:
            return jsonify({"error": "Invalid start month or day"}), 400

        with get_db() as conn:
            cursor = conn.execute("""
                INSERT INTO recurring_rules
                    (title, amount, kind, category, day_of_month, start_month, active)
                VALUES (?, ?, ?, ?, ?, ?, 1)
            """, (title, amount, kind, category, day, start_month))

            row = conn.execute(
                "SELECT * FROM recurring_rules WHERE id = ?",
                (cursor.lastrowid,)
            ).fetchone()

        return jsonify(dict(row)), 201

    with get_db() as conn:
        rows = conn.execute("""
            SELECT * FROM recurring_rules ORDER BY id DESC
        """).fetchall()

    return jsonify([dict(row) for row in rows])


@app.route("/api/recurring/<int:rule_id>", methods=["PUT", "DELETE"])
def recurring_detail(rule_id):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM recurring_rules WHERE id = ?", (rule_id,)
        ).fetchone()

        if not existing:
            return jsonify({"error": "Recurring rule not found"}), 404

        if request.method == "DELETE":
            conn.execute(
                "DELETE FROM recurring_rules WHERE id = ?", (rule_id,)
            )
            return jsonify({"message": "Recurring rule deleted"})

        data = request.get_json(silent=True) or {}
        active = data.get("active", existing["active"])
        active = 1 if active in (True, 1, "1", "true") else 0

        conn.execute(
            "UPDATE recurring_rules SET active = ? WHERE id = ?",
            (active, rule_id)
        )

        row = conn.execute(
            "SELECT * FROM recurring_rules WHERE id = ?", (rule_id,)
        ).fetchone()

    return jsonify(dict(row))


@app.route("/api/recurring/apply", methods=["POST"])
def apply_recurring():
    data = request.get_json(silent=True) or {}
    month = str(data.get("month") or current_month())

    if not valid_month(month):
        return jsonify({"error": "Month must be YYYY-MM"}), 400

    created = 0

    with get_db() as conn:
        rules = conn.execute("""
            SELECT * FROM recurring_rules
            WHERE active = 1 AND (start_month IS NULL OR start_month <= ?)
        """, (month,)).fetchall()

        for rule in rules:
            existing = conn.execute("""
                SELECT id FROM recurring_entries
                WHERE rule_id = ? AND entry_month = ?
            """, (rule["id"], month)).fetchone()

            if existing:
                continue

            year, mon = map(int, month.split("-"))
            last_day = __import__("calendar").monthrange(year, mon)[1]
            day = min(max(1, rule["day_of_month"] or 1), last_day)
            txn_date = f"{month}-{day:02d}"

            transaction_cursor = conn.execute("""
                INSERT INTO transactions
                    (title, amount, kind, category, txn_date, notes)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                rule["title"], rule["amount"], rule["kind"],
                rule["category"], txn_date, "Recurring transaction"
            ))
            transaction_id = transaction_cursor.lastrowid

            # Include transaction_id for compatibility with older databases.
            conn.execute("""
                INSERT INTO recurring_entries
                    (rule_id, entry_month, transaction_id)
                VALUES (?, ?, ?)
            """, (rule["id"], month, transaction_id))

            created += 1

    return jsonify({"message": "Recurring transactions applied", "created": created})


@app.route("/api/export/csv")
def export_csv():
    month = request.args.get("month", current_month())

    if not valid_month(month):
        return jsonify({"error": "Month must be YYYY-MM"}), 400

    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, title, amount, kind, category, txn_date, notes
            FROM transactions
            WHERE substr(txn_date, 1, 7) = ?
            ORDER BY txn_date DESC, id DESC
        """, (month,)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Title", "Amount", "Type", "Category", "Date", "Notes"
    ])

    for row in rows:
        writer.writerow([
            row["id"], row["title"], row["amount"], row["kind"],
            row["category"], row["txn_date"], row["notes"]
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=transactions-{month}.csv"
        }
    )
@app.route("/api/export/pdf")
def export_pdf():
    month = request.args.get("month", current_month())

    if not valid_month(month):
        return jsonify({"error": "Month must be YYYY-MM"}), 400

    with get_db() as conn:
        rows = conn.execute("""
            SELECT title, amount, kind, category, txn_date
            FROM transactions
            WHERE substr(txn_date, 1, 7) = ?
            ORDER BY txn_date DESC, id DESC
        """, (month,)).fetchall()

        totals = conn.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN kind='income' THEN amount ELSE 0 END), 0) AS income,
                COALESCE(SUM(CASE WHEN kind='expense' THEN amount ELSE 0 END), 0) AS expenses
            FROM transactions
            WHERE substr(txn_date, 1, 7) = ?
        """, (month,)).fetchone()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(f"Personal Finance Report - {month}", styles["Title"]),
        Spacer(1, 12),
        Paragraph(f"Income: Rs. {totals['income']:.2f}", styles["Normal"]),
        Paragraph(f"Expenses: Rs. {totals['expenses']:.2f}", styles["Normal"]),
        Paragraph(
            f"Net Savings: Rs. {totals['income'] - totals['expenses']:.2f}",
            styles["Normal"]
        ),
        Spacer(1, 16),
    ]

    table_data = [["Date", "Title", "Type", "Category", "Amount"]]
    for row in rows:
        table_data.append([
            str(row["txn_date"]),
            str(row["title"])[:35],
            str(row["kind"]),
            str(row["category"]),
            f"Rs. {row['amount']:.2f}",
        ])

    table = Table(table_data, repeatRows=1)
    table.setStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightblue),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("PADDING", (0, 0), (-1, -1), 6),
    ])
    story.append(table)
    doc.build(story)

    buffer.seek(0)
    return Response(
        buffer.getvalue(),
        mimetype="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=finance-report-{month}.pdf"
        },
    )

@app.route("/api/budget-alerts")
def budget_alerts():
    month = request.args.get("month", current_month())

    if not valid_month(month):
        return jsonify({"error": "Month must be YYYY-MM"}), 400

    with get_db() as conn:
        rows = conn.execute("""
            SELECT
                b.id,
                b.category,
                b.amount AS budget,
                COALESCE(SUM(t.amount), 0) AS spent
            FROM budgets b
            LEFT JOIN transactions t
                ON t.category = b.category
                AND t.kind = 'expense'
                AND substr(t.txn_date, 1, 7) = b.month
            WHERE b.month = ?
            GROUP BY b.id, b.category, b.amount
            ORDER BY b.category
        """, (month,)).fetchall()

    alerts = []

    for row in rows:
        budget = float(row["budget"] or 0)
        spent = float(row["spent"] or 0)

        percent_used = (
            round((spent / budget) * 100, 2)
            if budget > 0 else 0
        )

        if percent_used >= 100:
            status = "exceeded"
            message = f'{row["category"]} budget limit cross ho gayi!'
        elif percent_used >= 80:
            status = "warning"
            message = f'{row["category"]} budget ka 80% use ho chuka hai.'
        else:
            status = "normal"
            message = f'{row["category"]} budget normal hai.'

        alerts.append({
            "id": row["id"],
            "category": row["category"],
            "budget": budget,
            "spent": spent,
            "remaining": round(budget - spent, 2),
            "percent_used": percent_used,
            "status": status,
            "message": message
        })

    return jsonify({
        "month": month,
        "alerts": alerts
    })

from datetime import date, timedelta
from flask import jsonify
import sqlite3

@app.route("/api/month-comparison")
def month_comparison():
    today = date.today()
    current_start = today.replace(day=1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end.replace(day=1)

    def get_totals(start, end):
        conn = sqlite3.connect("finance.db")
        conn.row_factory = sqlite3.Row

        rows = conn.execute("""
            SELECT kind, COALESCE(SUM(amount), 0) AS total
            FROM transactions
            WHERE txn_date >= ? AND txn_date < ?
            GROUP BY kind
        """, (start.isoformat(), end.isoformat())).fetchall()

        conn.close()
        totals = {"income": 0, "expenses": 0}

        for row in rows:
            if row["kind"] == "income":
                totals["income"] = row["total"]
            elif row["kind"] == "expense":
                totals["expenses"] = row["total"]

        totals["savings"] = totals["income"] - totals["expenses"]
        return totals

    current = get_totals(current_start, today + timedelta(days=1))
    previous = get_totals(previous_start, current_start)

    def change(key):
        old = previous[key]
        new = current[key]

        if old == 0:
            return None if new != 0 else 0

        return round(((new - old) / abs(old)) * 100, 2)

    return jsonify({
        "current_month": current_start.strftime("%B %Y"),
        "previous_month": previous_start.strftime("%B %Y"),
        "current": current,
        "previous": previous,
        "change_percent": {
            key: change(key)
            for key in ("income", "expenses", "savings")
        }
    })

if __name__ == "__main__":
    init_db()

    # Apply recurring transactions directly at startup.
    # Calling the view directly avoids an unauthenticated HTTP request.
    with app.test_request_context(
        "/api/recurring/apply",
        method="POST",
        json={"month": current_month()}
    ):
        response = apply_recurring()
        if response.status_code == 200:
            print("Monthly recurring transactions:", response.get_json())
        else:
            print(
                "Recurring transaction error:",
                response.get_data(as_text=True)
            )

    app.run(debug=True, host="127.0.0.1", port=5001)