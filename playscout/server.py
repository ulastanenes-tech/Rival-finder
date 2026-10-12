"""Yerel HTTP sunucusu: web arayüzü + JSON API. Yalnızca standart kütüphane.

Tarayıcı yalnızca göreli URL'ler kullanır (/api/...). Varsayılan 127.0.0.1; kimlik doğrulaması yoktur,
bu yüzden 0.0.0.0 yalnızca güvenilir bir ağda veya önizleme ortamında kullanılmalıdır."""
import json
import mimetypes
import re
import threading
import traceback
import uuid
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__, config, db, exporter, filters as flt, keywords as kw, manual, pipeline, scoring, reviews
from .fetcher import Fetcher

JOBS = {}
JOBS_LOCK = threading.Lock()
SEARCH_LOCK = threading.Lock()  # aynı anda tek arama: nazik istek hızı
MAX_BODY = 5_000_000


def meta():
    return {
        "version": __version__,
        "presets": [{"value": v, "label": l} for v, l in [
            ("none", "Tarih filtresi yok"), ("1", "Son 1 ay"), ("2", "Son 2 ay"), ("3", "Son 3 ay"),
            ("6", "Son 6 ay"), ("9", "Son 9 ay"), ("12", "Son 12 ay"), ("24", "Son 24 ay"),
            ("custom", "Özel tarih aralığı")]],
        "download_thresholds": [1000, 5000, 10000, 50000, 100000, 500000, 1000000, 5000000,
                                10000000, 50000000, 100000000],
        "sorts": [{"value": k, "label": v[0]} for k, v in flt.SORTS.items()],
        "weights": config.DEFAULT_WEIGHTS,
        "weight_labels": scoring.COMPONENT_LABELS,
        "min_review_sample": config.MIN_REVIEW_SAMPLE,
        "new_app_months": config.NEW_APP_MONTHS,
        "sources": [{"name": n, "base": b, "purpose": p, "policy": pol} for n, b, p, pol in db.SOURCES],
        "review_categories": reviews.CATEGORY_LABELS_TR,
        "revenue_statuses": {1: "Doğrudan gelir kanıtı bulundu", 2: "Gelir modeli mevcut, gerçek gelir doğrulanmadı",
                             3: "Ticari potansiyel var, kanıt zayıf", 4: "Gelir hakkında yeterli veri yok"},
        "evidence_kinds": ["developer_disclosed", "reliable_report", "verifiable_product", "commercial_potential"],
        "limits": {"search_is_disabled": "Play ve AppBrain arama sayfaları robots.txt ile yasaklıdır; "
                                         "keşif tohum paket adları ve AppBrain 'benzer uygulamalar' bağlantılarıyla yapılır."},
    }


def _run_job(job_id, params):
    conn = db.connect()
    job = JOBS[job_id]

    def progress(stage, done, total, msg):
        job.update(stage=stage, done=done, total=total, message=msg)

    try:
        with SEARCH_LOCK:
            res = pipeline.run_search(conn, params, fetcher=Fetcher(conn, offline=bool(params.get("offline"))),
                                      progress=progress, today=date.today())
        job.update(state="done", result=res, message="Tamamlandı")
    except pipeline.RunError as e:
        job.update(state="error", error=str(e))
    except ValueError as e:
        job.update(state="error", error=str(e))
    except Exception as e:  # beklenmeyen hata: sunucu çökmez, iş raporlanır
        job.update(state="error", error=f"Beklenmeyen hata: {e}", trace=traceback.format_exc()[-1500:])
    finally:
        conn.close()


