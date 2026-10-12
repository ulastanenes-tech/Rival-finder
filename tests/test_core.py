import unittest
from datetime import date

from playscout import filters as flt, keywords as kw, reviews, revenue, scoring
from playscout.fetcher import policy_check

TODAY = date(2026, 10, 12)


class DateFilterTests(unittest.TestCase):
    def test_presets_and_month_arithmetic(self):
        self.assertEqual(flt.add_months(date(2026, 10, 12), -6), date(2026, 4, 12))
        self.assertEqual(flt.add_months(date(2026, 3, 31), -1), date(2026, 2, 28))
        self.assertEqual(flt.date_window("1", today=TODAY), (date(2026, 9, 12), TODAY))
        self.assertIsNone(flt.date_window("none", today=TODAY))

    def test_custom_range_validation(self):
        with self.assertRaises(ValueError):
            flt.date_window("custom", "2026-05-01", "2026-01-01", today=TODAY)
        with self.assertRaises(ValueError):
            flt.date_window("custom", None, None, today=TODAY)
        with self.assertRaises(ValueError):
            flt.validate_filters({"date_from": "12.10.2026"})

    def test_unknown_dates_are_not_silently_dropped(self):
        views = [
            {"package": "a", "first_release_date": None, "first_release_status": "unknown"},
            {"package": "b", "first_release_date": "2026-06-01", "first_release_precision": "month",
             "first_release_status": "verified"},
            {"package": "c", "first_release_date": "2019-01-01", "first_release_precision": "day",
             "first_release_status": "verified"},
        ]
        kept, explain = flt.apply(views, {"date_preset": "6"}, today=TODAY)
        self.assertEqual([v["package"] for v in kept], ["b"])
        self.assertEqual(explain[0]["eliminated"], 2)
        kept2, _ = flt.apply(views, {"date_preset": "6", "include_unknown_dates": True}, today=TODAY)
        self.assertEqual(sorted(v["package"] for v in kept2), ["a", "b"])

    def test_download_threshold_is_lower_bound(self):
        views = [{"package": "x", "download_floor": 500_000}, {"package": "y", "download_floor": 1_000_000},
                 {"package": "z", "download_floor": 10_000_000}]
        kept, _ = flt.apply(views, {"min_downloads": 1_000_000}, today=TODAY)
        self.assertEqual([v["package"] for v in kept], ["y", "z"])
        kept, _ = flt.apply(views, {"max_downloads": 5_000_000}, today=TODAY)
        self.assertEqual([v["package"] for v in kept], ["x", "y"])

    def test_combined_filters(self):
        views = [
            {"package": "p1", "download_floor": 1_000_000, "rating": 4.0, "price_type": "free",
             "first_release_date": "2026-08-01", "first_release_precision": "day", "first_release_status": "verified"},
            {"package": "p2", "download_floor": 1_000_000, "rating": 4.6, "price_type": "free",
             "first_release_date": "2026-08-01", "first_release_precision": "day", "first_release_status": "verified"},
        ]
        kept, explain = flt.apply(views, {"date_preset": "6", "min_downloads": 1_000_000, "max_rating": 4.4},
                                  today=TODAY)
        self.assertEqual([v["package"] for v in kept], ["p1"])
        self.assertEqual([e["key"] for e in explain], ["date", "min_downloads", "max_rating"])

    def test_sort_newest_puts_unknown_last(self):
        views = [{"package": "u", "first_release_date": None}, {"package": "o", "first_release_date": "2020-01-01"},
                 {"package": "n", "first_release_date": "2026-01-01"}]
        self.assertEqual([v["package"] for v in flt.sort(views, "newest")], ["n", "o", "u"])


class KeywordTests(unittest.TestCase):
    def test_exact_mode_only_niche(self):
        self.assertEqual(kw.expand("AI photo editor", "exact"), [("ai photo editor", "user")])

    def test_discovery_generates_related_terms(self):
        terms = [t for t, _ in kw.expand("AI photo editor", "discovery")]
        self.assertEqual(terms[0], "ai photo editor")
        self.assertIn("photo editor", terms)
        self.assertIn("artificial intelligence photo editor", terms)
        self.assertNotIn("editor", terms, "tek kelimelik geniş terim üretilmez")

    def test_invalid_niche(self):
        for bad in ["", "   ", "!!!", "the app"]:
            with self.assertRaises(ValueError):
                kw.validate_niche(bad)

    def test_broaden_is_bounded(self):
        self.assertEqual(kw.broaden("AI photo editor", 1), ["photo editor"])
        self.assertEqual(kw.broaden("AI photo editor", 2), ["photo editor", "editor"])
        self.assertEqual(kw.broaden("AI photo editor", 3), [])
        self.assertEqual(kw.broaden("editor", 1), [])

    def test_relevance(self):
        exact = kw.expand("AI photo editor", "exact")
        self.assertGreaterEqual(kw.relevance(exact, "AI Photo Editor - Lumii", "", "")[0], 0.999)
        score, _ = kw.relevance(exact, "Photo Editor Pro", "", "")
        self.assertLess(score, 0.999, "exact modda tüm çekirdek kelimeler şarttır")


