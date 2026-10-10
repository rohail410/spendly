"""Tests for Step 6: Date filter on GET /profile.

Based on .claude/specs/06-date-filter-profile-page.md.
All tests run against an isolated temporary SQLite file.
"""
import html as html_lib
import re
from datetime import date, timedelta

import pytest

from database import db


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


def _add_expenses(user_id, rows):
    """rows: iterable of (amount, category, iso_date, description)."""
    conn = db.get_db()
    try:
        conn.executemany(
            "INSERT INTO expenses (user_id, amount, category, date, description) "
            "VALUES (?, ?, ?, ?, ?)",
            [(user_id, a, c, d, desc) for a, c, d, desc in rows],
        )
        conn.commit()
    finally:
        conn.close()


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess["user_id"] = user_id


# Fixed-date dataset (total 150.00, 5 transactions)
FIXED_ROWS = [
    (10.00, "Food", "2024-01-10", "JanTen"),
    (20.00, "Transport", "2024-02-01", "FebFirst"),
    (30.00, "Food", "2024-02-15", "FebMid"),
    (40.00, "Bills", "2024-02-29", "FebLast"),
    (50.00, "Other", "2024-03-01", "MarFirst"),
]
FEB_DESCRIPTIONS = {"FebFirst", "FebMid", "FebLast"}
OUTSIDE_FEB_DESCRIPTIONS = {"JanTen", "MarFirst"}
ALL_DESCRIPTIONS = FEB_DESCRIPTIONS | OUTSIDE_FEB_DESCRIPTIONS


@pytest.fixture
def user_id(temp_db):
    uid = temp_db.create_user("Filter User", "filter@example.com", "pw12345")
    _add_expenses(uid, FIXED_ROWS)
    return uid


@pytest.fixture
def other_user_id(temp_db):
    uid = temp_db.create_user("Other Person", "other@example.com", "pw12345")
    _add_expenses(uid, [(999.00, "Shopping", "2024-02-10", "OtherUserItem")])
    return uid


@pytest.fixture
def empty_user_id(temp_db):
    return temp_db.create_user("Empty User", "empty@example.com", "pw12345")


@pytest.fixture
def auth_client(client, user_id):
    _login(client, user_id)
    return client


def _page(client, **params):
    response = client.get("/profile", query_string=params)
    assert response.status_code == 200, "Expected /profile to render with 200"
    return response.get_data(as_text=True)


def _present(page, descriptions):
    return {d for d in descriptions if d in page}


def _anchor_attrs(page, label):
    match = re.search(
        r"<a\b([^>]*)>\s*" + re.escape(label) + r"\s*</a>", page, re.DOTALL
    )
    assert match, f"Expected a link labelled {label!r} on the profile page"
    return match.group(1)


def _anchor_href(page, label):
    attrs = _anchor_attrs(page, label)
    href = re.search(r'href="([^"]*)"', attrs)
    assert href, f"Link {label!r} has no href"
    return html_lib.unescape(href.group(1))


def _anchor_is_active(page, label):
    attrs = _anchor_attrs(page, label)
    cls = re.search(r'class="([^"]*)"', attrs)
    return bool(cls) and "active" in cls.group(1).split()


# ------------------------------------------------------------------ #
# Auth guard                                                          #
# ------------------------------------------------------------------ #

class TestAuthGuard:
    def test_profile_unauthenticated_redirects_to_login(self, client):
        response = client.get("/profile")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_profile_with_filter_params_unauthenticated_redirects_to_login(self, client):
        response = client.get(
            "/profile", query_string={"date_from": "2024-02-01", "date_to": "2024-02-29"}
        )
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


# ------------------------------------------------------------------ #
# Unfiltered behaviour (Step 5 equivalence)                           #
# ------------------------------------------------------------------ #

