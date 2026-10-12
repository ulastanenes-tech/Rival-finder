"""Kullanıcı yorumu analiz motoru (kural tabanlı, TR+EN). Oranlar YALNIZCA analiz edilen yorumların
içindeki oranlardır; tüm kullanıcıların oranı gibi sunulmaz.

Yorumlar yalnızca manuel içe aktarma (CSV/JSON) ile gelir. Play yorum uç noktaları robots.txt'de
yasaklıdır ve kullanılmaz."""
import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import date, datetime, timedelta

from . import config

CATEGORIES = {
    "crashes_bugs": r"crash|crashes|crashing|force close|freez|bug|buggy|glitch|error|not working|doesn'?t work|"
                    r"won'?t open|stuck|black screen|hata|çöküyor|çöktü|çök|donuyor|donma|açılmıyor|bozuk|çalışmıyor",
    "ads": r"\bads?\b|advert|commercial|pop-?ups?|reklam",
    "pricing_subscription": r"subscri|paywall|expensive|pricey|overpriced|price|cost|charg|refund|paid|money|"
                            r"abonelik|pahalı|ücret|para|ödeme|kredi|üyelik",
    "missing_features": r"missing|no option|wish|please add|add (?:a |an )?(?:feature|option)|lack|need(?:s)? (?:a |an )?feature|"
                        r"eksik|keşke|özellik ekle|olsaydı|yok\b|no way to",
    "usability": r"confus|complicat|hard to use|difficult|unintuitive|user.?friendly|interface|hard to find|"
                 r"karmaşık|zor|anlaşılmaz|kullanışsız",
    "performance": r"slow|lag|laggy|battery|drain|heavy|storage|memory|takes forever|yavaş|pil|batarya|ısın",
    "privacy_trust": r"privacy|data|permission|tracking|spy|secur|scam|fraud|gizlilik|veri|izin|güven|dolandır|virüs",
    "support": r"support|customer service|reply|respond|ticket|help desk|no help|destek|cevap",
    "switching_intent": r"switch|switched|alternative|better app|uninstall|moved to|another app|cancel my|"
                        r"geçtim|başka uygulama|sileceğim|sildim|rakip",
    "liked_features": r"love|great|good|awesome|excellent|best|amazing|nice|helpful|easy to use|fantastic|"
                      r"harika|süper|çok iyi|güzel|mükemmel|beğen|kullanışlı",
}
CATEGORY_LABELS_TR = {
    "crashes_bugs": "Hatalar ve çökmeler", "ads": "Reklam yoğunluğu", "pricing_subscription": "Ücretlendirme ve abonelik",
    "missing_features": "Eksik özellikler", "usability": "Kullanım zorluğu", "performance": "Performans",
    "privacy_trust": "Gizlilik ve güven", "support": "Müşteri desteği", "switching_intent": "Rakibe geçme isteği",
    "liked_features": "Beğenilen özellikler", "other": "Diğer",
}
COMPLAINT_CATEGORIES = [c for c in CATEGORIES if c != "liked_features"]
_COMPILED = {k: re.compile(v, re.I) for k, v in CATEGORIES.items()}


def review_hash(text):
    norm = " ".join((text or "").lower().split())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:24]


def classify(text):
    cats = [k for k, rx in _COMPILED.items() if rx.search(text or "")]
    return cats or ["other"]


def parse_import(content, fmt, package=None):
    """CSV veya JSON metnini yorum listesine çevirir. Sütunlar/anahtarlar: text|review|body,
    rating|score|stars, date|review_date, version|app_version, url|source_url, package."""
    rows = []
    if fmt == "json":
        data = json.loads(content)
        if isinstance(data, dict):
            data = data.get("reviews", [])
        rows = list(data)
    elif fmt == "csv":
        rows = list(csv.DictReader(io.StringIO(content)))
    else:
        raise ValueError("Biçim csv veya json olmalıdır.")
    out, skipped = [], 0
    for r in rows:
        r = {str(k).strip().lower(): v for k, v in r.items()}
        pkg = r.get("package") or r.get("package_name") or package
        text = str(r.get("text") or r.get("review") or r.get("body") or r.get("content") or "").strip()
        if not text or (package and pkg and pkg != package):
            skipped += 1
            continue
        rating = r.get("rating") or r.get("score") or r.get("stars")
        try:
            rating = int(float(rating)) if rating not in (None, "") else None
        except (TypeError, ValueError):
            rating = None
        if rating is not None and not 1 <= rating <= 5:
            rating = None
        d = r.get("date") or r.get("review_date")
        out.append({
            "package": pkg, "text": text, "rating": rating,
            "date": _norm_date(d), "version": (str(r.get("version") or r.get("app_version") or "").strip() or None),
            "url": (r.get("url") or r.get("source_url") or None), "language": r.get("language"),
        })
    return out, skipped