class RevenueTests(unittest.TestCase):
    def test_no_evidence_is_status_4_not_invented(self):
        r = revenue.classify({"price_type": "free", "has_ads": None, "has_iap": None}, [])
        self.assertEqual(r["status"], 4)
        self.assertIn("gerçek aylık gelir", r["missing"])

    def test_model_only_is_status_2_and_not_claimed_as_revenue(self):
        r = revenue.classify({"price_type": "free", "has_ads": 1, "has_iap": None}, [])
        self.assertEqual(r["status"], 2)
        self.assertIn("doğrulanmadı", r["label"])

    def test_direct_requires_url(self):
        ev = [{"kind": "developer_disclosed", "url": None, "description": "x"}]
        self.assertEqual(revenue.classify({}, ev)["status"], 4)
        ev = [{"kind": "developer_disclosed", "url": "https://example.com/post", "description": "x",
               "evidence_date": "2026-01-01"}]
        self.assertEqual(revenue.classify({}, ev)["status"], 1)

    def test_top_grossing_is_weak(self):
        r = revenue.classify({"price_type": "free"}, [], "#4 Top Grossing, Photography, France")
        self.assertEqual(r["status"], 3)


class ReviewTests(unittest.TestCase):
    def test_small_sample_is_flagged_and_no_change_computed(self):
        rs = [{"text": "crashes on start", "rating": 1, "date": "2026-10-01", "version": "2.1", "url": "u1"},
              {"text": "great app", "rating": 5, "date": "2026-09-01", "version": None, "url": None}]
        a = reviews.analyze(rs, as_of=TODAY)
        self.assertTrue(a["low_sample"])
        self.assertIsNone(a["categories"]["crashes_bugs"]["change_30d"])

    def test_turkish_and_english_classification(self):
        self.assertIn("ads", reviews.classify("çok fazla reklam var"))
        self.assertIn("crashes_bugs", reviews.classify("uygulama çöküyor"))
        self.assertEqual(reviews.classify("nothing special"), ["other"])

    def test_dedupe_hash_and_csv_import(self):
        content = "text,rating,date\nCrash on launch,1,2026-10-01\nCrash on launch,1,2026-10-01\n,5,\n"
        rows, skipped = reviews.parse_import(content, "csv")
        self.assertEqual(len(rows), 2)
        self.assertEqual(skipped, 1)
        self.assertEqual(reviews.review_hash("A  b"), reviews.review_hash("a b"))

    def test_import_rejects_bad_format(self):
        with self.assertRaises(ValueError):
            reviews.parse_import("x", "xml")


class ScoringTests(unittest.TestCase):
    def test_missing_data_is_neutral_not_zero(self):
        app = {"package": "x", "download_floor": None, "first_release_status": "unknown"}
        rev = revenue.classify(app, [])
        sc = scoring.score_app(app, {"sample_size": 0, "low_sample": True}, rev, [],
                               scoring.normalize_weights(), today=TODAY)
        self.assertGreater(sc["opportunity"], 0)
        self.assertEqual(sc["confidence"], "düşük")
        self.assertTrue(sc["missing"])

    def test_weights_normalize_to_100(self):
        w = scoring.normalize_weights({"demand": 40})
        self.assertAlmostEqual(sum(w.values()), 100, places=0)
        with self.assertRaises(ValueError):
            scoring.normalize_weights({"nope": 1})

    def test_research_score_and_confidence_are_separate_fields(self):
        app = {"package": "x", "download_floor": 1_000_000, "review_count": 100000, "rating": 3.2,
               "developer_name": "D", "first_release_status": "verified", "first_release_date": "2026-05-01",
               "first_release_precision": "month", "last_updated": "2026-09-01", "appbrain_data_date": "2026-10-10"}
        rev = revenue.classify(app, [])
        an = {"sample_size": 40, "low_sample": False, "low_star_share": 0.5,
              "categories": {"ads": {"share": 0.4}}}
        sc = scoring.score_app(app, an, rev, [], scoring.normalize_weights(), today=TODAY)
        self.assertIn("opportunity", sc)
        self.assertIn(sc["confidence"], ("düşük", "orta", "yüksek"))


class PolicyTests(unittest.TestCase):
    def test_disallowed_paths_are_blocked(self):
        self.assertIsNone(policy_check("https://play.google.com/store/apps/details?id=com.a.b&hl=en&gl=US"))
        self.assertIsNotNone(policy_check("https://play.google.com/store/search?q=photo"))
        self.assertIsNotNone(policy_check("https://play.google.com/store/getreviews?id=x"))
        self.assertIsNotNone(policy_check("https://www.appbrain.com/search?q=photo"))
        self.assertIsNotNone(policy_check("https://www.appbrain.com/app_details/x"))
        self.assertIsNotNone(policy_check("http://play.google.com/store/apps/details?id=x"))
        self.assertIsNotNone(policy_check("https://example.org/store/apps/details?id=x"))


if __name__ == "__main__":
    unittest.main()


class StaleDataTests(unittest.TestCase):
    def test_old_or_missing_timestamps_are_flagged_stale(self):
        from datetime import datetime, timedelta, timezone
        from playscout import pipeline
        old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        fresh = datetime.now(timezone.utc).isoformat()
        self.assertTrue(pipeline._is_stale(old))
        self.assertTrue(pipeline._is_stale(None))
        self.assertFalse(pipeline._is_stale(fresh))
