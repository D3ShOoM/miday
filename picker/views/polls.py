import secrets
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models.functions import Lower
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .. import catalog, voting
from ..forms import PollForm, default_poll_title
from ..gmaps import service
from ..models import Poll, PollOption, Restaurant, Vote, Voter

ADMIN_COOKIE_AGE = 180 * 24 * 3600
SUGGEST = "suggest"  # message tag: shown in the "add a restaurant" panel, not the top banner


def _admin_cookie(poll):
    return f"pa_{poll.slug}"


def is_admin(request, poll):
    return secrets.compare_digest(request.COOKIES.get(_admin_cookie(poll), "").encode(), poll.admin_key.encode())


def _grant_admin(response, poll):
    response.set_cookie(
        _admin_cookie(poll), poll.admin_key, max_age=ADMIN_COOKIE_AGE,
        path=poll.get_absolute_url(), httponly=True, samesite="Lax",
    )
    return response


def public_url(request, path):
    """An absolute link colleagues can open (not the creator's ``localhost``)."""
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL + path
    return request.build_absolute_uri(path)


def create(request):
    if request.method == "POST":
        form = PollForm(request.POST)
        if form.is_valid():
            poll = _create_poll(form)
            return _grant_admin(redirect(poll.get_absolute_url() + "?new=1"), poll)
    else:
        form = PollForm(initial={"title": default_poll_title()})
    return render(request, "picker/polls/new.html", {
        "form": form,
        "restaurant_count": Restaurant.objects.active().count(),
    })


def _create_poll(form):
    for _ in range(5):  # a slug collision is astronomically rare, but cheap to retry
        try:
            with transaction.atomic():
                poll = Poll.objects.create(title=form.cleaned_data["title"], closes_at=form.closes_at())
                PollOption.objects.bulk_create(
                    PollOption(poll=poll, restaurant=restaurant, position=i)
                    for i, restaurant in enumerate(form.cleaned_data["restaurants"])
                )
                return poll
        except IntegrityError:
            continue
    raise IntegrityError("could not allocate a poll slug")


@never_cache
def detail(request, slug):
    poll = get_object_or_404(Poll, slug=slug)
    if request.GET.get("s") == poll.state:
        return HttpResponse(status=204)  # nothing changed since the page last looked
    tallies, voter_count = voting.tally(poll, request.voter_id)
    ranked = voting.rank(tallies)
    in_poll = {t.restaurant.pk for t in tallies}
    admin = is_admin(request, poll)
    share_url = public_url(request, poll.get_absolute_url())
    host_mismatch = ""
    if settings.PUBLIC_BASE_URL and urlsplit(settings.PUBLIC_BASE_URL).netloc.lower() != request.get_host().lower():
        host_mismatch = settings.PUBLIC_BASE_URL
    return render(request, "picker/polls/detail.html", {
        "poll": poll,
        "closed": poll.is_closed,
        "tallies": tallies,
        "ranked": ranked,
        "outcome": voting.outcome(ranked),
        "max_votes": max([t.total for t in tallies] + [1]),
        "voter_count": voter_count,
        "voter": Voter.objects.filter(pk=request.voter_id).first(),
        "is_admin": admin,
        "share_url": share_url,
        "whatsapp_text": f"{poll.title} — vote here: {share_url}",
        "manage_url": public_url(request, reverse("poll_manage", args=[poll.slug, poll.admin_key])) if admin else "",
        "host_mismatch": host_mismatch,
        "is_new": admin and "new" in request.GET,
        "addable": [r for r in Restaurant.objects.active().order_by(Lower("name")) if r.pk not in in_poll],
        "options_full": len(tallies) >= voting.MAX_OPTIONS,
        "live_refresh_ms": settings.LIVE_REFRESH_SECONDS * 1000,
    })


def _back_to(poll, anchor=""):
    return redirect(poll.get_absolute_url() + anchor)


