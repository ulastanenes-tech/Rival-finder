"""Komut satırı arayüzü: python -m playscout <komut>"""
import argparse
import json
import sys
from datetime import date

from . import config, db, exporter, manual, pipeline, reviews, server
from .fetcher import Fetcher, policy_check


def _print_summary(res):
    st = res["stats"]
    print(f"Durum: {res['status']}  (çalıştırma #{res['run_id']})")
    print(f"  Bulunan aday:            {st['candidates_found']}")
    print(f"  Play'de doğrulanan:      {st['play_verified']}")
    print(f"  Alakalı (sonuç havuzu):  {st['relevant_count']}")
    print(f"  Alaka dışı / veri yok:   {st['excluded']['alaka_uyumsuz']} / {st['excluded']['veri_yok']}")
    print(f"  Anahtar kelimeler:       {', '.join(st['keyword_terms'])}")
    if st.get("fallback"):
        print(f"  Geri dönüş:              {st['fallback']['message']} ({', '.join(st['fallback']['terms'])})")
    if st["source_errors"]:
        print(f"  Kaynak hataları ({len(st['source_errors'])}):")
        for e in st["source_errors"][:10]:
            print(f"    - {e['source']} / {e.get('package')}: {e['error']}")
    print(f"  İstek sayısı: {st['requests_made']}, süre: {st['duration_seconds']} sn")


