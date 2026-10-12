"""Merkezi ayarlar. Ücretli servis, API anahtarı veya bulut bağımlılığı yoktur."""
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = pathlib.Path(os.environ.get("PLAYSCOUT_DATA", ROOT / "data"))
DB_PATH = DATA_DIR / "playscout.db"
WEB_DIR = ROOT / "web"

# Kimliği açık bir User-Agent. İletişim bilgisini kendiniz ayarlayın.
CONTACT = os.environ.get("PLAYSCOUT_CONTACT", "belirtilmedi")
# HTTP başlıkları ASCII olmalıdır (latin-1 kodlaması); bu yüzden Türkçe karakter kullanılmaz.
USER_AGENT = f"PlayScout/0.1 (local research tool; contact: {CONTACT})".encode("ascii", "replace").decode("ascii")

# Nazik tarama: aynı host'a istekler arasında en az bu kadar saniye.
MIN_INTERVAL_SECONDS = float(os.environ.get("PLAYSCOUT_MIN_INTERVAL", "3.0"))
REQUEST_TIMEOUT = 20
MAX_RETRIES = 2
CIRCUIT_BREAKER_FAILURES = 5  # Bir host'ta arka arkaya bu kadar hata -> o çalıştırmada durdur

CACHE_TTL_SECONDS = {
    "play_details": 7 * 86400,
    "appbrain_app": 1 * 86400,
}

# Yalnızca bu host + yol önekleri kullanılır. robots.txt'de yasaklı yollar
# (ör. play.google.com/store/search, /store/getreviews, /store/xhr; appbrain.com/search)
# bilerek dahil edilmemiştir ve kod tarafında da engellenir.
ALLOWED_PREFIXES = {
    "play.google.com": ("/store/apps/details",),
    "www.appbrain.com": ("/app/",),
}
DISALLOWED_PATH_FRAGMENTS = (
    "/store/search", "/store/getreviews", "/store/xhr", "/xhr", "/search",
    "/app_details/", "/apps/search",
)

DEFAULT_WEIGHTS = {
    "demand": 20,       # Talep ve indirme sinyalleri
    "age_growth": 15,   # Uygulama yaşı ve büyüme
    "complaints": 20,   # Kullanıcı şikâyetleri ve iyileştirme alanı
    "revenue": 20,      # Gelir modeline ilişkin kanıt
    "weak_rivals": 15,  # Rakiplerin zayıf olduğu alanlar
    "feasibility": 10,  # Geliştirme ve bakım uygulanabilirliği
}

MIN_REVIEW_SAMPLE = 30  # Bu sayının altındaki yorum örneği "düşük örneklem" sayılır
NEW_APP_MONTHS = 6      # "Yeni yayınlanmış" filtresi için pencere
STALE_DAYS = 30         # Bu günden eski kayıtlar "eski veri" olarak işaretlenir

# Alaka eşiği (keşif modu). Türetilmiş bir terim (alt niş/eş anlamlı/modifikatör) tam geçerse
# keywords.relevance bunu en az 0.6 yapar; yani bu eşik her zaman bu tür eşleşmeyi kabul eder.
# Tam eşleşme (exact) modu ise eşiği değil, niş metninin tamamını ister (pipeline.py).
RELEVANCE_THRESHOLD = 0.5