class TestUnfiltered:
    def test_no_params_shows_all_expenses(self, auth_client):
        page = _page(auth_client)
        assert _present(page, ALL_DESCRIPTIONS) == ALL_DESCRIPTIONS
        assert "₹150.00" in page

    def test_no_params_excludes_other_users_data(self, client, user_id, other_user_id):
        _login(client, user_id)
        page = _page(client)
        assert "OtherUserItem" not in page
        assert "₹999.00" not in page

    def test_filtered_view_excludes_other_users_data(self, client, user_id, other_user_id):
        _login(client, user_id)
        page = _page(client, date_from="2024-02-01", date_to="2024-02-29")
        assert "OtherUserItem" not in page


# ------------------------------------------------------------------ #
# Custom range                                                        #
# ------------------------------------------------------------------ #

class TestCustomRange:
    def test_custom_range_filters_transactions(self, auth_client):
        page = _page(auth_client, date_from="2024-02-01", date_to="2024-02-29")
        assert _present(page, FEB_DESCRIPTIONS) == FEB_DESCRIPTIONS
        assert _present(page, OUTSIDE_FEB_DESCRIPTIONS) == set(), (
            "Expenses outside the range must not be listed"
        )

    def test_custom_range_filters_summary_stats(self, auth_client):
        page = _page(auth_client, date_from="2024-02-01", date_to="2024-02-29")
        assert "₹90.00" in page, "Total spent for Feb should be 90.00"
        assert "₹150.00" not in page
        assert "Bills" in page, "Top category in Feb is Bills"

    def test_custom_range_filters_category_breakdown(self, auth_client):
        page = _page(auth_client, date_from="2024-02-01", date_to="2024-02-29")
        # "Other" (50.00, March) must not appear in the breakdown / anywhere
        assert "₹50.00" not in page
        for amount in ("₹40.00", "₹30.00", "₹20.00"):
            assert amount in page, f"Expected category total {amount} in Feb breakdown"

    def test_inclusive_lower_and_upper_bounds(self, auth_client):
        page = _page(auth_client, date_from="2024-02-01", date_to="2024-02-29")
        assert "FebFirst" in page, "date_from bound must be inclusive"
        assert "FebLast" in page, "date_to bound must be inclusive"

    def test_single_day_range_is_inclusive(self, auth_client):
        page = _page(auth_client, date_from="2024-02-15", date_to="2024-02-15")
        assert "FebMid" in page
        assert _present(page, ALL_DESCRIPTIONS - {"FebMid"}) == set()

    def test_custom_range_keeps_rupee_symbol(self, auth_client):
        page = _page(auth_client, date_from="2024-02-01", date_to="2024-02-29")
        assert "₹" in page

    def test_sql_injection_in_date_params_is_safe(self, auth_client):
        payload = "2024-01-01' OR '1'='1"
        response = auth_client.get(
            "/profile", query_string={"date_from": payload, "date_to": payload}
        )
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert _present(page, ALL_DESCRIPTIONS) == ALL_DESCRIPTIONS, (
            "Malformed input falls back to unfiltered view"
        )

    def test_filter_does_not_modify_database(self, auth_client, temp_db):
        _page(auth_client, date_from="2024-02-01", date_to="2024-02-29")
        conn = temp_db.get_db()
        try:
            count = conn.execute("SELECT COUNT(*) AS c FROM expenses").fetchone()["c"]
        finally:
            conn.close()
        assert count == len(FIXED_ROWS)


# ------------------------------------------------------------------ #
# Validation: reversed range and malformed dates                      #
# ------------------------------------------------------------------ #

