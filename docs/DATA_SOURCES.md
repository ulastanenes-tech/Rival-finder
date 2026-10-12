# Veri kaynakları, robots.txt kararları ve alan kökenleri

Son kontrol: 2026-10-12 (fetch aracıyla `robots.txt` ve örnek sayfalar okunarak).

## 1. Kaynak kararları

| Kaynak | Kullanılan yol | Yasaklı/atlanan yol | Karar |
|---|---|---|---|
| Google Play | `/store/apps/details?id=…` | `/store/search`, `/store/getreviews`, `/store/xhr`, `/store/apps/datasafety`, `/apps`, `/xhr` | Detay sayfası kullanılır. Arama ve yorum uç noktaları **kullanılmaz**. |
| AppBrain | `/app/<paket>` | `/search`, `/appstore/search`, `/app_details/`, `/user/`, `/admin/` | Uygulama sayfası ve benzer uygulama bağlantıları kullanılır. Arama kullanılmaz. |
| Manuel | — | — | Kullanıcının kendi dışa aktardığı veriler. |

Ücretli API, anahtar gerektiren uç nokta, CAPTCHA aşma ve gizli uç nokta kullanılmaz.

## 2. Alan kökenleri

| Veri alanı | Kaynak | Hassasiyet / not |
|---|---|---|
| Uygulama adı, paket, Play bağlantısı | Google Play detay | Paket, URL'den gelir |
| Geliştirici adı, Play geliştirici kimliği | Google Play detay (geliştirici bağlantısı) | |
| Kategori | Google Play detay (kategori bağlantısı) | |
| Puan | Google Play detay | Yuvarlanmış tek ondalık |
| Yorum sayısı | Google Play detay ("54.2M reviews") | Yaklaşık; ham ve birim etiketi saklanır |
| İndirme aralığı | Google Play detay ("10B+ Downloads") | **Alt sınırdır**, kesin sayı değildir |
| Ücret türü | Google Play detay (Install / Buy) | |
| Reklam / IAP | Google Play detay ("Contains ads", "In-app purchases") | Etiket yoksa "kanıt yok" (NULL) |
| Abonelik | — | Güvenilir kaynak yok; NULL bırakılır |
| Son güncelleme | Google Play ("Updated on") veya AppBrain ("Last updated") | **İlk yayın değildir.** Kaynak alanda saklanır. |
| İlk yayın tarihi | AppBrain ("On Google Play since") | **Yalnızca ay/yıl**; `first_release_precision=month`. Play'de yok. |
| İlk yayın durumu | Hesaplanır | `verified` yalnızca kaynak tarihi varsa; yoksa `unknown` ve "yeni" etiketi **verilmez** |
| 30 gün yükleme | AppBrain ("Installs, last 30 days") | **Tahmin**; arayüzde işaretli |
| Toplam yükleme | AppBrain ("Total installs") | **Tahmin** |
| Sıralama | AppBrain ("Best rank") | Metin olarak saklanır |
| Benzer uygulamalar | AppBrain ("Alternatives") | Keşif için; Play'deki bilgiler ayrıca çekilir |
| Yorumlar ve yorum metinleri | Manuel içe aktarma | Otomatik toplama yok |
| Gelir kanıtı | Manuel içe aktarma (geliştirici açıklaması / rapor / doğrulanabilir ürün) | Doğrudan kanıt için https bağlantı zorunlu |
| Yeniden markalama ipucu | Hesaplanır | Aynı geliştirici + ad benzerliği ≥%80; doğrulanmamış |

## 3. Veri tazeliği
- Her kayıtta `last_checked_at` ve kaynak başına `Sources.last_ok_at` tutulur.
- Son kontrolü 30 günden eski kayıtlar arayüzde "eski veri" olarak işaretlenir.
- AppBrain sayfasındaki "Data updated" tarihi `appbrain_data_date` alanında saklanır.

## 4. Gelecekte değiştirilebilecek olanlar
- Play'in resmi (ücretsiz) bir yorum dışa aktarma yolu sunması durumunda manuel içe aktarma yerine kullanılabilir.
- Google Trends için yalnızca Trends'in kendi herkese açık görünümü izinliyse ve robots.txt buna izin veriyorsa eklenir.
