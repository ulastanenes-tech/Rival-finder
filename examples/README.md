# Örnek çıktılar

- `sample_run.json` — `make_demo.py` ile üretilmiştir: Mod 2, tohumlar `com.photoroom.app` ve
  `com.google.android.apps.photos`, tarih filtresi yok.
- `sample_export.csv` — aynı çalıştırmanın CSV dışa aktarması (Excel için UTF-8 BOM'lu).

**Önemli:** Bu dosyalar `tests/fixtures/` içindeki sentetik HTML sayfalarından üretilmiştir (2026-10-12 tarihli
herkese açık sayfa değerlerine dayanır). Canlı Play/AppBrain verisi değildir. Gösterdikleri:
- Photoroom: ilk yayın AppBrain'den **ay hassasiyetiyle** (2020-12), son güncelleme Play'den (2025-01-16) — iki ayrı alan.
- Google Photos: alakasız bulunduğu için elenir (Mod 2'de alakalı değil) — alaka filtresi çalışıyor.
- Dört AppBrain alternatifi: fikstürü olmadığı için "veri yok" olarak raporlanır — kaynak hatası raporlama.
- Yorum verisi yok → "yorum örneği yok; nötr" ve eksik veri listesi gösterilir; uydurma yorum oranı yoktur.
- Gelir kanıtı durumu 2 (reklam/IAP etiketleri var), gerçek gelir **doğrulanmadı**.
