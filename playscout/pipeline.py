"""Araştırma akışı. Her adım hata toleranslıdır: bir kaynak başarısız olursa rapor edilir, akış devam eder.

Akış:
 1. Anahtar kelimeler (Mod 1: tam eşleşme / Mod 2: niş keşfi) ve doğrulama
 2. Aday havuzu: kullanıcı tohumları + (opsiyonel) AppBrain 'alternatives' + daha önce kaydedilmiş uygulamalar
 3. Her aday için Play detay sayfası ve AppBrain sayfası (önbellekli, nazik, izinli yollar)
 4. Paket adına göre tekilleştirme, alaka filtresi, yorum/gelir analizi, fırsat puanı
 5. Çalıştırma kaydı (SearchRuns, SearchRunApps, Keywords, AppSnapshots)
"""
import difflib
import json
import time
from datetime import date

from . import config, db, filters as flt, keywords as kw, parsers, revenue, reviews, scoring
from .fetcher import Fetcher

PLAY = "Google Play detay sayfası"
APPBRAIN = "AppBrain uygulama sayfası"
MANUAL = "Manuel içe aktarma"
MAX_ALTERNATIVES_PER_SEED = 15
MAX_CANDIDATES_CAP = 200  # tek çalıştırmada en fazla bu kadar aday (nazik tarama)


class RunError(ValueError):
    """Kullanıcıya gösterilecek, düzeltilebilir girdi hataları."""


def play_url(pkg, country):
    return f"https://play.google.com/store/apps/details?id={pkg}&hl=en&gl={country}"


def appbrain_url(pkg):
    return f"https://www.appbrain.com/app/{pkg}"


