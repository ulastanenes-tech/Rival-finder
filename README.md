# PlayScout — Ücretsiz Google Play Rakip Araştırma Sistemi

PlayScout, bir niş veya tohum uygulama listesinden başlayarak Google Play uygulamalarını **ücretsiz, herkese açık ve
izinli** kaynaklarla araştıran, verileri **yerel SQLite** veritabanında saklayan ve rakip fırsatlarını
**fırsat puanı + kanıt güveni** ayrımıyla sıralayan yerel bir araçtır.

- API anahtarı yok, ücretli servis yok, bulut bağımlılığı yok.
- Harici Python paketi yok: yalnızca **Python 3.10+ standart kütüphanesi** (`sqlite3`, `http.server`, `urllib`).
- Tarayıcı arayüzü: düz HTML/CSS/JS (framework yok).
- Çevrimdışı mod: kayıtlı verileri ağa çıkmadan analiz eder.

> **Önemli dürüstlük notu:** Sistemin en kritik kısıtı, Google Play ve AppBrain'in `robots.txt` kurallarıdır. Play'in
> `/store/search` ve yorum uç noktaları (`/store/getreviews`, `/store/xhr`) ve AppBrain'in `/search` sayfası
> **yasaklıdır**. Bu yüzden PlayScout bu sayfaları **kullanmaz**. Keşif, sizin verdiğiniz tohum uygulamalardan ve
> AppBrain'in izinli "benzer uygulamalar" bağlantılarından yapılır. Yorumlar ve gelir kanıtları manuel içe aktarılır.
> Ayrıntılar: [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

---

## 1. Kurulum

Gereksinim: **Python 3.10 veya üzeri**. Başka bir kurulum gerekmez.

```bash
git clone https://github.com/ulastanenes-tech/Rival-finder.git
cd Rival-finder
git checkout arena/dc07ab4f-rival-finder
# İsteğe bağlı: iletişim bilgisi (HTTP User-Agent içinde, Google/AppBrain'in sizinle iletişime geçebilmesi için)
export PLAYSCOUT_CONTACT="siz@example.com"
python -m playscout doctor            # ortam + robots.txt uyumu kontrolü
python -m playscout doctor --network  # (isteğe bağlı) tek bir izinli sayfayı açıp ayrıştırmayı dener
python -m playscout serve             # http://127.0.0.1:8000 adresinde arayüzü açar
```

Veriler varsayılan olarak `data/playscout.db` dosyasında tutulur (git'e eklenmez). Farklı bir konum için
`PLAYSCOUT_DATA=/yol/klasor` ortam değişkenini kullanın.

Testler (ağ gerektirmez):

```bash
python -m unittest discover -s tests -t .      # 63 test
python examples/make_demo.py                    # fikstürlerden örnek araştırma üretir
```

---

## 2. Kullanım

### Web arayüzü
1. **Niş** kutusuna bir anahtar kelime yazın (ör. `AI photo editor`). **Mod**: *Tam eşleşme* (yalnızca bu niş) veya
   *Niş keşfi* (alt nişler ve eş anlamlılar). **Öner** düğmesi kelimeleri gösterir; düzenleyebilirsiniz.
2. **Tohum uygulamalar** kutusuna paket adları veya Play/AppBrain bağlantıları yapıştırın, örn.
   `com.photoroom.app`. Arama sonuçlarını tarayıcınızda açıp bağlantılarını buraya kopyalamanız keşfi genişletir.
3. Tarih (ilk yayın), indirme alt/üst eşiği, puan, yorum sayısı, sonuç sayısını seçin; **Araştırmayı başlat**.
4. Sonuçlar tablo veya kart olarak görünür. Filtreler her değişiklikte sunucuda yeniden hesaplanır.
   Sütun başlığına tıklayarak sıralayabilir, **Detaylı analiz** ile rakip kartını açabilirsiniz.
5. Favoriler, karşılaştırma listesi, CSV/JSON dışa aktarma, önceki araştırmayı yeniden açma ve "aynı nişi yeniden
   tara" işlemleri arayüzdedir.

### Komut satırı
```bash
python -m playscout search --niche "AI photo editor" --mode discovery \
  --seeds "com.photoroom.app" --filters '{"date_preset":"6","min_downloads":1000000}' --out run.json
python -m playscout search --niche "AI photo editor" --offline        # yalnızca kayıtlı veriler
python -m playscout reviews --package com.photoroom.app --file yorumlar.csv   # manuel yorum içe aktarma
python -m playscout export --run 1 --format csv --out sonuclar.csv
python -m playscout backup --out yedek.json        # tüm veriler (geçmiş dâhil)
python -m playscout backup --restore yedek.json    # mevcut veriyi silmeden birleştirir
```

### Manuel yorum dosyası biçimi (CSV veya JSON)
`text` (zorunlu), `rating` (1–5), `date` (YYYY-AA-GG), `version`, `url`, `package`. Örnek:
```csv
text,rating,date,version,url
"Crashes every time I open the editor",1,2026-10-01,3.2.1,https://example.com/review/1
```
Yorumları yalnızca **kendi hesabınızdan veya izinle** elde ettiğiniz dışa aktarmalardan alın. Sistem Play yorum
uç noktalarından otomatik yorum toplamaz.

---

## 3. Özellik durumu

| Alan | Durum | Not |
|---|---|---|
| Niş / anahtar kelime, Mod 1 ve Mod 2 | Tamam | Kural tabanlı üretim; ücretli AI yok. Mod 2, alt nişler, eş anlamlılar ve modifikatörlerle genişler (tek kelimelik genel terimler üretilmez). |
| Kontrollü geri dönüş (broadening) | Tamam | Hiç alakalı yoksa en fazla 2 seviye geniş terim; açıkça işaretlenir. |
| Play arama sonuçlarından keşif | **Yok (kasıtlı)** | `/store/search` robots.txt ile yasaklı. Yerine tohum + AppBrain alternatifleri. |
| Play detay alanları (ad, paket, geliştirici, kategori, puan, yorum sayısı, indirme aralığı, ücret, reklam/IAP etiketi, son güncelleme) | Tamam | Metin/etiket tabanlı; sayfa yapısı değişirse ayrıştırıcı güncellenmelidir. |
| İlk yayın tarihi | Kısmi | Play bu tarihi göstermez. AppBrain "On Google Play since" (**yalnızca ay/yıl**) kullanılır, kaynak ve hassasiyet gösterilir. Yoksa "doğrulanmadı". |
| AppBrain 30 gün yükleme, toplam yükleme, sıralama | Tamam (tahmin) | AppBrain tahminidir; arayüzde "tahmin" olarak işaretlidir. |
| Benzer uygulamalar | Tamam | AppBrain "Alternatives" bağlantılarından 1 seviye. |
| Yorum analizi (11 kategori, oran, 30/90/180 gün, sürüm, örnek bağlantı, çapraz rakip) | Tamam | Yalnızca manuel içe aktarılan yorumlarda. Örneklem < 30 ise "düşük örneklem" uyarısı. |
| Gelir kanıtı (4 durum, kanıt bağlantısı ve tarihi) | Tamam | Doğrudan kanıt yalnızca https bağlantılı manuel kanıtla. Uydurma gelir/oran yok. |
| Fırsat puanı (0–100) + kanıt güveni (düşük/orta/yüksek) | Tamam | Ağırlıklar ayarlanabilir; eksik veri nötr (%50) sayılır, otomatik ceza yok. |
| Filtreler (spec 6–7) | Tamam | Hepsi arayüzde; kapatılabilir; birlikte çalışır; eleme açıklaması gösterilir. |
| Sıralama (8 seçenek) | Tamam | |
| CSV / JSON dışa aktarma, yedek/geri yükleme | Tamam | Kaynak ve tarih sütunlarıyla. |
| Favoriler, karşılaştırma listesi | Tamam | Favori arayüzde ekler; liste görünümü sınırlı. |
| Google Trends | **Yok** | Bu sürümde uygulanmadı. |
| Tampermonkey modülü | **Yok** | Plan: [docs/ROADMAP.md](docs/ROADMAP.md). |
| Mobil kullanılabilirlik | Kısmi | Duyarlı CSS ve jsdom ile DOM testi yapıldı; gerçek cihazda görsel test yapılmadı. |

---

## 4. Veri kaynakları ve alan kökenleri
Her alanın kaynağı veritabanında (`Apps`, `AppSnapshots`, `Sources`) ayrıca saklanır. Ayrıntılı tablo:
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).

Kısaca:
- **Google Play detay sayfası** (`/store/apps/details`): ad, paket, geliştirici, kategori, puan, yorum sayısı, indirme
  aralığı, son güncelleme, ücret/reklam/IAP etiketleri.
- **AppBrain uygulama sayfası** (`/app/<paket>`): ilk yayın ayı, 30 gün ve toplam yükleme tahmini, sıralama, benzer
  uygulamalar.
- **Manuel içe aktarma**: yorumlar, gelir kanıtları, paket listeleri.

---

## 5. Politika ve nazik tarama
- Yalnızca izinli yollar çağrılır. `fetcher.policy_check` yasaklı yolları **kod tarafında engeller** (test edilir).
- Host başına istekler arasında en az **3 saniye** (`PLAYSCOUT_MIN_INTERVAL`).
- Önbellek: Play 7 gün, AppBrain 1 gün. Önbellekteki veri aynı çalıştırmada yeniden çekilmez.
- Yeniden deneme: en fazla 2 kez, artan bekleme; 429'da `Retry-After`.
- Bir host'ta 5 ardışık hata olursa o çalıştırmada devre kesici açılır.
- CAPTCHA/"unusual traffic" sayfası algılanırsa kayıt "bot koruması" olarak işaretlenir; **aşmaya çalışılmaz**.
- Kaynak erişilemezse çalıştırma **çökmez**; kaynak hatası istatistiklerde raporlanır ve diğer kaynaklarla devam edilir.
- Sunucu varsayılan olarak yalnızca `127.0.0.1` dinler. Kimlik doğrulaması yoktur; ağa açmayın.

---

## 6. Doğrulama ve testler

63 otomatik test (`tests/`), sahte ağ (`tests/helpers.FakeOpener`) ile çalışır:

- Ayrıştırıcılar: indirme aralıkları (alt sınır), "54.2M", "3,960,725", ay/yıl tarihleri, bot-engel sayfası.
- Tarih mantığı: 1/6 ay, özel aralık, ay sonu taşmaları, tarihi bilinmeyenlerin açık dâhil/hariç kuralı.
- İndirme eşiği: 500K+ ile 1M eşiği (elenir), 10M+ ile 5M üst sınırı (kesin elenir).
- Yorum analizi: küçük örneklemde değişim hesaplanmaz, tekrar yorumlar tekilleştirilir, CSV içe aktarma.
- Gelir kanıtı: kanıt yoksa durum 4, kaynaksız doğrudan kanıt kabul edilmez.
- Pipeline: tekilleştirme, Mod 1 sıkı alaka, geri dönüş, kaynak erişilemezliği, çevrimdışı mod (0 istek),
  yeniden açılınca veri korunması, yasaklı yolların hiç istenmemesi.
- HTTP sunucusu: doğrulama hataları (400), yol geçişi engeli, bozuk JSON, karşılaştırma ve yedek uç noktaları.

Ek olarak yapılan uçtan uca kontroller (arayüz duman testi `tests/ui/smoke.js`, jsdom gerektirir):
- **Canlı başarısızlık yolu**: sandbox'ta Play ve AppBrain'e ağ erişimi yoktur. Gerçek bir arama çalıştırıldı;
  bağlantı hataları yeniden denenip raporlandı, süreç çökmedi, çalıştırma kaydı oluşturuldu.
- **Arayüz (jsdom, gerçek DOM)**: sayfa yüklemesi, filtre değişimi, eleme açıklaması, detay kartı, kart görünümü,
  sıralama sonrası düğme bağlarının korunması, karşılaştırma sayacı. Bu sırada bulunan iki hata düzeltildi
  (varsayılan 6 ay filtresi ve sıralamada düğmelerin kopması).

Spec 17. bölüm eşlemesi:

| # | Test | Durum |
|---|---|---|
| 1 | Boş arama | Otomatik (pipeline + HTTP) |
| 2 | Geçersiz anahtar kelime | Otomatik |
| 3 | Son 1 ay | Otomatik (pencere hesabı); canlı veriyle doğrulanmadı |
| 4 | Son 6 ay | Otomatik + jsdom |
| 5 | 1 milyon indirme | Otomatik |
| 6 | Birden fazla filtre | Otomatik |
| 7 | Yayın tarihi olmayan | Otomatik |
| 8 | Aynı uygulama birden fazla sorguda | Otomatik (aynı çalıştırmada). Çalıştırmalar arası tekilleştirme veritabanı anahtarıyla sağlanır. |
| 9 | Kaynak erişilemiyor | Otomatik + **canlı** (sandbox) |
| 10 | Yetersiz sonuç | Otomatik (shortfall mesajı) |
| 11 | CSV / JSON | Otomatik + `examples/` |
| 12 | Yeniden açılınca veri korunması | Otomatik (DB yeniden açılır) |
| 13 | Yanlış/eski veri işaretleme | Otomatik (bayat zaman damgası) |
| 14 | Gelir kanıtı yok → doğru etiket | Otomatik |
| 15 | Mobil kullanılabilirlik | Kısmi (CSS + DOM; gerçek cihaz testi yok) |

**Canlı Play/AppBrain testi yapılamadı.** Sandbox dış sitelere erişemiyor. Ayrıştırıcılar, fetch aracıyla 2026-10-12
tarihinde okunan gerçek sayfa değerlerinden türetilmiş sentetik HTML'lerle test edildi (bkz. `tests/fixtures/README.md`).
Sayfa yapısı değişirse `python -m playscout doctor --network` ile kendi makinenizde kontrol edin.

---

## 7. Örnek çıktılar
- [examples/sample_run.json](examples/sample_run.json) — tam araştırma çıktısı (fikstür tabanlı).
- [examples/sample_export.csv](examples/sample_export.csv) — CSV dışa aktarma örneği.
- [examples/README.md](examples/README.md) — bu örneklerin nasıl üretildiği ve neyi göstermediği.

---

## 8. Bilinen hatalar ve sınırlamalar
1. **Keşif sınırı:** Niş girişinden otomatik Play araması yapılmaz (robots.txt). Yeterli aday için tohum vermeniz gerekir.
2. **Tam eşleşme modunda** ek anahtar kelimeler alaka hesabında kullanılmaz; yalnızca niş metni geçerlidir.
3. **İlk yayın tarihi** Play'de yoktur; AppBrain'in ay hassasiyetli tarihi kullanılır. Gün bazında kesin değildir.
4. **AppBrain yükleme sayıları tahmindir**; Play'in indirme aralıkları da kesin sayı değildir (alt sınır).
5. **Yorumlar otomatik toplanmaz.** Yorum analizi yalnızca içe aktarılan veriler için yapılır.
6. **Abonelik tespiti güvenilir değildir**; sayfada açıkça belirtilmiyorsa "bilinmiyor" kalır.
7. **Ayrıştırıcılar metin/etiket tabanlıdır.** Play sayfası yapısı değişirse alanlar boş (bilinmiyor) kalır, sistem çökmez,
   ancak doğruluk düşebilir.
8. **Yeniden markalama ipucu** basit ad benzerliği + aynı geliştirici ile çalışır; doğrulanmış değildir.
9. **Google Trends yok**; "son 30 gün büyüme" yalnızca AppBrain tahmini veya ardışık snapshot indirme alt sınırı
   artışından gelir.
10. **Yerel arayüz kimlik doğrulaması içermez.** Varsayılan `127.0.0.1`.
11. **Ölçekleme:** Her aday iki istek (Play + AppBrain) gerektirir; 40 aday ≈ 4–5 dakika (nazik hız sınırı nedeniyle).
    Büyük listeler için çalıştırmayı parçalara bölün.

---

## 9. Proje yapısı
```
playscout/
  config.py      ayarlar, izinli host/yollar, önbellek TTL, ağırlıklar
  db.py          SQLite şeması (istenen tablolar + yardımcı tablolar), kaynaklar
  fetcher.py     nazik HTTP istemcisi: politika, önbellek, hız sınırı, yeniden deneme, devre kesici
  parsers.py     saf ayrıştırıcılar (Play, AppBrain, sayı/tarih)
  keywords.py    niş doğrulama, Mod 1/2 üretimi, alaka, geri dönüş
  pipeline.py    araştırma akışı ve kalıcı kayıt
  reviews.py     yorum analiz motoru ve içe aktarma
  revenue.py     gelir kanıtı durumları (1–4)
  scoring.py     fırsat puanı ve kanıt güveni
  filters.py     filtre, eleme açıklaması, sıralama
  manual.py      yorum/kanıt/karşılaştırma manuel işlemleri, rakip kartı
  exporter.py    CSV/JSON dışa aktarma ve yedekten içe aktarma
  server.py      HTTP API ve arayüz sunucusu
  cli.py         komut satırı
web/             index.html, app.js, style.css
tests/           63 birim/entegrasyon testi + fikstürler
examples/        örnek çıktılar ve üretim betiği
docs/            veri kaynakları, yol haritası
```

## 10. Ağırlıklı fırsat puanı (özet)
| Bileşen | Ağırlık | Nasıl hesaplanır |
|---|---|---|
| Talep ve indirme | 20 | İndirme alt sınırı (log ölçeği) %60 + yorum sayısı %40; AppBrain 30 gün tahmini varsa +%10 |
| Yaş ve büyüme | 15 | Doğrulanmış ilk yayın yaşı + AppBrain 30 gün/toplam oranı |
| Şikâyetler | 20 | En yüksek tekil şikâyet oranı (yeterli örneklemde) %70 + 1–2★ oranı %30; örneklem küçükse nötr |
| Gelir kanıtı | 20 | Durum 1: %100, 2: %70, 3: %40, 4: nötr %50 |
| Zayıf rakipler | 15 | Aynı kategorideki rakiplerin %'si (puan<4.0 veya şikâyet>%30) |
| Uygulanabilirlik | 10 | Son güncelleme ≤90 gün tam; ≥100M indirme için %30 indirim |

Ağırlıklar arayüzde/API'de değiştirilebilir ve 100'e normalize edilir. Kanıt güveni, dolu olan 8 alan sayısından türetilir
(≥7 yüksek, 4–6 orta, diğer düşük).
