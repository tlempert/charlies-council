"""The one thing standing between the public internet and a shell on this Mac.

Tailscale Funnel terminates TLS and forwards everything, with no client
identity attached, so the password and the signed cookie are the whole of the
security model. The rate limit is process-wide for the same reason: there is no
per-client key to count against.
"""
import http.client
import threading
import time
import urllib.parse

import pytest

from dashboard import app as app_mod
from dashboard import store as store_mod

PASSWORD = "correct horse battery staple"


@pytest.fixture
def config():
    return app_mod.make_config(PASSWORD, port=0)


class TestPasswordHashing:
    def test_the_password_itself_is_never_stored(self, config):
        assert PASSWORD not in repr(config)
        assert config["password_hash"] != PASSWORD

    def test_the_right_password_is_accepted(self, config):
        assert app_mod.check_password(config, PASSWORD) is True

    def test_a_wrong_password_is_refused(self, config):
        assert app_mod.check_password(config, "wrong") is False
        assert app_mod.check_password(config, "") is False
        assert app_mod.check_password(config, None) is False

    def test_two_installs_of_the_same_password_hash_differently(self):
        assert app_mod.make_config(PASSWORD)["password_hash"] != app_mod.make_config(PASSWORD)["password_hash"]

    def test_each_install_gets_its_own_cookie_secret(self):
        assert app_mod.make_config(PASSWORD)["cookie_secret"] != app_mod.make_config(PASSWORD)["cookie_secret"]


class TestCookie:
    def test_a_freshly_signed_cookie_verifies(self, config):
        assert app_mod.verify_cookie(config, app_mod.sign_cookie(config)) is True

    def test_a_cookie_signed_by_another_install_is_refused(self, config):
        other = app_mod.make_config(PASSWORD)
        assert app_mod.verify_cookie(config, app_mod.sign_cookie(other)) is False

    def test_a_tampered_expiry_is_refused_because_it_is_signed(self, config):
        cookie = app_mod.sign_cookie(config)
        expiry, signature = cookie.split(".", 1)
        forged = f"{int(expiry) + 86400}.{signature}"
        assert app_mod.verify_cookie(config, forged) is False

    def test_an_expired_cookie_is_refused(self, config):
        assert app_mod.verify_cookie(config, app_mod.sign_cookie(config, max_age=-1)) is False

    def test_a_cookie_lasts_thirty_days(self, config):
        expiry = int(app_mod.sign_cookie(config).split(".", 1)[0])
        assert 29 * 86400 < expiry - time.time() <= 30 * 86400

    def test_garbage_where_a_cookie_should_be_is_refused(self, config):
        for junk in ("", "nonsense", "abc.def", "..", None):
            assert app_mod.verify_cookie(config, junk) is False


class TestRateLimit:
    def test_a_fresh_limiter_lets_an_attempt_through(self):
        assert app_mod.RateLimiter().blocked() is False

    def test_four_failures_are_forgiven_and_the_fifth_shuts_the_door(self):
        limiter = app_mod.RateLimiter()
        for _ in range(4):
            limiter.record_failure()
        assert limiter.blocked() is False
        limiter.record_failure()
        assert limiter.blocked() is True

    def test_failures_older_than_the_window_no_longer_count(self):
        limiter = app_mod.RateLimiter(limit=5, window=600)
        limiter.failures.extend([time.time() - 601] * 5)
        assert limiter.blocked() is False

    def test_a_successful_login_clears_the_slate(self):
        limiter = app_mod.RateLimiter()
        for _ in range(5):
            limiter.record_failure()
        limiter.record_success()
        assert limiter.blocked() is False


# --- the same rules, over real HTTP -------------------------------------------

@pytest.fixture
def client(tmp_path, config):
    store = store_mod.Store(tmp_path / "council.db")
    server = app_mod.create_server(store, config, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield _Client(server.server_address[1])
    server.shutdown()
    server.server_close()


class _Client:
    def __init__(self, port):
        self.port = port
        self.cookie = None
        self.location = None

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, form):
        return self._request("POST", path, urllib.parse.urlencode(form),
                             {"Content-Type": "application/x-www-form-urlencoded"})

    def _request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = dict(headers or {})
        if self.cookie:
            headers["Cookie"] = self.cookie
        conn.request(method, path, body, headers)
        response = conn.getresponse()
        payload = response.read().decode("utf-8", "replace")
        self.location = response.getheader("Location")
        set_cookie = response.getheader("Set-Cookie")
        if set_cookie:
            self.cookie = set_cookie.split(";", 1)[0]
        conn.close()
        return response.status, payload


class TestLoginOverHttp:
    def test_the_job_list_is_not_reachable_without_logging_in(self, client):
        status, _ = client.get("/")
        assert status == 303

    def test_the_login_page_is_reachable_without_a_cookie(self, client):
        status, body = client.get("/login")
        assert status == 200
        assert "password" in body

    def test_the_right_password_opens_the_job_list(self, client):
        assert client.post("/login", {"password": PASSWORD})[0] == 303
        status, body = client.get("/")
        assert status == 200
        assert "Silicon Council" in body

    def test_the_wrong_password_says_so_and_grants_nothing(self, client):
        status, body = client.post("/login", {"password": "wrong"})
        assert status == 401
        assert "incorrect" in body.lower()
        assert client.get("/")[0] == 303

    def test_logging_out_takes_the_cookie_back(self, client):
        client.post("/login", {"password": PASSWORD})
        assert client.post("/logout", {})[0] == 303
        assert client.get("/")[0] == 303

    def test_a_sixth_wrong_password_is_rate_limited(self, client):
        for _ in range(5):
            client.post("/login", {"password": "wrong"})
        status, body = client.post("/login", {"password": "wrong"})
        assert status == 429
        assert "too many" in body.lower()

    def test_the_rate_limit_holds_even_for_the_right_password(self, client):
        for _ in range(5):
            client.post("/login", {"password": "wrong"})
        assert client.post("/login", {"password": PASSWORD})[0] == 429
