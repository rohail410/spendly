import pytest

from database import db


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the app at a throwaway SQLite file seeded with the demo user."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    db.seed_db()
    return db


@pytest.fixture
def demo_user_id(temp_db):
    return temp_db.get_user_by_email("demo@spendly.com")["id"]


@pytest.fixture
def empty_user_id(temp_db):
    return temp_db.create_user("Empty User", "empty@example.com", "pw12345")


@pytest.fixture
def client(temp_db):
    import app as app_module

    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


# --- TESTS: transaction history (subagent 1) ---
def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


def test_recent_transactions_newest_first_with_keys(demo_user_id):
    from database.queries import get_recent_transactions

    result = get_recent_transactions(demo_user_id)

    assert len(result) == 8
    assert set(result[0]) == {"date", "description", "category", "amount"}
    dates = [item["date"] for item in result]
    assert dates == sorted(dates, reverse=True)


def test_recent_transactions_respects_limit(demo_user_id):
    from database.queries import get_recent_transactions

    assert len(get_recent_transactions(demo_user_id, limit=3)) == 3


def test_recent_transactions_empty_for_user_without_expenses(empty_user_id):
    from database.queries import get_recent_transactions

    assert get_recent_transactions(empty_user_id) == []


def test_profile_shows_transactions(client, demo_user_id):
    _login(client, demo_user_id)
    response = client.get("/profile")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Dinner out" in html
    assert "₹32.40" in html
# --- END TESTS: transaction history ---


# --- TESTS: summary stats (subagent 2) ---
def test_summary_stats_for_demo_user(demo_user_id):
    from database.queries import get_summary_stats

    stats = get_summary_stats(demo_user_id)

    assert stats["total_spent"] == pytest.approx(433.64)
    assert stats["transaction_count"] == 8
    assert stats["top_category"] == "Shopping"


def test_summary_stats_for_user_without_expenses(empty_user_id):
    from database.queries import get_summary_stats

    assert get_summary_stats(empty_user_id) == {
        "total_spent": 0,
        "transaction_count": 0,
        "top_category": "—",
    }


def test_profile_shows_summary_stats(client, demo_user_id):
    _login(client, demo_user_id)
    html = client.get("/profile").get_data(as_text=True)

    assert "Demo User" in html
    assert "demo@spendly.com" in html
    assert "₹433.64" in html
    assert "Shopping" in html


def test_profile_empty_user_shows_zeroes(client, empty_user_id):
    _login(client, empty_user_id)
    response = client.get("/profile")

    assert response.status_code == 200
    assert "₹0.00" in response.get_data(as_text=True)


def test_profile_requires_login(client):
    response = client.get("/profile")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
# --- END TESTS: summary stats ---


# --- TESTS: category breakdown (subagent 3) ---
def test_category_breakdown_ordered_desc_all_categories(demo_user_id):
    from database.queries import get_category_breakdown

    result = get_category_breakdown(demo_user_id)
    assert len(result) == 7
    amounts = [item["amount"] for item in result]
    assert amounts == sorted(amounts, reverse=True)
    assert result[0]["name"] == "Shopping"
    assert result[0]["amount"] == 150.00


def test_category_breakdown_pct_ints_sum_to_100(demo_user_id):
    from database.queries import get_category_breakdown

    result = get_category_breakdown(demo_user_id)
    assert all(isinstance(item["pct"], int) for item in result)
    assert sum(item["pct"] for item in result) == 100


def test_category_breakdown_empty_user(empty_user_id):
    from database.queries import get_category_breakdown

    assert get_category_breakdown(empty_user_id) == []


def test_category_breakdown_remainder_goes_to_largest(temp_db, empty_user_id):
    from database.queries import get_category_breakdown

    conn = temp_db.get_db()
    try:
        for category in ("Food", "Bills", "Travel"):
            conn.execute(
                "INSERT INTO expenses (user_id, amount, category, date, description) "
                "VALUES (?, ?, ?, ?, ?)",
                (empty_user_id, 10.0, category, "2026-01-01", "x"),
            )
        conn.commit()
    finally:
        conn.close()

    result = get_category_breakdown(empty_user_id)
    pcts = sorted(item["pct"] for item in result)
    # plain rounding gives 33 + 33 + 33 = 99; remainder goes to the largest
    assert pcts == [33, 33, 34]
    assert sum(pcts) == 100


def test_profile_route_shows_all_categories(client, demo_user_id):
    from database.queries import get_category_breakdown

    with client.session_transaction() as sess:
        sess["user_id"] = demo_user_id

    response = client.get("/profile")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    names = [item["name"] for item in get_category_breakdown(demo_user_id)]
    assert len(names) == 7
    for name in names:
        assert name in body
# --- END TESTS: category breakdown ---
