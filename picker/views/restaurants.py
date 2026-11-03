from django.contrib import messages
from django.db.models import F
from django.db.models.functions import Lower
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .. import voting
from ..forms import RestaurantForm, apply_lookup
from ..gmaps import service
from ..models import Poll, Restaurant

SORTS = {
    "name": ("Name", [Lower("name")]),
    "rating": ("Rating", [F("rating").desc(nulls_last=True), Lower("name")]),
    "reviews": ("Most reviewed", [F("review_count").desc(nulls_last=True), Lower("name")]),
    "newest": ("Newest", ["-created_at"]),
}
RECENT_POLLS = 6


def index(request):
    sort = request.GET.get("sort", "name")
    if sort not in SORTS:
        sort = "name"
    restaurants = Restaurant.objects.active().order_by(*SORTS[sort][1])
    undo = None
    if request.GET.get("undo", "").isdigit():
        undo = Restaurant.objects.removed().filter(pk=request.GET["undo"]).first()
    recent_polls = []
    for poll in Poll.objects.all()[:RECENT_POLLS]:
        tallies, voters = voting.tally(poll, request.voter_id)
        recent_polls.append((poll, voting.outcome(voting.rank(tallies)), voters))
    return render(request, "picker/restaurants/index.html", {
        "restaurants": restaurants,
        "removed": Restaurant.objects.removed().order_by("-removed_at")[:20],
        "sort": sort,
        "sorts": {key: label for key, (label, _) in SORTS.items()},
        "undo": undo,
        "recent_polls": recent_polls,
    })


def edit(request, pk=None):
    instance = get_object_or_404(Restaurant.objects.active(), pk=pk) if pk else None
    lookup = None
    changed = set()
    if request.method == "POST" and request.POST.get("action") == "fetch":
        data = request.POST.copy()
        lookup = service.lookup(data.get("maps_url", ""), force=instance is not None)
        if lookup.ok:
            changed = apply_lookup(data, lookup.fields, refresh=instance is not None)
            data["info_source"] = lookup.source
            data["info_fetched_at"] = timezone.now().isoformat()
        # Unbound, so a half-filled form doesn't shout "required" before Save.
        form = RestaurantForm(initial=data.dict(), instance=instance)
        # Highlight what a refresh changed; on a new restaurant everything is new.
        changed = {n for n in changed if not form.fields[n].widget.is_hidden} if instance else set()
    elif request.method == "POST":
        form = RestaurantForm(request.POST, instance=instance)
        if form.is_valid():
            restaurant = form.save()
            messages.success(request, f"Saved “{restaurant.name}”.")
            return redirect(reverse("home") + f"#r{restaurant.pk}")
    else:
        form = RestaurantForm(instance=instance)
    return render(request, "picker/restaurants/form.html", {
        "form": form,
        "restaurant": instance,
        "lookup": lookup,
        "changed": changed,
    })


@require_POST
def remove(request, pk):
    restaurant = get_object_or_404(Restaurant.objects.active(), pk=pk)
    restaurant.removed_at = timezone.now()
    restaurant.save(update_fields=["removed_at", "updated_at"])
    return redirect(reverse("home") + f"?undo={restaurant.pk}")


@require_POST
def restore(request, pk):
    restaurant = get_object_or_404(Restaurant.objects.removed(), pk=pk)
    duplicate = restaurant.find_active_duplicate()
    if duplicate:
        messages.error(request, f"“{duplicate.name}” is already in the list, so the removed copy stays removed.")
        return redirect(reverse("home") + f"#r{duplicate.pk}")
    restaurant.removed_at = None
    restaurant.save(update_fields=["removed_at", "updated_at"])
    messages.success(request, f"“{restaurant.name}” is back in the list.")
    return redirect(reverse("home") + f"#r{restaurant.pk}")
