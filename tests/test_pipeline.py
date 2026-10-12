import os
import tempfile
import unittest
import urllib.error
from datetime import date

from playscout import db, pipeline
from playscout.fetcher import Fetcher
from tests.helpers import FakeOpener, fixture, no_sleep, temp_conn

TODAY = date(2026, 10, 12)
PHOTOROOM_PLAY = "https://play.google.com/store/apps/details?id=com.photoroom.app"
GPHOTOS_PLAY = "https://play.google.com/store/apps/details?id=com.google.android.apps.photos"


def routes(extra=None):
    r = {
        "https://play.google.com/store/apps/details?id=com.photoroom.app": fixture("play_photoroom.html"),
        "https://play.google.com/store/apps/details?id=com.google.android.apps.photos": fixture("play_google_photos.html"),
        "https://www.appbrain.com/app/com.photoroom.app": fixture("appbrain_photoroom.html"),
        "https://www.appbrain.com/app/com.google.android.apps.photos": fixture("appbrain_google_photos.html"),
        "https://play.google.com/store/apps/details?id=com.gizastudios.productplus": fixture("play_bad_page.html"),
    }
    r.update(extra or {})
    return r


def make_fetcher(conn, opener, offline=False):
    return Fetcher(conn, offline=offline, min_interval=0, opener=opener, sleep=no_sleep, clock=lambda: 0.0)


