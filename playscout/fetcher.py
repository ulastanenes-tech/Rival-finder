"""Nazik, önbellekli ve politika uyumlu HTTP istemcisi (yalnızca standart kütüphane).

- Yalnızca config.ALLOWED_PREFIXES içindeki yollara istek atar (robots.txt yasaklı yollar hariç).
- Host başına istekler arasında minimum bekleme uygular.
- Önbellek: HttpCache tablosu, kaynağa göre TTL.
- Hata durumunda istisna fırlatmaz; FetchResult.error ile raporlar.
- Bir host'ta arka arkaya çok hata olursa o çalıştırmada devre dışı bırakır (devre kesici).
"""
import gzip
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from . import config
from .db import utc_now


@dataclass
class FetchResult:
    url: str
    ok: bool
    body: str = ""
    status: int = 0
    from_cache: bool = False
    stale: bool = False
    error: str = ""


def policy_check(url):
    """URL politika ihlali içeriyorsa hata metni, yoksa None döner."""
    p = urllib.parse.urlparse(url)
    if p.scheme != "https":
        return "yalnızca https desteklenir"
    prefixes = config.ALLOWED_PREFIXES.get(p.netloc)
    if prefixes is None:
        return f"host izinli listede değil: {p.netloc}"
    if not any(p.path.startswith(pre) for pre in prefixes):
        return f"yol izinli değil: {p.path}"
    lowered = (p.path + "?" + p.query).lower()
    for frag in config.DISALLOWED_PATH_FRAGMENTS:
        if frag in lowered:
            return f"robots.txt ile yasaklı yol: {frag}"
    return None


class Fetcher:
    def __init__(self, conn, offline=False, min_interval=None, opener=None, sleep=time.sleep, clock=time.monotonic):
        self.conn = conn
        self.offline = offline
        self.min_interval = config.MIN_INTERVAL_SECONDS if min_interval is None else min_interval
        self._opener = opener or urllib.request.build_opener()
        self._sleep = sleep
        self._clock = clock
        self._last_request = {}
        self._failures = {}
        self.requests_made = 0
        self.log = []  # (url, sonuç) — çalıştırma raporu için

    def _cache_get(self, url):
        return self.conn.execute("SELECT * FROM HttpCache WHERE url=?", (url,)).fetchone()

    def _cache_put(self, url, status, body, source_name):
        self.conn.execute(
            "INSERT OR REPLACE INTO HttpCache(url, fetched_at, status, body, source_name) VALUES (?,?,?,?,?)",
            (url, utc_now(), status, body, source_name))
        self.conn.commit()

    def _age_seconds(self, fetched_at):
        t = datetime.fromisoformat(fetched_at)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds()

    def get(self, url, source_name, ttl, use_cache=True):
        bad = policy_check(url)
        if bad:
            return FetchResult(url, False, error=f"politika: {bad}")

        row = self._cache_get(url) if use_cache else None
        if row is not None and row["body"] and self._age_seconds(row["fetched_at"]) < ttl:
            return FetchResult(url, True, body=row["body"], status=row["status"] or 200, from_cache=True)

        host = urllib.parse.urlparse(url).netloc
        if self.offline:
            if row is not None and row["body"]:
                return FetchResult(url, True, body=row["body"], status=row["status"] or 200, from_cache=True,
                                   stale=True, error="çevrimdışı mod: eski önbellek kullanıldı")
            return FetchResult(url, False, error="çevrimdışı mod ve önbellekte yok")

        if self._failures.get(host, 0) >= config.CIRCUIT_BREAKER_FAILURES:
            return FetchResult(url, False, error=f"devre kesici: {host} bu çalıştırmada devre dışı")

        last_error = ""
        for attempt in range(config.MAX_RETRIES + 1):
            self._respect_rate_limit(host)
            self.requests_made += 1
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": config.USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.8,tr;q=0.6",
                    "Accept-Encoding": "gzip",
                })
                with self._opener.open(req, timeout=config.REQUEST_TIMEOUT) as resp:
                    raw = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        raw = gzip.decompress(raw)
                    body = raw.decode("utf-8", errors="replace")
                    status = resp.status
                self._failures[host] = 0
                self._cache_put(url, status, body, source_name)
                self.log.append({"url": url, "status": status})
                return FetchResult(url, True, body=body, status=status)
            except urllib.error.HTTPError as e:
                last_error = f"HTTP {e.code}"
                if e.code in (404, 410):
                    break  # Kalıcı hata: yeniden deneme yok
                if e.code == 429:
                    retry_after = e.headers.get("Retry-After") if e.headers else None
                    wait = min(60, int(retry_after)) if retry_after and retry_after.isdigit() else 30
                    self._sleep(wait)
                elif e.code >= 500 or e.code in (403,):
                    self._sleep(2 ** attempt * 2)
                else:
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_error = f"ağ hatası: {getattr(e, 'reason', e)}"
                self._sleep(2 ** attempt * 2)
            except Exception as e:  # beklenmeyen hata da kaynak hatasıdır; akış devam eder
                last_error = f"beklenmeyen hata: {type(e).__name__}: {e}"
                break
        self._failures[host] = self._failures.get(host, 0) + 1
        self.log.append({"url": url, "error": last_error})
        # Eski önbellek varsa onu kullan ve bunu işaretle
        if row is not None and row["body"]:
            return FetchResult(url, True, body=row["body"], status=row["status"] or 200, from_cache=True,
                               stale=True, error=f"{last_error}; eski önbellek kullanıldı")
        return FetchResult(url, False, error=last_error or "bilinmeyen hata")

    def _respect_rate_limit(self, host):
        last = self._last_request.get(host)
        if last is not None:
            wait = self.min_interval - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_request[host] = self._clock()