def run_search(conn, params, fetcher=None, progress=None, today=None):
    today = today or date.today()
    started = time.time()
    progress = progress or (lambda stage, done, total, msg: None)
    log = []
    errors = []

    niche = kw.validate_niche(params.get("niche", ""))
    mode = params.get("mode", "exact")
    if mode not in ("exact", "discovery"):
        raise RunError("Mod 'exact' veya 'discovery' olmalıdır.")
    offline = bool(params.get("offline"))
    country = (params.get("country") or "US").upper()
    if not (len(country) == 2 and country.isalpha()):
        raise RunError("Ülke iki harfli ISO kodu olmalıdır (ör. US, TR).")
    weights = scoring.normalize_weights(params.get("weights"))
    flt.validate_filters(params.get("filters") or {})
    max_candidates = min(int(params.get("max_candidates") or 40), MAX_CANDIDATES_CAP)
    expand = int(params.get("expand_depth", 1 if mode == "discovery" else 0))
    if expand not in (0, 1):
        raise RunError("expand_depth 0 veya 1 olmalıdır (daha derin keşif izinli değildir).")

    # 1) Anahtar kelimeler
    user_terms = [t for t in (params.get("keywords") or []) if kw.norm(t)]
    if user_terms:
        terms = [(kw.norm(niche), "user")] + [(kw.norm(t), "user") for t in user_terms if kw.norm(t) != kw.norm(niche)]
    else:
        terms = kw.expand(niche, mode)
    seeds = parsers.extract_packages(params.get("seeds") or "")
    db_pkgs = [r["package"] for r in conn.execute("SELECT package FROM Apps").fetchall()]
    if not seeds and not db_pkgs:
        raise RunError("Google Play paket adı veya bağlantısı girin (ör. com.photoroom.app). "
                       "Arama kutusu Play/AppBrain arama sayfalarını kullanmaz; bunlar robots.txt ile yasaklıdır. "
                       "Veya çevrimdışı modda daha önce kaydedilmiş verileri analiz edin.")
    run_id = _create_run(conn, niche, mode, params, status="running")
    for term, origin in terms:
        conn.execute("INSERT OR IGNORE INTO Keywords(run_id, term, mode, origin) VALUES (?,?,?,?)",
                     (run_id, term, mode, origin))
    conn.commit()
    keyword_terms = terms

    fetcher = fetcher or Fetcher(conn, offline=offline)
    fetcher.offline = offline

    # 2) Aday havuzu
    pool = []  # (paket, köken)
    seen = set()

    def push(pkg, origin):
        if pkg not in seen:
            seen.add(pkg)
            pool.append((pkg, origin))

    for s in seeds:
        push(s, "seed")

    # AppBrain alternatifleri (tohumlardan 1 seviye). Çevrimdışıda yalnızca önbellek kullanılır.
    if expand >= 1:
        for i, s_pkg in enumerate(seeds):
            progress("expand", i, len(seeds), f"{s_pkg} için benzer uygulamalar (AppBrain)")
            res = fetcher.get(appbrain_url(s_pkg), APPBRAIN, config.CACHE_TTL_SECONDS["appbrain_app"])
            if not res.ok:
                errors.append({"source": APPBRAIN, "package": s_pkg, "error": res.error})
                continue
            ab = parsers.parse_appbrain_app(res.body, s_pkg)
            for alt in ab.get("alternatives", [])[:MAX_ALTERNATIVES_PER_SEED]:
                push(alt, "appbrain_alternative")

    for p in db_pkgs:  # kayıtlı veriler: aynı uygulamayı tekrar işlemek yerine tekilleştirilmiş havuza ekle
        push(p, "kayıtlı veri")

    pool = pool[:max_candidates] if max_candidates else pool
    candidates_found = len(pool)

    # 3) Veri toplama (her aday: Play + AppBrain)
    play_verified, relevant_packages, excluded = 0, [], {"alaka_uyumsuz": 0, "veri_yok": 0}
    for i, (pkg, origin) in enumerate(pool):
        progress("collect", i, len(pool), f"{pkg} ({i + 1}/{len(pool)})")
        if not offline:
            _collect_play(conn, fetcher, pkg, country, errors)
        if not offline:
            _collect_appbrain(conn, fetcher, pkg, errors)
        app = db.get_app(conn, pkg)
        if not app or not app.get("title"):
            excluded["veri_yok"] += 1
            db.upsert_app(conn, pkg, play_url=play_url(pkg, country))
            continue
        if app.get("play_status") == "verified":
            play_verified += 1
        # 4) Alaka
        rel_terms = _relevance_terms(keyword_terms, mode)
        score, matched = kw.relevance(rel_terms, app["title"], app.get("description") or "", app.get("description") or "",
                                      app.get("category"))
        ok = score >= 0.999 if mode == "exact" else score >= 0.5 or bool(matched)
        if not ok:
            excluded["alaka_uyumsuz"] += 1
            continue
        relevant_packages.append((pkg, origin, score))

    # Kontrollü geri dönüş: hiç alakalı yoksa daha geniş terimlerle yeniden değerlendir (ağ yok)
    fallback_used = None
    if not relevant_packages and params.get("allow_broaden", True):
        for level in range(1, kw.BROADEN_LEVELS + 1):
            broad = kw.broaden(niche, level)
            if not broad:
                break
            bterms = [(kw.norm(niche), "user")] + [(b, "fallback") for b in broad]
            found = []
            for pkg, _o in pool:
                app = db.get_app(conn, pkg)
                if not app or not app.get("title"):
                    continue
                s, m = kw.relevance(bterms, app["title"], app.get("description") or "", app.get("description") or "",
                                    app.get("category"))
                if s >= 0.5 or m:
                    found.append((pkg, "fallback", s))
            for b in broad:
                conn.execute("INSERT OR IGNORE INTO Keywords(run_id, term, mode, origin) VALUES (?,?,?,?)",
                             (run_id, b, mode, "fallback"))
            conn.commit()
            if found:
                relevant_packages = found
                excluded["alaka_uyumsuz"] = max(0, excluded["alaka_uyumsuz"] - len(found))
                fallback_used = {"level": level, "terms": broad,
                                 "message": "Tam eşleşme bulunamadı; daha geniş terimlerle sonuç gösteriliyor."}
                break

    # 5) Analiz + puanlama
    analyses, revenues, views = {}, {}, {}
    for pkg, origin, rel in relevant_packages:
        app = db.get_app(conn, pkg)
        rev_rows = [dict(r) for r in conn.execute("SELECT * FROM RevenueEvidence WHERE package=?", (pkg,))]
        rv_list = [dict(r) for r in conn.execute(
            "SELECT text, rating, review_date AS date, app_version AS version, source_url AS url FROM ReviewSamples WHERE package=?",
            (pkg,))]
        analyses[pkg] = reviews.analyze(rv_list, as_of=today)
        appbrain_rank = app.get("appbrain_rank")
        revenues[pkg] = revenue.classify(app, rev_rows, appbrain_rank)
        if analyses[pkg]["sample_size"]:
            _store_category_rows(conn, pkg, analyses[pkg], today)
        views[pkg] = {"origin": origin, "relevance": rel, "app": app}

    by_cat = {}
    for pkg, v in views.items():
        by_cat.setdefault((v["app"].get("category") or "").lower(), []).append(pkg)

    results = []
    for pkg, v in views.items():
        app = v["app"]
        cat_key = (app.get("category") or "").lower()
        cluster = by_cat.get(cat_key, [pkg]) if cat_key else [pkg]
        peers = []
        for other in views:
            if other == pkg:
                continue
            if cat_key and other in cluster:
                oa = views[other]["app"]
                an = analyses.get(other) or {}
                peers.append({"package": other, "rating": oa.get("rating"),
                              "complaint_share": reviews.complaint_share(an) if an.get("sample_size") else None})
        dev_count = conn.execute("SELECT COUNT(*) FROM Apps WHERE developer_key=?",
                                 (app.get("developer_key"),)).fetchone()[0] if app.get("developer_key") else 0
        rebrand = _rebrand_hint(conn, app)
        growing = _growing(conn, pkg, app)
        sc = scoring.score_app(app, analyses[pkg], revenues[pkg], peers, weights, today=today)
        view = _build_view(app, analyses[pkg], revenues[pkg], sc, v, cluster_size=len(cluster),
                           developer_app_count=dev_count, growing=growing, rebrand=rebrand)
        results.append(view)
        db.upsert_app(conn, pkg, rebrand_hint=rebrand)
        conn.execute(
            """INSERT OR REPLACE INTO SearchRunApps(run_id, package, origin, relevance, opportunity, confidence,
               revenue_status, score_json) VALUES (?,?,?,?,?,?,?,?)""",
            (run_id, pkg, v["origin"], v["relevance"], sc["opportunity"], sc["confidence"], revenues[pkg]["status"],
             json.dumps(view, ensure_ascii=False, default=str)))
    conn.commit()

    stats = {
        "candidates_found": candidates_found,
        "play_verified": play_verified,
        "relevant_count": len(results),
        "excluded": excluded,
        "keyword_terms": [t for t, _ in keyword_terms],
        "fallback": fallback_used,
        "requests_made": getattr(fetcher, "requests_made", 0),
        "source_errors": errors[:50],
        "offline": offline,
        "duration_seconds": round(time.time() - started, 1),
        "as_of": today.isoformat(),
        "not_relevant_note": "Alaka filtresi dışında kalan adaylar sonuçta gösterilmez.",
    }
    if errors:
        status = "completed_with_errors"
    elif not results:
        status = "no_results"
    else:
        status = "completed"
    _finish_run(conn, run_id, status, stats, log)
    progress("done", len(pool), len(pool), "Tamamlandı")
    return {"run_id": run_id, "status": status, "stats": stats}


