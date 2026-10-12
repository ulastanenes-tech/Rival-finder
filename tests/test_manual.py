import unittest

from playscout import db, exporter, manual
from tests.helpers import temp_conn


class ManualTests(unittest.TestCase):
    def test_review_import_dedupes_and_reports(self):
        conn = temp_conn()
        content = "text,rating,date,version\nCrash on open,1,2026-10-01,3.0\nCrash on open,1,2026-10-01,3.0\nToo many ads,2,2026-09-20,3.0\n"
        res = manual.import_reviews(conn, "com.x.app", "csv", content)
        self.assertEqual(res["read"], 3)
        self.assertEqual(res["added"], 2)
        n = conn.execute("SELECT COUNT(*) FROM ReviewSamples WHERE package='com.x.app'").fetchone()[0]
        self.assertEqual(n, 2)

    def test_review_import_rejects_empty(self):
        conn = temp_conn()
        with self.assertRaises(ValueError):
            manual.import_reviews(conn, "com.x.app", "json", '[{"rating": 1}]')

    def test_direct_evidence_requires_https_url(self):
        conn = temp_conn()
        with self.assertRaises(ValueError):
            manual.add_evidence(conn, "com.x.app", "developer_disclosed", "gelir açıklaması", None)
        with self.assertRaises(ValueError):
            manual.add_evidence(conn, "com.x.app", "developer_disclosed", "x", "http://insecure")
        manual.add_evidence(conn, "com.x.app", "developer_disclosed", "Geliştirici blog yazısı",
                            "https://example.com/post", "2026-03-01")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM RevenueEvidence").fetchone()[0], 1)

    def test_comparison_needs_two_apps(self):
        conn = temp_conn()
        with self.assertRaises(ValueError):
            manual.save_comparison(conn, "A vs B", ["com.a.a"])
        cid = manual.save_comparison(conn, "A vs B", ["com.a.a", "com.b.b", "com.a.a"])
        row = conn.execute("SELECT packages_json FROM SavedComparisons WHERE id=?", (cid,)).fetchone()
        self.assertEqual(row[0], '["com.a.a", "com.b.b"]')

    def test_csv_and_json_export_include_sources_and_flags(self):
        view = {"package": "com.a.a", "title": "T", "opportunity": 55.0, "confidence": "orta",
                "missing": ["yorum örneği"], "low_sample": True, "stale": False,
                "sources": [{"source": "Google Play detay sayfası", "date": "2026-10-12", "url": "https://play.google.com/x"}]}
        csv_text = exporter.views_to_csv([view])
        self.assertIn("Paket adı", csv_text)
        self.assertIn("Google Play detay sayfası / 2026-10-12", csv_text)
        self.assertIn("yorum örneği", csv_text)
        import json
        j = json.loads(exporter.views_to_json([view], run={"id": 1}))
        self.assertEqual(j["count"], 1)
        self.assertEqual(j["results"][0]["package"], "com.a.a")

    def test_import_roundtrip_keeps_existing_data(self):
        import os, tempfile
        src = temp_conn()
        db.upsert_app(src, "com.a.a", title="Alpha", rating=4.1)
        manual.save_comparison(src, "c", ["com.a.a", "com.b.b"])
        path = os.path.join(tempfile.mkdtemp(), "d.json")
        data = db.dump_json(src, path)
        dst = temp_conn()
        db.upsert_app(dst, "com.a.a", title=None)  # eksik alan doldurulmalı
        counts = exporter.import_dump(dst, data)
        self.assertEqual(dst.execute("SELECT title FROM Apps WHERE package='com.a.a'").fetchone()[0], "Alpha")
        self.assertEqual(counts.get("SavedComparisons"), 1)
        exporter.import_dump(dst, data)  # ikinci içe aktarma yinelemeyi çoğaltmamalı
        self.assertEqual(dst.execute("SELECT COUNT(*) FROM SavedComparisons").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
