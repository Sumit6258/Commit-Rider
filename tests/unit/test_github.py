import datetime as dt
import json
import logging
import random
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from commit_rider.errors import (
    APIResponseError,
    AuthenticationError,
    ConfigError,
    MissingTokenError,
    NetworkError,
    RateLimitError,
    UserNotFoundError,
)
from commit_rider.github.client import GitHubClient, TransportResponse, urllib_transport
from commit_rider.github.graphql import CONTRIBUTIONS_QUERY, GRAPHQL_ENDPOINT, build_variables, windows
from commit_rider.github.parser import parse_calendar_response
from commit_rider.logging_utils import RedactingFilter, redact, register_secret

TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
START, END = dt.date(2026, 1, 1), dt.date(2026, 12, 31)


def calendar_payload(start, end, login="octocat", restricted=0, total=None, count=lambda i: i % 4):
    days, cursor, i = [], start, 0
    while cursor <= end:
        days.append({"date": cursor.isoformat(), "contributionCount": count(i)})
        cursor += dt.timedelta(days=1)
        i += 1
    weeks = [{"contributionDays": days[k : k + 7]} for k in range(0, len(days), 7)]
    if total is None:
        total = sum(d["contributionCount"] for d in days)
    return {
        "data": {
            "user": {
                "login": login,
                "contributionsCollection": {
                    "restrictedContributionsCount": restricted,
                    "hasAnyRestrictedContributions": restricted > 0,
                    "contributionCalendar": {"totalContributions": total, "weeks": weeks},
                },
            }
        }
    }


def ok(payload):
    return TransportResponse(200, {}, json.dumps(payload).encode())


def http(status, headers=None, body=b"{}"):
    return TransportResponse(status, headers or {}, body if isinstance(body, bytes) else body.encode())


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "body": json.loads(body), "timeout": timeout})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def make_client(*responses, **kwargs):
    transport = FakeTransport(*responses)
    sleeps = []
    client = GitHubClient(TOKEN, transport=transport, sleep=sleeps.append, rng=random.Random(1), **kwargs)
    return client, transport, sleeps


class GraphqlHelperTests(unittest.TestCase):
    def test_windows_cover_the_range_without_overlap(self):
        spans = windows(dt.date(2025, 1, 1), dt.date(2026, 6, 30))
        self.assertEqual(spans[0][0], dt.date(2025, 1, 1))
        self.assertEqual(spans[-1][1], dt.date(2026, 6, 30))
        for (_, a_end), (b_start, _) in zip(spans, spans[1:]):
            self.assertEqual(b_start - a_end, dt.timedelta(days=1))
        self.assertTrue(all((b - a).days + 1 <= 365 for a, b in spans))
        self.assertEqual(len(windows(START, dt.date(2026, 12, 31))), 1)  # exactly 365 days: one request
        self.assertEqual(len(windows(dt.date(2028, 1, 1), dt.date(2028, 12, 31))), 2)  # leap year: 366 days
        with self.assertRaises(ValueError):
            windows(END, START)

    def test_variables_use_utc_day_boundaries(self):
        v = build_variables("octocat", dt.date(2026, 2, 28), dt.date(2026, 3, 1))
        self.assertEqual(v, {"login": "octocat", "from": "2026-02-28T00:00:00Z", "to": "2026-03-01T23:59:59Z"})

    def test_query_only_asks_for_aggregate_fields(self):
        for forbidden in ("repository", "commit", "nameWithOwner", "message", "issue", "pullRequest"):
            self.assertNotIn(forbidden, CONTRIBUTIONS_QUERY)
        for wanted in ("contributionCalendar", "contributionCount", "restrictedContributionsCount", "totalContributions"):
            self.assertIn(wanted, CONTRIBUTIONS_QUERY)


