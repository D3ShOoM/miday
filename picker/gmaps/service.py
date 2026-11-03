"""Turn whatever the user pasted into restaurant fields.

Order: read the link itself → official Places API (if a key is set and the
daily cap allows) → the unofficial Maps page (if enabled and the API didn't
answer). For each field the first source that has a value wins. Nothing here
raises: problems become plain-language notes for the form.
"""
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError

from ..models import Restaurant
from . import http, links, maps_page, places_api, resolve

log = logging.getLogger(__name__)

TIME_BUDGET_S = 15
CACHE_OK_S = 24 * 3600
CACHE_FAILED_S = 10 * 60
SOURCE_LABELS = {
    "places_api": "Google Places API",
    "maps_page": "Google Maps (unofficial lookup)",
    "link": "the link itself",
}
TEXT_FIELDS = ["name", "cuisine", "address", "phone", "place_id", "cid", "opening_hours"]
# Google writes times as "8\u202fAM\u2009–\u200911\u202fPM"; plain spaces are easier to edit.
ODD_SPACES_RE = re.compile(r"[\u00a0\u2009\u202f]")
URL_FIELDS = ["website", "photo_url", "maps_url"]
SHORT_LINK_BLOCKED = (
    "This server can't open short links like maps.app.goo.gl. Open the link in your browser "
    "and paste the full google.com/maps address from the address bar instead."
)


@dataclass
class LookupResult:
    fields: dict = field(default_factory=dict)
    source: str = ""  # places_api | maps_page | link | "" (nothing found)
    notes: list = field(default_factory=list)

    @property
    def ok(self):
        return bool(self.fields.get("name"))

    @property
    def source_label(self):
        return SOURCE_LABELS.get(self.source, "")


def lookup(text, force=False):
    url = links.find_url(text)
    if not url:
        return LookupResult(notes=["Paste a Google Maps link, e.g. https://maps.app.goo.gl/…"])
    cache_key = "gmaps:lookup:" + hashlib.sha1(url.encode()).hexdigest()
    if not force:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached
    result = _lookup(url)
    cache.set(cache_key, result, CACHE_OK_S if result.source in ("places_api", "maps_page") else CACHE_FAILED_S)
    return result


def _lookup(url):
    deadline = time.monotonic() + TIME_BUDGET_S
    try:
        pasted = links.normalize(url)
        resolved = resolve.resolve(pasted)
    except links.LinkError as exc:
        return LookupResult(notes=[str(exc)])
    except http.BlockedByProxy as exc:
        # PythonAnywhere's free plan only reaches allowlisted hosts, and the
        # shorteners aren't on it. Google's API can follow the link instead.
        if not (settings.GOOGLE_MAPS_API_KEY and links.is_shortener(pasted)):
            log.warning("Proxy refused %s (%s); set GOOGLE_MAPS_API_KEY to handle short links.", url, exc)
            return LookupResult(notes=[SHORT_LINK_BLOCKED])
        resolved = pasted
    except http.HttpError as exc:
        log.warning("Could not follow %s: %s", url, exc)
        return LookupResult(notes=["Couldn't reach Google to open that link. Check the connection and try again."])

    info = links.parse(resolved)
    notes = []
    sources = []
    if settings.GOOGLE_MAPS_API_KEY:
        try:
            place_id = places_api.find_place_id(info, pasted)
            if place_id:
                sources.append(("places_api", places_api.details(place_id)))
            else:
                notes.append("Google couldn't match this link to a single place.")
        except places_api.DailyCapReached:
            notes.append("Today's Google Places lookups are used up (GMAPS_DAILY_DETAILS_CAP).")
        except (places_api.ApiError, http.HttpError, ValueError) as exc:
            log.warning("Places API lookup failed for %s: %s", url, exc)
            notes.append("The Google Places API lookup failed; see the server log.")

    if not sources and settings.GMAPS_KEYLESS and time.monotonic() < deadline:
        try:
            page = maps_page.lookup(info)
            if page.get("name"):
                sources.append(("maps_page", page))
            else:
                notes.append("Google Maps didn't return details for this link.")
        except (http.HttpError, links.LinkError, ValueError) as exc:
            log.warning("Keyless Maps lookup failed for %s: %s", url, exc)
            notes.append("Couldn't read the details from Google Maps.")

    sources.append(("link", {
        "name": info.name, "place_id": info.place_id, "cid": info.cid,
        "latitude": info.lat, "longitude": info.lng,
    }))
    fields = _merge(values for _, values in sources)
    fields["maps_url"] = _maps_url(pasted, fields)
    source = sources[0][0]
    if source == "link":
        if fields.get("name"):
            notes.append("Only the name and location could be read from the link; fill in the rest.")
        else:
            source = ""
            notes.append("Couldn't find a place name in that link; fill in the details by hand.")
    return LookupResult(_clean(fields), source, notes)


def _merge(sources):
    merged = {}
    for values in sources:
        for key, value in values.items():
            if value not in (None, "", []) and merged.get(key) in (None, "", []):
                merged[key] = value
    return merged


def _maps_url(pasted, fields):
    """Keep the pasted link when it opens Maps; otherwise use Google's own link."""
    if links.is_maps_link(pasted):
        return pasted
    if fields.get("google_maps_uri"):
        return fields["google_maps_uri"]
    if fields.get("cid"):
        return f"https://maps.google.com/?cid={fields['cid']}"
    return pasted


def _max_length(name):
    return Restaurant._meta.get_field(name).max_length


def _clean(fields):
    """Fit fetched values to the model so the form never rejects them."""
    clean = {}
    for name in TEXT_FIELDS:
        value = ODD_SPACES_RE.sub(" ", str(fields.get(name) or "")).strip()
        limit = _max_length(name)
        clean[name] = value[:limit] if limit else value
    validate_url = URLValidator(schemes=["http", "https"])
    for name in URL_FIELDS:
        value = str(fields.get(name) or "").strip()
        try:
            validate_url(value)
        except ValidationError:
            value = ""
        clean[name] = value if len(value) <= _max_length(name) else ""
    rating = fields.get("rating")
    if isinstance(rating, (int, float)) and 0 <= rating <= 5:
        clean["rating"] = Decimal(str(round(float(rating), 1)))
    review_count = fields.get("review_count")
    if isinstance(review_count, int) and review_count >= 0:
        clean["review_count"] = review_count
    if fields.get("price_level") in (1, 2, 3, 4):
        clean["price_level"] = fields["price_level"]
    lat, lng = fields.get("latitude"), fields.get("longitude")
    if isinstance(lat, (int, float)) and isinstance(lng, (int, float)) and -90 <= lat <= 90 and -180 <= lng <= 180:
        clean["latitude"], clean["longitude"] = round(lat, 7), round(lng, 7)
    return {k: v for k, v in clean.items() if v not in (None, "")}
