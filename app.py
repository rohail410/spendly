import calendar
import sqlite3
from datetime import date, datetime

from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import check_password_hash

from database.db import get_db, init_db, seed_db, create_user, get_user_by_email
from database.queries import (
    get_user_by_id,
    get_summary_stats,
    get_recent_transactions,
    get_category_breakdown,
)

app = Flask(__name__)
app.secret_key = "dev-secret-key-change-in-production"

with app.app_context():
    init_db()
    seed_db()


# ------------------------------------------------------------------ #
# Routes                                                              #
# ------------------------------------------------------------------ #

@app.route("/")
def landing():
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("landing"))

    if request.method == "GET":
        return render_template("register.html")

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not name or not email or not password or not confirm_password:
        flash("All fields are required.", "error")
        return render_template("register.html")

    if password != confirm_password:
        flash("Passwords do not match.", "error")
        return render_template("register.html")

    try:
        create_user(name, email, password)
    except sqlite3.IntegrityError:
        flash("Email already registered.", "error")
        return render_template("register.html")

    flash("Account created successfully! Please sign in.", "success")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("landing"))

    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    user = get_user_by_email(email)
    if user is None or not check_password_hash(user["password_hash"], password):
        flash("Invalid email or password.", "error")
        return render_template("login.html")

    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    return redirect(url_for("profile"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("landing"))


@app.route("/terms")
def terms():
    return render_template("terms.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ------------------------------------------------------------------ #
# Profile page sections — each helper is owned by one subagent        #
# ------------------------------------------------------------------ #

def _parse_date_param(value):
    """Return value if it is a valid YYYY-MM-DD string, else None."""
    try:
        datetime.strptime(value or "", "%Y-%m-%d")
    except ValueError:
        return None
    return value


def _resolve_date_filter(args):
    date_from = _parse_date_param(args.get("date_from"))
    date_to = _parse_date_param(args.get("date_to"))
    if date_from and date_to and date_from > date_to:
        flash("Start date must be before end date.", "error")
        return None, None
    return date_from, date_to


def _months_ago(today, months):
    month_index = today.year * 12 + today.month - 1 - months
    year, month = divmod(month_index, 12)
    month += 1
    day = min(today.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _filter_presets(today, date_from, date_to):
    presets = [
        ("This Month", today.replace(day=1), today),
        ("Last 3 Months", _months_ago(today, 3), today),
        ("Last 6 Months", _months_ago(today, 6), today),
        ("All Time", None, None),
    ]
    return [
        {
            "label": label,
            "date_from": start.isoformat() if start else None,
            "date_to": end.isoformat() if end else None,
            "active": (start.isoformat() if start else None) == date_from
            and (end.isoformat() if end else None) == date_to,
        }
        for label, start, end in presets
    ]


# --- SECTION: transaction history (subagent 1) ---
def _transactions_section(user_id, date_from=None, date_to=None):
    transactions = []
    for item in get_recent_transactions(
        user_id, limit=5, date_from=date_from, date_to=date_to
    ):
        tx_date = datetime.strptime(item["date"], "%Y-%m-%d")
        transactions.append(
            {
                "date": f"{tx_date.strftime('%b')} {tx_date.day}, {tx_date.year}",
                "description": item["description"] or "",
                "category": item["category"],
                "amount": f"₹{item['amount']:.2f}",
            }
        )
    return transactions
# --- END SECTION: transaction history ---


# --- SECTION: summary stats (subagent 2) ---
def _stats_section(user_id, date_from=None, date_to=None):
    summary = get_summary_stats(user_id, date_from=date_from, date_to=date_to)
    return [
        {"label": "Total Spent", "value": f"₹{summary['total_spent']:.2f}"},
        {"label": "Transactions", "value": str(summary["transaction_count"])},
        {"label": "Top Category", "value": summary["top_category"]},
    ]
# --- END SECTION: summary stats ---


# --- SECTION: category breakdown (subagent 3) ---
def _categories_section(user_id, date_from=None, date_to=None):
    return [
        {
            "name": item["name"],
            "total": f"₹{item['amount']:.2f}",
            "percent": item["pct"],
        }
        for item in get_category_breakdown(
            user_id, date_from=date_from, date_to=date_to
        )
    ]
# --- END SECTION: category breakdown ---


# ------------------------------------------------------------------ #
# Placeholder routes — students will implement these                  #
# ------------------------------------------------------------------ #

@app.route("/profile")
def profile():
    if not session.get("user_id"):
        flash("Please sign in to view your profile.", "error")
        return redirect(url_for("login"))

    user_id = session["user_id"]
    user = get_user_by_id(user_id)
    if user is None:
        session.clear()
        flash("Please sign in to view your profile.", "error")
        return redirect(url_for("login"))
    user["initials"] = "".join(word[0] for word in user["name"].split()[:2]).upper()

    date_from, date_to = _resolve_date_filter(request.args)
    presets = _filter_presets(date.today(), date_from, date_to)
    custom_active = bool(date_from or date_to) and not any(p["active"] for p in presets)

    stats = _stats_section(user_id, date_from, date_to)
    transactions = _transactions_section(user_id, date_from, date_to)
    categories = _categories_section(user_id, date_from, date_to)

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
        date_from=date_from,
        date_to=date_to,
        presets=presets,
        custom_active=custom_active,
    )


@app.route("/analytics")
def analytics():
    if not session.get("user_id"):
        flash("Please sign in to view analytics.", "error")
        return redirect(url_for("login"))
    return render_template("analytics.html")


@app.route("/expenses/add")
def add_expense():
    return "Add expense — coming in Step 7"


@app.route("/expenses/<int:id>/edit")
def edit_expense(id):
    return "Edit expense — coming in Step 8"


@app.route("/expenses/<int:id>/delete")
def delete_expense(id):
    return "Delete expense — coming in Step 9"


if __name__ == "__main__":
    app.run(debug=True, port=5001)
