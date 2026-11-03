from django.test import SimpleTestCase

from picker.gmaps import links
from picker.gmaps.links import LinkError

DESKTOP = (
    "https://www.google.com/maps/place/Garh+Jaisal's+Kitchen/@26.9132724,70.9117075,17z/"
    "data=!4m6!3m5!1s0x3947bd9e89a679cf:0xd196c3f044898c10!8m2!3d26.9130337!4d70.914347"
    "!16s%2Fg%2F11p_1p5s7d?authuser=1&entry=tts"
)
MOBILE = (
    "https://www.google.com/maps/place/L'Enoteca,+V%C3%A4stergatan+6C,+211+21+Malm%C3%B6,+Sweden/"
    "data=!4m2!3m1!1s0x4653a3fe92080cd7:0x233b080286a29c3a!18m1!1e1?utm_source=mstt_1&entry=gps"
)
ANDROID = (
    "https://maps.google.com/?q=Takeshi,+5+Chome-52-2+Higashinippori,+Arakawa+City,+Tokyo+116-0014"
    "&ftid=0x60188d7815e5780b:0x4d2253d101760cd3&entry=gps&g_st=ic"
)


class FindUrlTests(SimpleTestCase):
    def test_link_inside_share_text(self):
        text = "ALBAIK\n4.3 ★ · Fast food restaurant\nhttps://maps.app.goo.gl/AbC123?g_st=ic"
        self.assertEqual(links.find_url(text), "https://maps.app.goo.gl/AbC123?g_st=ic")

    def test_trailing_punctuation_is_dropped_but_apostrophes_kept(self):
        self.assertEqual(
            links.find_url("Try (https://www.google.com/maps/place/Katz's+Deli/)."),
            "https://www.google.com/maps/place/Katz's+Deli/",
        )

    def test_no_link(self):
        self.assertIsNone(links.find_url("just a name"))
        self.assertIsNone(links.find_url(""))


class NormalizeTests(SimpleTestCase):
    def test_upgrades_http_and_drops_fragment(self):
        self.assertEqual(
            links.normalize("http://maps.google.com/?cid=1#x"), "https://maps.google.com/?cid=1"
        )

    def test_accepts_google_country_domains_and_shorteners(self):
        for url in [
            "https://www.google.com.sa/maps/place/X",
            "https://www.google.co.uk/maps/place/X",
            "https://google.ca/maps/place/X",
            "https://maps.app.goo.gl/AbC",
            "https://goo.gl/maps/AbC",
            "https://share.google/AbC",
            "https://g.co/kgs/AbC",
        ]:
            self.assertTrue(links.normalize(url).startswith("https://"), url)

    def test_rejects_everything_else(self):
        for url in [
            "https://google.com.evil.com/maps/place/X",
            "https://evilgoogle.com/maps",
            "https://google.xyz/maps/place/X",
            "https://maps.google.com@evil.com/",
            "https://169.254.169.254/latest/meta-data",
            "http://localhost:8000/",
            "https://maps.google.com:8443/",
            "https://goo.gl/abc",
            "ftp://maps.google.com/",
            "javascript:alert(1)",
        ]:
            with self.assertRaises(LinkError, msg=url):
                links.normalize(url)

    def test_unwraps_consent_page(self):
        url = "https://consent.google.com/m?continue=https://www.google.com/maps/place/X&gl=DE"
        self.assertEqual(links.normalize(url), "https://www.google.com/maps/place/X")

    def test_shorteners(self):
        self.assertTrue(links.is_shortener("https://maps.app.goo.gl/x"))
        self.assertTrue(links.is_shortener("https://www.google.com/share.google?q=x"))
        self.assertFalse(links.is_shortener("https://www.google.com/maps/place/x"))


class ParseTests(SimpleTestCase):
    def test_desktop_place_link(self):
        info = links.parse(DESKTOP)
        self.assertEqual(info.name, "Garh Jaisal's Kitchen")
        self.assertEqual(info.feature_id, "0x3947bd9e89a679cf:0xd196c3f044898c10")
        self.assertEqual(info.cid, str(0xD196C3F044898C10))
        # The pin (!3d/!4d), not the map centre (@…).
        self.assertEqual((info.lat, info.lng), (26.9130337, 70.914347))

    def test_mobile_place_link_cuts_the_address(self):
        info = links.parse(MOBILE)
        self.assertEqual(info.name, "L'Enoteca")
        self.assertEqual(info.query, "L'Enoteca, Västergatan 6C, 211 21 Malmö, Sweden")
        self.assertEqual(info.feature_id, "0x4653a3fe92080cd7:0x233b080286a29c3a")
        self.assertIsNone(info.lat)

    def test_android_query_link(self):
        info = links.parse(ANDROID)
        self.assertEqual(info.name, "Takeshi")
        self.assertTrue(info.query.startswith("Takeshi, 5 Chome-52-2"))
        self.assertEqual(info.feature_id, "0x60188d7815e5780b:0x4d2253d101760cd3")
        self.assertEqual(info.cid, str(0x4D2253D101760CD3))

    def test_plus_code_and_arabic_comma(self):
        info = links.parse(
            "https://maps.google.com/?q=RV25%2B6HJ+%D9%85%D8%B7%D8%B9%D9%85+%D9%86%D8%AC%D9%85%D8%A9"
            "%D8%8C+%D8%A7%D9%84%D8%B1%D9%8A%D8%A7%D8%B6&ftid=0x3e2fab00083c2a81:0x1770c9995996ff65"
        )
        self.assertEqual(info.name, "مطعم نجمة")

    def test_arabic_place_name(self):
        info = links.parse(
            "https://www.google.com/maps/place/%D8%A7%D9%84%D8%A8%D9%8A%D9%83/@26.2,50.19,17z"
        )
        self.assertEqual(info.name, "البيك")
        self.assertEqual((info.lat, info.lng), (26.2, 50.19))

    def test_cid_link(self):
        self.assertEqual(links.parse("https://maps.google.com/?cid=5896571644380111477").cid, "5896571644380111477")

    def test_place_id_links(self):
        self.assertEqual(
            links.parse("https://www.google.com/maps/search/?api=1&query=Katz&query_place_id=ChIJabc").place_id,
            "ChIJabc",
        )
        self.assertEqual(
            links.parse("https://www.google.com/maps/place/?q=place_id:ChIJxyz").place_id, "ChIJxyz"
        )

    def test_search_page_from_share_google(self):
        info = links.parse("https://www.google.com/search?kgmid=/g/11yzw288tr&hl=en&q=Di+Riso+Teloni+Italia")
        self.assertEqual(info.name, "Di Riso Teloni Italia")
        self.assertEqual(info.feature_id, "")

    def test_dropped_pin_and_coordinate_query(self):
        info = links.parse("https://www.google.com/maps/search/5.811698,+-55.118891?entry=tts")
        self.assertEqual((info.name, info.lat, info.lng), ("", 5.811698, -55.118891))
        info = links.parse("https://maps.google.com/?q=29.961549,31.277048")
        self.assertEqual((info.name, info.lat), ("", 29.961549))
