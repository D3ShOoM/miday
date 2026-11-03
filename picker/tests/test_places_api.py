import json

from django.test import override_settings

from picker.gmaps import links, places_api

from .base import AppTestCase

DETAILS = {
    "id": "ChIJCar0f49ZwokR6ozLV-dHNTE",
    "displayName": {"text": "Katz's Delicatessen", "languageCode": "en"},
    "formattedAddress": "205 E Houston St, New York, NY 10002, USA",
    "location": {"latitude": 40.7222, "longitude": -73.9874},
    "rating": 4.5,
    "userRatingCount": 56154,
    "priceLevel": "PRICE_LEVEL_MODERATE",
    "primaryTypeDisplayName": {"text": "Deli", "languageCode": "en"},
    "googleMapsUri": "https://maps.google.com/?cid=3545819340560108778",
    "websiteUri": "https://katzsdelicatessen.com/",
    "internationalPhoneNumber": "+1 212-254-2246",
    "regularOpeningHours": {"weekdayDescriptions": ["Monday: 8:00 AM – 11:00 PM", "Tuesday: 8:00 AM – 11:00 PM"]},
}
PLACE_URL = "https://www.google.com/maps/place/Katz's/data=!3d40.7!4d-73.9!1s0x1:0x2"


@override_settings(GOOGLE_MAPS_API_KEY="test-key")
class FindPlaceIdTests(AppTestCase):
    def test_place_id_in_link_needs_no_request(self):
        info = links.parse("https://www.google.com/maps/place/?q=place_id:ChIJxyz")
        self.assertEqual(places_api.find_place_id(info, info.url), "ChIJxyz")
        self.assertEqual(self.google.calls, [])

    def test_resolve_maps_urls(self):
        self.google.add("POST", places_api.RESOLVE_URL, text=json.dumps({"entities": [{"place": "places/ChIJ1"}]}))
        info = links.parse(PLACE_URL)
        self.assertEqual(places_api.find_place_id(info, "https://maps.app.goo.gl/AbC"), "ChIJ1")
        method, url, kwargs = self.google.calls[0]
        self.assertEqual(kwargs["json_body"], {"urls": ["https://maps.app.goo.gl/AbC", PLACE_URL]})
        self.assertEqual(kwargs["headers"]["X-Goog-Api-Key"], "test-key")
        self.assertNotIn("key=", url)

    def test_falls_back_to_free_text_search_near_the_pin(self):
        self.google.add("POST", places_api.RESOLVE_URL, status=403, text='{"error": "not enabled"}')
        self.google.add("POST", places_api.SEARCH_URL, text=json.dumps({"places": [{"id": "ChIJ2"}]}))
        info = links.parse(PLACE_URL)
        self.assertEqual(places_api.find_place_id(info, PLACE_URL), "ChIJ2")
        kwargs = self.google.calls[1][2]
        self.assertEqual(kwargs["headers"]["X-Goog-FieldMask"], "places.id")
        self.assertEqual(kwargs["json_body"]["textQuery"], "Katz's")
        self.assertEqual(kwargs["json_body"]["locationBias"]["circle"]["center"], {"latitude": 40.7, "longitude": -73.9})

    def test_nothing_found(self):
        self.google.add("POST", places_api.RESOLVE_URL, text=json.dumps({"entities": [{}]}))
        self.google.add("POST", places_api.SEARCH_URL, text="{}")
        self.assertEqual(places_api.find_place_id(links.parse(PLACE_URL), PLACE_URL), "")


@override_settings(GOOGLE_MAPS_API_KEY="test-key", GMAPS_DAILY_DETAILS_CAP=2)
class DetailsTests(AppTestCase):
    def test_maps_fields(self):
        self.google.add("GET", "https://places.googleapis.com/v1/places/", text=json.dumps(DETAILS))
        fields = places_api.details("ChIJCar0f49ZwokR6ozLV-dHNTE")
        self.assertEqual(fields["name"], "Katz's Delicatessen")
        self.assertEqual(fields["cuisine"], "Deli")
        self.assertEqual(fields["price_level"], 2)
        self.assertEqual(fields["review_count"], 56154)
        self.assertEqual(fields["cid"], "3545819340560108778")
        self.assertEqual(fields["opening_hours"], "Monday: 8:00 AM – 11:00 PM\nTuesday: 8:00 AM – 11:00 PM")
        kwargs = self.google.calls[0][2]
        self.assertIn("rating", kwargs["headers"]["X-Goog-FieldMask"])
        self.assertEqual(kwargs["params"]["languageCode"], "en")

    def test_daily_cap(self):
        self.google.add("GET", "https://places.googleapis.com/v1/places/", text=json.dumps(DETAILS))
        places_api.details("a")
        places_api.details("b")
        with self.assertRaises(places_api.DailyCapReached):
            places_api.details("c")
        self.assertEqual(len(self.google.calls), 2)

    def test_error_status(self):
        self.google.add("GET", "https://places.googleapis.com/v1/places/", status=403, text="denied")
        with self.assertRaises(places_api.ApiError):
            places_api.details("a")