def _norm_date(value):
    if not value:
        return None
    s = str(value).strip()[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date().isoformat()
    except ValueError:
        pass
    for fmt in ("%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(str(value).strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def analyze(reviews, as_of=None, min_sample=config.MIN_REVIEW_SAMPLE):
    """reviews: [{text, rating, date, version, url}] (tek uygulamaya ait).
    Dönüş: {sample_size, low_sample, categories: {kategori: {...}}, low_star_share, mean_rating, dated_count, stale}."""
    as_of = as_of or date.today()
    n = len(reviews)
    result = {"sample_size": n, "low_sample": n < min_sample, "min_sample": min_sample,
              "categories": {}, "low_star_share": None, "mean_rating": None,
              "dated_count": 0, "stale": False, "note": None}
    if n == 0:
        result["note"] = "Yorum örneği yok; yorum analizi yapılmadı."
        return result
    rated = [r["rating"] for r in reviews if r.get("rating")]
    if rated:
        result["mean_rating"] = round(sum(rated) / len(rated), 2)
        result["low_star_share"] = round(sum(1 for x in rated if x <= 2) / len(rated), 3)
    dated = []
    for r in reviews:
        if r.get("date"):
            try:
                dated.append((datetime.strptime(r["date"], "%Y-%m-%d").date(), r))
            except ValueError:
                pass
    result["dated_count"] = len(dated)
    if dated:
        newest = max(d for d, _ in dated)
        result["stale"] = (as_of - newest).days > config.STALE_DAYS * 6
        result["newest_review_date"] = newest.isoformat()

    per_cat = {c: [] for c in CATEGORY_LABELS_TR}
    for r in reviews:
        for c in classify(r["text"]):
            per_cat[c].append(r)

    for cat, items in per_cat.items():
        if not items and cat == "other":
            continue
        entry = {
            "label": CATEGORY_LABELS_TR[cat],
            "mention_count": len(items),
            "share": round(len(items) / n, 3),
            "example_urls": [r["url"] for r in items if r.get("url")][:3],
            "examples": [r["text"][:160] for r in items[:2]],
            "top_version": None,
        }
        versions = Counter(r["version"] for r in items if r.get("version"))
        if versions:
            v, cnt = versions.most_common(1)[0]
            if cnt >= 2:
                entry["top_version"] = v
        for w in (30, 90, 180):
            cur = _count_window(items, as_of, 0, w)
            prev = _count_window(items, as_of, w, 2 * w)
            entry[f"mentions_{w}d"] = cur
            entry[f"mentions_prev_{w}d"] = prev
            # Değişim yalnızca yeterli tarihli veri varsa hesaplanır
            entry[f"change_{w}d"] = _change(cur, prev) if result["dated_count"] >= 10 else None
        result["categories"][cat] = entry
    return result


def _count_window(items, as_of, start_days, end_days):
    lo, hi = as_of - timedelta(days=end_days), as_of - timedelta(days=start_days)
    cnt = 0
    for r in items:
        if not r.get("date"):
            continue
        d = datetime.strptime(r["date"], "%Y-%m-%d").date()
        if lo < d <= hi:
            cnt += 1
    return cnt


def _change(cur, prev):
    if prev < 3:
        return None  # Çok küçük tabanda yüzde değişim anlamsız
    return round((cur - prev) / prev, 3)


def top_complaints(analysis, limit=3):
    """Şikâyet kategorilerini (liked/other hariç) oranına göre sıralar."""
    items = [(k, v) for k, v in analysis.get("categories", {}).items() if k in COMPLAINT_CATEGORIES]
    items.sort(key=lambda kv: kv[1]["share"], reverse=True)
    return [{"key": k, "label": v["label"], "share": v["share"], "count": v["mention_count"]}
            for k, v in items[:limit] if v["mention_count"] > 0]


def complaint_share(analysis):
    """Analiz edilen yorumlar içinde en sık geçen tekil şikâyet kategorisinin oranı (0..1)."""
    if not analysis or analysis.get("sample_size", 0) == 0:
        return None
    vals = [v["share"] for k, v in analysis.get("categories", {}).items() if k in COMPLAINT_CATEGORIES]
    return max(vals) if vals else 0.0
