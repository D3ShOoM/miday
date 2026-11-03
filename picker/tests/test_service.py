import json
from decimal import Decimal

from django.test import override_settings

from picker.gmaps import http, places_api, service

from .base import AppTestCase, fixture
from .test_places_api import DETAILS

SHORT = "https://maps.app.goo.gl/AbC"
PLACE = (
    "https://www.google.com/maps/place/Katz's+Delicatessen/@40.72,-73.98,17z/"
    "data=!4m5!3m4!1s0x89c2598f7ff4aa09:0x313547e757cb8cea!8m2!3d40.722233!4d-73.987429"
)


class LookupTests(AppTestCase):
    def keyless_google(self):
        self.google.redirect(SHORT, PLACE)
        self.google.add("GET", "https://www.google.com/maps/place/", text="<html></html>")
        self.google.add("GET", "https://www.google.com/maps/preview/place?", text=fixture("maps_preview_place.json"))

    def test_no_link(self):
        result = service.lookup("Katz's deli")
        self.assertFalse(result.ok)
        self.assertIn("Paste a Google Maps link", result.notes[0])

    def test_not_a_google_link(self):
        result = service.lookup("https://example.com/place")
        self.assertFalse(result.ok)
        self.assertIn("isn't a Google Maps link", result.notes[0])

    def test_keyless_lookup(self):
        self.keyless_google()
        result = service.lookup(f"Katz's\n{SHORT}?g_st=ic")
        self.assertEqual(result.source, "maps_page")
        self.assertEqual(result.fields["rating"], Decimal("4.5"))
        self.assertEqual(result.fields["review_count"], 56154)
        self.assertEqual(result.fields["maps_url"], f"{SHORT}?g_st=ic")
        self.assertTrue(result.fields["opening_hours"].startswith("Monday: 8 AM–11 PM\n"))
        self.assertEqual(result.notes, [])

    def test_results_are_cached_unless_forced(self):
        self.keyless_google()
        service.lookup(SHORT)
        calls = len(self.google.calls)
        service.lookup(SHORT)
        self.assertEqual(len(self.google.calls), calls)
        service.lookup(SHORT, force=True)
        self.assertGreater(len(self.google.calls), calls)

    @override_settings(GMAPS_KEYLESS=False)
    def test_link_only(self):
        self.google.redirect(SHORT, PLACE)
        result = service.lookup(SHORT)
        self.assertEqual(result.source, "link")
        self.assertEqual(result.fields["name"], "Katz's Delicatessen")
        self.assertEqual(result.fields["cid"], "3545819340560108778")
        self.assertIn("Only the name and location", result.notes[0])

    def test_keyless_failure_still_reads_the_link(self):
        self.google.redirect(SHORT, PLACE)
        self.google.add("GET", "https://www.google.com/maps/", status=500)
        result = service.lookup(SHORT)
        self.assertEqual(result.source, "link")
        self.assertEqual(result.fields["name"], "Katz's Delicatessen")
        self.assertIn("Google Maps didn't return details for this link.", result.notes)

    def test_unreachable_short_link(self):
        self.google.fail("GET", SHORT)
        with self.assertLogs("picker.gmaps", "WARNING"):
            result = service.lookup(SHORT)
        self.assertFalse(result.ok)
        self.assertIn("Couldn't reach Google", result.notes[0])

    def test_short_link_blocked_by_the_hosts_proxy(self):
        # PythonAnywhere's free plan can't reach maps.app.goo.gl.
        self.google.fail("GET", SHORT, "Tunnel connection failed: 403 Forbidden", error=http.BlockedByProxy)
        with self.assertLogs("picker.gmaps", "WARNING"):
            result = service.lookup(SHORT)
        self.assertFalse(result.ok)
        self.assertEqual(result.notes, [service.SHORT_LINK_BLOCKED])

    def test_search_page_link_without_details_keeps_the_pasted_link(self):
        self.google.redirect("https://share.google/XyZ", "https://www.google.com/search?kgmid=/g/1&q=Katz")
        result = service.lookup("https://share.google/XyZ")
        self.assertEqual(result.fields["name"], "Katz")
        self.assertEqual(result.fields["maps_url"], "https://share.google/XyZ")


@override_settings(GOOGLE_MAPS_API_KEY="test-key")
class OfficialLookupTests(AppTestCase):
    def test_api_wins_and_keyless_is_not_used(self):
        self.google.redirect(SHORT, PLACE)
        self.google.add("POST", places_api.RESOLVE_URL, text=json.dumps({"entities": [{"place": "places/ChIJ1"}]}))
        self.google.add("GET", "https://places.googleapis.com/v1/places/", text=json.dumps(DETAILS))
        result = service.lookup(SHORT)
        self.assertEqual(result.source, "places_api")
        self.assertEqual(result.fields["price_level"], 2)
        self.assertEqual(result.fields["address"], "205 E Houston St, New York, NY 10002, USA")
        self.assertFalse(any("/maps/preview" in url for url in self.google.urls()))

    def test_api_failure_falls_back_to_keyless(self):
        self.google.redirect(SHORT, PLACE)
        self.google.add("POST", places_api.RESOLVE_URL, status=500, text="boom")
        self.google.add("POST", places_api.SEARCH_URL, status=500, text="boom")
        self.google.add("GET", "https://www.google.com/maps/place/", text="<html></html>")
        self.google.add("GET", "https://www.google.com/maps/preview/place?", text=fixture("maps_preview_place.json"))
        with self.assertLogs("picker.gmaps", "WARNING"):
            result = service.lookup(SHORT)
        self.assertEqual(result.source, "maps_page")
        self.assertIn("The Google Places API lookup failed; see the server log.", result.notes)

    def test_blocked_short_link_is_opened_by_googles_api(self):
        self.google.fail("GET", SHORT, "Tunnel connection failed: 403 Forbidden", error=http.BlockedByProxy)
        self.google.add("POST", places_api.RESOLVE_URL, text=json.dumps({"entities": [{"place": "places/ChIJ1"}]}))
        self.google.add("GET", "https://places.googleapis.com/v1/places/", text=json.dumps(DETAILS))
        result = service.lookup(SHORT)
        self.assertEqual(result.source, "places_api")
        self.assertEqual(result.fields["name"], "Katz's Delicatessen")
        resolve_call = [c for c in self.google.calls if c[1] == places_api.RESOLVE_URL][0]
        self.assertEqual(resolve_call[2]["json_body"], {"urls": [SHORT]})

    def test_share_google_uses_googles_own_maps_link(self):
        self.google.redirect("https://share.google/XyZ", "https://www.google.com/search?kgmid=/g/1&q=Katz")
        self.google.add("POST", places_api.RESOLVE_URL, text=json.dumps({"entities": [{"place": "places/ChIJ1"}]}))
        self.google.add("GET", "https://places.googleapis.com/v1/places/", text=json.dumps(DETAILS))
        result = service.lookup("https://share.google/XyZ")
        self.assertEqual(result.fields["maps_url"], "https://maps.google.com/?cid=3545819340560108778")
