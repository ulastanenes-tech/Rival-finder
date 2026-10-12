# Yol haritası ve tamamlanmayan maddeler

## Bu sürümde tamamlananlar
- Aşama 1: Dashboard, filtreler, mod seçimi, sonuç tablosu/kart görünümü.
- Aşama 2: Play detay toplama, tekilleştirme, uygulama kartları (tohum tabanlı keşif).
- Aşama 3: AppBrain entegrasyonu (ilk yayın ayı, tahmini yüklemeler, benzer uygulamalar), kaynak doğrulama ve
  robots.txt uyumlu politika katmanı.
- Aşama 4: SQLite şeması (istenen tablolar), önbellek, çalıştırma geçmişi, veri koruma.
- Aşama 5: Yorum analiz motoru (manuel içe aktarma), 30/90/180 gün, örnek bağlantılar.
- Aşama 6: Gelir kanıtı durumları, fırsat puanı ve kanıt güveni.
- Aşama 7: CSV/JSON dışa aktarma, yedek, karşılaştırma, hata yönetimi.
- Aşama 8: 63 test, örnek çıktılar, kurulum belgesi (kısmi: performans ölçümü yapılmadı).

## Alaka eşiği (kapatıldı)
`config.RELEVANCE_THRESHOLD = 0.5` tek kaynaktır. Keşif modunda `score >= 0.5` veya türetilmiş terim eşleşmesi; tam eşleşmede tüm niş metni.

## Kalan / sonraki adımlar
1. **Canlı doğrulama:** Kullanıcının makinesinde `python -m playscout doctor --network` ve birkaç gerçek tohumla
   uçtan uca çalıştırma. Sandbox'ta Play/AppBrain'e erişim olmadığı için bu adım yapılamadı.
2. **Google Trends:** robots.txt izin veriyorsa ve yalnızca herkese açık görünüm kullanılırsa eklenecek.
3. **Tampermonkey modülü (plan):**
   - Yalnızca `https://play.google.com/store/apps/details*` ve `https://www.appbrain.com/app/*` sayfalarında çalışır (`@match`).
   - Kullanıcı "PlayScout'a gönder" düğmesine bastığında mevcut sayfanın metnini/etiketlerini yerel
     `http://127.0.0.1:8000/api/import-page` uç noktasına gönderir (kullanıcı eylemiyle tetiklenir).
   - Arka plan taraması yok; sayfa gezinmesinde otomatik istek yok; robots.txt yasaklı yollarda devre dışı.
   - Sunucu tarafında aynı ayrıştırıcılar kullanılır (`parsers.py`), böylece iki kaynak tutarlı kalır.
4. **Arayüz:** Karşılaştırma ekranında yan yana sütunlar ve grafikler; favori listesinin ayrı görünümü.
5. **Performans:** Büyük çalıştırmalar için arka plan işçisi ve sayfalı sonuç API'si.
6. **Yeniden markalama:** Geliştiricinin tüm uygulamalarını (kaynak izin verirse) ve paket geçmişini karşılaştırma.
