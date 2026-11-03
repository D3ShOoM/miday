from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from picker import voting
from picker.gmaps.service import LookupResult
from picker.models import Poll, PollOption, Restaurant, Vote, Voter

from .base import AppTestCase

ALICE = "a" * 32
BOB = "b" * 32


class PollTestCase(AppTestCase):
    def setUp(self):
        super().setUp()
        self.albaik = Restaurant.objects.create(name="Albaik", rating=Decimal("4.3"))
        self.shawarmer = Restaurant.objects.create(name="Shawarmer", rating=Decimal("4.6"))
        self.kudu = Restaurant.objects.create(name="Kudu")

    def make_poll(self, **kwargs):
        poll = Poll.objects.create(title="Lunch", **kwargs)
        for i, r in enumerate([self.albaik, self.shawarmer, self.kudu]):
            PollOption.objects.create(poll=poll, restaurant=r, position=i)
        return poll

    def option(self, poll, restaurant):
        return poll.options.get(restaurant=restaurant)

    def as_voter(self, voter_id):
        self.client.cookies["voter"] = voter_id


class CreateTests(PollTestCase):
    def test_create_gives_a_link_and_admin_rights(self):
        response = self.client.post(reverse("poll_new"), {
            "title": "Thursday lunch", "restaurants": [self.kudu.pk, self.albaik.pk], "deadline": "30",
        })
        poll = Poll.objects.get()
        self.assertRedirects(response, poll.get_absolute_url() + "?new=1", fetch_redirect_response=False)
        self.assertEqual(response.cookies[f"pa_{poll.slug}"].value, poll.admin_key)
        self.assertEqual(response.cookies[f"pa_{poll.slug}"]["path"], poll.get_absolute_url())
        self.assertEqual([o.restaurant.name for o in poll.options.all()], ["Albaik", "Kudu"])
        self.assertAlmostEqual((poll.closes_at - timezone.now()).total_seconds(), 1800, delta=5)
        page = self.client.get(response["Location"])
        self.assertTrue(page.context["is_admin"])
        self.assertContains(page, "Your vote is ready")
        self.assertContains(page, 'role="img" aria-label="thumbs up"')  # "No votes yet — tap 👍 or 👎"

    def test_needs_two_restaurants(self):
        response = self.client.post(reverse("poll_new"), {"title": "Lunch", "restaurants": [self.kudu.pk]})
        self.assertContains(response, "Pick at least two restaurants.")
        self.assertFalse(Poll.objects.exists())

    def test_at_most_the_option_limit(self):
        extra = [Restaurant.objects.create(name=f"Place {i}") for i in range(voting.MAX_OPTIONS)]
        response = self.client.post(reverse("poll_new"), {"title": "Lunch", "restaurants": [r.pk for r in extra] + [self.kudu.pk]})
        self.assertContains(response, f"Pick at most {voting.MAX_OPTIONS} restaurants.")
        self.assertFalse(Poll.objects.exists())

    def test_removed_restaurants_cannot_be_chosen(self):
        self.kudu.removed_at = timezone.now()
        self.kudu.save()
        response = self.client.post(reverse("poll_new"), {"title": "Lunch", "restaurants": [self.kudu.pk, self.albaik.pk]})
        self.assertTrue(response.context["form"].errors["restaurants"])

    @override_settings(PUBLIC_BASE_URL="http://10.0.0.5:8000")
    def test_share_link_uses_the_public_address(self):
        poll = self.make_poll()
        page = self.client.get(poll.get_absolute_url())  # test client host is "testserver"
        self.assertEqual(page.context["share_url"], f"http://10.0.0.5:8000/v/{poll.slug}/")
        self.assertEqual(page.context["host_mismatch"], "http://10.0.0.5:8000")

    @override_settings(PUBLIC_BASE_URL="https://TestServer")
    def test_host_names_compare_without_case(self):
        poll = self.make_poll()
        self.assertEqual(self.client.get(poll.get_absolute_url()).context["host_mismatch"], "")