class ClientSuccessTests(unittest.TestCase):
    def test_fetches_one_year_in_one_request(self):
        client, transport, sleeps = make_client(ok(calendar_payload(START, END)))
        series = client.fetch_contributions("octocat", START, END)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual((series.start, series.end, len(series)), (START, END, 365))
        self.assertEqual(series.source, "github")
        self.assertEqual(series.username, "octocat")
        self.assertEqual(series.reported_total, series.total)
        self.assertEqual(sleeps, [])
        call = transport.calls[0]
        self.assertEqual(call["url"], GRAPHQL_ENDPOINT)
        self.assertEqual(call["headers"]["Authorization"], f"Bearer {TOKEN}")
        self.assertTrue(call["headers"]["User-Agent"].startswith("commit-rider/"))
        self.assertEqual(call["body"]["variables"]["login"], "octocat")
        self.assertEqual(call["body"]["variables"]["from"], "2026-01-01T00:00:00Z")
        self.assertEqual(call["timeout"], 20.0)

    def test_long_ranges_are_chunked_and_merged_in_order(self):
        start, end = dt.date(2025, 3, 1), dt.date(2026, 7, 14)
        first, second = windows(start, end)
        client, transport, _ = make_client(ok(calendar_payload(*first)), ok(calendar_payload(*second)))
        series = client.fetch_contributions("octocat", start, end)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(len(series), (end - start).days + 1)
        self.assertEqual([d.date for d in series.days], sorted(d.date for d in series.days))
        self.assertEqual(series.filled_days, 0)

    def test_days_outside_the_window_are_dropped(self):
        payload = calendar_payload(dt.date(2025, 12, 28), END)  # GitHub returns whole weeks
        client, _, _ = make_client(ok(payload))
        series = client.fetch_contributions("octocat", START, END)
        self.assertEqual(series.start, START)

    def test_private_aggregate_only_when_requested(self):
        payload = calendar_payload(START, END, restricted=321)
        client, _, _ = make_client(ok(payload), ok(payload))
        self.assertEqual(client.fetch_contributions("octocat", START, END, include_private=True).restricted, 321)
        self.assertIsNone(client.fetch_contributions("octocat", START, END).restricted)

    def test_canonical_login_casing_is_used(self):
        client, _, _ = make_client(ok(calendar_payload(START, END, login="OctoCat")))
        self.assertEqual(client.fetch_contributions("octocat", START, END).username, "OctoCat")

    def test_warnings_for_missing_days_and_total_mismatch(self):
        payload = calendar_payload(START, END, total=999999)
        weeks = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
        del weeks[10]["contributionDays"][3]
        client, _, _ = make_client(ok(payload))
        with self.assertLogs("commit_rider", level="WARNING") as logs:
            series = client.fetch_contributions("octocat", START, END)
        text = "\n".join(logs.output)
        self.assertEqual(series.filled_days, 1)
        self.assertIn("no entry", text)
        self.assertIn("999999", text)