class TestValidation:
    def test_reversed_range_flashes_error(self, auth_client):
        page = _page(auth_client, date_from="2024-03-01", date_to="2024-02-01")
        assert "Start date must be before end date." in page

    def test_reversed_range_falls_back_to_unfiltered(self, auth_client):
        page = _page(auth_client, date_from="2024-03-01", date_to="2024-02-01")
        assert _present(page, ALL_DESCRIPTIONS) == ALL_DESCRIPTIONS
        assert "₹150.00" in page

    def test_equal_dates_do_not_flash_error(self, auth_client):
        page = _page(auth_client, date_from="2024-02-15", date_to="2024-02-15")
        assert "Start date must be before end date." not in page

    def test_valid_range_does_not_flash_error(self, auth_client):
        page = _page(auth_client, date_from="2024-02-01", date_to="2024-02-29")
        assert "Start date must be before end date." not in page

    @pytest.mark.parametrize(
        "params",
        [
            {"date_from": "not-a-date", "date_to": "also-bad"},
            {"date_from": "not-a-date", "date_to": "2024-02-29"},
            {"date_from": "2024-02-01", "date_to": "not-a-date"},
            {"date_from": "2024-13-45", "date_to": "2024-02-29"},
            {"date_from": "2024-02-30", "date_to": "2024-03-05"},
            {"date_from": "02/01/2024", "date_to": "02/29/2024"},
            {"date_from": "", "date_to": ""},
            {"date_from": "x" * 5000, "date_to": "y" * 5000},
        ],
    )
    def test_malformed_dates_do_not_crash_and_fall_back_to_unfiltered(
        self, auth_client, params
    ):
        response = auth_client.get("/profile", query_string=params)
        assert response.status_code == 200, "Malformed dates must not crash the app"
        page = response.get_data(as_text=True)
        assert _present(page, ALL_DESCRIPTIONS) == ALL_DESCRIPTIONS
        assert "₹150.00" in page

    @pytest.mark.parametrize(
        "params",
        [{"date_from": "2024-02-01"}, {"date_to": "2024-02-29"}],
    )
    def test_only_one_bound_falls_back_to_unfiltered(self, auth_client, params):
        """Spec: 'If either parameter is absent or malformed' -> unfiltered."""
        page = _page(auth_client, **params)
        assert _present(page, ALL_DESCRIPTIONS) == ALL_DESCRIPTIONS


# ------------------------------------------------------------------ #
# Empty range                                                         #
# ------------------------------------------------------------------ #

class TestEmptyRange:
    def test_range_without_expenses_shows_zero_state(self, auth_client):
        page = _page(auth_client, date_from="1990-01-01", date_to="1990-12-31")
        assert "₹0.00" in page
        assert _present(page, ALL_DESCRIPTIONS) == set()
        for amount in ("₹10.00", "₹20.00", "₹30.00", "₹40.00", "₹50.00", "₹150.00"):
            assert amount not in page

    def test_empty_range_helpers_return_zero_values(self, user_id):
        from database.queries import (
            get_category_breakdown,
            get_recent_transactions,
            get_summary_stats,
        )

        kwargs = {"date_from": "1990-01-01", "date_to": "1990-12-31"}
        stats = get_summary_stats(user_id, **kwargs)
        assert stats["total_spent"] == 0
        assert stats["transaction_count"] == 0
        assert get_recent_transactions(user_id, **kwargs) == []
        assert get_category_breakdown(user_id, **kwargs) == []

    def test_user_without_any_expenses_filtered_page_ok(self, client, empty_user_id):
        _login(client, empty_user_id)
        page = _page(client, date_from="2024-01-01", date_to="2024-12-31")
        assert "₹0.00" in page


# ------------------------------------------------------------------ #
# Presets                                                             #
# ------------------------------------------------------------------ #

PRESET_ROWS = [
    (1.00, "Food", None, "PresetToday", 0),
    (2.00, "Food", None, "Preset60DaysAgo", 60),
    (4.00, "Food", None, "Preset150DaysAgo", 150),
    (8.00, "Food", None, "Preset400DaysAgo", 400),
]
PRESET_DESCS = {r[3] for r in PRESET_ROWS}


