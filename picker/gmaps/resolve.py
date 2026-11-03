"""Following short links (maps.app.goo.gl, share.google…) to the real Maps URL."""
from urllib.parse import urljoin

from . import http, links

MAX_HOPS = 5
REDIRECT_CODES = {301, 302, 303, 307, 308}


def resolve(url):
    """Follow shortener redirects until a Google Maps/Search URL; never fetch that page.

    Every hop is re-checked against the Google host allowlist. Raises
    ``links.LinkError`` (message for the user) or ``http.HttpError``.
    """
    url = links.normalize(url)
    for _ in range(MAX_HOPS):
        if not links.is_shortener(url):
            return url
        # GET, not HEAD: share.google only redirects GET requests.
        resp = http.request("GET", url)
        location = resp.headers.get("location")
        if resp.status not in REDIRECT_CODES or not location:
            raise links.LinkError("That short link doesn't lead to a Google Maps place. Is it complete?")
        url = links.normalize(urljoin(url, location))
    if links.is_shortener(url):
        raise links.LinkError("That link redirects too many times.")
    return url