def _relevance_terms(keyword_terms, mode):
    if mode == "exact":
        return keyword_terms[:1]
    return keyword_terms


def _create_run(conn, niche, mode, params, status):
    safe = {k: v for k, v in params.items() if k not in ("weights",)}
    cur = conn.execute(
        "INSERT INTO SearchRuns(created_at, niche, mode, params_json, status) VALUES (?,?,?,?,?)",
        (db.utc_now(), niche, mode, json.dumps(safe, ensure_ascii=False, default=str), status))
    conn.commit()
    return cur.lastrowid


def _finish_run(conn, run_id, status, stats, log):
    conn.execute("UPDATE SearchRuns SET status=?, stats_json=?, log_json=?, finished_at=? WHERE id=?",
                 (status, json.dumps(stats, ensure_ascii=False, default=str),
                  json.dumps(log, ensure_ascii=False), db.utc_now(), run_id))
    conn.commit()


def _collect_play(conn, fetcher, pkg, country, errors):
    url = play_url(pkg, country)
    res = fetcher.get(url, PLAY, config.CACHE_TTL_SECONDS["play_details"])
    if not res.ok:
        errors.append({"source": PLAY, "package": pkg, "error": res.error})
        db.mark_source(conn, PLAY, ok=False, error=res.error)
        db.upsert_app(conn, pkg, play_status="error", play_error=res.error, last_checked_at=db.utc_now())
        return
    d = parsers.parse_play_details(res.body, pkg)
    if not d.get("_usable"):
        msg = "Play sayfası ayrıştırılamadı veya uygulama bulunamadı" + (" (bot koruması işareti)" if d.get("_bot_block") else "")
        errors.append({"source": PLAY, "package": pkg, "error": msg})
        db.upsert_app(conn, pkg, play_status="error", play_error=msg, last_checked_at=db.utc_now())
        return
    dev_key = db.upsert_developer(conn, d.get("developer_name"), d.get("developer_play_id"))
    fields = {
        "title": d.get("title"), "developer_key": dev_key, "developer_name": d.get("developer_name"),
        "category": d.get("category"), "play_url": url, "icon_url": d.get("icon_url"),
        "description": d.get("description"), "price_type": d.get("price_type"), "price_text": d.get("price_text"),
        "has_ads": d.get("has_ads"), "has_iap": d.get("has_iap"), "rating": d.get("rating"),
        "review_count": d.get("review_count"), "review_count_label": d.get("review_count_label"),
        "download_floor": d.get("download_floor"), "download_label": d.get("download_label"),
        "last_updated": d.get("last_updated"), "last_updated_source": PLAY if d.get("last_updated") else None,
        "play_status": "verified", "play_error": None, "last_checked_at": db.utc_now(),
    }
    db.upsert_app(conn, pkg, **fields)
    db.mark_source(conn, PLAY, ok=True)
    if not res.from_cache:
        db.add_snapshot(conn, pkg, PLAY, rating=d.get("rating"), review_count=d.get("review_count"),
                        download_floor=d.get("download_floor"), last_updated=d.get("last_updated"),
                        source_url=url)