class ClientErrorTests(unittest.TestCase):
    def fetch(self, *responses, **kwargs):
        client, transport, sleeps = make_client(*responses, **kwargs)
        return client, transport, sleeps

    def test_missing_token(self):
        for token in (None, "", "   "):
            with self.subTest(token=token), self.assertRaises(MissingTokenError):
                GitHubClient(token)

    def test_https_only_and_sane_limits(self):
        with self.assertRaises(ConfigError):
            GitHubClient(TOKEN, endpoint="http://api.github.com/graphql")
        with self.assertRaises(ConfigError):
            GitHubClient(TOKEN, timeout=0)
        with self.assertRaises(ConfigError):
            GitHubClient(TOKEN, max_retries=-1)

    def test_invalid_username_never_reaches_the_network(self):
        client, transport, _ = self.fetch()
        with self.assertRaises(ConfigError):
            client.fetch_contributions("bad name!", START, END)
        with self.assertRaises(ConfigError):
            client.fetch_contributions("octocat", END, START)
        self.assertEqual(transport.calls, [])

    def test_401_is_an_authentication_error_and_is_not_retried(self):
        client, transport, sleeps = self.fetch(http(401, body='{"message":"Bad credentials"}'))
        with self.assertRaises(AuthenticationError) as ctx:
            client.fetch_contributions("octocat", START, END)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(sleeps, [])
        self.assertIn("401", str(ctx.exception))

    def test_403_rate_limit_reports_the_reset_time(self):
        reset = str(int(dt.datetime(2026, 11, 20, 12, 30, tzinfo=dt.timezone.utc).timestamp()))
        client, transport, _ = self.fetch(
            http(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset}, '{"message":"API rate limit exceeded"}')
        )
        with self.assertRaises(RateLimitError) as ctx:
            client.fetch_contributions("octocat", START, END)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(ctx.exception.reset_at, dt.datetime(2026, 11, 20, 12, 30, tzinfo=dt.timezone.utc))
        self.assertIn("2026-11-20 12:30 UTC", str(ctx.exception))

    def test_secondary_rate_limit_honours_retry_after(self):
        client, transport, sleeps = self.fetch(http(403, {"retry-after": "2"}, "secondary rate limit"), ok(calendar_payload(START, END)))
        client.fetch_contributions("octocat", START, END)
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(sleeps, [2.0])

    def test_429_without_or_with_huge_retry_after(self):
        client, transport, _ = self.fetch(http(429))
        with self.assertRaises(RateLimitError):
            client.fetch_contributions("octocat", START, END)
        client, transport, sleeps = self.fetch(http(429, {"retry-after": "3600"}))
        with self.assertRaises(RateLimitError):
            client.fetch_contributions("octocat", START, END)
        self.assertEqual((len(transport.calls), sleeps), (1, []))

    def test_403_without_rate_limit_is_a_permission_error(self):
        client, _, _ = self.fetch(http(403, body='{"message":"Resource not accessible by integration"}'))
        with self.assertRaises(AuthenticationError) as ctx:
            client.fetch_contributions("octocat", START, END)
        self.assertIn("permission", str(ctx.exception))

    def test_5xx_is_retried_with_bounded_exponential_backoff(self):
        client, transport, sleeps = self.fetch(http(502), http(503), ok(calendar_payload(START, END)))
        client.fetch_contributions("octocat", START, END)
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(len(sleeps), 2)
        self.assertTrue(1.0 <= sleeps[0] <= 1.25 and 2.0 <= sleeps[1] <= 2.5, sleeps)

    def test_retries_are_bounded_and_capped(self):
        client, transport, sleeps = self.fetch(*[http(500)] * 10, max_retries=5, backoff_cap=4.0)
        with self.assertRaises(NetworkError):
            client.fetch_contributions("octocat", START, END)
        self.assertEqual(len(transport.calls), 6)  # first try + 5 retries, no more
        self.assertEqual(len(sleeps), 5)
        self.assertTrue(all(s <= 4.0 * 1.25 for s in sleeps), sleeps)
        self.assertEqual(sleeps[:3], sorted(sleeps[:3]))

    def test_network_failures_are_retried_then_reported(self):
        client, transport, sleeps = self.fetch(NetworkError("timed out"), ok(calendar_payload(START, END)))
        client.fetch_contributions("octocat", START, END)
        self.assertEqual(len(sleeps), 1)
        client, transport, _ = self.fetch(*[NetworkError("down")] * 4)
        with self.assertRaises(NetworkError):
            client.fetch_contributions("octocat", START, END)
        self.assertEqual(len(transport.calls), 4)

    def test_graphql_errors_map_to_specific_exceptions(self):
        cases = [
            ({"type": "NOT_FOUND", "message": "Could not resolve to a User"}, UserNotFoundError),
            ({"type": "RATE_LIMITED", "message": "limit"}, RateLimitError),
            ({"type": "FORBIDDEN", "message": "nope"}, AuthenticationError),
            ({"type": "INSUFFICIENT_SCOPES", "message": "needs read:user"}, AuthenticationError),
            ({"type": "SOMETHING", "message": "x" * 1000}, APIResponseError),
        ]
        for error, expected in cases:
            with self.subTest(error=error["type"]):
                client, _, _ = self.fetch(ok({"data": None, "errors": [error]}))
                with self.assertRaises(expected) as ctx:
                    client.fetch_contributions("octocat", START, END)
                self.assertLess(len(str(ctx.exception)), 400)

    def test_null_user_means_not_found(self):
        client, _, _ = self.fetch(ok({"data": {"user": None}}))
        with self.assertRaises(UserNotFoundError):
            client.fetch_contributions("octocat", START, END)

    def test_malformed_responses(self):
        good = calendar_payload(START, dt.date(2026, 1, 20))
        cal = lambda p: p["data"]["user"]["contributionsCollection"]["contributionCalendar"]  # noqa: E731
        broken = []
        for mutate in (
            lambda p: cal(p).update(weeks="nope"),
            lambda p: cal(p).update(totalContributions="12"),
            lambda p: cal(p)["weeks"][0]["contributionDays"][0].update(date="not-a-date"),
            lambda p: cal(p)["weeks"][0]["contributionDays"][0].update(contributionCount=-5),
            lambda p: cal(p)["weeks"][0].pop("contributionDays"),
            lambda p: p["data"]["user"]["contributionsCollection"].pop("contributionCalendar"),
            lambda p: p.update(data=[]),
        ):
            payload = json.loads(json.dumps(good))
            mutate(payload)
            broken.append(ok(payload))
        for response in broken + [http(200, body=b"<html>"), http(200, body=b"[1,2]"), http(418), http(404)]:
            client, _, _ = self.fetch(response)
            with self.subTest(response=response.body[:40]), self.assertRaises(APIResponseError):
                client.fetch_contributions("octocat", START, dt.date(2026, 1, 20))

    def test_parser_accepts_extra_fields_and_missing_restricted(self):
        payload = calendar_payload(START, dt.date(2026, 1, 14))
        payload["data"]["user"]["contributionsCollection"].pop("restrictedContributionsCount")
        window = parse_calendar_response(payload)
        self.assertEqual((len(window.days), window.restricted), (14, None))


