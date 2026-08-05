"""Tests for POST /api/query — the JQL search endpoint (issue #302).

The endpoint is a thin surface over the same ``run_jql()`` entry point the
CLI query tool uses, so the verification contract is parity: for the golden
query set, the endpoint must return exactly the same rows as a direct
``run_jql`` call with the identical query. Plus the error taxonomy — bad
queries return 4xx (never 500) with a structured detail the UI can anchor
inline (syntax errors carry position / found / expected), transport failures
are 502, and a server without a GitLab client is 503.
"""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from jql import JqlExecutionError
from server.app import app
from test_jql_query_parity import (
    GOLDEN_QUERIES,
    NOW,
    FakeGitLabBackend,
    QueryHarness,
)

pytestmark = pytest.mark.integration


class FixedNowHarness(QueryHarness):
    """QueryHarness pinned to the golden fixture's reference time so
    relative-date queries (``updated >= -4w``) stay deterministic no matter
    when the suite runs."""

    def run_jql(self, query, limit=None, push_down=True, now=None):
        return super().run_jql(query, limit=limit, push_down=push_down,
                               now=now or NOW)


@pytest.fixture()
def client():
    app.state.gl = FixedNowHarness()
    yield TestClient(app)
    app.state.gl = None


def post(client, body):
    return client.post("/api/query", json=body)


# ---------------------------------------------------------------------------
# Parity: endpoint rows == direct run_jql rows for every golden query
# ---------------------------------------------------------------------------

class TestEndpointParity:

    @pytest.mark.parametrize("query", GOLDEN_QUERIES)
    def test_endpoint_matches_run_jql(self, client, query):
        resp = post(client, {"jql": query, "limit": 1000})
        assert resp.status_code == 200

        direct = FixedNowHarness().run_jql(query, limit=1000)
        body = resp.json()
        assert body["items"] == direct["items"]       # exact rows, exact order
        assert body["count"] == direct["count"]
        assert body["truncated"] == direct["truncated"]

    def test_envelope_shape(self, client):
        body = post(client, {"jql": "state = opened"}).json()
        assert set(body) >= {"query", "items", "count", "limit",
                             "truncated", "plan"}
        assert body["query"] == "state = opened"
        assert body["limit"] == 100                   # run_jql default applies
        for item in body["items"]:
            assert set(item) >= {"iid", "title", "type", "state", "labels",
                                 "assignees", "weight", "created_at",
                                 "updated_at", "due_date", "web_url"}

    def test_limit_caps_and_flags_truncation(self, client):
        full = post(client, {"jql": "state = opened", "limit": 1000}).json()
        assert full["count"] > 2 and not full["truncated"]

        capped = post(client, {"jql": "state = opened", "limit": 2}).json()
        assert capped["count"] == 2
        assert capped["limit"] == 2
        assert capped["truncated"] is True
        assert capped["items"] == full["items"][:2]


# ---------------------------------------------------------------------------
# Error taxonomy — 4xx with structured detail, never 500
# ---------------------------------------------------------------------------

class TestQueryErrors:

    def test_syntax_error_carries_position_and_expectations(self, client):
        resp = post(client, {"jql": "state = opened AND"})
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["kind"] == "syntax"
        assert isinstance(detail["position"], int)
        assert 0 <= detail["position"] <= len("state = opened AND")
        assert detail["expected"]                     # non-empty vocabulary
        assert detail["message"]

    def test_syntax_error_position_points_at_the_defect(self, client):
        query = "state ="
        detail = post(client, {"jql": query}).json()["detail"]
        assert detail["kind"] == "syntax"
        assert detail["position"] == len(query)       # value missing at the end

    @pytest.mark.parametrize("bad", [
        "state =",
        "(state = opened",
        "state = opened ORDER BY",
        "AND state = opened",
        "weight >",
        "ORDER BY",
        "state = opened extra_garbage =",
        "labels IN (",
    ])
    def test_malformed_queries_are_4xx_never_500(self, client, bad):
        resp = post(client, {"jql": bad})
        assert resp.status_code == 400
        assert resp.json()["detail"]["kind"] in ("syntax", "semantic")

    def test_unknown_field_is_semantic_400(self, client):
        resp = post(client, {"jql": "flavor = chocolate"})
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["kind"] == "semantic"
        assert "flavor" in detail["message"]
        assert "state" in detail["message"]           # lists the vocabulary

    def test_unknown_taxonomy_value_is_semantic_400(self, client):
        resp = post(client, {"jql": "epic_type = banana"})
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["kind"] == "semantic"
        assert "banana" in detail["message"]

    @pytest.mark.parametrize("limit", [0, -5, "ten", 2.5, True, False])
    def test_bad_limit_is_request_400(self, client, limit):
        resp = post(client, {"jql": "state = opened", "limit": limit})
        assert resp.status_code == 400
        assert resp.json()["detail"]["kind"] == "request"

    @pytest.mark.parametrize("body", [{}, {"jql": None}, {"jql": 42},
                                      {"jql": ["state = opened"]}])
    def test_missing_or_nonstring_jql_is_request_400(self, client, body):
        resp = post(client, body)
        assert resp.status_code == 400
        assert resp.json()["detail"]["kind"] == "request"


# ---------------------------------------------------------------------------
# Availability / transport
# ---------------------------------------------------------------------------

class TestAvailability:

    def test_no_gitlab_client_is_503(self):
        app.state.gl = None
        resp = TestClient(app).post("/api/query", json={"jql": "state = opened"})
        assert resp.status_code == 503
        assert resp.json()["detail"]["kind"] == "unavailable"

    def test_transport_failure_is_502(self):
        gl = MagicMock()
        gl.run_jql.side_effect = JqlExecutionError("GraphQL work-items query failed")
        app.state.gl = gl
        try:
            resp = TestClient(app).post("/api/query", json={"jql": "state = opened"})
            assert resp.status_code == 502
            detail = resp.json()["detail"]
            assert detail["kind"] == "transport"
            assert "GraphQL" in detail["message"]
        finally:
            app.state.gl = None

    def test_limit_passes_through_to_run_jql(self):
        gl = MagicMock()
        gl.run_jql.return_value = {"query": "", "items": [], "count": 0,
                                   "limit": 7, "truncated": False, "plan": {}}
        app.state.gl = gl
        try:
            resp = TestClient(app).post(
                "/api/query", json={"jql": "state = opened", "limit": 7})
            assert resp.status_code == 200
            gl.run_jql.assert_called_once_with("state = opened", limit=7)
        finally:
            app.state.gl = None

    def test_absent_limit_defers_to_run_jql_default(self):
        gl = MagicMock()
        gl.run_jql.return_value = {"query": "", "items": [], "count": 0,
                                   "limit": 100, "truncated": False, "plan": {}}
        app.state.gl = gl
        try:
            resp = TestClient(app).post(
                "/api/query", json={"jql": "state = opened"})
            assert resp.status_code == 200
            gl.run_jql.assert_called_once_with("state = opened", limit=None)
        finally:
            app.state.gl = None