@pytest.fixture
def preset_client(client, temp_db):
    uid = temp_db.create_user("Preset User", "preset@example.com", "pw12345")
    today = date.today()
    _add_expenses(
        uid,
        [
            (amt, cat, (today - timedelta(days=offset)).isoformat(), desc)
            for amt, cat, _, desc, offset in PRESET_ROWS
        ],
    )
    _login(client, uid)
    return client


class TestPresets:
    def test_all_four_preset_links_present(self, preset_client):
        page = _page(preset_client)
        for label in ("This Month", "Last 3 Months", "Last 6 Months", "All Time"):
            assert label in page, f"Missing preset {label!r}"
            assert "/profile" in _anchor_href(page, label)

    def test_all_time_link_is_clean_profile_url(self, preset_client):
        page = _page(preset_client)
        href = _anchor_href(page, "All Time")
        assert href == "/profile", f"All Time must be a clean URL, got {href!r}"

    def test_this_month_link_covers_first_of_month_to_today(self, preset_client):
        page = _page(preset_client)
        href = _anchor_href(page, "This Month")
        today = date.today()
        assert f"date_from={today.replace(day=1).isoformat()}" in href
        assert f"date_to={today.isoformat()}" in href

    @pytest.mark.parametrize("label", ["Last 3 Months", "Last 6 Months"])
    def test_multi_month_links_end_today(self, preset_client, label):
        href = _anchor_href(_page(preset_client), label)
        assert f"date_to={date.today().isoformat()}" in href
        assert "date_from=" in href

    def test_this_month_link_shows_only_current_month(self, preset_client):
        page = _page(preset_client)
        href = _anchor_href(page, "This Month")
        filtered = preset_client.get(href).get_data(as_text=True)
        assert "PresetToday" in filtered
        assert _present(filtered, PRESET_DESCS - {"PresetToday"}) == set()

    def test_last_3_months_link_filters_window(self, preset_client):
        href = _anchor_href(_page(preset_client), "Last 3 Months")
        filtered = preset_client.get(href).get_data(as_text=True)
        assert _present(filtered, PRESET_DESCS) == {"PresetToday", "Preset60DaysAgo"}

    def test_last_6_months_link_filters_window(self, preset_client):
        href = _anchor_href(_page(preset_client), "Last 6 Months")
        filtered = preset_client.get(href).get_data(as_text=True)
        assert _present(filtered, PRESET_DESCS) == {
            "PresetToday",
            "Preset60DaysAgo",
            "Preset150DaysAgo",
        }

    def test_all_time_link_shows_everything(self, preset_client):
        narrowed = _anchor_href(_page(preset_client), "This Month")
        page = preset_client.get(narrowed).get_data(as_text=True)
        href = _anchor_href(page, "All Time")
        everything = preset_client.get(href).get_data(as_text=True)
        assert _present(everything, PRESET_DESCS) == PRESET_DESCS


# ------------------------------------------------------------------ #
# Active-state highlighting                                           #
# ------------------------------------------------------------------ #