class SecretHandlingTests(unittest.TestCase):
    def test_token_never_appears_in_repr_errors_or_logs(self):
        client, transport, _ = make_client(http(500), http(401), http(403, {"x-ratelimit-remaining": "0"}))
        self.assertNotIn(TOKEN, repr(client))
        self.assertNotIn(TOKEN, str(client.__dict__.get("endpoint")))
        with self.assertLogs("commit_rider", level="DEBUG") as logs:
            logging.getLogger("commit_rider").debug("starting")
            with self.assertRaises(AuthenticationError) as ctx:
                client.fetch_contributions("octocat", START, END)
        self.assertNotIn(TOKEN, "\n".join(logs.output))
        self.assertNotIn(TOKEN, str(ctx.exception))
        self.assertIn(TOKEN, transport.calls[0]["headers"]["Authorization"])  # only ever in the header

    def test_redaction_helpers(self):
        self.assertEqual(redact(f"token {TOKEN} here"), "token *** here")
        self.assertEqual(redact("github_pat_" + "A" * 30), "***")
        self.assertEqual(redact("nothing secret"), "nothing secret")
        register_secret("custom-secret-value")
        self.assertEqual(redact("x custom-secret-value y"), "x *** y")
        record = logging.LogRecord("n", logging.INFO, "f", 1, f"oops {TOKEN}", None, None)
        self.assertTrue(RedactingFilter().filter(record))
        self.assertNotIn(TOKEN, record.getMessage())


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if self.path == "/ok":
            body = b'{"hello": "world"}'
            self.send_response(200)
        elif self.path == "/401":
            body = b'{"message": "Bad credentials"}'
            self.send_response(401)
        elif self.path == "/slow":
            time.sleep(1.0)
            body, _ = b"{}", self.send_response(200)
        else:
            body = b"oops"
            self.send_response(500)
        try:
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Test", "yes")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client gave up (that is what the timeout test does)


class RealTransportTests(unittest.TestCase):
    """The default urllib transport, against a throw-away local HTTP server."""

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_success_and_http_errors_are_returned_not_raised(self):
        r = urllib_transport(self.base + "/ok", {"Content-Type": "application/json"}, b"{}", 5)
        self.assertEqual((r.status, json.loads(r.body), r.headers["x-test"]), (200, {"hello": "world"}, "yes"))
        self.assertEqual(urllib_transport(self.base + "/401", {}, b"{}", 5).status, 401)
        self.assertEqual(urllib_transport(self.base + "/boom", {}, b"{}", 5).status, 500)

    def test_timeout_and_refused_connection_become_network_errors(self):
        with self.assertRaises(NetworkError):
            urllib_transport(self.base + "/slow", {}, b"{}", 0.2)
        with self.assertRaises(NetworkError):
            urllib_transport("http://127.0.0.1:9/never", {}, b"{}", 1)

    def test_a_full_client_round_trip_over_the_real_transport(self):
        client = GitHubClient(TOKEN, endpoint="https://example.invalid/graphql", transport=lambda u, h, b, t: urllib_transport(self.base + "/401", h, b, t), sleep=lambda s: None)
        with self.assertRaises(AuthenticationError):
            client.fetch_contributions("octocat", START, END)


if __name__ == "__main__":
    unittest.main()
