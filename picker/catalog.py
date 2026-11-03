"""Putting a looked-up Google Maps place into the shared restaurant list."""
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Restaurant

LOOKUP_FIELDS = [
    "name", "maps_url", "place_id", "cid", "cuisine", "rating", "review_count", "price_level",
    "address", "phone", "website", "photo_url", "opening_hours", "latitude", "longitude",
]


def add_from_lookup(result):
    """The list entry for a successful ``service.lookup()`` result.

    Returns ``(restaurant, status)`` where status is "existing" (already in the
    list), "restored" (it had been removed) or "created".
    """
    fields = {k: v for k, v in result.fields.items() if k in LOOKUP_FIELDS}
    candidate = Restaurant(place_id=fields.get("place_id", ""), cid=fields.get("cid", ""))
    existing = candidate.find_active_duplicate()
    if existing:
        return existing, "existing"
    removed = _removed_duplicate(candidate)
    if removed:
        removed.removed_at = None
        removed.save(update_fields=["removed_at", "updated_at"])
        return removed, "restored"

    restaurant = Restaurant(**fields, info_source=result.source, info_fetched_at=timezone.now())
    try:
        restaurant.full_clean(validate_unique=False, validate_constraints=False)
    except ValidationError as exc:  # fetched values are pre-cleaned; drop whatever still doesn't fit
        for name in exc.error_dict:
            if name in LOOKUP_FIELDS and name != "name":
                setattr(restaurant, name, Restaurant._meta.get_field(name).get_default())
    try:
        with transaction.atomic():
            restaurant.save()
    except IntegrityError:  # the same place was added a moment ago
        return candidate.find_active_duplicate(), "existing"
    return restaurant, "created"


def _removed_duplicate(candidate):
    removed = Restaurant.objects.removed().order_by("-removed_at")
    if candidate.place_id:
        match = removed.filter(place_id=candidate.place_id).first()
        if match:
            return match
    if candidate.cid:
        return removed.filter(cid=candidate.cid).first()
    return None