@require_POST
def option(request, slug, option_id):
    poll = get_object_or_404(Poll, slug=slug)
    poll_option = get_object_or_404(PollOption, pk=option_id, poll=poll)
    try:
        if "value" in request.POST:
            try:
                value = int(request.POST["value"])
            except ValueError:
                return HttpResponseBadRequest("Invalid vote.")
            if value not in (Vote.UP, Vote.DOWN, Vote.NONE):
                return HttpResponseBadRequest("Invalid vote.")
            voting.cast_vote(poll_option, request.voter_id, value)
        elif "comment" in request.POST:
            voting.set_comment(poll_option, request.voter_id, request.POST["comment"])
        else:
            return HttpResponseBadRequest("Nothing to save.")
    except voting.VotingClosed:
        messages.warning(request, "Voting has closed, so that wasn't saved.")
    return _back_to(poll, f"#opt-{poll_option.pk}")


@require_POST
def add_option(request, slug):
    """A voter adds a restaurant to the vote: one from the list, or a new Maps link."""
    poll = get_object_or_404(Poll, slug=slug)
    if poll.is_closed:
        messages.warning(request, "Voting has closed, so no more restaurants can be added.")
        return _back_to(poll)
    status, notes = "existing", []
    if request.POST.get("restaurant", "").isdigit():
        restaurant = Restaurant.objects.active().filter(pk=request.POST["restaurant"]).first()
        if restaurant is None:
            messages.error(request, "That restaurant isn't in the list any more.", extra_tags=SUGGEST)
            return _back_to(poll, "#suggest")
    elif request.POST.get("maps_url", "").strip():
        result = service.lookup(request.POST["maps_url"])
        if not result.ok:
            messages.error(request, " ".join(result.notes) or "Nothing could be read from that link.", extra_tags=SUGGEST)
            return _back_to(poll, "#suggest")
        restaurant, status = catalog.add_from_lookup(result)
        if result.source == "link":
            notes.append("Only its name could be read; anyone can fill in the details on the Restaurants page.")
    else:
        messages.error(request, "Choose a restaurant from the list or paste a Google Maps link.", extra_tags=SUGGEST)
        return _back_to(poll, "#suggest")

    try:
        option = voting.add_option(poll, restaurant, request.voter_id)
    except voting.VotingClosed:
        messages.warning(request, "Voting has closed, so no more restaurants can be added.")
        return _back_to(poll)
    except voting.AlreadyInPoll:
        messages.info(request, f"“{restaurant.name}” is already in this vote.", extra_tags=SUGGEST)
        return _back_to(poll, "#suggest")
    except voting.TooManyOptions:
        messages.error(request, f"A vote can have at most {voting.MAX_OPTIONS} restaurants.", extra_tags=SUGGEST)
        return _back_to(poll, "#suggest")
    added = {
        "created": " It's new in the restaurant list too.",
        "restored": " It's back in the restaurant list too.",
    }.get(status, "")
    messages.success(request, " ".join([f"Added “{restaurant.name}” to the vote.{added}", *notes]), extra_tags=SUGGEST)
    return _back_to(poll, f"#opt-{option.pk}")


@require_POST
def set_name(request, slug):
    poll = get_object_or_404(Poll, slug=slug)
    voting.rename(request.voter_id, request.POST.get("name", ""))
    return _back_to(poll)


def manage(request, slug, key):
    poll = get_object_or_404(Poll, slug=slug)
    if not secrets.compare_digest(key.encode(), poll.admin_key.encode()):
        raise Http404
    return _grant_admin(redirect(poll.get_absolute_url()), poll)


@require_POST
def set_state(request, slug):
    poll = get_object_or_404(Poll, slug=slug)
    if not is_admin(request, poll):
        return HttpResponse("Only the person who started this vote can do that.", status=403)
    action = request.POST.get("action")
    if action == "close":
        voting.close(poll)
    elif action == "reopen":
        voting.reopen(poll)
    else:
        return HttpResponseBadRequest("Unknown action.")
    return _back_to(poll)