class TestActiveState:
    def test_all_time_active_with_no_params(self, preset_client):
        page = _page(preset_client)
        assert _anchor_is_active(page, "All Time")
        for label in ("This Month", "Last 3 Months", "Last 6 Months"):
            assert not _anchor_is_active(page, label), f"{label} should not be active"

    @pytest.mark.parametrize(
        "label", ["This Month", "Last 3 Months", "Last 6 Months"]
    )
    def test_selected_preset_is_highlighted_only(self, preset_client, label):
        href = _anchor_href(_page(preset_client), label)
        page = preset_client.get(href).get_data(as_text=True)
        assert _anchor_is_active(page, label), f"{label} should be active"
        others = {"This Month", "Last 3 Months", "Last 6 Months", "All Time"} - {label}
        for other in others:
            assert not _anchor_is_active(page, other), f"{other} should not be active"

    def test_custom_range_does_not_highlight_any_preset(self, auth_client):
        page = _page(auth_client, date_from="2024-02-01", date_to="2024-02-29")
        for label in ("This Month", "Last 3 Months", "Last 6 Months", "All Time"):
            assert not _anchor_is_active(page, label), f"{label} should not be active"

    def test_custom_range_reflected_in_date_inputs(self, auth_client):
        page = _page(auth_client, date_from="2024-02-01", date_to="2024-02-29")
        assert 'type="date"' in page
        assert re.search(r'name="date_from"[^>]*value="2024-02-01"', page)
        assert re.search(r'name="date_to"[^>]*value="2024-02-29"', page)

    def test_custom_form_has_two_date_inputs_and_apply_button(self, auth_client):
        page = _page(auth_client)
        assert len(re.findall(r'type="date"', page)) == 2
        assert re.search(r'name="date_from"', page)
        assert re.search(r'name="date_to"', page)
        assert "Apply" in page

    def test_custom_form_submits_via_get_to_profile(self, auth_client):
        page = _page(auth_client)
        forms = re.findall(r"<form\b([^>]*)>(.*?)</form>", page, re.DOTALL)
        matching = [attrs for attrs, body in forms if 'type="date"' in body]
        assert matching, "Expected a form containing the date inputs"
        assert "get" in matching[0].lower()
        assert "/profile" in matching[0]

    def test_invalid_range_highlights_all_time(self, auth_client):
        page = _page(auth_client, date_from="2024-03-01", date_to="2024-02-01")
        assert _anchor_is_active(page, "All Time")


# ------------------------------------------------------------------ #
# Rupee symbol                                                        #
# ------------------------------------------------------------------ #

class TestRupeeSymbol:
    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"date_from": "2024-02-01", "date_to": "2024-02-29"},
            {"date_from": "1990-01-01", "date_to": "1990-01-02"},
            {"date_from": "bad", "date_to": "worse"},
            {"date_from": "2024-03-01", "date_to": "2024-02-01"},
        ],
    )
    def test_rupee_symbol_shown_under_every_filter(self, auth_client, params):
        page = _page(auth_client, **params)
        assert "₹" in page, "Rupee symbol must be shown regardless of filter"


# ------------------------------------------------------------------ #
# Query helpers                                                       #
# ------------------------------------------------------------------ #

