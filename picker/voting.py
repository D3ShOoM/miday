"""Voting rules.

Every write runs in one transaction (IMMEDIATE on SQLite, so writers queue
instead of failing), re-reads the poll, refuses if voting has closed, and
bumps ``Poll.version`` so open pages know to refresh.
"""
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.db.models import F, Max
from django.utils import timezone

from .models import Poll, PollOption, Vote, Voter

NAME_MAX = Voter._meta.get_field("name").max_length
COMMENT_MAX = Vote._meta.get_field("comment").max_length
MAX_OPTIONS = 30


class VotingClosed(Exception):
    pass


class AlreadyInPoll(Exception):
    pass


class TooManyOptions(Exception):
    pass


def _open_poll(poll_id):
    poll = Poll.objects.get(pk=poll_id)
    if poll.is_closed:
        raise VotingClosed
    return poll


def _bump(*poll_ids):
    Poll.objects.filter(pk__in=poll_ids).update(version=F("version") + 1)


def cast_vote(option, voter_id, value):
    """Set this voter's vote on ``option`` to ``value`` (1, -1, or 0 to clear).

    Idempotent: posting the value you already have changes nothing. Clearing a
    vote keeps its comment; a row with neither is deleted.
    """
    if value not in (Vote.UP, Vote.DOWN, Vote.NONE):
        raise ValueError(f"invalid vote value: {value!r}")
    with transaction.atomic():
        _open_poll(option.poll_id)
        vote = Vote.objects.filter(option=option, voter_id=voter_id).first()
        if vote is None:
            if value == Vote.NONE:
                return
            Voter.objects.get_or_create(pk=voter_id)
            Vote.objects.create(option=option, voter_id=voter_id, value=value)
        elif vote.value == value:
            return
        elif value == Vote.NONE and not vote.comment:
            vote.delete()
        else:
            vote.value = value
            vote.save(update_fields=["value", "updated_at"])
        _bump(option.poll_id)


def set_comment(option, voter_id, comment):
    """Set (or clear, with an empty string) this voter's comment on ``option``."""
    comment = comment.strip()[:COMMENT_MAX]
    with transaction.atomic():
        _open_poll(option.poll_id)
        vote = Vote.objects.filter(option=option, voter_id=voter_id).first()
        if vote is None:
            if not comment:
                return
            Voter.objects.get_or_create(pk=voter_id)
            Vote.objects.create(option=option, voter_id=voter_id, comment=comment)
        elif vote.comment == comment:
            return
        elif not comment and vote.value == Vote.NONE:
            vote.delete()
        else:
            vote.comment = comment
            vote.save(update_fields=["comment", "updated_at"])
        _bump(option.poll_id)


def rename(voter_id, name):
    """Set the display name shown next to this voter's comments, in every poll."""
    name = " ".join(name.split())[:NAME_MAX]
    with transaction.atomic():
        voter, created = Voter.objects.get_or_create(pk=voter_id, defaults={"name": name})
        if not created:
            if voter.name == name:
                return
            Voter.objects.filter(pk=voter_id).update(name=name)
        poll_ids = set(
            Vote.objects.filter(voter_id=voter_id).values_list("option__poll_id", flat=True)
        )
        if poll_ids:
            _bump(*poll_ids)


def add_option(poll, restaurant, voter_id):
    """Add ``restaurant`` to an open poll, suggested by this voter."""
    with transaction.atomic():
        current = _open_poll(poll.pk)
        options = PollOption.objects.filter(poll=current)
        if options.filter(restaurant=restaurant).exists():
            raise AlreadyInPoll
        if options.count() >= MAX_OPTIONS:
            raise TooManyOptions
        last = options.aggregate(last=Max("position"))["last"]
        Voter.objects.get_or_create(pk=voter_id)
        try:
            with transaction.atomic():
                option = PollOption.objects.create(
                    poll=current, restaurant=restaurant, added_by_id=voter_id,
                    position=0 if last is None else last + 1,
                )
        except IntegrityError:  # someone else added it a moment ago
            raise AlreadyInPoll from None
        _bump(current.pk)
        return option


def close(poll):
    with transaction.atomic():
        Poll.objects.filter(pk=poll.pk, closed_at__isnull=True).update(
            closed_at=timezone.now(), version=F("version") + 1,
        )


def reopen(poll):
    """Open voting again; a deadline that has already passed is dropped."""
    with transaction.atomic():
        current = Poll.objects.get(pk=poll.pk)
        changes = {"closed_at": None}
        if current.closes_at and current.closes_at <= timezone.now():
            changes["closes_at"] = None
        Poll.objects.filter(pk=poll.pk).update(version=F("version") + 1, **changes)


@dataclass
class OptionTally:
    option: PollOption
    ups: int = 0
    downs: int = 0
    my_value: int = Vote.NONE
    my_comment: str = ""
    comments: list = field(default_factory=list)

    @property
    def restaurant(self):
        return self.option.restaurant

    @property
    def score(self):
        return self.ups - self.downs

    @property
    def total(self):
        return self.ups + self.downs


@dataclass
class Outcome:
    kind: str  # "none", "leader" or "tie"
    leaders: list


def tally(poll, voter_id):
    """Per-option counts, comments and this voter's own choices, in poll order."""
    options = list(poll.options.select_related("restaurant", "added_by"))
    by_option = {o.pk: OptionTally(o) for o in options}
    votes = Vote.objects.filter(option__poll=poll).select_related("voter")
    voters = set()
    for vote in votes:
        t = by_option[vote.option_id]
        voters.add(vote.voter_id)
        if vote.value == Vote.UP:
            t.ups += 1
        elif vote.value == Vote.DOWN:
            t.downs += 1
        if vote.comment:
            t.comments.append(vote)
        if vote.voter_id == voter_id:
            t.my_value = vote.value
            t.my_comment = vote.comment
    return [by_option[o.pk] for o in options], len(voters)


def _rank_key(t):
    rating = t.restaurant.rating
    return (-t.score, -t.ups, -(rating if rating is not None else -1), t.restaurant.name.lower())


def rank(tallies):
    """Best first: score, then more 👍, then Google rating, then name."""
    return sorted(tallies, key=_rank_key)


def outcome(ranked):
    if not any(t.total for t in ranked):
        return Outcome("none", [])
    top = ranked[0]
    tied = [t for t in ranked if t.score == top.score and t.ups == top.ups]
    return Outcome("tie" if len(tied) > 1 else "leader", tied)
