from datetime import timedelta

from django import forms
from django.core.validators import URLValidator
from django.db.models.functions import Lower
from django.utils import timezone

from . import voting
from .gmaps import links
from .models import Poll, Restaurant

# Applied by "Fetch details" / "Refresh from Google" on an existing restaurant.
REFRESH_ALWAYS = {"rating", "review_count", "price_level", "opening_hours", "place_id", "cid", "latitude", "longitude"}
REFRESH_IF_BLANK = {"name", "cuisine", "address", "phone", "website", "photo_url"}
# Fetching a different link on the Add form drops these leftovers from the previous place.
PLACE_SPECIFIC = {"rating", "review_count", "opening_hours", "place_id", "cid", "latitude", "longitude", "photo_url"}


class RestaurantForm(forms.ModelForm):
    # Plain text, not type=url: people paste whole share messages ("ALBAIK … https://…").
    maps_url = forms.CharField(
        label="Google Maps link", required=False, max_length=2000,
        widget=forms.TextInput(attrs={
            "inputmode": "url", "autocomplete": "off", "spellcheck": "false",
            "placeholder": "https://maps.app.goo.gl/…",
        }),
    )
    website = forms.URLField(required=False, max_length=500, assume_scheme="https")
    photo_url = forms.URLField(label="Photo link", required=False, max_length=2000, assume_scheme="https")

    class Meta:
        model = Restaurant
        fields = [
            "maps_url", "name", "cuisine", "rating", "review_count", "price_level",
            "address", "phone", "website", "photo_url", "opening_hours", "notes",
            "place_id", "cid", "latitude", "longitude", "info_source", "info_fetched_at",
        ]
        widgets = {
            "rating": forms.NumberInput(attrs={"step": "0.1", "min": "0", "max": "5"}),
            "review_count": forms.NumberInput(attrs={"min": "0"}),
            "opening_hours": forms.Textarea(attrs={"rows": 4}),
            "notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Dishes to try, parking, delivery…"}),
            "place_id": forms.HiddenInput,
            "cid": forms.HiddenInput,
            "latitude": forms.HiddenInput,
            "longitude": forms.HiddenInput,
            "info_source": forms.HiddenInput,
            "info_fetched_at": forms.HiddenInput,
        }
        labels = {"price_level": "Price", "review_count": "Number of reviews", "rating": "Rating (0–5)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["price_level"].choices = [("", "—"), *Restaurant.PRICE_CHOICES]
        self.duplicate = None
        for name, field in self.fields.items():
            widget = field.widget
            if widget.is_hidden:
                continue
            widget.attrs["class"] = "form-select" if isinstance(widget, forms.Select) else "form-control"
            if name in ("name", "cuisine", "address", "opening_hours", "notes"):
                widget.attrs["dir"] = "auto"

    def clean_maps_url(self):
        value = self.cleaned_data["maps_url"].strip()
        if not value:
            return ""
        url = links.find_url(value) or value
        URLValidator(schemes=["http", "https"])(url)
        return url

    def clean(self):
        cleaned = super().clean()
        candidate = Restaurant(
            pk=self.instance.pk,
            place_id=cleaned.get("place_id") or "",
            cid=cleaned.get("cid") or "",
        )
        duplicate = candidate.find_active_duplicate()
        if duplicate is None and (candidate.place_id or candidate.cid):
            removed = Restaurant.objects.removed().exclude(pk=self.instance.pk)
            duplicate = (
                removed.filter(place_id=candidate.place_id).first() if candidate.place_id else None
            ) or (removed.filter(cid=candidate.cid).first() if candidate.cid else None)
        if duplicate is not None:
            self.duplicate = duplicate
            if duplicate.is_removed:
                raise forms.ValidationError("This place was removed from the list earlier. Restore it instead of adding it again.")
            raise forms.ValidationError("This place is already in the list.")
        return cleaned


def apply_lookup(data, fields, refresh):
    """Copy looked-up ``fields`` into the form ``data``; return the names that changed.

    Adding: everything found is filled in. Refreshing an existing restaurant:
    Google's numbers are updated, the team's own edits (name, notes, the link)
    are kept, and other details are only filled where they are blank.
    """
    changed = set()
    if not refresh:
        for name in PLACE_SPECIFIC - fields.keys():
            if str(data.get(name, "") or "").strip():
                data[name] = ""
                changed.add(name)
    for name, value in fields.items():
        if name not in RestaurantForm.base_fields or value in (None, ""):
            continue
        current = str(data.get(name, "") or "").strip()
        if refresh:
            if name not in REFRESH_ALWAYS and not (name in REFRESH_IF_BLANK and not current):
                continue
        value = str(value)
        if value != current:
            data[name] = value
            changed.add(name)
    return changed


DEADLINE_CHOICES = [
    ("", "No deadline"),
    ("15", "15 minutes"),
    ("30", "30 minutes"),
    ("60", "1 hour"),
    ("120", "2 hours"),
    ("240", "4 hours"),
]


class PollForm(forms.Form):
    title = forms.CharField(max_length=Poll._meta.get_field("title").max_length)
    restaurants = forms.ModelMultipleChoiceField(
        queryset=Restaurant.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        error_messages={"required": "Pick at least two restaurants."},
    )
    deadline = forms.ChoiceField(choices=DEADLINE_CHOICES, required=False, label="Voting closes after")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["restaurants"].queryset = Restaurant.objects.active().order_by(Lower("name"))
        self.fields["restaurants"].widget.attrs["class"] = "form-check-input mt-0"

    def clean_restaurants(self):
        chosen = self.cleaned_data["restaurants"]
        if len(chosen) < 2:
            raise forms.ValidationError("Pick at least two restaurants.")
        if len(chosen) > voting.MAX_OPTIONS:
            raise forms.ValidationError(f"Pick at most {voting.MAX_OPTIONS} restaurants.")
        return chosen

    def closes_at(self):
        minutes = self.cleaned_data.get("deadline")
        return timezone.now() + timedelta(minutes=int(minutes)) if minutes else None


def default_poll_title():
    now = timezone.localtime()
    return f"Where should we eat? · {now:%a} {now.day} {now:%b}"
