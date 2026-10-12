import unittest

from playscout import parsers
from tests.helpers import fixture


class CompactNumberTests(unittest.TestCase):
    def test_compact_numbers(self):
        self.assertEqual(parsers.parse_compact_number("54.2M"), 54_200_000)
        self.assertEqual(parsers.parse_compact_number("3,960,725"), 3_960_725)
        self.assertEqual(parsers.parse_compact_number("1.1 million"), 1_100_000)
        self.assertEqual(parsers.parse_compact_number("15 billion"), 15_000_000_000)
        self.assertEqual(parsers.parse_compact_number("10B+"), 10_000_000_000)
        self.assertIsNone(parsers.parse_compact_number("çok"))
        self.assertIsNone(parsers.parse_compact_number(None))

    def test_download_bucket_is_lower_bound(self):
        self.assertEqual(parsers.parse_download_bucket("1,000,000+"), (1_000_000, "1,000,000+"))
        self.assertEqual(parsers.parse_download_bucket("10B+"), (10_000_000_000, "10B+"))
        self.assertEqual(parsers.parse_download_bucket("nothing"), (None, None))

    def test_play_date_and_month(self):
        self.assertEqual(parsers.parse_play_date("Oct 8, 2026"), "2026-10-08")
        self.assertEqual(parsers.parse_play_date("September 28, 2026"), "2026-09-28")
        self.assertIsNone(parsers.parse_play_date("bilinmiyor"))
        self.assertEqual(parsers.parse_month_year("December", "2020"), ("2020-12-01", "month"))


class PlayDetailsTests(unittest.TestCase):
    def test_google_photos_fields(self):
        d = parsers.parse_play_details(fixture("play_google_photos.html"), "com.google.android.apps.photos")
        self.assertEqual(d["title"], "Google Photos")
        self.assertEqual(d["developer_name"], "Google LLC")
        self.assertEqual(d["category"], "Photography")
        self.assertEqual(d["rating"], 4.4)
        self.assertEqual(d["review_count"], 54_200_000)
        self.assertEqual(d["download_floor"], 10_000_000_000)
        self.assertEqual(d["last_updated"], "2026-10-08")
        self.assertEqual(d["has_iap"], 1)
        self.assertIsNone(d["has_ads"], "reklam etiketi yoksa kanıt yok (None), False değil")
        self.assertEqual(d["price_type"], "free")
        self.assertIsNone(d["has_subscription"])
        self.assertTrue(d["_usable"])

    def test_photoroom_ads_and_rating_from_aria(self):
        d = parsers.parse_play_details(fixture("play_photoroom.html"), "com.photoroom.app")
        self.assertEqual(d["rating"], 4.7)
        self.assertEqual(d["download_floor"], 100_000_000)
        self.assertEqual(d["has_ads"], 1)
        self.assertEqual(d["has_iap"], 1)

    def test_bot_block_page_is_not_usable(self):
        d = parsers.parse_play_details(fixture("play_bad_page.html"), "com.x.y")
        self.assertFalse(d["_usable"])
        self.assertTrue(d["_bot_block"])

    def test_missing_downloads_stay_none(self):
        d = parsers.parse_play_details("<html><title>x</title><h1>Only title</h1></html>", "a.b.c")
        self.assertIsNone(d["download_floor"])
        self.assertIsNone(d["rating"])


class AppBrainTests(unittest.TestCase):
    def test_first_release_is_month_precision_and_separate_from_update(self):
        ab = parsers.parse_appbrain_app(fixture("appbrain_photoroom.html"), "com.photoroom.app")
        self.assertEqual(ab["first_release_date"], "2020-12-01")
        self.assertEqual(ab["first_release_precision"], "month")
        self.assertEqual(ab["last_updated"], "2025-01-16")
        self.assertNotEqual(ab["first_release_date"], ab["last_updated"])
        self.assertEqual(ab["total_installs"], 180_000_000)
        self.assertEqual(ab["installs_30d"], 1_100_000)
        self.assertEqual(ab["rank_text"], "#4 Top Grossing, Photography, France")
        self.assertEqual(ab["data_date"], "2026-10-10")

    def test_alternatives_exclude_self(self):
        ab = parsers.parse_appbrain_app(fixture("appbrain_photoroom.html"), "com.photoroom.app")
        self.assertIn("com.gizastudios.productplus", ab["alternatives"])
        self.assertIn("ai.photo.editor.eraser.app", ab["alternatives"])
        self.assertNotIn("com.photoroom.app", ab["alternatives"])

    def test_google_photos_appbrain(self):
        ab = parsers.parse_appbrain_app(fixture("appbrain_google_photos.html"), "com.google.android.apps.photos")
        self.assertEqual(ab["first_release_date"], "2015-05-01")
        self.assertEqual(ab["installs_30d"], 160_000_000)
        self.assertIn("com.simplemobiletools.gallery.pro", ab["alternatives"])


class ExtractPackagesTests(unittest.TestCase):
    def test_mixed_input_order_and_dedupe(self):
        text = ("https://play.google.com/store/apps/details?id=com.photoroom.app\n"
                "com.picsart.studio, com.photoroom.app\n"
                "https://www.appbrain.com/app/product-plus/com.gizastudios.productplus")
        self.assertEqual(parsers.extract_packages(text),
                         ["com.photoroom.app", "com.picsart.studio", "com.gizastudios.productplus"])

    def test_rejects_garbage(self):
        self.assertEqual(parsers.extract_packages("hello world !!! https://evil.example/x"), [])


if __name__ == "__main__":
    unittest.main()
