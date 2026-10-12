# Arayüz duman testi (jsdom)

Gerçek bir DOM'da sayfayı yükler, filtre değiştirir, detay kartını açar, sıralar ve karşılaştırma ekler.

```bash
npm install --prefix tests/ui jsdom@24          # bir kerelik, isteğe bağlı
PLAYSCOUT_DATA=/tmp/ps-demo python -m playscout serve --port 8000 &   # demo veriyle (examples/make_demo.py ile hazırlanan DB'yi kopyalayın)
node tests/ui/smoke.js                          # PLAYSCOUT_URL ile başka adres verilebilir
```

Not: `node_modules` git'e eklenmez (.gitignore).
