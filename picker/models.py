import secrets

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone


class RestaurantQuerySet(models.QuerySet):
    def active(self):
        return self.filter(removed_at__isnull=True)

    def removed(self):
        return self.filter(removed_at__isnull=False)


class Restaurant(models.Model):
    PRICE_CHOICES = [(1, "$"), (2, "$$"), (3, "$$$"), (4, "$$$$")]

    name = models.CharField(max_length=200)
    maps_url = models.URLField("Google Maps link", max_length=2000, blank=True)
    place_id = models.CharField("Google place ID", max_length=300, blank=True)
    cid = models.CharField("Google CID", max_length=30, blank=True)
    cuisine = models.CharField(max_length=100, blank=True)
    rating = models.DecimalField(
        max_digits=2, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(5)],
    )
    review_count = models.PositiveIntegerField("number of reviews", null=True, blank=True)
    price_level = models.PositiveSmallIntegerField(choices=PRICE_CHOICES, null=True, blank=True)
    address = models.CharField(max_length=300, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    website = models.URLField(max_length=500, blank=True)
    photo_url = models.URLField("photo link", max_length=2000, blank=True)
    opening_hours = models.TextField(blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True)
    info_source = models.CharField(max_length=20, blank=True)
    info_fetched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    removed_at = models.DateTimeField(null=True, blank=True)

    objects = RestaurantQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["place_id"],
                condition=Q(removed_at__isnull=True) & ~Q(place_id=""),
                name="unique_active_place_id",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def is_removed(self):
        return self.removed_at is not None

    @property
    def price_coins(self):
        """One item per coin the page draws for the price level."""
        return range(self.price_level or 0)

    @property
    def initial(self):
        return (self.name.strip()[:1] or "?").upper()

    @property
    def tile_class(self):
        return f"tile-{(self.pk or 0) % 5 + 1}"

    def find_active_duplicate(self):
        """Another restaurant in the list for the same Google place, if any."""
        match = Q()
        if self.place_id:
            match |= Q(place_id=self.place_id)
        if self.cid:
            match |= Q(cid=self.cid)
        if not match:
            return None
        return Restaurant.objects.active().filter(match).exclude(pk=self.pk).first()


class Voter(models.Model):
    """An anonymous browser, identified by the long-lived ``voter`` cookie."""

    id = models.CharField(primary_key=True, max_length=32, editable=False)
    name = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name or f"Anonymous {self.id[:6]}"


def new_slug():
    return secrets.token_urlsafe(6)


def new_admin_key():
    return secrets.token_urlsafe(16)


class Poll(models.Model):
    """A voting session over a few restaurants, shared by its link."""

    slug = models.SlugField(max_length=16, unique=True, default=new_slug, editable=False)
    admin_key = models.CharField(max_length=32, default=new_admin_key, editable=False)
    title = models.CharField(max_length=120)
    closes_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    # Bumped by every write so open pages can tell cheaply whether to refresh.
    version = models.PositiveIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    restaurants = models.ManyToManyField(Restaurant, through="PollOption", related_name="polls")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("poll", args=[self.slug])

    @property
    def is_closed(self):
        return self.closed_at is not None or (
            self.closes_at is not None and timezone.now() >= self.closes_at
        )

    @property
    def state(self):
        return f"{self.version}-{int(self.is_closed)}"


class PollOption(models.Model):
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="options")
    restaurant = models.ForeignKey(Restaurant, on_delete=models.PROTECT, related_name="poll_options")
    position = models.PositiveSmallIntegerField(default=0)
    # Set when a voter suggested this option after the vote started.
    added_by = models.ForeignKey(Voter, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["position", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["poll", "restaurant"], name="unique_poll_restaurant"),
        ]

    def __str__(self):
        return f"{self.poll} — {self.restaurant}"


class Vote(models.Model):
    """One voter's stance on one option: 👍, 👎, or just a comment."""

    UP, DOWN, NONE = 1, -1, 0
    VALUE_CHOICES = [(UP, "👍"), (DOWN, "👎"), (NONE, "no vote")]

    option = models.ForeignKey(PollOption, on_delete=models.CASCADE, related_name="votes")
    voter = models.ForeignKey(Voter, on_delete=models.CASCADE, related_name="votes")
    value = models.SmallIntegerField(choices=VALUE_CHOICES, default=NONE)
    comment = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["option", "voter"], name="unique_vote_per_option"),
            models.CheckConstraint(condition=Q(value__in=[-1, 0, 1]), name="vote_value_valid"),
        ]

    def __str__(self):
        return f"{self.voter} {self.get_value_display()} {self.option.restaurant}"