def _collect_appbrain(conn, fetcher, pkg, errors):
    url = appbrain_url(pkg)
    res = fetcher.get(url, APPBRAIN, config.CACHE_TTL_SECONDS["appbrain_app"])
    if not res.ok:
        errors.append({"source": APPBRAIN, "package": pkg, "error": res.error})
        db.mark_source(conn, APPBRAIN, ok=False, error=res.error)
        return
    ab = parsers.parse_appbrain_app(res.body, pkg)
    if not ab.get("_usable"):
        return
    fields = {
        "appbrain_installs_30d": ab.get("installs_30d"),
        "appbrain_total_installs": ab.get("total_installs"),
        "appbrain_rank": ab.get("rank_text"),
        "appbrain_data_date": ab.get("data_date"),
    }
    if ab.get("first_release_date"):
        fields.update(first_release_date=ab["first_release_date"], first_release_precision=ab["first_release_precision"],
                      first_release_source=f"{APPBRAIN} ('On Google Play since', ay hassasiyeti)",
                      first_release_status="verified")
    app = db.get_app(conn, pkg) or {}
    if not app.get("last_updated") and ab.get("last_updated"):
        fields.update(last_updated=ab["last_updated"], last_updated_source=APPBRAIN)
    db.upsert_app(conn, pkg, **fields)
    db.mark_source(conn, APPBRAIN, ok=True)
    if not res.from_cache:
        db.add_snapshot(conn, pkg, APPBRAIN, installs_30d=ab.get("installs_30d"),
                        total_installs=ab.get("total_installs"), rank_text=ab.get("rank_text"), source_url=url,
                        last_updated=ab.get("last_updated"))


