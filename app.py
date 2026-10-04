import sqlite3
from datetime import datetime

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

# --- SECTION: transaction history (subagent 1) ---
def _transactions_section(user_id):
    transactions = []
    for item in get_recent_transactions(user_id, limit=5):
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
def _stats_section(user_id):
    summary = get_summary_stats(user_id)
    return [
        {"label": "Total Spent", "value": f"₹{summary['total_spent']:.2f}"},
        {"label": "Transactions", "value": str(summary["transaction_count"])},
        {"label": "Top Category", "value": summary["top_category"]},
    ]
# --- END SECTION: summary stats ---


# --- SECTION: category breakdown (subagent 3) ---
def _categories_section(user_id):
    return [
        {
            "name": item["name"],
            "total": f"₹{item['amount']:.2f}",
            "percent": item["pct"],
        }
        for item in get_category_breakdown(user_id)
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

    stats = _stats_section(user_id)
    transactions = _transactions_section(user_id)
    categories = _categories_section(user_id)

    return render_template(
        "profile.html",
        user=user,
        stats=stats,
        transactions=transactions,
        categories=categories,
    )


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
