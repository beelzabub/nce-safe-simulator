"""GraphQL calls must survive a transient network blip.

graphql_query's ``retries`` only ever covered GraphQL *errors* — the retry
branch sits behind a parsed response body, so a read timeout or dropped
connection raised straight out of requests.post and aborted the caller. A
create-lorem-data run can spend half an hour building a portfolio and lose it
to one timed-out mutation, leaving a half-built tree that cannot be re-run.

The transport retry is therefore unconditional (callers passing retries=0 want
a blip absorbed too), and the read timeout follows api_timeout like every other
call rather than a hardcoded 30s.
"""
import pytest
import requests
from unittest.mock import patch, Mock

from mixins.utils import UtilitiesMixin

pytestmark = pytest.mark.unit


class _GL(UtilitiesMixin):
    def __init__(self, api_timeout=300):
        self.url           = "https://gitlab.example"
        self.private_token = "tok"
        self.ssl_verify    = True
        self.api_timeout   = api_timeout


def _ok(body=None):
    r = Mock()
    r.raise_for_status.return_value = None
    r.json.return_value = body if body is not None else {"data": {"ok": True}}
    return r


def _http_error(status):
    resp = Mock(status_code=status)
    err  = requests.HTTPError(f"{status}", response=resp)
    r    = Mock()
    r.raise_for_status.side_effect = err
    return r


def test_read_timeout_is_retried_then_succeeds():
    gl = _GL()
    with patch("mixins.utils.requests.post",
               side_effect=[requests.ReadTimeout("boom"), _ok()]) as post, \
         patch("mixins.utils.time.sleep"):
        assert gl.graphql_query("query {}") == {"ok": True}
    assert post.call_count == 2


def test_connection_error_is_retried():
    gl = _GL()
    with patch("mixins.utils.requests.post",
               side_effect=[requests.ConnectionError("reset"), _ok()]), \
         patch("mixins.utils.time.sleep"):
        assert gl.graphql_query("query {}") == {"ok": True}


def test_retry_budget_is_finite_and_reraises_the_real_error():
    gl = _GL()
    with patch("mixins.utils.requests.post",
               side_effect=requests.ReadTimeout("boom")) as post, \
         patch("mixins.utils.time.sleep"):
        with pytest.raises(requests.ReadTimeout):
            gl.graphql_query("query {}")
    assert post.call_count == UtilitiesMixin._GQL_TRANSPORT_ATTEMPTS


def test_transport_retry_applies_even_when_caller_asked_for_no_retries():
    # The create-lorem-data path that lost a 19-minute run passed retries=2,
    # but most callers pass 0 — a blip must not depend on which.
    gl = _GL()
    with patch("mixins.utils.requests.post",
               side_effect=[requests.ReadTimeout("boom"), _ok()]), \
         patch("mixins.utils.time.sleep"):
        assert gl.graphql_query("query {}", retries=0) == {"ok": True}


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_http_statuses_are_retried(status):
    gl = _GL()
    with patch("mixins.utils.requests.post",
               side_effect=[_http_error(status), _ok()]), \
         patch("mixins.utils.time.sleep"):
        assert gl.graphql_query("query {}") == {"ok": True}


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_client_errors_fail_immediately(status):
    # A bad token or malformed query is not going to fix itself — retrying only
    # delays the error the user needs to see.
    gl = _GL()
    with patch("mixins.utils.requests.post",
               side_effect=[_http_error(status), _ok()]) as post, \
         patch("mixins.utils.time.sleep"):
        with pytest.raises(requests.HTTPError):
            gl.graphql_query("query {}")
    assert post.call_count == 1


def test_read_timeout_follows_api_timeout_not_a_hardcoded_30s():
    gl = _GL(api_timeout=300)
    with patch("mixins.utils.requests.post", return_value=_ok()) as post:
        gl.graphql_query("query {}")
    connect, read = post.call_args.kwargs["timeout"]
    assert read == 300, "read timeout must honour api_timeout"
    assert connect == 15, "connect stays short so an unreachable host fails fast"


def test_graphql_errors_still_use_the_callers_retry_budget():
    # Unchanged behaviour: a server that answered with errors retries only as
    # many times as the caller asked, then reports.
    gl = _GL()
    errored = _ok({"errors": [{"message": "nope"}]})
    with patch("mixins.utils.requests.post", return_value=errored) as post, \
         patch("mixins.utils.time.sleep"):
        assert gl.graphql_query("query {}", retries=2) is None
    assert post.call_count == 3
