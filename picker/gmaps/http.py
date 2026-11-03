"""The only place this app talks to the network. Tests replace ``request``."""
import json
import re
from dataclasses import dataclass

import requests

TIMEOUT = (3, 6)  # connect, read
MAX_BYTES = 3 * 1024 * 1024
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
_CHARSET = re.compile(r"charset=([\w-]+)", re.I)


class HttpError(Exception):
    """The request could not be completed (DNS, timeout, oversized body…)."""


class BlockedByProxy(HttpError):
    """An outbound proxy refused the host, e.g. one missing from PythonAnywhere's free allowlist."""


@dataclass
class Resp:
    status: int
    url: str
    headers: dict  # lower-cased names
    text: str

    def json(self):
        return json.loads(self.text)


def request(method, url, *, headers=None, params=None, json_body=None, timeout=TIMEOUT):
    """Make one HTTP request. Redirects are never followed; callers decide."""
    all_headers = {"User-Agent": USER_AGENT, "Accept-Language": "en"}
    all_headers.update(headers or {})
    try:
        with requests.request(
            method, url, headers=all_headers, params=params, json=json_body,
            timeout=timeout, allow_redirects=False, stream=True,
        ) as r:
            body = bytearray()
            for chunk in r.iter_content(64 * 1024):
                body += chunk
                if len(body) > MAX_BYTES:
                    raise HttpError(f"response from {r.url.split('?')[0]} is too large")
            match = _CHARSET.search(r.headers.get("Content-Type", ""))
            encoding = match.group(1) if match else "utf-8"
            try:
                text = body.decode(encoding, errors="replace")
            except LookupError:
                text = body.decode("utf-8", errors="replace")
            return Resp(r.status_code, r.url, {k.lower(): v for k, v in r.headers.items()}, text)
    except requests.exceptions.ProxyError as exc:
        raise BlockedByProxy(str(exc)) from exc
    except requests.RequestException as exc:
        raise HttpError(str(exc)) from exc
