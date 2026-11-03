from pathlib import Path
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings

from picker.gmaps import http

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeGoogle:
    """Stands in for ``http.request``: answers from routes, fails on anything else."""

    def __init__(self):
        self.routes = []
        self.calls = []

    def add(self, method, url_prefix, status=200, text="", headers=None):
        self.routes.append((method, url_prefix, http.Resp(status, url_prefix, headers or {}, text)))

    def redirect(self, url_prefix, location, status=302):
        self.add("GET", url_prefix, status=status, headers={"location": location})

    def fail(self, method, url_prefix, message="connection failed", error=http.HttpError):
        self.routes.append((method, url_prefix, error(message)))

    def __call__(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        for route_method, prefix, resp in self.routes:
            if route_method == method and url.startswith(prefix):
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"unexpected network call: {method} {url}")

    def urls(self, method=None):
        return [url for m, url, _ in self.calls if method in (None, m)]


@override_settings(GOOGLE_MAPS_API_KEY="", GMAPS_KEYLESS=True, PUBLIC_BASE_URL="", GMAPS_DAILY_DETAILS_CAP=50)
class AppTestCase(TestCase):
    """No test may reach the network: every request goes to ``self.google``."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.google = FakeGoogle()
        patcher = mock.patch.object(http, "request", self.google)
        patcher.start()
        self.addCleanup(patcher.stop)
