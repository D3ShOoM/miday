"""Official lookup through Google's Places API (New).

Finding the place id is free (Maps Grounding Lite ``resolveMapsUrls``, or a
Text Search that asks only for ``places.id``). The one billable call is Place
Details with the fields below (Enterprise SKU: 1,000 free per month), and
``GMAPS_DAILY_DETAILS_CAP`` limits how many of those are made per day.
"""
import logging
from urllib.parse import quote

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from . import http, links

log = logging.getLogger(__name__)

RESOLVE_URL = "https://mapstools.googleapis.com/v1:resolveMapsUrls"
SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{}"
DETAILS_FIELDS = ",".join([
    "id", "displayName", "formattedAddress", "location", "rating", "userRatingCount",
    "priceLevel", "primaryTypeDisplayName", "googleMapsUri", "websiteUri",
    "internationalPhoneNumber", "regularOpeningHours.weekdayDescriptions",
])
PRICE_LEVELS = {
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}
SEARCH_RADIUS_M = 300.0


class ApiError(Exception):
    pass


class DailyCapReached(ApiError):
    pass


def _headers(field_mask=None):
    headers = {"X-Goog-Api-Key": settings.GOOGLE_MAPS_API_KEY}
    if field_mask:
        headers["X-Goog-FieldMask"] = field_mask
    return headers


def _describe(resp):
    return f"HTTP {resp.status}: {resp.text[:300]}"


def find_place_id(info, pasted_url):
    """The Google place id for a parsed link, or "" if Google can't tell."""
    if info.place_id:
        return info.place_id
    urls = list(dict.fromkeys(u for u in (pasted_url, info.url) if u))
    resp = http.request("POST", RESOLVE_URL, headers=_headers(), json_body={"urls": urls})
    if resp.status == 200:
        for entity in resp.json().get("entities") or []:
            place = (entity or {}).get("place", "")
            if place.startswith("places/"):
                return place.removeprefix("places/")
    else:
        # Typically "Maps Grounding Lite" isn't enabled for the key; Text Search still works.
        log.warning("resolveMapsUrls failed, falling back to Text Search: %s", _describe(resp))

    text = info.query or info.name
    if not text:
        return ""
    body = {
        "textQuery": text,
        "pageSize": 1,
        "languageCode": settings.GMAPS_LANGUAGE,
        "regionCode": settings.GMAPS_REGION,
    }
    if info.lat is not None:
        body["locationBias"] = {"circle": {
            "center": {"latitude": info.lat, "longitude": info.lng},
            "radius": SEARCH_RADIUS_M,
        }}
    resp = http.request("POST", SEARCH_URL, headers=_headers("places.id"), json_body=body)
    if resp.status != 200:
        raise ApiError(f"Text Search failed: {_describe(resp)}")
    places = resp.json().get("places") or []
    return places[0].get("id", "") if places else ""


def _reserve_details_call():
    key = f"gmaps:details:{timezone.localdate().isoformat()}"
    cache.add(key, 0, timeout=2 * 24 * 3600)
    if cache.incr(key) > settings.GMAPS_DAILY_DETAILS_CAP:
        raise DailyCapReached


def details(place_id):
    """Restaurant fields for a place id (one billable call)."""
    _reserve_details_call()
    resp = http.request(
        "GET", DETAILS_URL.format(quote(place_id, safe="")),
        headers=_headers(DETAILS_FIELDS),
        params={"languageCode": settings.GMAPS_LANGUAGE, "regionCode": settings.GMAPS_REGION},
    )
    if resp.status != 200:
        raise ApiError(f"Place Details failed: {_describe(resp)}")
    return to_fields(resp.json())


def to_fields(place):
    location = place.get("location") or {}
    hours = (place.get("regularOpeningHours") or {}).get("weekdayDescriptions") or []
    maps_uri = place.get("googleMapsUri", "")
    return {
        "name": (place.get("displayName") or {}).get("text", ""),
        "cuisine": (place.get("primaryTypeDisplayName") or {}).get("text", ""),
        "rating": place.get("rating"),
        "review_count": place.get("userRatingCount"),
        "price_level": PRICE_LEVELS.get(place.get("priceLevel", "")),
        "address": place.get("formattedAddress", ""),
        "phone": place.get("internationalPhoneNumber", ""),
        "website": place.get("websiteUri", ""),
        "opening_hours": "\n".join(hours),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "place_id": place.get("id", ""),
        "cid": links.parse(maps_uri).cid if maps_uri else "",
        "google_maps_uri": maps_uri,
    }
