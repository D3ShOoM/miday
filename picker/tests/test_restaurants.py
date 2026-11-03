from decimal import Decimal
from unittest import mock

from django.urls import reverse

from picker.gmaps.service import LookupResult
from picker.models import Restaurant

from .base import AppTestCase

KATZ = {
    "name": "Katz's Delicatessen", "cuisine": "Deli", "rating": Decimal("4.5"), "review_count": 56154,
    "address": "205 E Houston St, New York", "phone": "+1 212-254-2246",
    "website": "https://katzsdelicatessen.com/", "opening_hours": "Monday: 8 AM–11 PM",
    "latitude": 40.722233, "longitude": -73.987429, "place_id": "ChIJkatz", "cid": "3545819340560108778",
    "photo_url": "https://lh3.googleusercontent.com/p/katz", "maps_url": "https://maps.app.goo.gl/Katz",
}


def found(fields=KATZ, source="maps_page", notes=()):
    return mock.patch("picker.gmaps.service.lookup", return_value=LookupResult(dict(fields), source, list(notes)))


class IndexTests(AppTestCase):
    def test_lists_active_restaurants_and_sorts(self):
        Restaurant.objects.create(name="Zaatar", rating=Decimal("4.9"))
        Restaurant.objects.create(name="Albaik", rating=Decimal("4.3"))
        Restaurant.objects.create(name="Gone", removed_at="2026-10-01T10:00Z")
        response = self.client.get(reverse("home"))
        names = [r.name for r in response.context["restaurants"]]
        self.assertEqual(names, ["Albaik", "Zaatar"])
        self.assertContains(response, "Recently removed (1)")
        response = self.client.get(reverse("home"), {"sort": "rating"})
        self.assertEqual([r.name for r in response.context["restaurants"]], ["Zaatar", "Albaik"])

    def test_sets_the_voter_cookie(self):
        response = self.client.get(reverse("home"))
        self.assertRegex(response.cookies["voter"].value, r"^[0-9a-f]{32}$")
        self.assertTrue(response.cookies["voter"]["httponly"])

    def test_price_level_is_drawn_as_coins(self):
        Restaurant.objects.create(name="Kudu", price_level=2)
        response = self.client.get(reverse("home"))
        self.assertContains(response, 'role="img" aria-label="Price level 2 of 4"')
        self.assertContains(response, '<i class="px-coin"></i>', count=2)


class AddTests(AppTestCase):
    def test_fetch_fills_the_form_without_saving(self):
        with found() as lookup:
            response = self.client.post(reverse("restaurant_add"), {"action": "fetch", "maps_url": "ALBAIK https://maps.app.goo.gl/Katz"})
        lookup.assert_called_once_with("ALBAIK https://maps.app.goo.gl/Katz", force=False)
        form = response.context["form"]
        self.assertFalse(form.is_bound)
        self.assertEqual(form.initial["name"], "Katz's Delicatessen")
        self.assertEqual(form.initial["maps_url"], "https://maps.app.goo.gl/Katz")
        self.assertEqual(form.initial["info_source"], "maps_page")
        self.assertEqual(response.context["changed"], set())  # nothing to highlight on a new one
        self.assertContains(response, "Filled in from Google Maps (unofficial lookup)")
        self.assertEqual(Restaurant.objects.count(), 0)

    def test_fetching_another_link_drops_the_previous_places_numbers(self):
        partial = {"name": "New place", "maps_url": "https://maps.app.goo.gl/New", "cid": "42"}
        with found(partial):
            response = self.client.post(reverse("restaurant_add"), {
                "action": "fetch", "maps_url": "https://maps.app.goo.gl/New",
                "name": "Old place", "rating": "4.5", "review_count": "100", "price_level": "2", "cid": "7",
            })
        initial = response.context["form"].initial
        self.assertEqual((initial["name"], initial["cid"]), ("New place", "42"))
        self.assertEqual((initial["rating"], initial["review_count"]), ("", ""))
        self.assertEqual(initial["price_level"], "2")  # chosen by hand, Google never sends it

    def test_failed_fetch_keeps_what_was_typed(self):
        failed = LookupResult({}, "", ["That isn't a Google Maps link."])
        with mock.patch("picker.gmaps.service.lookup", return_value=failed):
            response = self.client.post(reverse("restaurant_add"), {"action": "fetch", "maps_url": "nope", "name": "Mine"})
        self.assertEqual(response.context["form"].initial["name"], "Mine")
        self.assertContains(response, "That isn&#x27;t a Google Maps link.")

    def test_save(self):
        data = {k: str(v) for k, v in KATZ.items()} | {"action": "save", "notes": "Get the pastrami"}
        response = self.client.post(reverse("restaurant_add"), data)
        restaurant = Restaurant.objects.get()
        self.assertRedirects(response, reverse("home") + f"#r{restaurant.pk}")
        self.assertEqual(restaurant.rating, Decimal("4.5"))
        self.assertEqual(restaurant.review_count, 56154)
        self.assertEqual(restaurant.notes, "Get the pastrami")

    def test_save_extracts_the_link_from_share_text(self):
        self.client.post(reverse("restaurant_add"), {"action": "save", "name": "X", "maps_url": "X\nhttps://maps.app.goo.gl/AbC"})
        self.assertEqual(Restaurant.objects.get().maps_url, "https://maps.app.goo.gl/AbC")

    def test_name_is_required(self):
        response = self.client.post(reverse("restaurant_add"), {"action": "save", "name": ""})
        self.assertTrue(response.context["form"].errors["name"])
        self.assertEqual(Restaurant.objects.count(), 0)

    def test_duplicate_place_is_refused(self):
        existing = Restaurant.objects.create(name="Katz's", cid="3545819340560108778")
        response = self.client.post(reverse("restaurant_add"), {"action": "save", "name": "Katz again", "cid": "3545819340560108778"})
        self.assertEqual(response.context["form"].duplicate, existing)
        self.assertContains(response, "already in the list")
        self.assertEqual(Restaurant.objects.count(), 1)

    def test_removed_duplicate_offers_restore(self):
        Restaurant.objects.create(name="Katz's", place_id="ChIJkatz", removed_at="2026-10-01T10:00Z")
        response = self.client.post(reverse("restaurant_add"), {"action": "save", "name": "Katz", "place_id": "ChIJkatz"})
        self.assertContains(response, "Restore it instead")
        self.assertContains(response, 'id="restore-duplicate"')


class EditTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.restaurant = Restaurant.objects.create(
            name="Katz (the deli)", notes="Cash only", maps_url="https://maps.app.goo.gl/Mine",
            rating=Decimal("4.1"), review_count=10, cuisine="Sandwiches",
        )

    def post(self, **data):
        url = reverse("restaurant_edit", args=[self.restaurant.pk])
        fields = {
            "name": self.restaurant.name, "notes": self.restaurant.notes, "maps_url": self.restaurant.maps_url,
            "rating": "4.1", "review_count": "10", "cuisine": "Sandwiches",
        }
        return self.client.post(url, fields | data)

    def test_refresh_updates_numbers_but_keeps_the_teams_edits(self):
        with found() as lookup:
            response = self.post(action="fetch")
        lookup.assert_called_once_with("https://maps.app.goo.gl/Mine", force=True)
        initial = response.context["form"].initial
        self.assertEqual(initial["rating"], "4.5")
        self.assertEqual(initial["review_count"], "56154")
        self.assertEqual(initial["address"], "205 E Houston St, New York")  # was blank
        self.assertEqual(initial["name"], "Katz (the deli)")
        self.assertEqual(initial["notes"], "Cash only")
        self.assertEqual(initial["maps_url"], "https://maps.app.goo.gl/Mine")
        self.assertEqual(initial["cuisine"], "Sandwiches")  # not blank, so kept
        self.assertEqual(response.context["changed"], {"rating", "review_count", "address", "phone", "website", "photo_url", "opening_hours"})
        self.assertContains(response, "7 fields were updated (highlighted)")
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.rating, Decimal("4.1"))  # nothing saved yet

    def test_save_edit(self):
        response = self.post(action="save", name="Katz's")
        self.assertRedirects(response, reverse("home") + f"#r{self.restaurant.pk}")
        self.restaurant.refresh_from_db()
        self.assertEqual(self.restaurant.name, "Katz's")

    def test_removed_restaurant_cannot_be_edited(self):
        self.restaurant.removed_at = "2026-10-01T10:00Z"
        self.restaurant.save()
        self.assertEqual(self.client.get(reverse("restaurant_edit", args=[self.restaurant.pk])).status_code, 404)


class RemoveRestoreTests(AppTestCase):
    def test_remove_then_undo(self):
        restaurant = Restaurant.objects.create(name="Albaik")
        response = self.client.post(reverse("restaurant_remove", args=[restaurant.pk]))
        self.assertRedirects(response, reverse("home") + f"?undo={restaurant.pk}")
        restaurant.refresh_from_db()
        self.assertTrue(restaurant.is_removed)
        page = self.client.get(response["Location"])
        self.assertContains(page, "Removed “<span dir=\"auto\">Albaik</span>”")
        self.client.post(reverse("restaurant_restore", args=[restaurant.pk]))
        restaurant.refresh_from_db()
        self.assertFalse(restaurant.is_removed)

    def test_remove_needs_post(self):
        restaurant = Restaurant.objects.create(name="Albaik")
        self.assertEqual(self.client.get(reverse("restaurant_remove", args=[restaurant.pk])).status_code, 405)

    def test_restore_refuses_when_the_place_is_back_already(self):
        old = Restaurant.objects.create(name="Albaik", place_id="ChIJ1", removed_at="2026-10-01T10:00Z")
        Restaurant.objects.create(name="Albaik (new)", place_id="ChIJ1")
        response = self.client.post(reverse("restaurant_restore", args=[old.pk]), follow=True)
        self.assertContains(response, "already in the list")
        old.refresh_from_db()
        self.assertTrue(old.is_removed)