def cmd_serve(a):
    srv = server.make_server(a.host, a.port)
    print(f"PlayScout {config.DB_PATH} üzerinde çalışıyor: http://{a.host}:{a.port}  (Ctrl+C ile durdurun)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def cmd_search(a):
    conn = db.connect()
    params = {"niche": a.niche, "mode": a.mode, "seeds": a.seeds or "", "offline": a.offline,
              "country": a.country, "expand_depth": a.expand, "max_candidates": a.max_candidates,
              "filters": json.loads(a.filters) if a.filters else {}}
    if a.keywords:
        params["keywords"] = [k.strip() for k in a.keywords.split(",") if k.strip()]
    try:
        res = pipeline.run_search(conn, params, fetcher=Fetcher(conn, offline=a.offline), progress=_progress)
    except ValueError as e:
        print(f"Hata: {e}", file=sys.stderr)
        return 2
    print()
    _print_summary(res)
    if a.out:
        from .server import run_results
        body = run_results(conn, res["run_id"], {"filters": params["filters"], "limit": a.limit})
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(exporter.views_to_json(body["results"], run=body["run"], filters=params["filters"],
                                           explain=body["filter_explanation"]))
        print(f"JSON yazıldı: {a.out}")
    return 0


def _progress(stage, done, total, msg):
    print(f"  [{stage}] {done}/{total} {msg}", file=sys.stderr)


def cmd_export(a):
    conn = db.connect()
    from .server import run_results
    body = run_results(conn, a.run, {"filters": json.loads(a.filters) if a.filters else {}, "limit": 100000})
    text = exporter.views_to_csv(body["results"]) if a.format == "csv" else \
        exporter.views_to_json(body["results"], run=body["run"], explain=body["filter_explanation"])
    if a.format == "csv":
        with open(a.out, "w", encoding="utf-8-sig", newline="") as f:
            f.write(text)
    else:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(f"{len(body['results'])} kayıt yazıldı: {a.out}")


def cmd_reviews(a):
    conn = db.connect()
    with open(a.file, encoding="utf-8") as f:
        content = f.read()
    fmt = "json" if a.file.lower().endswith(".json") else "csv"
    res = manual.import_reviews(conn, a.package, fmt, content)
    print(f"Okunan: {res['read']}, eklenen: {res['added']}, yinelenen/atlanan: {res['duplicates_or_skipped']}")
    rows = [dict(r) for r in conn.execute(
        "SELECT text, rating, review_date AS date, app_version AS version, source_url AS url FROM ReviewSamples "
        "WHERE package=?", (a.package,))]
    an = reviews.analyze(rows, as_of=date.today())
    print(f"Analiz edilen yorum: {an['sample_size']} {'(DÜŞÜK ÖRNEKLEM)' if an['low_sample'] else ''}")
    for cat, e in sorted(an["categories"].items(), key=lambda kv: -kv[1]["share"]):
        print(f"  {e['label']:<28} {e['mention_count']:>4}  (%{e['share'] * 100:.0f} of analiz edilen yorumlar)")


def cmd_backup(a):
    conn = db.connect()
    if a.restore:
        with open(a.restore, encoding="utf-8") as f:
            counts = exporter.import_dump(conn, json.load(f))
        print("İçe aktarıldı:", counts)
    else:
        db.dump_json(conn, a.out)
        print(f"Yedek yazıldı: {a.out}")


def cmd_doctor(a):
    """Yerel ortam ve kaynak erişimini kontrol eder. Yalnızca izinli tek bir sayfayı, düşük hızda açar."""
    print(f"Python {sys.version.split()[0]}")
    conn = db.connect()
    print(f"Veritabanı: {config.DB_PATH} (yazılabilir)")
    print("Politika kontrolü (robots.txt uyumu):")
    for u in ["https://play.google.com/store/apps/details?id=com.photoroom.app",
              "https://play.google.com/store/search?q=photo", "https://www.appbrain.com/app/com.photoroom.app",
              "https://www.appbrain.com/search?q=photo"]:
        bad = policy_check(u)
        print(f"  {'izinli ' if not bad else 'YASAK  '} {u}" + (f"  -> {bad}" if bad else ""))
    if a.network:
        f = Fetcher(conn, min_interval=config.MIN_INTERVAL_SECONDS)
        for name, url in [("Google Play detay", "https://play.google.com/store/apps/details?id=com.photoroom.app&hl=en&gl=US"),
                          ("AppBrain uygulama", "https://www.appbrain.com/app/com.photoroom.app")]:
            r = f.get(url, name, ttl=0, use_cache=False)
            print(f"  {name}: {'OK ' + str(r.status) if r.ok else 'HATA: ' + r.error}")
        print("  (Not: Bu, sayfa yapısının bugün ayrıştırılabildiğini de gösterir.)")
        from . import parsers
        if r.ok:
            d = parsers.parse_play_details(r.body, "com.photoroom.app")
            print(f"  Ayrıştırma: başlık={d.get('title')!r} puan={d.get('rating')} indirme={d.get('download_label')!r} "
                  f"son güncelleme={d.get('last_updated')}")
    else:
        print("Ağ kontrolü atlandı (--network ile çalıştırın).")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="playscout", description="Ücretsiz Google Play rakip araştırma aracı")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="Web arayüzünü başlat")
    s.add_argument("--host", default="127.0.0.1", help="Varsayılan yalnız bu bilgisayar. Ağa açmak için 0.0.0.0 (kimlik doğrulaması yoktur!)")
    s.add_argument("--port", type=int, default=8000)
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("search", help="Komut satırından araştırma çalıştır")
    s.add_argument("--niche", required=True)
    s.add_argument("--mode", choices=["exact", "discovery"], default="exact")
    s.add_argument("--seeds", help="Paket adları veya Play/AppBrain bağlantıları (boşlukla/virgülle)")
    s.add_argument("--keywords", help="Virgülle ayrılmış düzenlenmiş anahtar kelimeler")
    s.add_argument("--country", default="US")
    s.add_argument("--expand", type=int, default=1)
    s.add_argument("--max-candidates", type=int, default=40)
    s.add_argument("--offline", action="store_true", help="Yalnızca kayıtlı veriler")
    s.add_argument("--filters", help="JSON filtre nesnesi")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--out", help="JSON çıktı dosyası")
    s.set_defaults(fn=cmd_search)
    s = sub.add_parser("export", help="Bir araştırmayı CSV/JSON olarak dışa aktar")
    s.add_argument("--run", type=int, required=True)
    s.add_argument("--format", choices=["csv", "json"], default="csv")
    s.add_argument("--filters")
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_export)
    s = sub.add_parser("reviews", help="Manuel yorum dosyası (CSV/JSON) içe aktar ve analiz et")
    s.add_argument("--package", required=True)
    s.add_argument("--file", required=True)
    s.set_defaults(fn=cmd_reviews)
    s = sub.add_parser("backup", help="Tüm verileri JSON yedeğine al veya geri yükle")
    s.add_argument("--out", default="playscout-backup.json")
    s.add_argument("--restore")
    s.set_defaults(fn=cmd_backup)
    s = sub.add_parser("doctor", help="Ortam ve kaynak erişimi kontrolü")
    s.add_argument("--network", action="store_true", help="Gerçek ağ isteği yapar (tek sayfa)")
    s.set_defaults(fn=cmd_doctor)
    a = p.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
