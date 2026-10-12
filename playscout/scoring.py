"""Fırsat puanı (0–100) ve kanıt güveni (düşük/orta/yüksek). Ayrı değerlerdir.

- Eksik veri -> o bileşen nötr (%50) alır ve eksik liste raporlanır; uygulama otomatik kötü sayılmaz.
- Ağırlıklar config.DEFAULT_WEIGHTS'tan gelir; kullanıcı geçersiz kılabilir ve toplam 100'e normalize edilir.
"""
import math
from datetime import date, datetime

from . import config
from .reviews import complaint_share
from .revenue import STATUS_SCORE

COMPONENTS = ["demand", "age_growth", "complaints", "revenue", "weak_rivals", "feasibility"]
COMPONENT_LABELS = {
    "demand": "Talep ve indirme sinyalleri", "age_growth": "Uygulama yaşı ve büyüme",
    "complaints": "Kullanıcı şikâyetleri ve iyileştirme alanı", "revenue": "Gelir modeli kanıtı",
    "weak_rivals": "Rakiplerin zayıf olduğu alanlar", "feasibility": "Geliştirme ve bakım uygulanabilirliği",
}


def normalize_weights(overrides=None):
    w = dict(config.DEFAULT_WEIGHTS)
    if overrides:
        for k, v in overrides.items():
            if k not in w:
                raise ValueError(f"Bilinmeyen ağırlık: {k}")
            v = float(v)
            if v < 0:
                raise ValueError("Ağırlık negatif olamaz.")
            w[k] = v
    total = sum(w.values())
    if total <= 0:
        raise ValueError("Ağırlıkların toplamı sıfır olamaz.")
    return {k: round(v * 100 / total, 2) for k, v in w.items()}


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _months_between(d, today):
    return (today.year - d.year) * 12 + (today.month - d.month)


