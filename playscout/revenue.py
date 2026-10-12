"""Gelir kanıtı sınıflandırması. Uydurma gelir, reklam oranı veya dönüşüm tahmini YOKTUR.

Durumlar:
  1 = Doğrudan gelir kanıtı bulundu (geliştirici açıklaması / güvenilir rapor / doğrulanabilir ürün)
  2 = Gelir modeli mevcut, gerçek gelir doğrulanmadı (reklam, IAP, abonelik, ücretli)
  3 = Ticari potansiyel var ama kanıt zayıf (ör. AppBrain'de Top Grossing sıralaması)
  4 = Gelir hakkında yeterli veri yok
"""
DIRECT_KINDS = {"developer_disclosed", "reliable_report", "verifiable_product"}
STATUS_LABELS = {
    1: "Doğrudan gelir kanıtı bulundu",
    2: "Gelir modeli mevcut, gerçek gelir doğrulanmadı",
    3: "Ticari potansiyel var, kanıt zayıf",
    4: "Gelir hakkında yeterli veri yok",
}
STATUS_SCORE = {1: 1.0, 2: 0.7, 3: 0.4, 4: 0.5}  # 4: nötr (cezalandırma yok)


def classify(app, evidence_rows, appbrain_rank=None):
    """app: Apps satırı (dict); evidence_rows: RevenueEvidence satırları; appbrain_rank: metin.
    Dönüş: {status, label, signals, proofs, missing}."""
    proofs = []
    for e in evidence_rows:
        if e["kind"] in DIRECT_KINDS and e.get("url"):
            proofs.append({"kind": e["kind"], "description": e.get("description"), "url": e["url"],
                           "date": e.get("evidence_date"), "source": "manuel kanıt"})
    if proofs:
        return _out(1, proofs, [], [])

    signals = []
    if app.get("price_type") == "paid":
        signals.append({"signal": "ücretli uygulama", "source": "Google Play", "detail": app.get("price_text")})
    if app.get("has_ads"):
        signals.append({"signal": "reklam içeriyor", "source": "Google Play", "detail": "'Contains ads' etiketi"})
    if app.get("has_iap"):
        signals.append({"signal": "uygulama içi satın alma", "source": "Google Play", "detail": "IAP etiketi"})
    if app.get("has_subscription"):
        signals.append({"signal": "abonelik", "source": "manuel kanıt", "detail": "abonelik işaretli"})
    if signals:
        return _out(2, proofs, signals, [])

    weak = []
    if appbrain_rank and "Top Grossing" in appbrain_rank:
        weak.append({"signal": "AppBrain'de Top Grossing sıralamasında görünüyor", "source": "AppBrain",
                     "detail": appbrain_rank})
    if any(e["kind"] == "commercial_potential" for e in evidence_rows):
        weak.append({"signal": "manuel: ticari potansiyel notu", "source": "manuel kanıt", "detail": None})
    if weak:
        return _out(3, proofs, weak, [])
    missing = ["gerçek aylık gelir", "gerçek kâr", "aktif kullanıcı sayısı", "kullanıcı başına gelir",
               "pazarlama maliyeti"]
    return _out(4, proofs, [], missing)


def _out(status, proofs, signals, missing):
    return {"status": status, "label": STATUS_LABELS[status], "proofs": proofs,
            "signals": signals, "missing": missing}
