import json

from picker.gmaps import links, maps_page

from .base import AppTestCase, fixture

PAGE_URL = (
    "https://www.google.com/maps/place/Katz's+Delicatessen/@40.722233,-73.987434,17z/"
    "data=!4m5!3m4!1s0x89c2598f7ff4aa09:0x313547e757cb8cea!8m2!3d40.722233!4d-73.987429"
)
PRELOAD_HTML = (
    '<html><head><link href="/maps/preview/place?authuser=0&amp;hl=ar&amp;gl=sa&amp;'
    'pb=%211m14%211s0x89c2598f7ff4aa09%3A0x313547e757cb8cea" as="fetch"></head></html>'
)


class ParseRecordTests(AppTestCase):
    def test_fields_from_recorded_response(self):
        payload = json.loads(fixture("maps_preview_place.json").split("\n", 1)[1])
        fields = maps_page.to_fields(payload[6])
        self.assertEqual(fields["name"], "Katz's Delicatessen")
        self.assertEqual(fields["rating"], 4.5)
        self.assertEqual(fields["review_count"], 56154)
        self.assertEqual(fields["cuisine"], "Deli")
        self.assertEqual(fields["address"], "205 E Houston St, New York, NY 10002, United States")
        self.assertEqual(fields["phone"], "+1 212-254-2246")
        self.assertEqual(fields["website"], "https://katzsdelicatessen.com/")
        self.assertEqual(fields["place_id"], "ChIJCar0f49ZwokR6ozLV-dHNTE")
        self.assertEqual(fields["cid"], "3545819340560108778")
        self.assertAlmostEqual(fields["latitude"], 40.722233, places=5)
        self.assertTrue(fields["photo_url"].startswith("https://lh3.googleusercontent.com/"))
        self.assertTrue(fields["opening_hours"].startswith("Monday: 8\u202fAM–11\u202fPM\nTuesday:"))
        self.assertIn("Saturday: Open 24 hours", fields["opening_hours"])

    def test_negative_cid_becomes_unsigned(self):
        place = [None] * 38
        place[37] = [[[None] * 29 + [[None, "-3344270236566582256"]]]]
        self.assertEqual(maps_page.to_fields(place)["cid"], str(0xD196C3F044898C10))

    def test_unexpected_shapes_give_blanks(self):
        fields = maps_page.to_fields(["not", "a", {"place": 1}])
        self.assertEqual(fields["name"], "")
        self.assertIsNone(fields["rating"])


class LookupTests(AppTestCase):
    def test_reads_the_preloaded_record_in_english(self):
        self.google.add("GET", "https://www.google.com/maps/place/", text=PRELOAD_HTML)
        self.google.add("GET", "https://www.google.com/maps/preview/place?", text=fixture("maps_preview_place.json"))
        fields = maps_page.lookup(links.parse(PAGE_URL))
        self.assertEqual(fields["name"], "Katz's Delicatessen")
        page_url, preview_url = self.google.urls()
        self.assertIn("hl=en", page_url)
        self.assertIn("hl=en", preview_url)
        self.assertNotIn("hl=ar", preview_url)

    def test_falls_back_to_the_feature_id(self):
        self.google.add("GET", "https://www.google.com/maps/place/", text="<html>no preload</html>")
        self.google.add("GET", "https://www.google.com/maps/preview/place?", text=fixture("maps_preview_place.json"))
        fields = maps_page.lookup(links.parse(PAGE_URL))
        self.assertEqual(fields["review_count"], 56154)
        self.assertIn("pb=%211m1%211s0x89c2598f7ff4aa09%3A0x313547e757cb8cea", self.google.urls()[-1])

    def test_cid_only_link(self):
        self.google.add("GET", "https://maps.google.com/", text="<html></html>")
        self.google.add("GET", "https://www.google.com/maps/preview/place?", text=fixture("maps_preview_place.json"))
        fields = maps_page.lookup(links.parse("https://maps.google.com/?cid=3545819340560108778"))
        self.assertEqual(fields["name"], "Katz's Delicatessen")
        self.assertIn("0x0%3A0x313547e757cb8cea", self.google.urls()[-1])

    def test_follows_google_redirects_only(self):
        self.google.redirect("https://maps.google.com/", "https://www.google.com/maps?q=Takeshi&ftid=0x1:0x2")
        self.google.add("GET", "https://www.google.com/maps?", text=PRELOAD_HTML)
        self.google.add("GET", "https://www.google.com/maps/preview/place?", text=fixture("maps_preview_place.json"))
        fields = maps_page.lookup(links.parse("https://maps.google.com/?q=Takeshi&ftid=0x1:0x2"))
        self.assertEqual(fields["name"], "Katz's Delicatessen")

    def test_empty_stub_means_nothing_found(self):
        self.google.add("GET", "https://www.google.com/maps/place/", text="<html></html>")
        self.google.add("GET", "https://www.google.com/maps/preview/place?", text=")]}'\n[null,null]")
        self.assertEqual(maps_page.lookup(links.parse(PAGE_URL)), {})