class VotingRuleTests(PollTestCase):
    def test_votes_are_idempotent_and_switchable(self):
        poll = self.make_poll()
        option = self.option(poll, self.albaik)
        voting.cast_vote(option, ALICE, 1)
        voting.cast_vote(option, ALICE, 1)  # double click
        self.assertEqual(Vote.objects.get().value, 1)
        voting.cast_vote(option, ALICE, -1)
        self.assertEqual(Vote.objects.get().value, -1)
        voting.cast_vote(option, ALICE, 0)
        self.assertFalse(Vote.objects.exists())
        poll.refresh_from_db()
        self.assertEqual(poll.version, 3)  # the repeated click didn't count

    def test_clearing_a_vote_keeps_the_comment(self):
        poll = self.make_poll()
        option = self.option(poll, self.albaik)
        voting.cast_vote(option, ALICE, 1)
        voting.set_comment(option, ALICE, "  Great fries  ")
        voting.cast_vote(option, ALICE, 0)
        vote = Vote.objects.get()
        self.assertEqual((vote.value, vote.comment), (0, "Great fries"))
        voting.set_comment(option, ALICE, "")
        self.assertFalse(Vote.objects.exists())

    def test_comment_only(self):
        poll = self.make_poll()
        voting.set_comment(self.option(poll, self.kudu), BOB, "Allergic to sesame")
        tallies, voters = voting.tally(poll, BOB)
        kudu = tallies[2]
        self.assertEqual((kudu.ups, kudu.downs, voters), (0, 0, 1))
        self.assertEqual(kudu.my_comment, "Allergic to sesame")

    def test_closed_poll_refuses_writes(self):
        poll = self.make_poll(closed_at=timezone.now())
        with self.assertRaises(voting.VotingClosed):
            voting.cast_vote(self.option(poll, self.albaik), ALICE, 1)
        expired = self.make_poll(closes_at=timezone.now() - timedelta(seconds=1))
        self.assertTrue(expired.is_closed)
        with self.assertRaises(voting.VotingClosed):
            voting.set_comment(self.option(expired, self.albaik), ALICE, "late")

    def test_reopen_drops_a_passed_deadline(self):
        poll = self.make_poll(closes_at=timezone.now() - timedelta(minutes=1))
        voting.reopen(poll)
        poll.refresh_from_db()
        self.assertIsNone(poll.closes_at)
        self.assertFalse(poll.is_closed)

    def test_ranking_and_outcome(self):
        poll = self.make_poll()
        tallies, _ = voting.tally(poll, ALICE)
        self.assertEqual(voting.outcome(voting.rank(tallies)).kind, "none")
        voting.cast_vote(self.option(poll, self.albaik), ALICE, 1)
        voting.cast_vote(self.option(poll, self.kudu), BOB, 1)
        ranked = voting.rank(voting.tally(poll, ALICE)[0])
        outcome = voting.outcome(ranked)
        self.assertEqual(outcome.kind, "tie")
        # Tied on votes; the better Google rating is listed first.
        self.assertEqual([t.restaurant.name for t in outcome.leaders], ["Albaik", "Kudu"])
        voting.cast_vote(self.option(poll, self.kudu), ALICE, 1)
        outcome = voting.outcome(voting.rank(voting.tally(poll, ALICE)[0]))
        self.assertEqual((outcome.kind, outcome.leaders[0].restaurant.name), ("leader", "Kudu"))

    def test_rename_updates_every_poll(self):
        first, second = self.make_poll(), self.make_poll()
        voting.set_comment(self.option(first, self.albaik), ALICE, "yes")
        voting.cast_vote(self.option(second, self.kudu), ALICE, 1)
        versions = (Poll.objects.get(pk=first.pk).version, Poll.objects.get(pk=second.pk).version)
        voting.rename(ALICE, "  محمد   علي ")
        self.assertEqual(Voter.objects.get(pk=ALICE).name, "محمد علي")
        self.assertEqual(Poll.objects.get(pk=first.pk).version, versions[0] + 1)
        self.assertEqual(Poll.objects.get(pk=second.pk).version, versions[1] + 1)


