"""CSV/JSON dışa aktarma ve yedekten içe aktarma. Mevcut veriler içe aktarmada silinmez; yinelenenler atlanır."""
import csv
import io
import json


CSV_COLUMNS = [
    ("package", "Paket adı"), ("title", "Uygulama adı"), ("developer", "Geliştirici"), ("category", "Kategori"),
    ("play_url", "Google Play bağlantısı"), ("price_type", "Ücret türü"), ("has_ads", "Reklam kanıtı (1=var)"),
    ("has_iap", "Uygulama içi satın alma (1=var)"), ("rating", "Puan"), ("review_count_label", "Yorum sayısı (Play)"),
    ("download_label", "İndirme aralığı (Play)"), ("download_floor", "İndirme alt sınırı"),
    ("appbrain_installs_30d", "30 gün tahmini yükleme (AppBrain, tahmin)"),
    ("first_release_date", "İlk yayın (doğrulanmışsa)"), ("first_release_status", "İlk yayın durumu"),
    ("first_release_source", "İlk yayın kaynağı"), ("last_updated", "Son güncelleme"),
    ("last_updated_source", "Son güncelleme kaynağı"), ("opportunity", "Fırsat puanı (0-100)"),
    ("confidence", "Kanıt güveni"), ("revenue_status", "Gelir kanıtı durumu (1-4)"),
    ("complaint_share", "En yüksek tekil şikâyet oranı (analiz edilen yorumlarda)"),
    ("low_sample", "Düşük örneklem"), ("cluster_size", "Aynı kategorideki aday sayısı"),
    ("developer_app_count", "Geliştiricinin bu veritabanındaki uygulama sayısı"),
    ("rebrand_hint", "Yeniden markalama ipucu"), ("missing", "Eksik veriler"), ("stale", "Eski veri"),
    ("sources", "Kaynaklar (kaynak / tarih / bağlantı)"), ("last_checked_at", "Son kontrol"),
]


def _flat(view, key):
    if key == "missing":
        return "; ".join(view.get("missing") or [])
    if key == "sources":
        return " | ".join(f"{s['source']} / {s.get('date') or 'tarih yok'} / {s.get('url') or '-'}"
                          for s in view.get("sources", []))
    if key == "low_sample":
        return "evet" if view.get("low_sample") else "hayır"
    if key == "stale":
        return "evet" if view.get("stale") else "hayır"
    v = view.get(key)
    if isinstance(v, bool):
        return 1 if v else 0
    return "" if v is None else v


def views_to_csv(views):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([label for _, label in CSV_COLUMNS])
    for v in views:
        w.writerow([_flat(v, key) for key, _ in CSV_COLUMNS])
    return buf.getvalue()


def views_to_json(views, run=None, filters=None, explain=None):
    payload = {
        "run": run,
        "filters": filters,
        "filter_explanation": explain,
        "count": len(views),
        "note": "Fırsat puanı ve kanıt güveni ayrı değerlerdir. Tahmini alanlar kaynak adıyla işaretlidir.",
        "results": views,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def import_dump(conn, data):
    """db.dump_json çıktısını içe aktarır. Yinelenen doğal anahtarlar atlanır. Dönüş: sayılar sözlüğü."""
    tables = data.get("tables", data)
    counts = {}

    def cols(table):
        return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]

    def insert_ignore(table, row, skip=("id",)):
        c = [k for k in cols(table) if k in row and k not in skip]
        cur = conn.execute(f"INSERT OR IGNORE INTO {table} ({','.join(c)}) VALUES ({','.join('?' * len(c))})",
                           [row[k] for k in c])
        return cur.rowcount

    for r in tables.get("Sources", []):
        counts["Sources"] = counts.get("Sources", 0) + insert_ignore("Sources", r, skip=("id",))
    for r in tables.get("Developers", []):
        counts["Developers"] = counts.get("Developers", 0) + insert_ignore("Developers", r, skip=())
    for r in tables.get("Apps", []):
        exists = conn.execute("SELECT 1 FROM Apps WHERE package=?", (r["package"],)).fetchone()
        if not exists:
            counts["Apps"] = counts.get("Apps", 0) + insert_ignore("Apps", r, skip=())
        else:  # Eksik alanları doldur, mevcut dolu alanları ezme
            for k, v in r.items():
                if v is not None and k != "package":
                    conn.execute(f"UPDATE Apps SET {k}=? WHERE package=? AND {k} IS NULL", (v, r["package"]))
    for r in tables.get("AppSnapshots", []):
        dup = conn.execute("SELECT 1 FROM AppSnapshots WHERE package=? AND captured_at=?",
                           (r["package"], r["captured_at"])).fetchone()
        if not dup:
            counts["AppSnapshots"] = counts.get("AppSnapshots", 0) + insert_ignore("AppSnapshots", r, skip=("id", "source_id"))
    for r in tables.get("ReviewSamples", []):
        counts["ReviewSamples"] = counts.get("ReviewSamples", 0) + insert_ignore("ReviewSamples", r, skip=("id", "source_id"))
    for r in tables.get("RevenueEvidence", []):
        dup = conn.execute("SELECT 1 FROM RevenueEvidence WHERE package=? AND kind=? AND COALESCE(url,'')=COALESCE(?, '')",
                           (r["package"], r["kind"], r.get("url"))).fetchone()
        if not dup:
            counts["RevenueEvidence"] = counts.get("RevenueEvidence", 0) + insert_ignore(
                "RevenueEvidence", r, skip=("id", "source_id"))
    for r in tables.get("SavedComparisons", []):
        dup = conn.execute("SELECT 1 FROM SavedComparisons WHERE name=? AND created_at=?", (r["name"], r["created_at"])).fetchone()
        if not dup:
            counts["SavedComparisons"] = counts.get("SavedComparisons", 0) + insert_ignore("SavedComparisons", r)
    conn.commit()
    return counts
