"""Filtre ve sıralama motoru. Saf fonksiyonlar: her değişiklikte yeniden hesaplanabilir.

Kurallar:
- Tarih filtresi YALNIZCA ilk yayın tarihine uygulanır; son güncelleme ayrı filtredir.
- İlk yayın doğrulanmamışsa uygulama sessizce elenmez: 'bilinmiyor' olarak işaretlenir ve
  include_unknown_dates açıksa dâhil edilir.
- İndirme aralığı: Play "1,000,000+" gösteriyorsa gerçek sayı en az 1M'dir. Alt sınır eşiği karşılamıyorsa
  eleme yapılır (doğrulanamadı); üst sınır, aralığın alt sınırı bile üst eşiği aşıyorsa kesin elenir.
- Veri gerektiren diğer filtreler: veri yoksa uygulama o filtrede elenir (eşleşme doğrulanamadı).
"""
import re
from datetime import date, datetime

from . import config

DATE_PRESETS = {"1": 1, "2": 2, "3": 3, "6": 6, "9": 9, "12": 12, "24": 24}


def add_months(d, months):
    """Ay aritmetiği; ay sonu taşmalarında (31 Mart -> 28/29 Şubat) geçerli son günü kullanır."""
    import calendar
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def date_window(preset, date_from=None, date_to=None, today=None):
    """(başlangıç, bitiş) veya None (tarih filtresi yok). preset: none|1|2|3|6|9|12|24|custom."""
    today = today or date.today()
    if preset in (None, "", "none"):
        return None
    if preset == "custom":
        lo = datetime.fromisoformat(date_from).date() if date_from else None
        hi = datetime.fromisoformat(date_to).date() if date_to else None
        if lo and hi and lo > hi:
            raise ValueError("Başlangıç tarihi bitiş tarihinden sonra olamaz.")
        if not lo and not hi:
            raise ValueError("Özel tarih aralığı için en az bir tarih girin.")
        return (lo or date(1990, 1, 1), hi or today)
    if str(preset) not in DATE_PRESETS:
        raise ValueError(f"Geçersiz tarih seçeneği: {preset}")
    return (add_months(today, -DATE_PRESETS[str(preset)]), today)


def _release_overlaps(view, window):
    d, prec = view.get("first_release_date"), view.get("first_release_precision")
    if not d:
        return None
    start = datetime.fromisoformat(d).date()
    if prec == "month":
        end_m = add_months(start, 1)
        end = date.fromordinal(end_m.toordinal() - 1)
    else:
        end = start
    lo, hi = window
    return start <= hi and end >= lo


def _has(view, key):
    return view.get(key) not in (None, "", 0, False)


# (anahtar, açıklama, uygulayıcı) — sıra, açıklamadaki eleme sayımında kullanılır
def _rules(f, window, today):
    rules = []
    if window:
        def date_rule(v):
            ov = _release_overlaps(v, window)
            if ov is None:
                return bool(f.get("include_unknown_dates"))
            return ov
        rules.append(("date", "İlk yayın tarihi aralığı", date_rule))
    if f.get("min_downloads"):
        def dl_min(v):
            fl = v.get("download_floor")
            return fl is not None and fl >= int(f["min_downloads"])
        rules.append(("min_downloads", "Minimum indirme (alt sınır)", dl_min))
    if f.get("max_downloads"):
        def dl_max(v):
            fl = v.get("download_floor")
            return fl is None or fl <= int(f["max_downloads"])
        rules.append(("max_downloads", "Maksimum indirme", dl_max))
    if f.get("min_rating") is not None:
        rules.append(("min_rating", "Minimum puan", lambda v: v.get("rating") is not None and v["rating"] >= float(f["min_rating"])))
    if f.get("max_rating") is not None:
        rules.append(("max_rating", "Maksimum puan", lambda v: v.get("rating") is not None and v["rating"] <= float(f["max_rating"])))
    if f.get("min_reviews"):
        rules.append(("min_reviews", "Minimum yorum sayısı", lambda v: (v.get("review_count") or 0) >= int(f["min_reviews"])))
    if f.get("category"):
        cat = str(f["category"]).lower()
        rules.append(("category", "Kategori", lambda v: cat in (v.get("category") or "").lower()))
    if f.get("price_type") in ("free", "paid"):
        rules.append(("price_type", "Ücretsiz/ücretli", lambda v: v.get("price_type") == f["price_type"]))
    if f.get("has_ads") == "yes":
        rules.append(("has_ads", "Reklam içeren", lambda v: bool(v.get("has_ads"))))
    if f.get("has_ads") == "no":
        rules.append(("no_ads", "Reklamsız (kanıtlanmamış reklamlar dâhil)", lambda v: not v.get("has_ads")))
    if f.get("has_iap"):
        rules.append(("has_iap", "Uygulama içi satın alma", lambda v: bool(v.get("has_iap"))))
    if f.get("has_subscription"):
        rules.append(("has_subscription", "Abonelik (doğrulanabilirse)", lambda v: bool(v.get("has_subscription"))))
    if f.get("last_updated_days"):
        n = int(f["last_updated_days"])

        def upd(v):
            if not v.get("last_updated"):
                return bool(f.get("include_unknown_dates"))
            d = datetime.fromisoformat(v["last_updated"]).date()
            return (today - d).days <= n
        rules.append(("last_updated", f"Son güncelleme ≤ {n} gün", upd))
    if f.get("new_only"):
        def new_ok(v):
            if v.get("first_release_status") != "verified" or not v.get("first_release_date"):
                return False
            ws = add_months(today, -config.NEW_APP_MONTHS)
            return datetime.fromisoformat(v["first_release_date"]).date() >= ws
        rules.append(("new_only", f"Yeni yayınlanan (doğrulanmış, son {config.NEW_APP_MONTHS} ay)", new_ok))
    if f.get("high_complaints"):
        rules.append(("high_complaints", "Yüksek şikâyet oranı (≥%30, yeterli örneklem)",
                      lambda v: not v.get("low_sample") and (v.get("complaint_share") or 0) >= 0.3))
    if f.get("weak_reviews"):
        rules.append(("weak_reviews", "Yorumları yetersiz (puan<4.0 veya 1–2★ ≥%30)",
                      lambda v: (v.get("rating") is not None and v["rating"] < 4.0)
                      or (v.get("low_star_share") or 0) >= 0.3))
    if f.get("multi_rivals"):
        rules.append(("multi_rivals", "Birden fazla rakibi olan niş (aynı kategoride ≥3)",
                      lambda v: (v.get("cluster_size") or 0) >= 3))
    if f.get("multi_app_developer"):
        rules.append(("multi_app_developer", "Geliştiricinin birden fazla uygulaması",
                      lambda v: (v.get("developer_app_count") or 0) >= 2))
    if f.get("growing"):
        rules.append(("growing", "Son dönemde büyüyen", lambda v: bool(v.get("growing"))))
    if f.get("missing_data"):
        rules.append(("missing_data", "Kaynak verisi eksik olanlar", lambda v: bool(v.get("missing"))))
    if f.get("max_revenue_status"):
        mx = int(f["max_revenue_status"])
        rules.append(("revenue", "Gelir kanıtı durumu", lambda v: v.get("revenue_status") is not None and v["revenue_status"] <= mx))
    if f.get("min_confidence"):
        order = {"düşük": 0, "orta": 1, "yüksek": 2}
        need = order[f["min_confidence"]]
        rules.append(("min_confidence", "Minimum kanıt güveni", lambda v: order.get(v.get("confidence"), -1) >= need))
    if f.get("min_opportunity") is not None:
        rules.append(("min_opportunity", "Minimum fırsat puanı", lambda v: (v.get("opportunity") or 0) >= float(f["min_opportunity"])))
    return rules