def score_app(app, analysis, revenue, peers, weights, today=None):
    """app: Apps satırı; analysis: reviews.analyze çıktısı; revenue: revenue.classify çıktısı;
    peers: aynı çalıştırmadaki diğer uygulamaların (dict) listesi.
    Dönüş: {opportunity, components{key:{points,max,note,missing}}, confidence, missing, evidence_fields}."""
    today = today or date.today()
    comps, missing = {}, []

    # 1) Talep
    note = []
    floor = app.get("download_floor")
    reviews_n = app.get("review_count")
    if floor:
        dl = _clamp((math.log10(floor) - 3) / 6)  # 1e3 -> 0, 1e9 -> 1
        rv = _clamp((math.log10(reviews_n) - 2) / 5) if reviews_n and reviews_n > 0 else 0.3
        base = 0.6 * dl + 0.4 * rv
        if app.get("appbrain_installs_30d"):
            base = _clamp(base + 0.1)
            note.append("AppBrain 30 gün tahmini var (tahmindir)")
        comps["demand"] = _comp(weights, "demand", base, note or ["Play indirme aralığı + yorum sayısı"])
    else:
        comps["demand"] = _comp(weights, "demand", 0.5, ["indirme aralığı bilinmiyor"])
        missing.append("indirme aralığı")

    # 2) Yaş ve büyüme
    age_part, growth_part = 0.5, 0.5
    notes = []
    if app.get("first_release_status") == "verified" and app.get("first_release_date"):
        d = datetime.fromisoformat(app["first_release_date"]).date()
        m = _months_between(d, today)
        age_part = 1.0 if m <= 12 else 0.6 if m <= 36 else 0.3
        notes.append(f"ilk yayın {app['first_release_date'][:7]} (doğrulanmış)")
    else:
        missing.append("doğrulanmış ilk yayın tarihi")
    total = app.get("appbrain_total_installs")
    inst30 = app.get("appbrain_installs_30d")
    if total and inst30:
        ratio = inst30 / total
        growth_part = 1.0 if ratio >= 0.10 else 0.6 if ratio >= 0.03 else 0.3
        notes.append(f"30 gün/toplam oranı {ratio:.1%} (AppBrain tahmini)")
    else:
        missing.append("30 günlük büyüme verisi")
    comps["age_growth"] = _comp(weights, "age_growth", 0.5 * age_part + 0.5 * growth_part, notes or ["veri yok"])

    # 3) Şikâyetler
    if analysis and not analysis.get("low_sample") and analysis.get("sample_size", 0) > 0:
        share = complaint_share(analysis) or 0.0
        cp = _clamp(share / 0.35)
        lss = analysis.get("low_star_share")
        rp = _clamp(lss / 0.4) if lss is not None else 0.5
        comps["complaints"] = _comp(weights, "complaints", 0.7 * cp + 0.3 * rp,
                                    [f"en sık şikâyet oranı {share:.0%} ({analysis['sample_size']} yorum)"])
    else:
        n = analysis.get("sample_size", 0) if analysis else 0
        comps["complaints"] = _comp(weights, "complaints", 0.5,
                                    [f"yorum örneği düşük ({n}); nötr" if n else "yorum örneği yok; nötr"])
        missing.append(f"yeterli yorum örneği (en az {config.MIN_REVIEW_SAMPLE})")

    # 4) Gelir kanıtı
    st = revenue["status"]
    comps["revenue"] = _comp(weights, "revenue", STATUS_SCORE[st], [revenue["label"]])
    if st == 4:
        missing.append("gelir kanıtı")

    # 5) Zayıf rakipler (aynı çalıştırmadaki benzer uygulamalar; yalnızca puan/şikâyet verisi kullanılır)
    if peers:
        weak = 0
        judged = 0
        for p in peers:
            if p.get("rating") is None and not p.get("complaint_share"):
                continue
            judged += 1
            if (p.get("rating") is not None and p["rating"] < 4.0) or (p.get("complaint_share") or 0) > 0.3:
                weak += 1
        if judged:
            comps["weak_rivals"] = _comp(weights, "weak_rivals", weak / judged,
                                         [f"{judged} rakipten {weak} tanesi zayıf (puan<4.0 veya şikâyet>%30)"])
        else:
            comps["weak_rivals"] = _comp(weights, "weak_rivals", 0.5, ["değerlendirilebilir rakip yok"])
            missing.append("rakip değerlendirme verisi")
    else:
        comps["weak_rivals"] = _comp(weights, "weak_rivals", 0.5, ["aynı çalıştırmada rakip yok"])

    # 6) Uygulanabilirlik
    if app.get("last_updated"):
        lu = datetime.fromisoformat(app["last_updated"]).date()
        days = (today - lu).days
        fe = 1.0 if days <= 90 else 0.6 if days <= 365 else 0.3
        notes = [f"son güncelleme {days} gün önce (Play/AppBrain)"]
    else:
        fe, notes = 0.5, ["son güncelleme bilinmiyor"]
        missing.append("son güncelleme tarihi")
    if floor and floor >= 100_000_000:
        fe = fe * 0.7
        notes.append("çok büyük mevcut oyuncular (≥100M)")
    comps["feasibility"] = _comp(weights, "feasibility", fe, notes)

    opportunity = round(sum(c["points"] for c in comps.values()), 1)
    fields = {
        "geliştirici": bool(app.get("developer_name")),
        "puan ve yorum sayısı": app.get("rating") is not None and app.get("review_count") is not None,
        "indirme aralığı": bool(floor),
        "doğrulanmış ilk yayın": app.get("first_release_status") == "verified",
        "son güncelleme": bool(app.get("last_updated")),
        "yorum örneği (yeterli)": bool(analysis and not analysis.get("low_sample")),
        "gelir kanıtı": revenue["status"] in (1, 2),
        "AppBrain verisi": bool(app.get("appbrain_data_date")),
    }
    got = sum(fields.values())
    confidence = "yüksek" if got >= 7 else "orta" if got >= 4 else "düşük"
    return {
        "opportunity": opportunity,
        "components": comps,
        "confidence": confidence,
        "missing": missing,
        "evidence_fields": fields,
    }


def _comp(weights, key, fraction, notes):
    fraction = _clamp(fraction)
    mx = weights[key]
    return {"label": COMPONENT_LABELS[key], "points": round(mx * fraction, 2), "max": mx,
            "fraction": round(fraction, 3), "notes": notes}
