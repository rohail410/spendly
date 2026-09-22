import os
import sqlite3
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.path.join(_BASE_DIR, "..", "expense_tracker.db"))


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL,
                date TEXT NOT NULL,
                description TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def create_user(name, email, password):
    conn = get_db()
    try:
        password_hash = generate_password_hash(password)
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, password_hash),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_user_by_email(email):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    finally:
        conn.close()


def seed_db():
    conn = get_db()
    try:
        row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        if row["count"] > 0:
            return

        password_hash = generate_password_hash("demo123")
        cursor = conn.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            ("Demo User", "demo@spendly.com", password_hash),
        )
        user_id = cursor.lastrowid

        # (amount, category, description, fraction-of-elapsed-month)
        # fraction spreads dates across however much of the current month
        # has elapsed so far, so seeding never lands on a future date or an
        # invalid day-of-month regardless of when it runs.
        sample_expenses = [
            (45.50, "Food", "Groceries", 1 / 8),
            (12.00, "Transport", "Bus fare", 2 / 8),
            (89.99, "Bills", "Electricity bill", 3 / 8),
            (25.00, "Health", "Pharmacy purchase", 4 / 8),
            (60.00, "Entertainment", "Movie night", 5 / 8),
            (150.00, "Shopping", "New shoes", 6 / 8),
            (18.75, "Other", "Miscellaneous", 7 / 8),
            (32.40, "Food", "Dinner out", 8 / 8),
        ]

        today = date.today()
        first_of_month = today.replace(day=1)
        days_elapsed = today.day

        rows = []
        for amount, category, description, fraction in sample_expenses:
            day_offset = max(0, round(fraction * days_elapsed) - 1)
            expense_date = first_of_month + timedelta(days=day_offset)
            rows.append((user_id, amount, category, expense_date.isoformat(), description))

        conn.executemany(
            """
            INSERT INTO expenses (user_id, amount, category, date, description)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()