class TestQueryHelpers:
    def test_summary_stats_default_is_unfiltered(self, user_id):
        from database.queries import get_summary_stats

        stats = get_summary_stats(user_id)
        assert stats["total_spent"] == pytest.approx(150.00)
        assert stats["transaction_count"] == 5

    def test_summary_stats_explicit_none_equals_default(self, user_id):
        from database.queries import get_summary_stats

        assert get_summary_stats(user_id, date_from=None, date_to=None) == (
            get_summary_stats(user_id)
        )

    def test_summary_stats_with_range(self, user_id):
        from database.queries import get_summary_stats

        stats = get_summary_stats(user_id, date_from="2024-02-01", date_to="2024-02-29")
        assert stats["total_spent"] == pytest.approx(90.00)
        assert stats["transaction_count"] == 3
        assert stats["top_category"] == "Bills"

    def test_summary_stats_range_bounds_inclusive(self, user_id):
        from database.queries import get_summary_stats

        stats = get_summary_stats(user_id, date_from="2024-02-15", date_to="2024-02-15")
        assert stats["transaction_count"] == 1
        assert stats["total_spent"] == pytest.approx(30.00)

    def test_summary_stats_positional_signature(self, user_id):
        from database.queries import get_summary_stats

        stats = get_summary_stats(user_id, "2024-02-01", "2024-02-29")
        assert stats["transaction_count"] == 3

    def test_recent_transactions_default_is_unfiltered(self, user_id):
        from database.queries import get_recent_transactions

        assert len(get_recent_transactions(user_id)) == 5

    def test_recent_transactions_with_range_newest_first(self, user_id):
        from database.queries import get_recent_transactions

        result = get_recent_transactions(
            user_id, date_from="2024-02-01", date_to="2024-02-29"
        )
        assert [r["description"] for r in result] == ["FebLast", "FebMid", "FebFirst"]
        assert set(result[0]) == {"date", "description", "category", "amount"}

    def test_recent_transactions_limit_still_applies_with_range(self, user_id):
        from database.queries import get_recent_transactions

        result = get_recent_transactions(
            user_id, limit=2, date_from="2024-02-01", date_to="2024-02-29"
        )
        assert [r["description"] for r in result] == ["FebLast", "FebMid"]

    def test_recent_transactions_limit_keyword_default_preserved(self, user_id):
        from database.queries import get_recent_transactions

        assert len(get_recent_transactions(user_id, limit=3)) == 3

    def test_category_breakdown_default_is_unfiltered(self, user_id):
        from database.queries import get_category_breakdown

        names = {c["name"] for c in get_category_breakdown(user_id)}
        assert names == {"Food", "Transport", "Bills", "Other"}

    def test_category_breakdown_with_range(self, user_id):
        from database.queries import get_category_breakdown

        result = get_category_breakdown(
            user_id, date_from="2024-02-01", date_to="2024-02-29"
        )
        assert [c["name"] for c in result] == ["Bills", "Food", "Transport"]
        assert result[0]["amount"] == pytest.approx(40.00)
        assert "Other" not in {c["name"] for c in result}

    def test_category_pct_sums_to_100_in_filtered_range(self, user_id):
        from database.queries import get_category_breakdown

        result = get_category_breakdown(
            user_id, date_from="2024-02-01", date_to="2024-02-29"
        )
        assert sum(c["pct"] for c in result) == 100

    def test_category_pct_sums_to_100_with_awkward_thirds(self, temp_db):
        from database.queries import get_category_breakdown

        uid = temp_db.create_user("Thirds", "thirds@example.com", "pw12345")
        _add_expenses(
            uid,
            [
                (10.00, "Food", "2024-05-01", "a"),
                (10.00, "Bills", "2024-05-02", "b"),
                (10.00, "Other", "2024-05-03", "c"),
                (999.00, "Shopping", "2024-06-01", "outside"),
            ],
        )
        result = get_category_breakdown(uid, date_from="2024-05-01", date_to="2024-05-31")
        assert len(result) == 3
        assert sum(c["pct"] for c in result) == 100

    def test_category_pct_sums_to_100_on_profile_page(self, temp_db, client):
        uid = temp_db.create_user("Thirds2", "thirds2@example.com", "pw12345")
        _add_expenses(
            uid,
            [
                (10.00, "Food", "2024-05-01", "a"),
                (10.00, "Bills", "2024-05-02", "b"),
                (10.00, "Other", "2024-05-03", "c"),
            ],
        )
        from database.queries import get_category_breakdown

        _login(client, uid)
        page = _page(client, date_from="2024-05-01", date_to="2024-05-31")
        pcts = [
            c["pct"]
            for c in get_category_breakdown(
                uid, date_from="2024-05-01", date_to="2024-05-31"
            )
        ]
        assert sum(pcts) == 100
        assert "₹10.00" in page

    def test_helpers_scope_range_to_user(self, user_id, other_user_id):
        from database.queries import get_summary_stats

        stats = get_summary_stats(
            user_id, date_from="2024-02-01", date_to="2024-02-29"
        )
        assert stats["total_spent"] == pytest.approx(90.00)

    def test_helpers_reject_injection_safely(self, user_id):
        from database.queries import get_summary_stats

        stats = get_summary_stats(
            user_id, date_from="2024-01-01' OR '1'='1", date_to="2024-12-31"
        )
        assert stats["transaction_count"] >= 0
        # table must still exist and be intact
        assert get_summary_stats(user_id)["transaction_count"] == 5
