"""Tests for Step 7: Add Expense (GET/POST /expenses/add) and insert_expense.

Based on .claude/specs/07-add-expense.md.
All tests run against an isolated temporary SQLite file.
"""
import pytest

from database import db
from database.queries import insert_expense

CATEGORIES = [
    "Food", "Transport", "Bills", "Health",
    "Entertainment", "Shopping", "Other",
]
ADD_URL = "/expenses/add"
ERROR_MARKER = b"auth-error"  # error flash container rendered by base.html


# ------------------------------------------------------------------ #
# Fixtures and helpers                                                #
# ------------------------------------------------------------------ #

@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the app at a throwaway SQLite file (never the real DB)."""
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    return db


@pytest.fixture
def client(temp_db):
    import app as app_module

    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.fixture
def user_id(temp_db):
    return temp_db.create_user("Add User", "add@example.com", "pw12345")


@pytest.fixture
def auth_client(client, user_id):
    _login(client, user_id)
    return client


def _login(client, uid):
    with client.session_transaction() as sess:
        sess["user_id"] = uid


def _all_expenses():
    conn = db.get_db()
    try:
        return conn.execute("SELECT * FROM expenses ORDER BY id").fetchall()
    finally:
        conn.close()


def _valid_form(**overrides):
    data = {
        "amount": "50.0",
        "category": "Food",
        "date": "2026-03-20",
        "description": "Lunch",
    }
    data.update(overrides)
    return data


def _location_path(response):
    return response.headers["Location"].split("?")[0]


# ------------------------------------------------------------------ #
# Unit tests: insert_expense                                          #
# ------------------------------------------------------------------ #

class TestInsertExpense:
    def test_insert_expense_valid_data_inserts_row(self, temp_db, user_id):
        insert_expense(user_id, 50.0, "Food", "2026-03-20", "Lunch")

        rows = _all_expenses()
        assert len(rows) == 1, "Expected exactly one expense row"
        row = rows[0]
        assert row["user_id"] == user_id
        assert row["amount"] == pytest.approx(50.0)
        assert row["category"] == "Food"
        assert row["date"] == "2026-03-20"
        assert row["description"] == "Lunch"

    def test_insert_expense_none_description_stores_null(self, temp_db, user_id):
        insert_expense(user_id, 12.5, "Transport", "2026-03-21", None)

        rows = _all_expenses()
        assert len(rows) == 1
        assert rows[0]["description"] is None, "description should be NULL"

    def test_insert_expense_multiple_calls_insert_multiple_rows(
        self, temp_db, user_id
    ):
        insert_expense(user_id, 1.0, "Food", "2026-03-20", "a")
        insert_expense(user_id, 2.0, "Bills", "2026-03-21", "b")

        assert len(_all_expenses()) == 2

    def test_insert_expense_unknown_user_violates_foreign_key(self, temp_db):
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            insert_expense(99999, 5.0, "Food", "2026-03-20", "orphan")
        assert _all_expenses() == []

    def test_insert_expense_sql_injection_description_stored_literally(
        self, temp_db, user_id
    ):
        payload = "x'); DROP TABLE expenses; --"
        insert_expense(user_id, 5.0, "Food", "2026-03-20", payload)

        rows = _all_expenses()
        assert len(rows) == 1, "expenses table should still exist with one row"
        assert rows[0]["description"] == payload


# ------------------------------------------------------------------ #
# Auth guards                                                         #
# ------------------------------------------------------------------ #

class TestAuthGuard:
    def test_get_unauthenticated_redirects_to_login(self, client):
        response = client.get(ADD_URL)
        assert response.status_code == 302
        assert _location_path(response).endswith("/login")

    def test_post_unauthenticated_redirects_to_login(self, client):
        response = client.post(ADD_URL, data=_valid_form())
        assert response.status_code == 302
        assert _location_path(response).endswith("/login")

    def test_post_unauthenticated_does_not_insert_row(self, client):
        client.post(ADD_URL, data=_valid_form())
        assert _all_expenses() == [], "No row should be created when logged out"


# ------------------------------------------------------------------ #
# GET (authenticated)                                                 #
# ------------------------------------------------------------------ #

class TestGetForm:
    def test_get_authenticated_returns_200(self, auth_client):
        assert auth_client.get(ADD_URL).status_code == 200

    def test_get_contains_post_form(self, auth_client):
        body = auth_client.get(ADD_URL).data.lower()
        assert b"<form" in body, "Expected a <form> element"
        assert b"post" in body, "Expected form method POST"

    def test_get_contains_all_form_fields(self, auth_client):
        body = auth_client.get(ADD_URL).data
        for name in (b'name="amount"', b'name="category"',
                     b'name="date"', b'name="description"'):
            assert name in body, f"Missing field {name!r}"

    @pytest.mark.parametrize("category", CATEGORIES)
    def test_get_select_contains_category_option(self, auth_client, category):
        body = auth_client.get(ADD_URL).data
        assert b"<select" in body
        assert category.encode() in body, f"Missing category option {category}"

    def test_get_category_select_has_exactly_seven_options(self, auth_client):
        body = auth_client.get(ADD_URL).data.decode()
        start = body.index("<select")
        end = body.index("</select>", start)
        assert body[start:end].count("<option") == 7

    def test_get_date_field_defaults_to_today(self, auth_client):
        from datetime import date

        body = auth_client.get(ADD_URL).data.decode()
        assert date.today().isoformat() in body, "Date should default to today"

    def test_get_has_save_button_and_cancel_link_to_profile(self, auth_client):
        body = auth_client.get(ADD_URL).data
        assert b"Save Expense" in body
        assert b'href="/profile"' in body

    def test_get_does_not_create_row(self, auth_client):
        auth_client.get(ADD_URL)
        assert _all_expenses() == []


# ------------------------------------------------------------------ #
# POST success                                                        #
# ------------------------------------------------------------------ #

class TestPostSuccess:
    def test_post_valid_redirects_to_profile(self, auth_client):
        response = auth_client.post(ADD_URL, data=_valid_form())
        assert response.status_code == 302
        assert _location_path(response).endswith("/profile")

    def test_post_valid_inserts_row_for_session_user(self, auth_client, user_id):
        auth_client.post(ADD_URL, data=_valid_form())

        rows = _all_expenses()
        assert len(rows) == 1
        row = rows[0]
        assert row["user_id"] == user_id
        assert row["amount"] == pytest.approx(50.0)
        assert row["category"] == "Food"
        assert row["date"] == "2026-03-20"
        assert row["description"] == "Lunch"

    def test_post_valid_expense_visible_on_profile_after_redirect(
        self, auth_client
    ):
        response = auth_client.post(
            ADD_URL, data=_valid_form(description="UniqueLunchMarker"),
            follow_redirects=True,
        )
        assert response.status_code == 200
        assert b"UniqueLunchMarker" in response.data

    @pytest.mark.parametrize("category", CATEGORIES)
    def test_post_each_valid_category_accepted(self, auth_client, category):
        response = auth_client.post(ADD_URL, data=_valid_form(category=category))
        assert response.status_code == 302
        assert _all_expenses()[0]["category"] == category

    def test_post_no_description_field_stores_null(self, auth_client):
        data = _valid_form()
        del data["description"]
        response = auth_client.post(ADD_URL, data=data)

        assert response.status_code == 302
        assert _location_path(response).endswith("/profile")
        rows = _all_expenses()
        assert len(rows) == 1
        assert rows[0]["description"] is None

    @pytest.mark.parametrize("blank", ["", "   ", "\t "])
    def test_post_blank_description_stores_null(self, auth_client, blank):
        response = auth_client.post(ADD_URL, data=_valid_form(description=blank))
        assert response.status_code == 302
        assert _all_expenses()[0]["description"] is None

    def test_post_description_is_stripped(self, auth_client):
        auth_client.post(ADD_URL, data=_valid_form(description="  Dinner  "))
        assert _all_expenses()[0]["description"] == "Dinner"

    def test_post_small_positive_amount_accepted(self, auth_client):
        response = auth_client.post(ADD_URL, data=_valid_form(amount="0.01"))
        assert response.status_code == 302
        assert _all_expenses()[0]["amount"] == pytest.approx(0.01)

    def test_post_sql_injection_description_stored_literally(self, auth_client):
        payload = "'); DROP TABLE expenses; --"
        auth_client.post(ADD_URL, data=_valid_form(description=payload))
        rows = _all_expenses()
        assert len(rows) == 1
        assert rows[0]["description"] == payload

    def test_post_ignores_user_id_in_form_data(self, auth_client, user_id, temp_db):
        other = temp_db.create_user("Other", "other@example.com", "pw12345")
        auth_client.post(ADD_URL, data=_valid_form(user_id=str(other)))
        rows = _all_expenses()
        assert len(rows) == 1
        assert rows[0]["user_id"] == user_id


# ------------------------------------------------------------------ #
# POST validation errors                                              #
# ------------------------------------------------------------------ #

class TestPostValidation:
    def _assert_error_rerender(self, response):
        assert response.status_code == 200, "Form should be re-rendered"
        assert ERROR_MARKER in response.data, "Expected an error message"
        assert b"<form" in response.data, "Expected the form to be re-rendered"
        assert _all_expenses() == [], "No row may be inserted on error"

    def test_post_missing_amount_field_shows_error(self, auth_client):
        data = _valid_form()
        del data["amount"]
        self._assert_error_rerender(auth_client.post(ADD_URL, data=data))

    def test_post_empty_amount_shows_error(self, auth_client):
        self._assert_error_rerender(
            auth_client.post(ADD_URL, data=_valid_form(amount=""))
        )

    def test_post_zero_amount_shows_error(self, auth_client):
        self._assert_error_rerender(
            auth_client.post(ADD_URL, data=_valid_form(amount="0"))
        )

    def test_post_negative_amount_shows_error(self, auth_client):
        self._assert_error_rerender(
            auth_client.post(ADD_URL, data=_valid_form(amount="-5"))
        )

    @pytest.mark.parametrize("bad", ["abc", "12abc", "1,5,5", "$$", " "])
    def test_post_non_numeric_amount_shows_error(self, auth_client, bad):
        self._assert_error_rerender(
            auth_client.post(ADD_URL, data=_valid_form(amount=bad))
        )

    @pytest.mark.parametrize(
        "bad", ["Groceries", "food", "", "Food; DROP TABLE expenses", "<script>"]
    )
    def test_post_invalid_category_shows_error(self, auth_client, bad):
        self._assert_error_rerender(
            auth_client.post(ADD_URL, data=_valid_form(category=bad))
        )

    def test_post_missing_category_field_shows_error(self, auth_client):
        data = _valid_form()
        del data["category"]
        self._assert_error_rerender(auth_client.post(ADD_URL, data=data))

    @pytest.mark.parametrize(
        "bad",
        ["not-a-date", "2026-13-01", "2026-02-30", "20-03-2026",
         "2026/03/20", "", "2026-3-2x"],
    )
    def test_post_invalid_date_shows_error(self, auth_client, bad):
        self._assert_error_rerender(
            auth_client.post(ADD_URL, data=_valid_form(date=bad))
        )

    def test_post_missing_date_field_shows_error(self, auth_client):
        data = _valid_form()
        del data["date"]
        self._assert_error_rerender(auth_client.post(ADD_URL, data=data))

    def test_post_error_retains_previously_entered_values(self, auth_client):
        response = auth_client.post(
            ADD_URL,
            data=_valid_form(amount="0", description="KeepMeText",
                             date="2026-03-20", category="Health"),
        )
        assert response.status_code == 200
        body = response.data
        assert b"KeepMeText" in body, "Description should be pre-filled"
        assert b"2026-03-20" in body, "Date should be pre-filled"
        assert b"Health" in body

    def test_post_invalid_category_retains_amount_and_description(
        self, auth_client
    ):
        response = auth_client.post(
            ADD_URL,
            data=_valid_form(category="Bogus", amount="77.5",
                             description="StillHere"),
        )
        assert response.status_code == 200
        assert b"77.5" in response.data
        assert b"StillHere" in response.data

    def test_post_error_does_not_redirect(self, auth_client):
        response = auth_client.post(ADD_URL, data=_valid_form(amount="abc"))
        assert "Location" not in response.headers
