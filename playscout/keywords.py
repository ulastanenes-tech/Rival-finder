"""Niş/anahtar kelime üretimi, alaka skoru ve kontrollü geri dönüş. Ücretli AI kullanmaz;
kurallara dayalıdır ve kullanıcı listeyi düzenleyebilir."""
import re

STOP = {"the", "a", "an", "and", "or", "for", "of", "to", "with", "in", "on", "by", "app", "apps",
        "android", "best", "new", "free", "ve", "ile", "için", "bir", "uygulama"}

SYNONYMS = {
    "photo": ["picture", "image"], "picture": ["photo"], "image": ["photo", "picture"],
    "editor": ["editing app", "maker"], "editing": ["editor"], "maker": ["generator", "creator"],
    "remover": ["eraser", "remove"], "generator": ["maker", "creator"], "enhancer": ["upscaler", "restoration"],
    "avatar": ["profile picture"], "headshot": ["portrait"], "portrait": ["headshot"],
    "background": ["bg"], "video": ["clip"], "ai": ["artificial intelligence"],
    "fitness": ["workout"], "budget": ["expense"], "expense": ["budget"],
}
MODIFIERS = ["free", "offline", "online"]
MAX_TERMS_DEFAULT = 12
BROADEN_LEVELS = 2


def norm(text):
    return " ".join((text or "").lower().split())


def tokens(text):
    return re.findall(r"[a-z0-9çğıöşü]+", norm(text))


def core_tokens(text):
    return [t for t in tokens(text) if t not in STOP]


def validate_niche(niche):
    """Boş, çok kısa veya harf içermeyen girdileri reddeder. (ValueError, Türkçe mesaj)"""
    n = norm(niche)
    if not n:
        raise ValueError("Niş/anahtar kelime boş olamaz.")
    if len(n) > 100:
        raise ValueError("Niş 100 karakteri geçemez.")
    if not re.search(r"[a-zçğıöşü]", n):
        raise ValueError("Niş en az bir harf içermelidir.")
    if len(core_tokens(n)) == 0:
        raise ValueError("Niş yalnızca genel kelimelerden oluşuyor; daha belirgin bir niş girin.")
    return n


def expand(niche, mode="exact", max_terms=MAX_TERMS_DEFAULT):
    """Mod 1 (exact): yalnızca girilen niş. Mod 2 (discovery): alt nişler, eş anlamlılar, modifikatörler.
    Dönüş: [(terim, köken)] — köken: user | generated_subniche | generated_synonym | generated_modifier."""
    base = validate_niche(niche)
    terms = [(base, "user")]
    if mode == "exact":
        return terms
    toks = core_tokens(base)
    seen = {base}

    def add(term, origin):
        t = norm(term)
        if t and t not in seen:
            seen.add(t)
            terms.append((t, origin))

    for i in range(1, len(toks) - 1):  # "ai photo editor" -> "photo editor" (tek kelime olmaz: çok geniş)
        add(" ".join(toks[i:]), "generated_subniche")
    for t in toks:
        for s in SYNONYMS.get(t, [])[:2]:
            add(base.replace(t, s, 1), "generated_synonym")
    for m in MODIFIERS:
        add(f"{base} {m}", "generated_modifier")
    return terms[:max_terms]


def broaden(niche, level=1):
    """Sonuç bulunamadığında kontrollü, daha geniş anahtar kelimeler. level en fazla BROADEN_LEVELS."""
    toks = core_tokens(niche)
    if level > BROADEN_LEVELS or len(toks) <= 1:
        return []
    out = [" ".join(toks[1:])]
    if level >= 2 and len(toks) >= 2:
        out.append(toks[-1])
    return [t for t in dict.fromkeys(out) if t and t != norm(niche)]


def relevance(keywords, title, short_text, description, category=None):
    """Alaka skoru (0..1) ve eşleşen türetilmiş terimler.

    keywords: [(terim, köken)], ilk eleman ana niştir.
    - Skor = ana nişin çekirdek kelimelerinin metinde geçme oranı.
    - Türetilmiş bir terim (alt niş/eş anlamlı/modifikatör) tam geçiyorsa skor en az 0.6 olur.
    - Başlıkta ana niş kelimesi geçiyorsa +0.1 bonus.
    """
    title_n = norm(title)
    haystack = norm(" ".join(filter(None, [title, short_text, description, category])))
    base = keywords[0][0] if keywords else ""
    base_toks = core_tokens(base)
    if not base_toks:
        return 0.0, []
    hits = sum(1 for t in base_toks if re.search(rf"\b{re.escape(t)}\b", haystack))
    score = hits / len(base_toks)
    matched = []
    for term, _ in keywords[1:]:
        if re.search(rf"\b{re.escape(term)}\b", haystack):
            matched.append(term)
    if matched:
        score = max(score, 0.6)
    if any(re.search(rf"\b{re.escape(t)}\b", title_n) for t in base_toks):
        score = min(1.0, score + 0.1)
    return round(score, 3), matched