def _store_category_rows(conn, pkg, analysis, today):
    now = db.utc_now()
    conn.execute("DELETE FROM ReviewIssueCategories WHERE package=? AND analyzed_at=?", (pkg, now))
    for cat, e in analysis["categories"].items():
        conn.execute(
            """INSERT INTO ReviewIssueCategories(package, analyzed_at, category, sample_size, mention_count, share,
               mentions_30d, mentions_prev_30d, mentions_90d, mentions_prev_90d, mentions_180d, mentions_prev_180d,
               top_version, example_urls_json, low_sample) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pkg, now, cat, analysis["sample_size"], e["mention_count"], e["share"],
             e["mentions_30d"], e["mentions_prev_30d"], e["mentions_90d"], e["mentions_prev_90d"],
             e["mentions_180d"], e["mentions_prev_180d"], e["top_version"],
             json.dumps(e["example_urls"], ensure_ascii=False), int(analysis["low_sample"])))
    conn.commit()


def _rebrand_hint(conn, app):
    dk = app.get("developer_key")
    t = (app.get("title") or "").lower()
    if not dk or not t:
        return None
    for r in conn.execute("SELECT package, title FROM Apps WHERE developer_key=? AND package<>?",
                          (dk, app["package"])):
        other = (r["title"] or "").lower()
        if other and difflib.SequenceMatcher(None, t, other).ratio() >= 0.8:
            return f"Aynı geliştiricinin benzer adlı paketi var: {r['package']} (olası yeniden markalama; doğrulanmadı)"
    return None


def _growing(conn, pkg, app):
    rows = conn.execute("SELECT download_floor, installs_30d, total_installs FROM AppSnapshots WHERE package=? "
                        "ORDER BY captured_at DESC LIMIT 2", (pkg,)).fetchall()
    total = app.get("appbrain_total_installs")
    inst = app.get("appbrain_installs_30d")
    if total and inst and inst / total >= 0.03:
        return True
    if len(rows) == 2 and rows[0]["download_floor"] and rows[1]["download_floor"]:
        return rows[0]["download_floor"] > rows[1]["download_floor"]
    return None


def _build_view(app, analysis, rev, sc, v, cluster_size, developer_app_count, growing, rebrand):
    cs = reviews.complaint_share(analysis) if analysis.get("sample_size") else None
    src = [{"source": PLAY, "date": app.get("last_checked_at"), "url": app.get("play_url"), "status": app.get("play_status")}]
    if app.get("appbrain_data_date") or app.get("appbrain_total_installs"):
        src.append({"source": APPBRAIN, "date": app.get("appbrain_data_date"),
                    "url": appbrain_url(app["package"]), "status": "verified"})
    if analysis.get("sample_size"):
        src.append({"source": "Manuel içe aktarma (yorumlar)", "date": analysis.get("newest_review_date"),
                    "url": None, "status": f"{analysis['sample_size']} yorum"})
    missing = list(dict.fromkeys(sc["missing"] + [f"revenue: {m}" for m in rev.get("missing", [])]))
    return {
        "package": app["package"],
        "title": app.get("title"),
        "developer": app.get("developer_name"),
        "developer_key": app.get("developer_key"),
        "category": app.get("category"),
        "play_url": app.get("play_url"),
        "icon_url": app.get("icon_url"),
        "description": (app.get("description") or "")[:600],
        "price_type": app.get("price_type"),
        "price_text": app.get("price_text"),
        "has_ads": app.get("has_ads"),
        "has_iap": app.get("has_iap"),
        "has_subscription": app.get("has_subscription"),
        "rating": app.get("rating"),
        "review_count": app.get("review_count"),
        "review_count_label": app.get("review_count_label"),
        "download_floor": app.get("download_floor"),
        "download_label": app.get("download_label"),
        "appbrain_installs_30d": app.get("appbrain_installs_30d"),
        "appbrain_total_installs": app.get("appbrain_total_installs"),
        "appbrain_rank": app.get("appbrain_rank"),
        "first_release_date": app.get("first_release_date"),
        "first_release_precision": app.get("first_release_precision"),
        "first_release_status": app.get("first_release_status") or "unknown",
        "first_release_source": app.get("first_release_source"),
        "last_updated": app.get("last_updated"),
        "last_updated_source": app.get("last_updated_source"),
        "play_status": app.get("play_status"),
        "play_error": app.get("play_error"),
        "last_checked_at": app.get("last_checked_at"),
        "origin": v["origin"],
        "relevance": v["relevance"],
        "opportunity": sc["opportunity"],
        "components": sc["components"],
        "confidence": sc["confidence"],
        "evidence_fields": sc["evidence_fields"],
        "missing": missing,
        "revenue_status": rev["status"],
        "revenue": rev,
        "analysis": {
            "sample_size": analysis.get("sample_size", 0),
            "low_sample": analysis.get("low_sample", True),
            "mean_rating": analysis.get("mean_rating"),
            "low_star_share": analysis.get("low_star_share"),
            "stale": analysis.get("stale"),
            "note": analysis.get("note"),
            "categories": analysis.get("categories", {}),
            "top_complaints": reviews.top_complaints(analysis),
        },
        "complaint_share": cs,
        "low_sample": analysis.get("low_sample", True),
        "low_star_share": analysis.get("low_star_share"),
        "cluster_size": cluster_size,
        "developer_app_count": developer_app_count,
        "growing": growing,
        "rebrand_hint": rebrand,
        "sources": src,
        "stale": _is_stale(app.get("last_checked_at")),
    }


def _is_stale(ts):
    if not ts:
        return True
    from datetime import datetime, timezone
    try:
        t = datetime.fromisoformat(ts)
    except ValueError:
        return True
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).days > config.STALE_DAYS