class PageTests(PollTestCase):
    def test_vote_redirects_back_and_shows_my_choice(self):
        poll = self.make_poll()
        self.as_voter(ALICE)
        option = self.option(poll, self.shawarmer)
        url = reverse("poll_option", args=[poll.slug, option.pk])
        response = self.client.post(url, {"value": "1"})
        self.assertRedirects(response, poll.get_absolute_url() + f"#opt-{option.pk}", fetch_redirect_response=False)
        page = self.client.get(poll.get_absolute_url())
        self.assertContains(page, f'id="opt-{option.pk}-up" value="0"')  # pressing again clears
        self.assertContains(page, "Leading: <span dir=\"auto\">Shawarmer</span>")

    def test_bad_values_are_rejected(self):
        poll = self.make_poll()
        url = reverse("poll_option", args=[poll.slug, self.option(poll, self.albaik).pk])
        self.assertEqual(self.client.post(url, {"value": "5"}).status_code, 400)
        self.assertEqual(self.client.post(url, {"value": "up"}).status_code, 400)
        self.assertEqual(self.client.post(url, {}).status_code, 400)
        other = self.make_poll()
        wrong = reverse("poll_option", args=[poll.slug, self.option(other, self.albaik).pk])
        self.assertEqual(self.client.post(wrong, {"value": "1"}).status_code, 404)

    def test_vote_on_closed_poll_flashes(self):
        poll = self.make_poll(closed_at=timezone.now())
        url = reverse("poll_option", args=[poll.slug, self.option(poll, self.albaik).pk])
        response = self.client.post(url, {"value": "1"}, follow=True)
        self.assertContains(response, "Voting has closed")
        self.assertFalse(Vote.objects.exists())

    def test_comment_and_name_with_arabic(self):
        poll = self.make_poll()
        self.as_voter(BOB)
        option = self.option(poll, self.kudu)
        self.client.post(reverse("poll_option", args=[poll.slug, option.pk]), {"comment": "البرجر ممتاز"})
        self.client.post(reverse("poll_name", args=[poll.slug]), {"name": "سارة"})
        page = self.client.get(poll.get_absolute_url())
        self.assertContains(page, "البرجر ممتاز")
        self.assertContains(page, '<span class="c-who" dir="auto">سارة</span> <span class="text-body-secondary">(you)</span>')

    def test_live_check_returns_204_until_something_changes(self):
        poll = self.make_poll()
        url = poll.get_absolute_url()
        state = poll.state
        response = self.client.get(url, {"s": state})
        self.assertEqual(response.status_code, 204)
        self.assertIn("voter", response.cookies)  # a first visit gets its cookie even on a 204
        voting.cast_vote(self.option(poll, self.albaik), ALICE, 1)
        self.assertEqual(self.client.get(url, {"s": state}).status_code, 200)

    def test_deadline_passing_changes_the_state(self):
        poll = self.make_poll(closes_at=timezone.now() + timedelta(minutes=5))
        state = poll.state
        Poll.objects.filter(pk=poll.pk).update(closes_at=timezone.now() - timedelta(seconds=1))
        response = self.client.get(poll.get_absolute_url(), {"s": state})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["closed"])

    def test_admin_actions_need_the_key(self):
        poll = self.make_poll()
        state_url = reverse("poll_state", args=[poll.slug])
        self.assertEqual(self.client.post(state_url, {"action": "close"}).status_code, 403)
        self.client.cookies[f"pa_{poll.slug}"] = "wrong"
        self.assertEqual(self.client.post(state_url, {"action": "close"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("poll_manage", args=[poll.slug, "wrong"])).status_code, 404)
        self.assertEqual(self.client.get(reverse("poll_manage", args=[poll.slug, "é"])).status_code, 404)
        self.client.cookies[f"pa_{poll.slug}"] = "é"
        self.assertFalse(self.client.get(poll.get_absolute_url()).context["is_admin"])

        response = self.client.get(reverse("poll_manage", args=[poll.slug, poll.admin_key]))
        self.assertEqual(response.cookies[f"pa_{poll.slug}"].value, poll.admin_key)
        self.client.post(state_url, {"action": "close"})
        poll.refresh_from_db()
        self.assertTrue(poll.is_closed)
        page = self.client.get(poll.get_absolute_url())
        self.assertContains(page, "Reopen voting")
        self.client.post(state_url, {"action": "reopen"})
        poll.refresh_from_db()
        self.assertFalse(poll.is_closed)

    def test_winner_banner_when_closed(self):
        poll = self.make_poll()
        voting.cast_vote(self.option(poll, self.kudu), ALICE, 1)
        voting.close(poll)
        page = self.client.get(poll.get_absolute_url())
        self.assertContains(page, '<span dir="auto">Kudu</span> wins!')
        self.assertContains(page, '<i class="px-ico px-lg px-crown" aria-hidden="true"></i>')

    def test_removed_restaurant_still_shows_in_old_polls(self):
        poll = self.make_poll()
        self.kudu.removed_at = timezone.now()
        self.kudu.save()
        self.assertContains(self.client.get(poll.get_absolute_url()), "removed from list")

    def test_unknown_poll(self):
        self.assertEqual(self.client.get("/v/nope/").status_code, 404)


class SuggestTests(PollTestCase):
    """Voters adding restaurants to a running vote."""

    def setUp(self):
        super().setUp()
        self.poll = Poll.objects.create(title="Lunch")
        for i, r in enumerate([self.albaik, self.shawarmer]):
            PollOption.objects.create(poll=self.poll, restaurant=r, position=i)
        self.url = reverse("poll_add", args=[self.poll.slug])
        self.as_voter(BOB)
        Voter.objects.create(pk=BOB, name="Sara")

    def lookup_returns(self, fields, source="maps_page", notes=()):
        return mock.patch("picker.gmaps.service.lookup", return_value=LookupResult(dict(fields), source, list(notes)))

    def test_add_from_the_list(self):
        version = self.poll.version
        response = self.client.post(self.url, {"restaurant": self.kudu.pk})
        option = self.poll.options.get(restaurant=self.kudu)
        self.assertRedirects(response, self.poll.get_absolute_url() + f"#opt-{option.pk}", fetch_redirect_response=False)
        self.assertEqual((option.position, option.added_by_id), (2, BOB))
        self.poll.refresh_from_db()
        self.assertEqual(self.poll.version, version + 1)  # open pages pick it up
        page = self.client.get(self.poll.get_absolute_url())
        self.assertContains(page, "Added “Kudu” to the vote.")
        self.assertContains(page, "Added by you")
        self.as_voter(ALICE)
        self.assertContains(self.client.get(self.poll.get_absolute_url()), 'Added by <span dir="auto">Sara</span>')
        self.assertNotIn(self.kudu, page.context["addable"])

    def test_addable_lists_only_restaurants_not_in_the_vote(self):
        page = self.client.get(self.poll.get_absolute_url())
        self.assertEqual(page.context["addable"], [self.kudu])

    def test_already_in_the_vote(self):
        response = self.client.post(self.url, {"restaurant": self.albaik.pk}, follow=True)
        # Shown once, next to the form the person used, not in the banner at the top.
        html = response.content.decode()
        message = "“Albaik” is already in this vote."
        self.assertEqual(html.count(message), 1)
        self.assertGreater(html.index(message), html.index('id="suggest-feedback"'))
        self.assertEqual(self.poll.options.count(), 2)

    def test_removed_restaurant(self):
        self.kudu.removed_at = timezone.now()
        self.kudu.save()
        response = self.client.post(self.url, {"restaurant": self.kudu.pk}, follow=True)
        self.assertContains(response, "isn&#x27;t in the list any more")
        self.assertEqual(self.poll.options.count(), 2)

    def test_closed_vote(self):
        voting.close(self.poll)
        response = self.client.post(self.url, {"restaurant": self.kudu.pk}, follow=True)
        self.assertContains(response, "no more restaurants can be added")
        self.assertEqual(self.poll.options.count(), 2)
        self.assertContains(response, '<details id="suggest" class="card suggest-panel mt-3" hidden>')

    def test_nothing_chosen(self):
        response = self.client.post(self.url, {"restaurant": "", "maps_url": "  "}, follow=True)
        self.assertContains(response, "Choose a restaurant from the list or paste a Google Maps link.")

    def test_new_place_from_a_link_joins_the_list_and_the_vote(self):
        fields = {"name": "Kabab Ali", "place_id": "ChIJnew", "cid": "99", "rating": Decimal("4.4"),
                  "review_count": 120, "maps_url": "https://maps.app.goo.gl/New"}
        with self.lookup_returns(fields):
            response = self.client.post(self.url, {"maps_url": "https://maps.app.goo.gl/New"}, follow=True)
        restaurant = Restaurant.objects.get(place_id="ChIJnew")
        self.assertEqual((restaurant.name, restaurant.review_count, restaurant.info_source), ("Kabab Ali", 120, "maps_page"))
        self.assertTrue(self.poll.options.filter(restaurant=restaurant, added_by_id=BOB).exists())
        self.assertContains(response, "Added “Kabab Ali” to the vote. It&#x27;s new in the restaurant list too.")

    def test_link_to_a_place_already_in_the_list_reuses_it(self):
        self.kudu.place_id = "ChIJkudu"
        self.kudu.save()
        with self.lookup_returns({"name": "KUDU (Dhahran)", "place_id": "ChIJkudu"}):
            self.client.post(self.url, {"maps_url": "https://maps.app.goo.gl/Kudu"})
        self.assertEqual(Restaurant.objects.filter(place_id="ChIJkudu").count(), 1)
        self.assertTrue(self.poll.options.filter(restaurant=self.kudu).exists())

    def test_link_to_a_removed_place_restores_it(self):
        self.kudu.cid = "77"
        self.kudu.removed_at = timezone.now()
        self.kudu.save()
        with self.lookup_returns({"name": "Kudu", "cid": "77"}):
            response = self.client.post(self.url, {"maps_url": "https://maps.app.goo.gl/Kudu"}, follow=True)
        self.kudu.refresh_from_db()
        self.assertFalse(self.kudu.is_removed)
        self.assertContains(response, "It&#x27;s back in the restaurant list too.")

    def test_unreadable_link(self):
        failed = LookupResult({}, "", ["That isn't a Google Maps link."])
        with mock.patch("picker.gmaps.service.lookup", return_value=failed):
            response = self.client.post(self.url, {"maps_url": "https://example.com/x"}, follow=True)
        self.assertContains(response, "That isn&#x27;t a Google Maps link.")
        self.assertEqual(Restaurant.objects.count(), 3)

    def test_link_with_only_a_name(self):
        with self.lookup_returns({"name": "Mystery Grill", "latitude": 26.3, "longitude": 50.1}, source="link"):
            response = self.client.post(self.url, {"maps_url": "https://www.google.com/maps/place/Mystery+Grill"}, follow=True)
        self.assertContains(response, "Only its name could be read")
        self.assertTrue(Restaurant.objects.filter(name="Mystery Grill").exists())

    def test_option_limit(self):
        for i in range(voting.MAX_OPTIONS - 2):
            PollOption.objects.create(poll=self.poll, restaurant=Restaurant.objects.create(name=f"R{i}"), position=10 + i)
        response = self.client.post(self.url, {"restaurant": self.kudu.pk}, follow=True)
        self.assertContains(response, f"at most {voting.MAX_OPTIONS} restaurants")
        self.assertTrue(response.context["options_full"])

    def test_live_check_sees_the_new_option(self):
        state = self.poll.state
        voting.add_option(self.poll, self.kudu, ALICE)
        response = self.client.get(self.poll.get_absolute_url(), {"s": state})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'id="opt-col-{self.poll.options.get(restaurant=self.kudu).pk}"')
