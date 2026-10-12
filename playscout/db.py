"""Yerel SQLite veri katmanı. Geçmiş kayıtlar silinmez; her değişiklik zaman damgalıdır."""
import json
import pathlib
import sqlite3
from datetime import datetime, timezone

from . import config

SCHEMA_VERSION = 1
MANUAL_SOURCE = "Manuel içe aktarma"

SCHEMA = """
CREATE TABLE IF NOT EXISTS Sources (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    base_url TEXT,
    purpose TEXT,
    robots_policy TEXT,
    last_checked_at TEXT,
    last_ok_at TEXT,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS Developers (
    developer_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    play_developer_id TEXT,
    play_url TEXT,
    last_seen_at TEXT
);
CREATE TABLE IF NOT EXISTS Apps (
    package TEXT PRIMARY KEY,
    title TEXT,
    developer_key TEXT,
    developer_name TEXT,
    category TEXT,
    play_url TEXT,
    icon_url TEXT,
    description TEXT,
    price_type TEXT,           -- free | paid | unknown
    price_text TEXT,
    has_ads INTEGER,           -- 1 | NULL (kanıt yok/bilinmiyor)
    has_iap INTEGER,
    has_subscription INTEGER,
    rating REAL,
    review_count INTEGER,      -- Play'in gösterdiği yaklaşık sayı (ör. 54.2M)
    review_count_label TEXT,
    download_floor INTEGER,    -- Play aralığının alt sınırı (ör. 1000000+ -> 1000000)
    download_label TEXT,
    last_updated TEXT,         -- SON GÜNCELLEME (ilk yayın değil)
    last_updated_source TEXT,
    first_release_date TEXT,   -- İLK YAYIN (ISO); yalnızca doğrulanmışsa dolu
    first_release_precision TEXT, -- day | month | NULL
    first_release_source TEXT,
    first_release_status TEXT NOT NULL DEFAULT 'unknown', -- verified | unknown
    appbrain_installs_30d INTEGER,  -- AppBrain TAHMİNİ
    appbrain_total_installs INTEGER,-- AppBrain TAHMİNİ
    appbrain_rank TEXT,
    appbrain_data_date TEXT,
    rebrand_hint TEXT,
    is_favorite INTEGER NOT NULL DEFAULT 0,
    first_seen_at TEXT,
    last_checked_at TEXT,
    play_status TEXT,          -- verified | error | not_fetched
    play_error TEXT
);
CREATE TABLE IF NOT EXISTS SearchRuns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    niche TEXT NOT NULL,
    mode TEXT NOT NULL,
    params_json TEXT NOT NULL,
    status TEXT NOT NULL,
    stats_json TEXT,
    log_json TEXT
);
CREATE TABLE IF NOT EXISTS Keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES SearchRuns(id) ON DELETE CASCADE,
    term TEXT NOT NULL,
    mode TEXT NOT NULL,
    origin TEXT NOT NULL,      -- user | generated_synonym | generated_subniche | generated_modifier | fallback
    UNIQUE(run_id, term)
);
CREATE TABLE IF NOT EXISTS SearchRunApps (
    run_id INTEGER NOT NULL REFERENCES SearchRuns(id) ON DELETE CASCADE,
    package TEXT NOT NULL REFERENCES Apps(package),
    origin TEXT,               -- seed | appbrain_alternative | manual_import
    relevance REAL,
    opportunity REAL,
    confidence TEXT,
    revenue_status INTEGER,
    score_json TEXT,
    PRIMARY KEY (run_id, package)
);
CREATE TABLE IF NOT EXISTS AppSnapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package TEXT NOT NULL REFERENCES Apps(package),
    captured_at TEXT NOT NULL,
    source_id INTEGER REFERENCES Sources(id),
    rating REAL,
    review_count INTEGER,
    download_floor INTEGER,
    last_updated TEXT,
    installs_30d INTEGER,
    total_installs INTEGER,
    rank_text TEXT,
    source_url TEXT
);
CREATE TABLE IF NOT EXISTS ReviewSamples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package TEXT NOT NULL REFERENCES Apps(package),
    review_hash TEXT NOT NULL,
    text TEXT NOT NULL,
    rating INTEGER,
    review_date TEXT,
    app_version TEXT,
    language TEXT,
    source_url TEXT,
    source_id INTEGER REFERENCES Sources(id),
    imported_at TEXT NOT NULL,
    UNIQUE(package, review_hash)
);
CREATE TABLE IF NOT EXISTS ReviewIssueCategories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package TEXT NOT NULL REFERENCES Apps(package),
    analyzed_at TEXT NOT NULL,
    category TEXT NOT NULL,
    sample_size INTEGER NOT NULL,
    mention_count INTEGER NOT NULL,
    share REAL NOT NULL,
    mentions_30d INTEGER, mentions_prev_30d INTEGER,
    mentions_90d INTEGER, mentions_prev_90d INTEGER,
    mentions_180d INTEGER, mentions_prev_180d INTEGER,
    top_version TEXT,
    example_urls_json TEXT,
    low_sample INTEGER NOT NULL DEFAULT 1,
    cross_rival_repeat INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS RevenueEvidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package TEXT NOT NULL REFERENCES Apps(package),
    kind TEXT NOT NULL,        -- developer_disclosed | reliable_report | verifiable_product | commercial_potential
    description TEXT,
    url TEXT,
    evidence_date TEXT,
    source_id INTEGER REFERENCES Sources(id),
    recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS SavedComparisons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    packages_json TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS HttpCache (
    url TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    status INTEGER,
    body TEXT,
    source_name TEXT
);
CREATE INDEX IF NOT EXISTS idx_snap_pkg ON AppSnapshots(package, captured_at);
CREATE INDEX IF NOT EXISTS idx_rev_pkg ON ReviewSamples(package);
CREATE INDEX IF NOT EXISTS idx_runapps ON SearchRunApps(run_id);
"""