class PipelineTests(unittest.TestCase):
    def test_discovery_run_end_to_end(self):
        conn = temp_conn()
        opener = FakeOpener(routes())
        res = pipeline.run_search(conn, {
            "niche": "AI photo editor", "mode": "discovery", "seeds": "com.photoroom.app",
            "filters": {}, "max_candidates": 10,
        }, fetcher=make_fetcher(conn, opener), today=TODAY)
        self.assertIn(res["status"], ("completed", "completed_with_errors"))
        st = res["stats"]
        self.assertGreaterEqual(st["candidates_found"], 1)
        self.assertGreaterEqual(st["play_verified"], 1)
        app = db.get_app(conn, "com.photoroom.app")
        self.assertEqual(app["title"], "Photoroom: AI Photo Editor")
        self.assertEqual(app["first_release_date"], "2020-12-01")
        self.assertEqual(app["first_release_precision"], "month")
        self.assertEqual(app["first_release_status"], "verified")
        self.assertEqual(app["last_updated"], "2025-01-16")  # Play'deki güncelleme tarihi (Jan 16, 2025)
        self.assertEqual(app["download_floor"], 100_000_000)
        # Alternatives (AppBrain) were discovered and tried; a 404 must not crash the run
        self.assertTrue(any("gizastudios" in u for u in opener.requested))
        self.assertTrue(any("gizastudios" in e.get("package", "") for e in st["source_errors"]))

    def test_search_pages_are_never_requested(self):
        conn = temp_conn()
        opener = FakeOpener(routes())
        pipeline.run_search(conn, {"niche": "AI photo editor", "mode": "discovery",
                                   "seeds": "com.photoroom.app com.google.android.apps.photos"},
                            fetcher=make_fetcher(conn, opener), today=TODAY)
        for u in opener.requested:
            self.assertNotIn("/store/search", u)
            self.assertNotIn("/search", u)
            self.assertNotIn("getreviews", u)

    def test_exact_mode_excludes_unrelated_and_reports_it(self):
        conn = temp_conn()
        res = pipeline.run_search(conn, {"niche": "AI photo editor", "mode": "exact",
                                         "seeds": "com.google.android.apps.photos,com.photoroom.app"},
                                  fetcher=make_fetcher(conn, FakeOpener(routes())), today=TODAY)
        self.assertGreaterEqual(res["stats"]["excluded"]["alaka_uyumsuz"], 1)
        pkgs = [r["package"] for r in conn.execute("SELECT package FROM SearchRunApps WHERE run_id=?", (res["run_id"],))]
        self.assertEqual(pkgs, ["com.photoroom.app"])

    def test_same_app_from_multiple_seeds_is_deduplicated(self):
        conn = temp_conn()
        res = pipeline.run_search(conn, {"niche": "AI photo editor", "mode": "exact",
                                         "seeds": "com.photoroom.app\nhttps://play.google.com/store/apps/details?id=com.photoroom.app"},
                                  fetcher=make_fetcher(conn, FakeOpener(routes())), today=TODAY)
        self.assertEqual(res["stats"]["candidates_found"], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM Apps WHERE package='com.photoroom.app'").fetchone()[0], 1)

    def test_empty_seed_and_empty_db_is_clear_error(self):
        conn = temp_conn()
        with self.assertRaises(pipeline.RunError) as cm:
            pipeline.run_search(conn, {"niche": "AI photo editor", "mode": "exact", "seeds": ""},
                                fetcher=make_fetcher(conn, FakeOpener({})), today=TODAY)
        self.assertIn("paket adı", str(cm.exception))
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM SearchRuns").fetchone()[0], 0,
                         "geçersiz girdide çalıştırma kaydı oluşmamalı")

    def test_invalid_niche_and_mode(self):
        conn = temp_conn()
        with self.assertRaises(ValueError):
            pipeline.run_search(conn, {"niche": "  ", "seeds": "com.a.b"}, fetcher=make_fetcher(conn, FakeOpener({})))
        with self.assertRaises(ValueError):
            pipeline.run_search(conn, {"niche": "photo", "mode": "wild", "seeds": "com.a.b"},
                                fetcher=make_fetcher(conn, FakeOpener({})))

    def test_source_unreachable_is_reported_not_fatal(self):
        conn = temp_conn()
        down = {"https://play.google.com/": urllib.error.URLError("network down"),
                "https://www.appbrain.com/": urllib.error.URLError("network down")}
        res = pipeline.run_search(conn, {"niche": "AI photo editor", "mode": "exact",
                                         "seeds": "com.photoroom.app"},
                                  fetcher=make_fetcher(conn, FakeOpener(down)), today=TODAY)
        self.assertEqual(res["status"], "completed_with_errors")
        self.assertTrue(res["stats"]["source_errors"])
        self.assertEqual(res["stats"]["play_verified"], 0)

    def test_offline_mode_uses_saved_data_and_makes_no_requests(self):
        conn = temp_conn()
        pipeline.run_search(conn, {"niche": "AI photo editor", "mode": "exact", "seeds": "com.photoroom.app"},
                            fetcher=make_fetcher(conn, FakeOpener(routes())), today=TODAY)
        opener = FakeOpener({})
        res = pipeline.run_search(conn, {"niche": "AI photo editor", "mode": "exact", "offline": True,
                                         "seeds": "com.photoroom.app"},
                                  fetcher=make_fetcher(conn, opener, offline=True), today=TODAY)
        self.assertEqual(opener.requested, [], "çevrimdışı modda ağ isteği yapılmamalı")
        self.assertEqual(res["stats"]["relevant_count"], 1)

    def test_data_survives_reopening_database(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "persist.db")
        conn = db.connect(path)
        pipeline.run_search(conn, {"niche": "AI photo editor", "mode": "exact", "seeds": "com.photoroom.app"},
                            fetcher=make_fetcher(conn, FakeOpener(routes())), today=TODAY)
        run_id = conn.execute("SELECT MAX(id) FROM SearchRuns").fetchone()[0]
        conn.close()
        conn2 = db.connect(path)
        row = conn2.execute("SELECT * FROM SearchRuns WHERE id=?", (run_id,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(conn2.execute("SELECT title FROM Apps WHERE package='com.photoroom.app'").fetchone()[0],
                         "Photoroom: AI Photo Editor")

    def test_bot_block_page_marks_play_error(self):
        conn = temp_conn()
        res = pipeline.run_search(conn, {"niche": "AI photo editor", "mode": "exact",
                                         "seeds": "com.gizastudios.productplus"},
                                  fetcher=make_fetcher(conn, FakeOpener(routes())), today=TODAY)
        app = db.get_app(conn, "com.gizastudios.productplus")
        self.assertEqual(app["play_status"], "error")
        self.assertIn("bot", app["play_error"].lower())
        self.assertEqual(res["stats"]["relevant_count"], 0)

    def test_fallback_broadens_when_no_exact_match(self):
        conn = temp_conn()
        page = ('<html><head><meta property="og:title" content="Photo Editor Pro - Apps on Google Play">'
                '<meta name="description" content="Crop, filter and retouch your photos."></head>'
                '<body><div>4.1</div><div>12K reviews</div><div>1M+</div><div>Downloads</div>'
                '<div>Install</div></body></html>')
        opener = FakeOpener(routes({"https://play.google.com/store/apps/details?id=com.example.photoeditorpro": page}))
        res = pipeline.run_search(conn, {"niche": "AI photo editor", "mode": "exact",
                                         "seeds": "com.example.photoeditorpro", "allow_broaden": True},
                                  fetcher=make_fetcher(conn, opener), today=TODAY)
        # Tam eşleşme ("AI" yok) reddedilir; geri dönüş "photo editor" ile bulunur ve açıkça işaretlenir
        self.assertEqual(res["stats"]["excluded"]["alaka_uyumsuz"], 0)
        self.assertIsNotNone(res["stats"]["fallback"])
        self.assertEqual(res["stats"]["fallback"]["level"], 1)
        self.assertEqual(res["stats"]["fallback"]["terms"], ["photo editor"])
        self.assertEqual(res["stats"]["relevant_count"], 1)

    def test_fallback_can_be_disabled(self):
        conn = temp_conn()
        page = ('<html><head><meta property="og:title" content="Photo Editor Pro - Apps on Google Play">'
                '</head><body><div>4.1</div><div>1M+</div><div>Downloads</div></body></html>')
        opener = FakeOpener(routes({"https://play.google.com/store/apps/details?id=com.example.photoeditorpro": page}))
        res = pipeline.run_search(conn, {"niche": "AI photo editor", "mode": "exact",
                                         "seeds": "com.example.photoeditorpro", "allow_broaden": False},
                                  fetcher=make_fetcher(conn, opener), today=TODAY)
        self.assertIsNone(res["stats"]["fallback"])
        self.assertEqual(res["stats"]["relevant_count"], 0)


class ExportAndDumpTests(unittest.TestCase):
    def test_dump_contains_required_tables(self):
        conn = temp_conn()
        pipeline.run_search(conn, {"niche": "AI photo editor", "mode": "exact", "seeds": "com.photoroom.app"},
                            fetcher=make_fetcher(conn, FakeOpener(routes())), today=TODAY)
        out = db.dump_json(conn, os.path.join(tempfile.mkdtemp(), "dump.json"))
        for t in ["Apps", "Developers", "Keywords", "SearchRuns", "AppSnapshots", "ReviewSamples",
                  "ReviewIssueCategories", "RevenueEvidence", "Sources", "SavedComparisons", "SearchRunApps"]:
            self.assertIn(t, out["tables"])
        self.assertTrue(out["tables"]["Apps"])
        self.assertTrue(any(s["name"].startswith("AppBrain") for s in out["tables"]["Sources"]))


if __name__ == "__main__":
    unittest.main()
