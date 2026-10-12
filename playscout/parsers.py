"""Saf ayrıştırma fonksiyonları (ağ yok). Google Play ve AppBrain sayfalarından alan çıkarır.

Her fonksiyon eksik veride None döner; tahmin üretmez.
"""
import re
from datetime import date, datetime
from html.parser import HTMLParser

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}
WORD_MULT = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
SUFFIX_MULT = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}
BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article", "header", "footer", "ul", "ol"}
SKIP_TAGS = {"script", "style", "noscript", "template"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.meta = {}
        self.links = []  # (href, anchor_text)
        self._skip = 0
        self._link = None
        self._link_text = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in SKIP_TAGS:
            self._skip += 1
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "meta":
            key = a.get("property") or a.get("name") or a.get("itemprop")
            if key and a.get("content") is not None:
                self.meta.setdefault(key.lower(), a["content"])
        if tag == "a" and a.get("href"):
            self._link = a["href"]
            self._link_text = []

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "a" and self._link is not None:
            self.links.append((self._link, " ".join("".join(self._link_text).split())))
            self._link = None

    def handle_data(self, data):
        if self._skip:
            return
        self.parts.append(data)
        if self._link is not None:
            self._link_text.append(data)


def html_to_text(html):
    """HTML -> (metin, meta sözlüğü, [(href, bağlantı metni)])."""
    p = _TextExtractor()
    p.feed(html or "")
    p.close()
    text = "".join(p.parts)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text, p.meta, p.links


def parse_compact_number(s):
    """'54.2M' -> 54_200_000, '3,960,725' -> 3960725, '1.1 million' -> 1100000, '10B+' -> 10e9."""
    if s is None:
        return None
    t = str(s).strip().replace("\xa0", " ").rstrip("+").strip()
    m = re.fullmatch(r"([\d.,]+)\s*([A-Za-z]+)?", t)
    if not m:
        return None
    num, unit = m.group(1), (m.group(2) or "").lower()
    if unit and unit not in WORD_MULT and unit not in SUFFIX_MULT:
        return None
    # Virgül binlik ayracı mı yoksa ondalık mı? Birim varsa ondalık (54.2M), yoksa binlik (3,960,725).
    if unit:
        num = num.replace(",", ".") if num.count(",") == 1 and "." not in num and len(num.split(",")[1]) != 3 else num.replace(",", "")
        try:
            value = float(num)
        except ValueError:
            return None
        mult = WORD_MULT.get(unit) or SUFFIX_MULT.get(unit)
        return int(round(value * mult))
    digits = num.replace(",", "").replace(".", "")
    return int(digits) if digits.isdigit() else None


def parse_download_bucket(text):
    """Play indirme aralığı: '1,000,000+' -> (1000000, '1,000,000+'); '10B+' -> (10_000_000_000, '10B+')."""
    if not text:
        return None, None
    m = re.search(r"(\d[\d.,]*\s*[KMBkmb]?)\s*\+", text)
    if not m:
        return None, None
    label = m.group(0).replace("  ", " ").strip()
    value = parse_compact_number(m.group(1).replace(" ", "") + "")
    if value is None:
        return None, None
    return value, label


def parse_play_date(text):
    """'Oct 8, 2026' veya 'October 8, 2026' -> '2026-10-08'."""
    if not text:
        return None
    t = " ".join(text.replace(",", ", ").split()).replace(",  ", ", ")
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(t.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_month_year(month_name, year):
    """AppBrain 'On Google Play since December 2020' -> ('2020-12-01', 'month')."""
    mnum = MONTHS.get(str(month_name).lower())
    if not mnum:
        return None, None
    return date(int(year), mnum, 1).isoformat(), "month"


def _pkg_from_href(href):
    m = re.search(r"[?&]id=([A-Za-z][\w]*(?:\.\w+)+)", href or "")
    return m.group(1) if m else None


PKG_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$")


def extract_packages(text):
    """Serbest metinden (Play/AppBrain bağlantıları, düz paket listesi) paket adlarını
    çıkarır; metindeki sıra korunur, tekrarlar atılır."""
    hits = []
    patterns = [
        r"[?&]id=([A-Za-z][\w]*(?:\.\w+)+)",
        r"/app/(?:[^/\"'\s?#)]+/)?([A-Za-z][\w]*(?:\.\w+)+)",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text or ""):
            hits.append((m.start(), m.group(1)))
    # Düz paket listesi (satır/virgül/boşlukla ayrılmış); URL parçaları hariç
    for m in re.finditer(r"[^\s,;]+", text or ""):
        tok = m.group(0)
        if "/" in tok or "=" in tok or "?" in tok or "&" in tok or "http" in tok:
            continue
        hits.append((m.start(), tok))
    found = []
    for _, pkg in sorted(hits, key=lambda h: h[0]):
        if PKG_RE.match(pkg) and pkg not in found:
            found.append(pkg)
    return found


def parse_play_details(html, package):
    """Google Play detay sayfası -> alan sözlüğü. Eksik alanlar None."""
    text, meta, links = html_to_text(html)
    out = {"package": package, "play_url": f"https://play.google.com/store/apps/details?id={package}"}

    og_title = meta.get("og:title") or meta.get("title") or ""
    title = re.sub(r"\s*-\s*(Android\s+)?Apps? on Google Play$", "", og_title).strip() or None
    out["title"] = title

    for href, label in links:
        if "/store/apps/dev" in href and label:
            dev_id = re.search(r"[?&]id=(\d+)", href)
            out["developer_name"] = label
            out["developer_play_id"] = dev_id.group(1) if dev_id else None
            break
    cat = re.search(r"/store/apps/category/([A-Z_]+)", html or "")
    out["category"] = cat.group(1).replace("_", " ").title() if cat else None

    rating = None
    for pat in (r"Rated\s+(\d(?:\.\d)?)\s+stars?", r'ratingValue"?\s*content="(\d(?:\.\d)?)"',
                r'itemprop="ratingValue"[^>]*>\s*(\d(?:\.\d)?)'):
        m = re.search(pat, html or "", re.I)
        if m:
            rating = float(m.group(1))
            break
    if rating is None:
        m = re.search(r"^\s*(\d\.\d)\s*$", text, re.M)
        if m:
            rating = float(m.group(1))
    out["rating"] = rating if rating is None or 0 <= rating <= 5 else None

    m = re.search(r"([\d.,]+\s*[KMB]?)\s+reviews\b", text, re.I)
    out["review_count_label"] = m.group(1).strip() if m else None
    out["review_count"] = parse_compact_number(m.group(1)) if m else None

    m = re.search(r"(\d[\d.,]*\s*[KMB]?\+)\s*\n\s*Downloads", text, re.I)
    if m:
        out["download_floor"], out["download_label"] = parse_download_bucket(m.group(1))
    else:
        out["download_floor"], out["download_label"] = None, None

    m = re.search(r"Updated on\s*\n?\s*([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4})", text)
    out["last_updated"] = parse_play_date(m.group(1)) if m else None

    if re.search(r"^\s*Buy\s*$", text, re.M):
        out["price_type"] = "paid"
        pm = re.search(r"(\$|€|£|₺)\s?\d[\d.,]*|\d[\d.,]*\s?(TL|USD|EUR)", text)
        out["price_text"] = pm.group(0) if pm else "satın al"
    elif re.search(r"^\s*Install\s*$", text, re.M):
        out["price_type"] = "free"
        out["price_text"] = "Ücretsiz"
    else:
        out["price_type"] = "unknown"
        out["price_text"] = None

    out["has_ads"] = 1 if re.search(r"Contains ads", text, re.I) else None
    out["has_iap"] = 1 if re.search(r"In-app purchases|Offers in-app purchases|In-App Purchases", text, re.I) else None
    out["has_subscription"] = None  # Sayfa açıkça belirtmiyorsa doğrulanmış kabul edilmez

    desc = meta.get("description") or meta.get("og:description")
    out["description"] = (desc or "")[:4000] or None
    out["icon_url"] = meta.get("og:image")

    out["_bot_block"] = bool(re.search(r"unusual traffic|captcha|not a robot", text, re.I))
    out["_usable"] = bool(title)
    return out


def parse_appbrain_app(html, package):
    """AppBrain uygulama sayfası -> ilk yayın ayı, son güncelleme, tahmini yüklemeler, benzerler."""
    text, meta, links = html_to_text(html)
    out = {"package": package, "appbrain_url": f"https://www.appbrain.com/app/{package}"}

    m = re.search(r"On Google Play since\s*\n?\s*([A-Za-z]+)\s+(\d{4})", text) or \
        re.search(r"available on Google Play since\s*_?\s*([A-Za-z]+)\s+(\d{4})", text)
    out["first_release_date"], out["first_release_precision"] = (
        parse_month_year(m.group(1), m.group(2)) if m else (None, None))

    m = re.search(r"Last updated\s*\n?\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})", text) or \
        re.search(r"The last update was on\s*_?\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})", text)
    out["last_updated"] = parse_play_date(m.group(1)) if m else None

    m = re.search(r"Installs,? last 30 days\s*\n?\s*([\d.,]+\s*(?:thousand|million|billion)?)", text, re.I)
    out["installs_30d"] = parse_compact_number(m.group(1)) if m else None

    m = re.search(r"Total installs\s*\n?\s*([\d.,]+\s*(?:thousand|million|billion)?)", text, re.I)
    out["total_installs"] = parse_compact_number(m.group(1)) if m else None

    m = re.search(r"Best rank\s*\n?\s*#(\d+)\s*\n?\s*([^\n\[]+)", text)
    out["rank_text"] = f"#{m.group(1)} {m.group(2).strip()}" if m else None

    m = re.search(r"Data updated\s*(\d{4}-\d{2}-\d{2})", text)
    out["data_date"] = m.group(1) if m else None

    alts = []
    for pat in (r"appbrain\.com/app/(?:[^/\"'\s?#)]+/)?([A-Za-z][\w]*(?:\.\w+)+)", r'href="/app/(?:[^/"\s?#]+/)?([A-Za-z][\w]*(?:\.\w+)+)"'):
        for mm in re.finditer(pat, html or ""):
            p = mm.group(1)
            if PKG_RE.match(p) and p != package and p not in alts:
                alts.append(p)
    out["alternatives"] = alts[:20]
    out["_bot_block"] = bool(re.search(r"unusual traffic|captcha|not a robot", text, re.I))
    out["_usable"] = bool(out["first_release_date"] or out["last_updated"] or out["installs_30d"]
                          or out["total_installs"])
    return out
