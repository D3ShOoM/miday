"""Reading Google Maps links. Pure functions — no network."""
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote_plus, urlsplit, urlunsplit

URL_RE = re.compile(r"https?://[^\s<>\"]+", re.I)
FEATURE_ID_RE = re.compile(r"[!/]1s(0x[0-9a-f]+:0x[0-9a-f]+)", re.I)
FEATURE_ID_VALUE_RE = re.compile(r"^0x[0-9a-f]+:0x[0-9a-f]+$", re.I)
PIN_RE = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
CENTER_RE = re.compile(r"/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
LATLNG_RE = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")
PLACE_NAME_RE = re.compile(r"/maps/place/([^/@?]+)")
SEARCH_PATH_RE = re.compile(r"/maps/search/([^/@?]+)")
# A leading Open Location Code ("RV25+6HJ ") that Android share links put before the name.
PLUS_CODE_RE = re.compile(r"^[23456789CFGHJMPQRVWX]{4,8}[+ ][23456789CFGHJMPQRVWX]{2,3}\s+", re.I)
NAME_SEPARATORS_RE = re.compile(r"[,،]")
GOOGLE_HOST_RE = re.compile(r"^(?:www\.|maps\.)?google\.(?:com|[a-z]{2}|com?\.[a-z]{2})$")
CONSENT_HOST_RE = re.compile(r"^consent\.google\.(?:com|[a-z]{2}|com?\.[a-z]{2})$")
SHORTENER_HOSTS = {"maps.app.goo.gl", "goo.gl", "share.google", "g.co"}

NOT_GOOGLE_MESSAGE = "That isn't a Google Maps link. Paste a link like https://maps.app.goo.gl/… or https://www.google.com/maps/place/…"


class LinkError(Exception):
    """The text can't be used as a Google Maps link; the message is for the user."""


def find_url(text):
    """The first web link in ``text`` (people paste whole share messages)."""
    match = URL_RE.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?)]}>'\"")


def is_google_host(host):
    return bool(GOOGLE_HOST_RE.match(host or ""))


def is_shortener(url):
    parts = urlsplit(url)
    host = parts.hostname or ""
    if host == "goo.gl":
        return parts.path.startswith("/maps")
    if host in SHORTENER_HOSTS:
        return True
    # share.google answers with a hop through www.google.com/share.google?q=…
    return is_google_host(host) and parts.path.rstrip("/") == "/share.google"


def normalize(url, _depth=0):
    """Return ``url`` as https on an allowed Google host, or raise LinkError.

    This is the SSRF guard: nothing else is ever fetched.
    """
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        raise LinkError(NOT_GOOGLE_MESSAGE) from None
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        raise LinkError(NOT_GOOGLE_MESSAGE)
    if port not in (None, 80, 443):
        raise LinkError(NOT_GOOGLE_MESSAGE)
    if CONSENT_HOST_RE.match(host) and _depth == 0:
        target = parse_qs(parts.query).get("continue", [""])[0]
        if target:
            return normalize(target, _depth=1)
    if host == "goo.gl" and not parts.path.startswith("/maps"):
        raise LinkError(NOT_GOOGLE_MESSAGE)
    if host not in SHORTENER_HOSTS and not is_google_host(host):
        raise LinkError(NOT_GOOGLE_MESSAGE)
    return urlunsplit(("https", host, parts.path, parts.query, ""))


def is_maps_link(url):
    """True for links that open Google Maps itself (not a search page)."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if host in ("maps.app.goo.gl", "goo.gl"):
        return True
    if not is_google_host(host):
        return False
    return host.startswith("maps.") or parts.path.startswith("/maps")


@dataclass
class LinkInfo:
    url: str
    name: str = ""
    query: str = ""  # best text to search for, often "Name, address"
    feature_id: str = ""  # "0x…:0x…"
    cid: str = ""  # decimal customer id
    place_id: str = ""
    lat: float | None = None
    lng: float | None = None


def _clean_name(text, cut_at_comma):
    text = PLUS_CODE_RE.sub("", " ".join(text.split()))
    if cut_at_comma:
        text = NAME_SEPARATORS_RE.split(text, 1)[0]
    return text.strip()


def _float_pair(lat, lng):
    lat, lng = float(lat), float(lng)
    if -90 <= lat <= 90 and -180 <= lng <= 180:
        return lat, lng
    return None, None


def parse(url):
    """Everything that can be read from a (resolved) Google Maps URL."""
    parts = urlsplit(url)
    params = parse_qs(parts.query)
    info = LinkInfo(url=url)

    match = FEATURE_ID_RE.search(parts.path)
    ftid = params.get("ftid", [""])[0]
    if match:
        info.feature_id = match.group(1).lower()
    elif FEATURE_ID_VALUE_RE.match(ftid):
        info.feature_id = ftid.lower()
    if info.feature_id:
        info.cid = str(int(info.feature_id.split(":")[1], 16))
    cid = params.get("cid", [""])[0]
    if cid.isdigit():
        info.cid = cid

    texts = params.get("q", []) + params.get("query", [])
    for text in texts:
        if text.startswith("place_id:"):
            info.place_id = text.removeprefix("place_id:").strip()
    if params.get("query_place_id"):
        info.place_id = params["query_place_id"][0].strip()

    match = PIN_RE.search(parts.path)
    if match:
        info.lat, info.lng = _float_pair(*match.groups())
    else:
        match = CENTER_RE.search(parts.path)
        if match:
            info.lat, info.lng = _float_pair(*match.groups())

    match = PLACE_NAME_RE.search(parts.path) or SEARCH_PATH_RE.search(parts.path)
    if match:
        raw = unquote_plus(match.group(1))
        coords = LATLNG_RE.match(raw)
        if coords:  # a dropped pin, not a place
            if info.lat is None:
                info.lat, info.lng = _float_pair(*coords.groups())
        else:
            info.query = " ".join(raw.split())
            # Desktop links carry just the name; app links append the address.
            info.name = _clean_name(raw, cut_at_comma="/@" not in parts.path)
    for text in texts:
        if text.startswith("place_id:"):
            continue
        coords = LATLNG_RE.match(text)
        if coords:
            if info.lat is None:
                info.lat, info.lng = _float_pair(*coords.groups())
            continue
        if not info.query:
            info.query = " ".join(PLUS_CODE_RE.sub("", text).split())
            info.name = _clean_name(text, cut_at_comma=True)
    return info
