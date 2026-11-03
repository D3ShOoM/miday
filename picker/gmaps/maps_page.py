"""Keyless lookup through the public Google Maps website — UNOFFICIAL.

Google doesn't document any of this, and its terms don't allow it. It reads the
same JSON the Maps website loads for a place: the place page names it in a
``<link href="/maps/preview/place?…">`` preload. The positions below were
checked against live responses on 2026-10-20; Google can move them at any
time, so every read goes through ``dig()`` and a missing value stays blank.
Turn it off with ``GMAPS_KEYLESS=0``.
"""
import html
import json
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from django.conf import settings

from . import http, links

PRELOAD_RE = re.compile(r'<link[^>]+href="(/maps/preview/place\?[^"]+)"')
XSSI_PREFIX = ")]}'"
MAX_PAGE_HOPS = 3
DAY_ORDER = {"Monday": 1, "Tuesday": 2, "Wednesday": 3, "Thursday": 4, "Friday": 5, "Saturday": 6, "Sunday": 7}

# Positions inside the place record (``d[6]`` of the preview JSON).
NAME = (11,)
RATING = (4, 7)
REVIEW_COUNT = (4, 8)
ADDRESS = (39,)
CATEGORIES = (13,)
PHONE = (178, 0, 0)
WEBSITE = (7, 0)
LATITUDE = (9, 2)
LONGITUDE = (9, 3)
FEATURE_ID = (10,)
PLACE_ID = (78,)
CID = (37, 0, 0, 29, 1)
PHOTO = (72, 0, 1, 6, 0)
HOURS = (203, 0)


def dig(data, *path):
    for key in path:
        try:
            data = data[key]
        except (IndexError, KeyError, TypeError):
            return None
    return data


def _with_params(url, **params):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _get_page(url):
    """GET a Google page, following redirects only within the allowed hosts."""
    for _ in range(MAX_PAGE_HOPS):
        resp = http.request("GET", url)
        location = resp.headers.get("location")
        if resp.status in (301, 302, 303, 307, 308) and location:
            url = links.normalize(urljoin(url, location))
            if not links.is_google_host(urlsplit(url).hostname):
                return None
            continue
        return resp
    return None


def _preview_json(path):
    url = _with_params(
        urljoin("https://www.google.com", path),
        hl=settings.GMAPS_LANGUAGE, gl=settings.GMAPS_REGION.lower(),
    )
    resp = http.request("GET", url)
    if resp.status != 200:
        return None
    text = resp.text
    if text.startswith(XSSI_PREFIX):
        text = text.split("\n", 1)[1] if "\n" in text else ""
    try:
        return json.loads(text)
    except ValueError:
        return None


def _place_record(payload):
    place = dig(payload, 6)
    return place if isinstance(place, list) and isinstance(dig(place, *NAME), str) else None


def lookup(info):
    """Restaurant fields for a parsed link, or {} when Google returns nothing."""
    place = None
    if links.is_maps_link(info.url):
        resp = _get_page(_with_params(info.url, hl=settings.GMAPS_LANGUAGE))
        match = PRELOAD_RE.search(resp.text) if resp is not None and resp.status == 200 else None
        if match:
            place = _place_record(_preview_json(html.unescape(match.group(1))))
    if place is None:
        # The page only preloads the full record when its link is well formed;
        # ask for the place directly by its feature id.
        feature_id = info.feature_id or (f"0x0:{int(info.cid):#x}" if info.cid else "")
        if feature_id:
            path = "/maps/preview/place?" + urlencode({"authuser": 0, "pb": f"!1m1!1s{feature_id}"})
            place = _place_record(_preview_json(path))
    return to_fields(place) if place else {}


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _hours(days):
    if not isinstance(days, list):
        return ""
    lines = []
    for day in days:
        name, ranges = dig(day, 0), dig(day, 3)
        if not isinstance(name, str) or not isinstance(ranges, list):
            continue
        text = ", ".join(r[0] for r in ranges if isinstance(dig(r, 0), str))
        lines.append((DAY_ORDER.get(name, 8), f"{name}: {text or 'Closed'}"))
    return "\n".join(line for _, line in sorted(lines))


def _unsigned_cid(value):
    """Google writes large CIDs as signed 64-bit numbers; links use unsigned."""
    value = _text(value)
    if value.lstrip("-").isdigit() and value.startswith("-"):
        return str(int(value) + 2**64)
    return value if value.isdigit() else ""


def to_fields(place):
    categories = dig(place, *CATEGORIES)
    photo = _text(dig(place, *PHOTO))
    if photo.startswith("//"):
        photo = "https:" + photo
    review_count = _number(dig(place, *REVIEW_COUNT))
    return {
        "name": _text(dig(place, *NAME)),
        "cuisine": _text(categories[0]) if isinstance(categories, list) and categories else "",
        "rating": _number(dig(place, *RATING)),
        "review_count": int(review_count) if review_count is not None else None,
        "address": _text(dig(place, *ADDRESS)),
        "phone": _text(dig(place, *PHONE)),
        "website": _text(dig(place, *WEBSITE)),
        "opening_hours": _hours(dig(place, *HOURS)),
        "latitude": _number(dig(place, *LATITUDE)),
        "longitude": _number(dig(place, *LONGITUDE)),
        "place_id": _text(dig(place, *PLACE_ID)),
        "cid": _unsigned_cid(dig(place, *CID)),
        "feature_id": _text(dig(place, *FEATURE_ID)),
        "photo_url": photo if photo.startswith("https://") else "",
    }
