import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from playscout import config, server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_db = config.DB_PATH
        config.DB_PATH = type(config.DB_PATH)(os.path.join(tempfile.mkdtemp(), "srv.db"))
        cls.httpd = server.make_server("127.0.0.1", 0)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        config.DB_PATH = cls._orig_db

    def req(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(self.base + path, data=data, method=method,
                                   headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                return resp.status, (json.loads(raw) if "json" in ctype else raw.decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def test_index_and_static(self):
        status, body = self.req("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("PlayScout", body)
        status, _ = self.req("GET", "/static/app.js")
        self.assertEqual(status, 200)

    def test_path_traversal_blocked(self):
        status, _ = self.req("GET", "/static/../playscout/config.py")
        self.assertIn(status, (403, 404))

    def test_health_and_meta(self):
        self.assertEqual(self.req("GET", "/api/health")[1]["ok"], True)
        meta = self.req("GET", "/api/meta")[1]
        self.assertEqual(len(meta["download_thresholds"]), 11)
        self.assertIn("6", [p["value"] for p in meta["presets"]])

    def test_validation_errors_are_400_with_turkish_message(self):
        status, body = self.req("POST", "/api/search", {"niche": "!!!"})
        self.assertEqual(status, 400)
        self.assertIn("harf", body["error"])
        status, body = self.req("POST", "/api/runs/1/results", {"filters": {"min_rating": 9}})
        self.assertIn(status, (400, 404))

    def test_bad_json_and_unknown_routes(self):
        r = urllib.request.Request(self.base + "/api/comparisons", data=b"{bad", method="POST",
                                   headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(r, timeout=10)
        self.assertEqual(cm.exception.code, 400)
        self.assertEqual(self.req("GET", "/api/unknown")[0], 404)

    def test_empty_seed_offline_search_returns_clear_result(self):
        status, body = self.req("POST", "/api/search", {"niche": "AI photo editor", "mode": "exact",
                                                        "seeds": "com.example.none", "offline": True})
        self.assertEqual(status, 202)
        import time
        for _ in range(100):
            _, job = self.req("GET", f"/api/jobs/{body['job_id']}")
            if job["state"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(job["state"], "done")
        run_id = job["result"]["run_id"]
        status, res = self.req("POST", f"/api/runs/{run_id}/results", {"filters": {}, "limit": 25})
        self.assertEqual(status, 200)
        self.assertEqual(res["counts"]["matching_filters"], 0)
        self.assertIn("alakalı", res["shortfall"]["message"])

    def test_comparison_and_favorite_roundtrip(self):
        self.assertEqual(self.req("POST", "/api/comparisons", {"name": "x", "packages": ["com.a.a"]})[0], 400)
        status, body = self.req("POST", "/api/comparisons", {"name": "A/B", "packages": ["com.a.a", "com.b.b"]})
        self.assertEqual(status, 200)
        comps = self.req("GET", "/api/comparisons")[1]["comparisons"]
        self.assertEqual(comps[0]["packages"], ["com.a.a", "com.b.b"])
        self.assertEqual(self.req("DELETE", f"/api/comparisons/{body['id']}")[0], 200)

    def test_backup_endpoint(self):
        status, body = self.req("GET", "/api/backup")
        self.assertEqual(status, 200)
        self.assertIn("Apps", body["tables"])


if __name__ == "__main__":
    unittest.main()
