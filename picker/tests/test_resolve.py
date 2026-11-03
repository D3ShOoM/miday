from picker.gmaps import resolve
from picker.gmaps.links import LinkError

from .base import AppTestCase

PLACE = "https://www.google.com/maps/place/Katz's+Delicatessen/data=!4m2!3m1!1s0x1:0x2"


class ResolveTests(AppTestCase):
    def test_maps_url_is_returned_without_fetching(self):
        self.assertEqual(resolve.resolve(PLACE), PLACE)
        self.assertEqual(self.google.calls, [])

    def test_short_link_one_hop_with_get(self):
        self.google.redirect("https://maps.app.goo.gl/AbC", PLACE)
        self.assertEqual(resolve.resolve("https://maps.app.goo.gl/AbC?g_st=ic"), PLACE)
        self.assertEqual(self.google.calls[0][0], "GET")

    def test_share_google_two_hops_and_relative_location(self):
        self.google.redirect("https://share.google/XyZ", "/share.google?q=XyZ")
        self.google.redirect("https://share.google/share.google", "https://www.google.com/share.google?q=XyZ")
        self.google.redirect(
            "https://www.google.com/share.google", "https://www.google.com/search?kgmid=/g/1&q=Cafe", status=301
        )
        self.assertEqual(
            resolve.resolve("https://share.google/XyZ"), "https://www.google.com/search?kgmid=/g/1&q=Cafe"
        )

    def test_redirect_off_google_is_refused(self):
        self.google.redirect("https://maps.app.goo.gl/Evil", "http://169.254.169.254/latest/")
        with self.assertRaises(LinkError):
            resolve.resolve("https://maps.app.goo.gl/Evil")

    def test_dead_short_link(self):
        self.google.add("GET", "https://maps.app.goo.gl/Dead", status=404)
        with self.assertRaises(LinkError):
            resolve.resolve("https://maps.app.goo.gl/Dead")

    def test_redirect_loop_stops(self):
        self.google.redirect("https://maps.app.goo.gl/Loop", "https://maps.app.goo.gl/Loop")
        with self.assertRaises(LinkError):
            resolve.resolve("https://maps.app.goo.gl/Loop")
        self.assertEqual(len(self.google.calls), resolve.MAX_HOPS)

    def test_non_google_link_is_refused_before_any_request(self):
        with self.assertRaises(LinkError):
            resolve.resolve("https://example.com/maps/place/X")
        self.assertEqual(self.google.calls, [])