def run_results(conn, run_id, body):
    row = conn.execute("SELECT * FROM SearchRuns WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise LookupError("Araştırma bulunamadı.")
    run = dict(row)
    stats = json.loads(run["stats_json"] or "{}")
    filt = body.get("filters") or {}
    flt.validate_filters(filt)
    rows = conn.execute("SELECT score_json FROM SearchRunApps WHERE run_id=?", (run_id,)).fetchall()
    views = [json.loads(r[0]) for r in rows if r[0]]
    matched, explain = flt.apply(views, filt, today=date.today())
    sorted_views = flt.sort(matched, body.get("sort") or "opportunity")
    target = int(body.get("limit") or 50)
    shown = sorted_views[:target]
    unknown_dates = flt.apply_unknown_dates_note(matched)
    shortfall = None
    if len(matched) < target:
        if not views:
            msg = ("Bu araştırmada alakalı uygulama bulunamadı. Kaynak hatalarını ve tohum listesini kontrol edin; "
                   "tohum ekleyip yeniden tarayın veya çevrimdışı modda kayıtlı verileri analiz edin.")
        else:
            biggest = sorted(explain, key=lambda e: e["eliminated"], reverse=True)
            blockers = [f"{e['label']} ({e['eliminated']} elendi)" for e in biggest if e["eliminated"] > 0][:4]
            msg = (f"Hedef {target}; filtrelerinize uyan {len(matched)} uygulama bulundu. "
                   f"Sonucu daraltan filtreler: {', '.join(blockers) or 'yok (aday havuzu küçük)'}. "
                   "Tarih aralığını genişletmeyi veya indirme eşiğini düşürmeyi deneyebilirsiniz. "
                   "Kalan sonuçlar için daha fazla tohum eklemek gerekir; sistem sonuç sayısını uydurmaz.")
        shortfall = {"target": target, "found_matching": len(matched), "message": msg}
    return {
        "run": {"id": run["id"], "niche": run["niche"], "mode": run["mode"], "created_at": run["created_at"],
                "status": run["status"], "params": json.loads(run["params_json"] or "{}")},
        "stats": stats,
        "counts": {
            "candidates_found": stats.get("candidates_found", len(views)),
            "play_verified": stats.get("play_verified", 0),
            "relevant": len(views),
            "matching_filters": len(matched),
            "returned": len(shown),
            "unknown_first_release": unknown_dates,
        },
        "filter_explanation": explain,
        "shortfall": shortfall,
        "results": shown,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = f"PlayScout/{__version__}"

    def log_message(self, fmt, *args):  # sessiz günlük; hatalar JSON ile döner
        return

    # ---- yardımcılar
    def _json(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError("İstek gövdesi çok büyük.")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw or b"{}")
        except json.JSONDecodeError:
            raise ValueError("Geçersiz JSON.")

    def _file(self, path):
        target = (config.WEB_DIR / path).resolve()
        if config.WEB_DIR.resolve() not in target.parents and target != config.WEB_DIR.resolve():
            return self._json(HTTPStatus.FORBIDDEN, {"error": "erişim reddedildi"})
        if not target.is_file():
            return self._json(HTTPStatus.NOT_FOUND, {"error": "bulunamadı"})
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") or "javascript" in ctype else ""))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method):
        url = urlparse(self.path)
        path = url.path
        try:
            if method == "GET" and path in ("/", "/index.html"):
                return self._file("index.html")
            if method == "GET" and path.startswith("/static/"):
                return self._file(path[len("/static/"):])
            if not path.startswith("/api/"):
                return self._json(HTTPStatus.NOT_FOUND, {"error": "bulunamadı"})
            return self._api(method, path, parse_qs(url.query))
        except LookupError as e:
            self._json(HTTPStatus.NOT_FOUND, {"error": str(e)})
        except (ValueError, KeyError, TypeError) as e:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(e) or "Geçersiz istek"})
        except Exception as e:
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"Sunucu hatası: {e}"})

    def _api(self, method, path, query):
        conn = db.connect()
        try:
            if method == "GET" and path == "/api/health":
                return self._json(200, {"ok": True, "version": __version__, "db": str(config.DB_PATH)})
            if method == "GET" and path == "/api/keywords":
                niche = (query.get("niche") or [""])[0]
                mode = (query.get("mode") or ["exact"])[0]
                terms = kw.expand(niche, mode)
                return self._json(200, {"terms": [{"term": t, "origin": o} for t, o in terms],
                                        "broaden_preview": kw.broaden(kw.validate_niche(niche), 1)})
            if method == "GET" and path == "/api/meta":
                return self._json(200, meta())
            if method == "POST" and path == "/api/search":
                body = self._body()
                return self._start_search(body)
            m = re.fullmatch(r"/api/jobs/([\w-]+)", path)
            if method == "GET" and m:
                job = JOBS.get(m.group(1))
                if not job:
                    raise LookupError("İş bulunamadı.")
                return self._json(200, job)
            if method == "GET" and path == "/api/runs":
                rows = conn.execute("SELECT id, niche, mode, created_at, finished_at, status, stats_json FROM SearchRuns "
                                    "ORDER BY id DESC LIMIT 200").fetchall()
                out = []
                for r in rows:
                    d = dict(r)
                    st = json.loads(d.pop("stats_json") or "{}")
                    d["relevant_count"] = st.get("relevant_count")
                    d["candidates_found"] = st.get("candidates_found")
                    out.append(d)
                return self._json(200, {"runs": out})
            m = re.fullmatch(r"/api/runs/(\d+)/results", path)
            if method == "POST" and m:
                return self._json(200, run_results(conn, int(m.group(1)), self._body()))
            m = re.fullmatch(r"/api/runs/(\d+)/export", path)
            if method == "POST" and m:
                return self._export_run(conn, int(m.group(1)), self._body())
            m = re.fullmatch(r"/api/apps/([A-Za-z0-9_.]+)", path)
            if method == "GET" and m:
                card = manual.app_card(conn, m.group(1))
                if not card:
                    raise LookupError("Uygulama bulunamadı.")
                return self._json(200, card)
            m = re.fullmatch(r"/api/apps/([A-Za-z0-9_.]+)/favorite", path)
            if method == "POST" and m:
                body = self._body()
                conn.execute("UPDATE Apps SET is_favorite=? WHERE package=?", (1 if body.get("value") else 0, m.group(1)))
                conn.commit()
                return self._json(200, {"ok": True})
            m = re.fullmatch(r"/api/apps/([A-Za-z0-9_.]+)/reviews", path)
            if method == "POST" and m:
                body = self._body()
                res = manual.import_reviews(conn, m.group(1), body.get("format", "csv"), body.get("content", ""))
                return self._json(200, res)
            m = re.fullmatch(r"/api/apps/([A-Za-z0-9_.]+)/evidence", path)
            if method == "POST" and m:
                body = self._body()
                manual.add_evidence(conn, m.group(1), body.get("kind"), body.get("description") or "",
                                    body.get("url"), body.get("date"))
                return self._json(200, {"ok": True})
            if method == "GET" and path == "/api/comparisons":
                rows = [dict(r) for r in conn.execute("SELECT * FROM SavedComparisons ORDER BY id DESC")]
                for r in rows:
                    r["packages"] = json.loads(r.pop("packages_json"))
                return self._json(200, {"comparisons": rows})
            if method == "POST" and path == "/api/comparisons":
                body = self._body()
                cid = manual.save_comparison(conn, body.get("name", ""), body.get("packages", []), body.get("notes"))
                return self._json(200, {"id": cid})
            m = re.fullmatch(r"/api/comparisons/(\d+)", path)
            if method == "DELETE" and m:
                conn.execute("DELETE FROM SavedComparisons WHERE id=?", (int(m.group(1)),))
                conn.commit()
                return self._json(200, {"ok": True})
            if method == "GET" and path == "/api/sources":
                return self._json(200, {"sources": [dict(r) for r in conn.execute("SELECT * FROM Sources")]})
            if method == "GET" and path == "/api/backup":
                return self._json(200, db.dump_data(conn))
            if method == "POST" and path == "/api/import":
                body = self._body()
                return self._json(200, {"imported": exporter.import_dump(conn, body.get("tables", body))})
            return self._json(HTTPStatus.NOT_FOUND, {"error": "bilinmeyen API uç noktası"})
        finally:
            conn.close()

    def _start_search(self, body):
        niche = body.get("niche", "")
        kw.validate_niche(niche)  # hemen geri bildirim
        flt.validate_filters(body.get("filters") or {})
        job_id = uuid.uuid4().hex[:12]
        with JOBS_LOCK:
            if any(j.get("state") == "running" for j in JOBS.values()):
                return self._json(HTTPStatus.CONFLICT, {"error": "Zaten çalışan bir araştırma var; bitmesini bekleyin."})
            JOBS[job_id] = {"id": job_id, "state": "running", "stage": "start", "done": 0, "total": 0,
                            "message": "Başlatılıyor", "started": db.utc_now()}
        t = threading.Thread(target=_run_job, args=(job_id, body), daemon=True)
        t.start()
        return self._json(202, {"job_id": job_id})

    def _export_run(self, conn, run_id, body):
        res = run_results(conn, run_id, {**body, "limit": body.get("limit") or 100000})
        fmt = body.get("format", "csv")
        if fmt == "csv":
            data = exporter.views_to_csv(res["results"]).encode("utf-8-sig")
            ctype, ext = "text/csv; charset=utf-8", "csv"
        elif fmt == "json":
            data = exporter.views_to_json(res["results"], run=res["run"], filters=body.get("filters"),
                                          explain=res["filter_explanation"]).encode("utf-8")
            ctype, ext = "application/json; charset=utf-8", "json"
        else:
            raise ValueError("format csv veya json olmalıdır.")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="playscout-run-{run_id}.{ext}"')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_DELETE(self):
        self._handle("DELETE")


def make_server(host="127.0.0.1", port=8000):
    db.connect().close()  # şemayı oluştur
    return ThreadingHTTPServer((host, port), Handler)