SOURCES = [
    ("Google Play detay sayfası", "https://play.google.com/store/apps/details",
     "Uygulama adı, paket, geliştirici, puan, yorum sayısı, indirme aralığı, son güncelleme, ücret/reklam/IAP işaretleri",
     "İzinli: /store/apps/details. Arama (/store/search) ve yorum uç noktaları (/store/getreviews, /store/xhr) YASAKLI, kullanılmaz."),
    ("AppBrain uygulama sayfası", "https://www.appbrain.com/app/",
     "İlk yayın ayı (\"On Google Play since\"), son güncelleme, 30 gün tahmini yükleme, benzer uygulamalar",
     "İzinli: /app/<paket>. /search ve /app_details/ YASAKLI, kullanılmaz. Tahminler AppBrain'e aittir."),
    ("Manuel içe aktarma", "local",
     "Kullanıcının kendi dışa aktardığı yorumlar, paket listeleri ve gelir kanıtları",
     "Otomatik toplama yapılmaz; kullanıcı veriyi kendisi sağlar ve kaynağını belirtir."),
]


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(path=None):
    path = pathlib.Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    init(conn)
    return conn


def init(conn):
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    for name, base, purpose, policy in SOURCES:
        conn.execute(
            "INSERT OR IGNORE INTO Sources(name, base_url, purpose, robots_policy) VALUES (?,?,?,?)",
            (name, base, purpose, policy),
        )
    conn.commit()


def source_id(conn, name):
    row = conn.execute("SELECT id FROM Sources WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    conn.execute("INSERT INTO Sources(name) VALUES (?)", (name,))
    return conn.execute("SELECT id FROM Sources WHERE name=?", (name,)).fetchone()["id"]


def mark_source(conn, name, ok, error=None):
    now = utc_now()
    conn.execute("UPDATE Sources SET last_checked_at=?, last_error=? WHERE name=?", (now, error, name))
    if ok:
        conn.execute("UPDATE Sources SET last_ok_at=? WHERE name=?", (now, name))
    conn.commit()


def upsert_app(conn, package, **fields):
    """Yalnızca verilen alanları günceller; verilmeyen (None olmayan) mevcut değerleri silmez."""
    now = utc_now()
    clean = {k: v for k, v in fields.items() if v is not None}
    row = conn.execute("SELECT package FROM Apps WHERE package=?", (package,)).fetchone()
    if row is None:
        clean.setdefault("first_seen_at", now)
        clean["package"] = package
        cols = ",".join(clean)
        qs = ",".join("?" for _ in clean)
        conn.execute(f"INSERT INTO Apps ({cols}) VALUES ({qs})", list(clean.values()))
    elif clean:
        sets = ",".join(f"{k}=?" for k in clean)
        conn.execute(f"UPDATE Apps SET {sets} WHERE package=?", list(clean.values()) + [package])
    conn.commit()


def upsert_developer(conn, name, play_developer_id=None, play_url=None):
    if not name:
        return None
    key = name.strip().lower()
    conn.execute(
        """INSERT INTO Developers(developer_key, name, play_developer_id, play_url, last_seen_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(developer_key) DO UPDATE SET
             name=excluded.name,
             play_developer_id=COALESCE(excluded.play_developer_id, Developers.play_developer_id),
             play_url=COALESCE(excluded.play_url, Developers.play_url),
             last_seen_at=excluded.last_seen_at""",
        (key, name.strip(), play_developer_id, play_url, utc_now()),
    )
    return key


def add_snapshot(conn, package, source_name, rating=None, review_count=None, download_floor=None,
                 last_updated=None, installs_30d=None, total_installs=None, rank_text=None, source_url=None):
    conn.execute(
        """INSERT INTO AppSnapshots(package, captured_at, source_id, rating, review_count, download_floor,
           last_updated, installs_30d, total_installs, rank_text, source_url)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (package, utc_now(), source_id(conn, source_name), rating, review_count, download_floor,
         last_updated, installs_30d, total_installs, rank_text, source_url),
    )
    conn.commit()


def add_reviews(conn, package, reviews, source_name):
    """reviews: dict listesi (text, rating, date, version, language, url). Tekrarlar atlanır."""
    from .reviews import review_hash
    sid = source_id(conn, source_name)
    added = 0
    for r in reviews:
        text = (r.get("text") or "").strip()
        if not text:
            continue
        cur = conn.execute(
            """INSERT OR IGNORE INTO ReviewSamples(package, review_hash, text, rating, review_date,
               app_version, language, source_url, source_id, imported_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (package, review_hash(text), text, r.get("rating"), r.get("date"), r.get("version"),
             r.get("language"), r.get("url"), sid, utc_now()),
        )
        added += cur.rowcount
    conn.commit()
    return added


def row_dict(row):
    return dict(row) if row is not None else None


def get_app(conn, package):
    return row_dict(conn.execute("SELECT * FROM Apps WHERE package=?", (package,)).fetchone())


def dump_data(conn):
    """Veritabanının tamamını (HttpCache hariç) sözlük olarak döndürür."""
    tables = ["Sources", "Developers", "Apps", "SearchRuns", "Keywords", "SearchRunApps", "AppSnapshots",
              "ReviewSamples", "ReviewIssueCategories", "RevenueEvidence", "SavedComparisons"]
    return {"schema_version": SCHEMA_VERSION, "exported_at": utc_now(),
            "tables": {t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}").fetchall()] for t in tables}}


def dump_json(conn, path):
    data = dump_data(conn)
    pathlib.Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data
