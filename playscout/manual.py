"""Manuel veri işlemleri: yorum içe aktarma, gelir kanıtı ekleme, favori/karşılaştırma. Ağ kullanmaz."""
import json
import re

from . import db, reviews
from .revenue import DIRECT_KINDS

EVIDENCE_KINDS = DIRECT_KINDS | {"commercial_potential"}


def import_reviews(conn, package, fmt, content):
    rows, skipped = reviews.parse_import(content, fmt, package=package)
    if not rows:
        raise ValueError("İçe aktarılacak geçerli yorum bulunamadı (text/review sütunu gerekli).")
    if not db.get_app(conn, package):
        db.upsert_app(conn, package, play_url=f"https://play.google.com/store/apps/details?id={package}")
    added = db.add_reviews(conn, package, rows, db.MANUAL_SOURCE)
    return {"read": len(rows), "added": added, "duplicates_or_skipped": (len(rows) - added) + skipped}


def add_evidence(conn, package, kind, description, url, evidence_date=None):
    if kind not in EVIDENCE_KINDS:
        raise ValueError(f"Geçersiz kanıt türü. Seçenekler: {', '.join(sorted(EVIDENCE_KINDS))}")
    if kind in DIRECT_KINDS and not url:
        raise ValueError("Doğrudan gelir kanıtı için bir bağlantı (URL) zorunludur.")
    if url and not url.startswith("https://"):
        raise ValueError("Kanıt bağlantısı https:// ile başlamalıdır.")
    if evidence_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", evidence_date):
        raise ValueError("Kanıt tarihi YYYY-AA-GG biçiminde olmalıdır.")
    if not db.get_app(conn, package):
        db.upsert_app(conn, package)
    conn.execute(
        """INSERT INTO RevenueEvidence(package, kind, description, url, evidence_date, source_id, recorded_at)
           VALUES (?,?,?,?,?,?,?)""",
        (package, kind, description, url, evidence_date, db.source_id(conn, db.MANUAL_SOURCE), db.utc_now()))
    conn.commit()


def save_comparison(conn, name, packages, notes=None):
    packages = list(dict.fromkeys(p for p in packages if p))
    if not name.strip():
        raise ValueError("Karşılaştırma adı boş olamaz.")
    if len(packages) < 2:
        raise ValueError("Karşılaştırma için en az iki uygulama seçin.")
    cur = conn.execute("INSERT INTO SavedComparisons(name, packages_json, notes, created_at) VALUES (?,?,?,?)",
                       (name.strip(), json.dumps(packages), notes, db.utc_now()))
    conn.commit()
    return cur.lastrowid


def app_card(conn, package):
    """Detaylı rakip kartı: tüm alanlar, geçmiş, kaynaklar, yorum kategorileri, gelir kanıtları."""
    app = db.get_app(conn, package)
    if not app:
        return None
    snaps = [dict(r) for r in conn.execute(
        "SELECT captured_at, rating, review_count, download_floor, last_updated, installs_30d, total_installs, "
        "rank_text, source_url, (SELECT name FROM Sources s WHERE s.id=AppSnapshots.source_id) AS source "
        "FROM AppSnapshots WHERE package=? ORDER BY captured_at DESC LIMIT 50", (package,))]
    cats = [dict(r) for r in conn.execute(
        "SELECT * FROM ReviewIssueCategories WHERE package=? AND analyzed_at=(SELECT MAX(analyzed_at) FROM "
        "ReviewIssueCategories WHERE package=?) ORDER BY share DESC", (package, package))]
    evidence = [dict(r) for r in conn.execute("SELECT * FROM RevenueEvidence WHERE package=? ORDER BY recorded_at DESC",
                                              (package,))]
    rev_count = conn.execute("SELECT COUNT(*) FROM ReviewSamples WHERE package=?", (package,)).fetchone()[0]
    runs = [dict(r) for r in conn.execute(
        "SELECT r.id AS run_id, r.niche, r.created_at, s.opportunity, s.confidence FROM SearchRunApps s "
        "JOIN SearchRuns r ON r.id=s.run_id WHERE s.package=? ORDER BY r.created_at DESC LIMIT 20", (package,))]
    comps = [dict(r) for r in conn.execute("SELECT id, name FROM SavedComparisons")]
    in_comps = [c for c in comps if package in json.loads(conn.execute(
        "SELECT packages_json FROM SavedComparisons WHERE id=?", (c["id"],)).fetchone()[0])]
    return {
        "app": app, "snapshots": snaps, "review_categories": cats, "revenue_evidence": evidence,
        "review_sample_count": rev_count, "runs": runs, "comparisons": in_comps,
        "similar": _similar_from_runs(conn, package),
    }


def _similar_from_runs(conn, package):
    """Aynı kategorideki diğer kayıtlı uygulamalar (benzer rakip adayları)."""
    row = conn.execute("SELECT category FROM Apps WHERE package=?", (package,)).fetchone()
    if not row or not row[0]:
        return []
    rows = conn.execute("SELECT package, title, rating FROM Apps WHERE category=? AND package<>? LIMIT 10",
                        (row[0], package)).fetchall()
    return [dict(r) for r in rows]