def apply(views, filters, today=None):
    """Sonuç: (geçenler, açıklama). açıklama: [{key,label,eliminated,remaining}] sıralı eleme."""
    today = today or date.today()
    window = date_window(filters.get("date_preset"), filters.get("date_from"), filters.get("date_to"), today)
    rules = _rules(filters, window, today)
    current = list(views)
    explain = []
    for key, label, fn in rules:
        before = len(current)
        current = [v for v in current if fn(v)]
        explain.append({"key": key, "label": label, "eliminated": before - len(current), "remaining": len(current)})
    return current, explain


def apply_unknown_dates_note(views):
    """Tarihi bilinmeyen uygulama sayısı (kullanıcıya ayrıca gösterilir)."""
    return sum(1 for v in views if v.get("first_release_status") != "verified")


SORTS = {
    "opportunity": ("En yüksek fırsat puanı", lambda v: -(v.get("opportunity") or 0)),
    "downloads": ("En yüksek indirme", lambda v: -(v.get("download_floor") or 0)),
    "newest": ("En yeni yayınlanan", lambda v: (v.get("first_release_date") is None,
                                                -(datetime.fromisoformat(v["first_release_date"]).date().toordinal())
                                                if v.get("first_release_date") else 0)),
    "rating": ("En yüksek puan", lambda v: -(v.get("rating") or 0)),
    "reviews": ("En fazla yorum", lambda v: -(v.get("review_count") or 0)),
    "revenue": ("En güçlü gelir kanıtı", lambda v: (v.get("revenue_status") or 9)),
    "complaints": ("En fazla kullanıcı şikâyeti", lambda v: -(v.get("complaint_share") or 0)),
    "confidence": ("En yüksek veri güvenilirliği",
                   lambda v: {"yüksek": 0, "orta": 1, "düşük": 2}.get(v.get("confidence"), 3)),
}


def sort(views, key="opportunity"):
    if key not in SORTS:
        raise ValueError(f"Bilinmeyen sıralama: {key}")
    return sorted(views, key=SORTS[key][1])


def validate_filters(f):
    """Girdi doğrulaması; hata varsa ValueError (Türkçe)."""
    for k in ("min_rating", "max_rating"):
        if f.get(k) not in (None, ""):
            v = float(f[k])
            if not 0 <= v <= 5:
                raise ValueError("Puan 0 ile 5 arasında olmalıdır.")
    if f.get("min_rating") not in (None, "") and f.get("max_rating") not in (None, "") \
            and float(f["min_rating"]) > float(f["max_rating"]):
        raise ValueError("Minimum puan maksimum puandan büyük olamaz.")
    for k in ("min_downloads", "max_downloads", "min_reviews"):
        if f.get(k) not in (None, "", 0) and int(f[k]) < 0:
            raise ValueError(f"{k} negatif olamaz.")
    if f.get("min_downloads") and f.get("max_downloads") and int(f["min_downloads"]) > int(f["max_downloads"]):
        raise ValueError("Minimum indirme maksimum indirmeden büyük olamaz.")
    if f.get("date_preset") not in (None, "", "none", "custom") and str(f["date_preset"]) not in DATE_PRESETS:
        raise ValueError("Geçersiz tarih seçeneği.")
    if f.get("date_preset") == "custom":
        date_window("custom", f.get("date_from"), f.get("date_to"))
    for key in ("date_from", "date_to"):
        if f.get(key) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(f[key])):
            raise ValueError("Tarihler YYYY-AA-GG biçiminde olmalıdır.")
    return True
