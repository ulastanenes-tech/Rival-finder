"use strict";
// PlayScout arayüzü: yalnızca göreli /api URL'leri. Dış veriler esc() ile kaçışlanır.
const $ = (id) => document.getElementById(id);
const state = { meta: null, runId: null, view: "table", results: [], sort: "opportunity", lastParams: null,
  compare: new Set(), filterTimer: null, sortKey: "opportunity", sortDir: 1 };

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const fmt = (n) => (n === null || n === undefined || n === "" ? "bilinmiyor" : Number(n).toLocaleString("tr-TR"));
const fmtDl = (floor, label) => (floor ? `${esc(label || fmt(floor) + "+")}` : "bilinmiyor");
const pct = (x) => (x === null || x === undefined ? "—" : `%${Math.round(x * 100)}`);

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined });
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) throw new Error((data && data.error) || `HTTP ${res.status}`);
  return data;
}

function toast(msg, bad = false) {
  const n = $("notice");
  n.hidden = false;
  n.textContent = msg;
  n.style.color = bad ? "var(--bad)" : "";
  clearTimeout(n._t);
  n._t = setTimeout(() => { n.hidden = true; }, 6000);
}

function fillSelect(sel, items, selected) {
  sel.innerHTML = items.map((o) => `<option value="${esc(o.value)}" ${String(o.value) === String(selected) ? "selected" : ""}>${esc(o.label)}</option>`).join("");
}

function filterDefs() {
  return [
    ["category", "Kategori (metin)", "text"],
    ["price_type", "Ücret türü", "select", [["any", "Hepsi"], ["free", "Ücretsiz"], ["paid", "Ücretli"]]],
    ["has_ads", "Reklam", "select", [["any", "Fark etmez"], ["yes", "Reklam içerenler"], ["no", "Reklam içermeyenler"]]],
    ["has_iap", "Uygulama içi satın alma olanlar", "check"],
    ["has_subscription", "Abonelik (doğrulanabilirse)", "check"],
    ["last_updated_days", "Son güncelleme", "select", [["", "Fark etmez"], ["30", "Son 30 gün"], ["90", "Son 90 gün"], ["180", "Son 180 gün"], ["365", "Son 1 yıl"]]],
    ["new_only", "Yeni yayınlanmış (doğrulanmış, son 6 ay)", "check"],
    ["high_complaints", "Yüksek şikâyet oranı (≥%30)", "check"],
    ["weak_reviews", "Yorumları yetersiz (puan<4.0 veya 1–2★ ≥%30)", "check"],
    ["multi_rivals", "Birden fazla rakibi olan niş", "check"],
    ["multi_app_developer", "Geliştiricinin birden fazla uygulaması", "check"],
    ["growing", "Son dönemde büyüyen", "check"],
    ["missing_data", "Kaynak verisi eksik olanlar", "check"],
    ["max_revenue_status", "Gelir kanıtı en fazla durum", "select", [["", "Fark etmez"], ["1", "1 – doğrudan kanıt"], ["2", "2 – model var"], ["3", "3 – zayıf potansiyel"]]],
    ["min_confidence", "Minimum kanıt güveni", "select", [["", "Fark etmez"], ["düşük", "Düşük+"], ["orta", "Orta+"], ["yüksek", "Yüksek"]]],
    ["min_opportunity", "Minimum fırsat puanı", "number"],
  ];
}

function renderFilters() {
  const html = filterDefs().map(([key, label, type, opts]) => {
    if (type === "check") return `<label class="check"><input type="checkbox" data-f="${key}"> ${esc(label)}</label>`;
    if (type === "select") return `<label class="field">${esc(label)}<select data-f="${key}">${opts.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("")}</select></label>`;
    if (type === "number") return `<label class="field">${esc(label)}<input type="number" min="0" max="100" data-f="${key}"></label>`;
    return `<label class="field">${esc(label)}<input data-f="${key}"></label>`;
  }).join("");
  $("filterGrid").innerHTML = html;
  $("filterGrid").querySelectorAll("[data-f]").forEach((el) => el.addEventListener("change", scheduleResults));
  $("filterGrid").querySelectorAll("input[type=text],input:not([type])").forEach((el) => el.addEventListener("input", scheduleResults));
  const w = state.meta.weights;
  $("weightGrid").innerHTML = Object.keys(w).map((k) => `<label class="field">${esc(state.meta.weight_labels[k])}<input type="number" min="0" step="1" data-w="${k}" value="${w[k]}"></label>`).join("");
}

function collectFilters() {
  const f = {};
  document.querySelectorAll("[data-f]").forEach((el) => {
    const k = el.dataset.f;
    if (el.type === "checkbox") { if (el.checked) f[k] = true; }
    else if (el.tagName === "SELECT") { if (el.value && el.value !== "any") f[k] = el.value; }
    else if (el.value !== "") f[k] = el.type === "number" ? Number(el.value) : el.value;
  });
  if (f.has_ads === undefined) delete f.has_ads;
  if (f.price_type && f.price_type === "any") delete f.price_type;
  if (f.last_updated_days) f.last_updated_days = Number(f.last_updated_days);
  if (f.max_revenue_status) f.max_revenue_status = Number(f.max_revenue_status);
  if (f.min_opportunity !== undefined) f.min_opportunity = Number(f.min_opportunity);
  if (f.min_confidence === "") delete f.min_confidence;
  return f;
}

function collectSearchFilters() {
  const f = {};
  const preset = $("datePreset").value;
  f.date_preset = preset;
  if (preset === "custom") { f.date_from = $("dateFrom").value || null; f.date_to = $("dateTo").value || null; }
  if ($("minDl").value) f.min_downloads = Number($("minDl").value);
  if ($("maxDl").value) f.max_downloads = Number($("maxDl").value);
  if ($("minRating").value) f.min_rating = Number($("minRating").value);
  if ($("maxRating").value) f.max_rating = Number($("maxRating").value);
  if ($("minReviews").value) f.min_reviews = Number($("minReviews").value);
  if ($("includeUnknown").checked) f.include_unknown_dates = true;
  return f;
}

function fullFilters() { return { ...collectSearchFilters(), ...collectFilters() }; }

function scheduleResults() {
  clearTimeout(state.filterTimer);
  state.filterTimer = setTimeout(loadResults, 250);
}

async function loadResults() {
  if (!state.runId) return;
  try {
    const data = await api(`/api/runs/${state.runId}/results`, { method: "POST",
      body: { filters: fullFilters(), sort: state.sort, limit: Number($("limit").value) } });
    state.results = data.results;
    renderCounts(data);
    renderResults(data.results);
  } catch (e) { toast(e.message, true); }
}

function renderCounts(d) {
  const c = d.counts, s = d.stats || {};
  $("counts").innerHTML = [
    `<span class="pill">Bulunan aday: ${fmt(c.candidates_found)}</span>`,
    `<span class="pill ok">Play'de doğrulanan: ${fmt(c.play_verified)}</span>`,
    `<span class="pill">Alakalı: ${fmt(c.relevant)}</span>`,
    `<span class="pill ${c.matching_filters ? "ok" : "warn"}">Filtrelerinize uyan: ${fmt(c.matching_filters)}</span>`,
    `<span class="pill">Gösterilen: ${fmt(c.returned)}</span>`,
    c.unknown_first_release ? `<span class="pill warn">İlk yayın tarihi bilinmeyen: ${fmt(c.unknown_first_release)}</span>` : "",
    s.offline ? `<span class="pill warn">Çevrimdışı veri</span>` : "",
    (s.source_errors || []).length ? `<span class="pill bad">Kaynak hatası: ${s.source_errors.length}</span>` : "",
  ].join("");
  const sf = $("shortfall");
  if (d.shortfall) { sf.hidden = false; sf.textContent = d.shortfall.message; } else sf.hidden = true;
  $("explain").innerHTML = (d.filter_explanation || []).map((e) =>
    `<div>${esc(e.label)}: <b>${e.eliminated}</b> elendi, <b>${e.remaining}</b> kaldı</div>`).join("") || "Etkin filtre yok.";
}

function confChip(c) { return `<span class="chip ${c === "yüksek" ? "ok" : c === "orta" ? "warn" : "bad"}">Kanıt güveni: ${esc(c)}</span>`; }
function revChip(s) {
  const map = { 1: ["ok", "Doğrudan gelir kanıtı"], 2: ["warn", "Model var, gelir doğrulanmadı"], 3: ["warn", "Potansiyel, kanıt zayıf"], 4: ["bad", "Gelir verisi yok"] };
  const [cls, label] = map[s] || ["bad", "—"]; return `<span class="chip ${cls}">${esc(label)}</span>`;
}
function dateCell(a) {
  if (a.first_release_status === "verified" && a.first_release_date) {
    return `${esc(a.first_release_date.slice(0, a.first_release_precision === "month" ? 7 : 10))}<div class="meta">${esc(a.first_release_source || "")}</div>`;
  }
  return `<span class="chip warn">İlk yayın doğrulanmadı</span>`;
}

function renderResults(list) {
  const q = ($("tableFilter").value || "").toLowerCase();
  let rows = list.filter((a) => !q || `${a.title} ${a.package} ${a.developer}`.toLowerCase().includes(q));
  if (state.view === "cards") {
    $("resultsView").innerHTML = `<div class="cards">${rows.map(cardHtml).join("") || emptyHtml()}</div>`;
  } else {
    if (state.sortKey && !["compare", "detail"].includes(state.sortKey)) {
      const k = state.sortKey, dir = state.sortDir;
      rows = [...rows].sort((a, b) => {
        const av = a[k] ?? "", bv = b[k] ?? "";
        return (av > bv ? 1 : av < bv ? -1 : 0) * dir;
      });
    }
    const head = [["title", "Uygulama"], ["opportunity", "Fırsat"], ["confidence", "Güven"], ["download_floor", "İndirme"],
      ["rating", "Puan"], ["review_count", "Yorum"], ["first_release_date", "İlk yayın"], ["last_updated", "Son güncelleme"],
      ["revenue_status", "Gelir kanıtı"], ["complaint_share", "Şikâyet*"], ["missing", "Eksik"], ["compare", "Karşılaştır"], ["detail", ""]];
    $("resultsView").innerHTML = `<div class="table-wrap"><table><thead><tr>${head.map(([k, l]) => `<th data-k="${k}">${esc(l)}${state.sortKey === k ? (state.sortDir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead>
      <tbody>${rows.map(rowHtml).join("") || `<tr><td colspan="${head.length}">${emptyHtml()}</td></tr>`}</tbody></table></div>
      <p class="muted">*Şikâyet oranı yalnızca analiz edilen yorum örneğinin içindeki orandır; tüm kullanıcıların oranı değildir.</p>`;
    $("resultsView").querySelectorAll("th[data-k]").forEach((th) => th.addEventListener("click", () => {
      const k = th.dataset.k;
      if (k === "compare" || k === "detail") return;
      state.sortDir = state.sortKey === k ? -state.sortDir : (k === "title" || k === "missing" ? 1 : -1);
      state.sortKey = k;
      renderResults(state.results);
    }));
  }
  $("resultsView").querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => openDetail(b.dataset.open)));
  $("resultsView").querySelectorAll("[data-cmp]").forEach((b) => b.addEventListener("change", () => {
    const p = b.dataset.cmp; b.checked ? state.compare.add(p) : state.compare.delete(p);
    $("cmpCount").textContent = state.compare.size;
  }));
  $("resultsView").querySelectorAll("[data-fav]").forEach((b) => b.addEventListener("click", async () => {
    try { await api(`/api/apps/${b.dataset.fav}/favorite`, { method: "POST", body: { value: true } }); toast("Favorilere eklendi."); }
    catch (e) { toast(e.message, true); }
  }));
}

function emptyHtml() {
  return `<div class="muted">Bu filtrelerle uygun uygulama yok. Tarih aralığını genişletmeyi, indirme eşiğini düşürmeyi veya filtreleri sıfırlamayı deneyin.</div>`;
}

function rowHtml(a) {
  const icon = a.icon_url ? `<img src="${esc(a.icon_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<img alt="">`;
  const stale = a.stale ? ` <span class="chip warn">eski veri</span>` : "";
  const miss = (a.missing || []).length ? `<span class="chip warn">${a.missing.length} eksik</span>` : `<span class="chip ok">tam</span>`;
  return `<tr>
    <td><div class="app-cell">${icon}<div><b>${esc(a.title || a.package)}</b><div class="muted">${esc(a.package)}</div><div class="muted">${esc(a.developer || "")}</div>${stale}</div></div></td>
    <td><div class="score">${esc(a.opportunity)} <small>/100</small></div></td>
    <td>${confChip(a.confidence)}</td>
    <td>${fmtDl(a.download_floor, a.download_label)}</td>
    <td>${a.rating ?? "bilinmiyor"}</td>
    <td>${esc(a.review_count_label || fmt(a.review_count))}</td>
    <td>${dateCell(a)}</td>
    <td>${esc(a.last_updated || "bilinmiyor")}</td>
    <td>${revChip(a.revenue_status)}</td>
    <td>${a.analysis && !a.analysis.low_sample ? pct(a.complaint_share) : `<span class="muted">örneklem düşük</span>`}</td>
    <td>${miss}</td>
    <td><input type="checkbox" data-cmp="${esc(a.package)}" ${state.compare.has(a.package) ? "checked" : ""} aria-label="Karşılaştırmaya ekle"></td>
    <td><button class="ghost" data-open="${esc(a.package)}">Detaylı analiz</button> <button class="ghost" data-fav="${esc(a.package)}" title="Favori">★</button></td>
  </tr>`;
}

function cardHtml(a) {
  const icon = a.icon_url ? `<img src="${esc(a.icon_url)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : "";
  return `<div class="card">
    <div class="head">${icon}<div><b>${esc(a.title || a.package)}</b><div class="meta">${esc(a.developer || "")}</div></div></div>
    <div class="score">${esc(a.opportunity)} <small>fırsat /100</small></div>
    <div class="chips">${confChip(a.confidence)}${revChip(a.revenue_status)}</div>
    <div class="meta">İndirme: ${fmtDl(a.download_floor, a.download_label)} · Puan: ${a.rating ?? "bilinmiyor"} · Yorum: ${esc(a.review_count_label || fmt(a.review_count))}</div>
    <div class="meta">İlk yayın: ${a.first_release_status === "verified" ? esc(a.first_release_date) : "<b>doğrulanmadı</b>"} · Son güncelleme: ${esc(a.last_updated || "bilinmiyor")}</div>
    <div class="meta">Eksik veri: ${(a.missing || []).length ? esc(a.missing.slice(0, 3).join(", ")) : "yok"}</div>
    <div class="row-between"><label class="check"><input type="checkbox" data-cmp="${esc(a.package)}" ${state.compare.has(a.package) ? "checked" : ""}> karşılaştır</label>
      <button class="ghost" data-open="${esc(a.package)}">Detaylı analiz</button></div>
  </div>`;
}

async function openDetail(pkg) {
  $("drawer").hidden = false;
  $("drawerContent").innerHTML = "Yükleniyor…";
  try {
    const c = await api(`/api/apps/${encodeURIComponent(pkg)}`);
    const a = c.app;
    const view = state.results.find((r) => r.package === pkg) || {};
    const comps = Object.entries(view.components || {}).map(([k, v]) =>
      `<div>${esc(v.label)}: <b>${v.points}</b> / ${v.max} <span class="muted">${esc((v.notes || []).join("; "))}</span></div>`).join("");
    const cats = (c.review_categories || []).map((r) =>
      `<div>${esc(state.meta.review_categories[r.category] || r.category)}: ${r.mention_count} yorum (analiz edilen yorumların %${Math.round(r.share * 100)}) ${r.low_sample ? '<span class="chip warn">düşük örneklem</span>' : ""}${r.example_urls_json && JSON.parse(r.example_urls_json).length ? " · " + JSON.parse(r.example_urls_json).map((u) => `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer">örnek</a>`).join(" ") : ""}</div>`).join("") || `<div class="muted">Yorum örneği yok. Aşağıdan manuel yorum içe aktarabilirsiniz.</div>`;
    const ev = (c.revenue_evidence || []).map((e) => `<div>${esc(e.kind)}: ${esc(e.description || "")} ${e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">kaynak</a>` : ""} <span class="muted">${esc(e.evidence_date || "")}</span></div>`).join("") || `<div class="muted">Manuel gelir kanıtı yok.</div>`;
    const snaps = (c.snapshots || []).slice(0, 8).map((s) => `<tr><td>${esc(s.captured_at)}</td><td>${esc(s.source || "")}</td><td>${s.rating ?? "—"}</td><td>${esc(s.review_count ?? "—")}</td><td>${esc(s.download_floor ?? "—")}</td><td>${esc(s.installs_30d ?? "—")}</td></tr>`).join("");
    const srcs = (view.sources || []).map((s) => `<div>${esc(s.source)} · ${esc(s.date || "tarih yok")} · ${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">bağlantı</a>` : "—"} · ${esc(s.status || "")}</div>`).join("");
    const top = (view.analysis && view.analysis.top_complaints || []).map((t) => `<span class="chip">${esc(t.label)} %${Math.round(t.share * 100)}</span>`).join(" ");
    $("drawerContent").innerHTML = `
      <h2 id="d-title">${esc(a.title || pkg)}</h2>
      <div class="muted">${esc(pkg)} · ${esc(a.developer_name || "")} · ${esc(a.category || "")}</div>
      <p><a href="${esc(a.play_url)}" target="_blank" rel="noopener noreferrer">Google Play sayfası</a>
        · <button class="ghost" id="dFav">★ Favori</button>
        · <button class="ghost" id="dCmp">Karşılaştırmaya ekle</button></p>
      <div class="kv">
        <div>Fırsat puanı (0–100)</div><div><b>${esc(view.opportunity ?? "hesaplanmadı")}</b></div>
        <div>Kanıt güveni</div><div>${esc(view.confidence || "—")}</div>
        <div>Puan / yorum (Play)</div><div>${a.rating ?? "bilinmiyor"} / ${esc(a.review_count_label || fmt(a.review_count))}</div>
        <div>İndirme aralığı (Play)</div><div>${fmtDl(a.download_floor, a.download_label)} <span class="muted">(alt sınır; kesin sayı değildir)</span></div>
        <div>AppBrain 30 gün (tahmin)</div><div>${esc(a.appbrain_installs_30d ? fmt(a.appbrain_installs_30d) : "bilinmiyor")}</div>
        <div>İlk yayın</div><div>${a.first_release_status === "verified" ? `${esc(a.first_release_date)} (${esc(a.first_release_precision)} hassasiyeti) — <span class="muted">${esc(a.first_release_source)}</span>` : "<b>Doğrulanamadı</b> — 'yeni uygulama' olarak etiketlenmez"}</div>
        <div>Son güncelleme</div><div>${esc(a.last_updated || "bilinmiyor")} <span class="muted">${esc(a.last_updated_source || "")}</span></div>
        <div>Ücret / reklam / IAP</div><div>${esc(a.price_type || "?")} · reklam: ${a.has_ads ? "var" : "kanıt yok"} · IAP: ${a.has_iap ? "var" : "kanıt yok"}</div>
        <div>Yeniden markalama ipucu</div><div>${esc(view.rebrand_hint || "yok")}</div>
        <div>Son kontrol</div><div>${esc(a.last_checked_at || "yok")} ${view.stale ? '<span class="chip warn">eski veri</span>' : ""}</div>
      </div>
      <div class="section"><h3>Gelir kanıtı</h3>
        <div>${revChip(view.revenue_status)} ${esc(view.revenue?.label || "")}</div>
        ${(view.revenue?.signals || []).map((s) => `<div>• ${esc(s.signal)} <span class="muted">(${esc(s.source)})</span></div>`).join("")}
        ${ev}
      </div>
      <div class="section"><h3>Kullanıcı şikâyetleri (yalnızca analiz edilen yorumlar)</h3>
        <div>Analiz edilen yorum: <b>${c.review_sample_count}</b> ${view.analysis?.low_sample ? '<span class="chip warn">düşük örneklem — oranlar kesin değildir</span>' : ""}</div>
        <div>${top || ""}</div>${cats}
      </div>
      <div class="section"><h3>Fırsat puanı bileşenleri</h3>${comps || '<div class="muted">Bu uygulama bir araştırma çalıştırmasında değerlendirilmemiş.</div>'}
        <div class="muted">Eksik veriler: ${esc((view.missing || []).join(", ") || "yok")}</div></div>
      <div class="section"><h3>Kaynaklar</h3>${srcs || '<div class="muted">Kaynak kaydı yok.</div>'}
        <table class="snap"><thead><tr><th>Tarih</th><th>Kaynak</th><th>Puan</th><th>Yorum</th><th>İndirme alt sınırı</th><th>30 gün (tahmin)</th></tr></thead><tbody>${snaps}</tbody></table></div>
      <div class="section"><h3>Manuel yorum içe aktarma (CSV/JSON)</h3>
        <p class="muted">Play yorum uç noktaları robots.txt ile yasaklıdır. Yorumları kendi dışa aktarmanızdan veya elle hazırladığınız bir dosyadan (sütun: text, rating, date, version, url) yükleyin.</p>
        <select id="rvFmt"><option value="csv">CSV</option><option value="json">JSON</option></select>
        <textarea id="rvText" rows="4" placeholder="text,rating,date,version&#10;Crashes on launch,1,2026-10-01,3.2.1"></textarea>
        <button class="ghost" id="rvBtn">Yorumları yükle ve analiz et</button></div>
      <div class="section"><h3>Gelir kanıtı ekle (manuel)</h3>
        <p class="muted">Doğrudan kanıt için geliştiricinin açıklaması, güvenilir bir rapor veya doğrulanabilir ürün bağlantısı gerekir.</p>
        <select id="evKind"><option value="developer_disclosed">Geliştirici açıkladı</option><option value="reliable_report">Güvenilir rapor</option><option value="verifiable_product">Doğrulanabilir ürün/abonelik</option><option value="commercial_potential">Ticari potansiyel (zayıf)</option></select>
        <input id="evDesc" placeholder="Açıklama"><input id="evUrl" placeholder="https://… (kaynak)"><input id="evDate" placeholder="YYYY-AA-GG">
        <button class="ghost" id="evBtn">Kanıtı kaydet</button></div>`;
    $("dFav").onclick = async () => { await api(`/api/apps/${encodeURIComponent(pkg)}/favorite`, { method: "POST", body: { value: true } }); toast("Favorilere eklendi."); };
    $("dCmp").onclick = () => { state.compare.add(pkg); $("cmpCount").textContent = state.compare.size; toast("Karşılaştırma listesine eklendi."); };
    $("rvBtn").onclick = async () => {
      try { const r = await api(`/api/apps/${encodeURIComponent(pkg)}/reviews`, { method: "POST", body: { format: $("rvFmt").value, content: $("rvText").value } });
        toast(`Okunan ${r.read}, eklenen ${r.added}. Analiz için araştırmayı yeniden çalıştırın.`); openDetail(pkg); }
      catch (e) { toast(e.message, true); }
    };
    $("evBtn").onclick = async () => {
      try { await api(`/api/apps/${encodeURIComponent(pkg)}/evidence`, { method: "POST", body: { kind: $("evKind").value, description: $("evDesc").value, url: $("evUrl").value || null, date: $("evDate").value || null } });
        toast("Kanıt kaydedildi."); openDetail(pkg); }
      catch (e) { toast(e.message, true); }
    };
  } catch (e) { $("drawerContent").innerHTML = `<div class="err">${esc(e.message)}</div>`; }
}

async function startSearch(params) {
  $("btnRun").disabled = true; $("btnRerun").disabled = true;
  $("progress").hidden = false; $("bar").style.width = "2%"; $("progressText").textContent = "Başlatılıyor…";
  state.lastParams = params;
  try {
    const { job_id } = await api("/api/search", { method: "POST", body: params });
    while (true) {
      await new Promise((r) => setTimeout(r, 1000));
      const j = await api(`/api/jobs/${job_id}`);
      const pct2 = j.total ? Math.max(2, Math.round((j.done / j.total) * 100)) : 5;
      $("bar").style.width = `${j.state === "done" ? 100 : pct2}%`;
      $("progressText").textContent = j.message || j.stage || "";
      if (j.state === "done") {
        state.runId = j.result.run_id;
        await loadRuns(state.runId);
        await loadResults();
        const st = j.result.status;
        toast(st === "completed" ? "Araştırma tamamlandı." : st === "completed_with_errors" ? "Tamamlandı; bazı kaynaklar erişilemedi (ayrıntılar istatistiklerde)." : st === "no_results" ? "Alakalı uygulama bulunamadı. Tohumları veya modu değiştirmeyi deneyin." : "Tamamlandı.", st !== "completed");
        break;
      }
      if (j.state === "error") { toast(j.error, true); break; }
    }
  } catch (e) { toast(e.message, true); }
  finally { $("btnRun").disabled = false; $("btnRerun").disabled = false; setTimeout(() => { $("progress").hidden = true; }, 1500); }
}

function buildParams(evt) {
  const niche = $("niche").value.trim();
  const kw = $("keywords").value.split(",").map((s) => s.trim()).filter(Boolean);
  const seeds = $("seeds").value;
  const weights = {};
  document.querySelectorAll("[data-w]").forEach((el) => { weights[el.dataset.w] = Number(el.value || 0); });
  const params = { niche, mode: document.querySelector("input[name=mode]:checked").value, keywords: kw, seeds,
    country: $("country").value.trim() || "US", offline: $("offline").checked, max_candidates: Number($("maxCandidates").value || 40),
    expand_depth: 1, allow_broaden: true, weights, filters: collectSearchFilters() };
  if (evt === "rerun" && state.lastParams) return { ...state.lastParams, filters: collectSearchFilters() };
  return params;
}

async function loadRuns(select) {
  const { runs } = await api("/api/runs");
  $("savedRuns").innerHTML = `<option value="">Önceki araştırmalar…</option>` + runs.map((r) =>
    `<option value="${r.id}" ${r.id === select ? "selected" : ""}>#${r.id} · ${esc(r.niche)} · ${esc(r.created_at.slice(0, 16).replace("T", " "))} · ${r.relevant_count ?? "?"} sonuç</option>`).join("");
}

function setDateDisplay() {
  const custom = $("datePreset").value === "custom";
  $("dateFrom").disabled = !custom; $("dateTo").disabled = !custom;
}

async function init() {
  state.meta = await api("/api/meta");
  $("ver").textContent = `v${state.meta.version}`;
  $("status").textContent = "Yerel sunucu hazır";
  fillSelect($("datePreset"), state.meta.presets, "none");
  fillSelect($("sort"), state.meta.sorts, "opportunity");
  const dl = [{ value: "", label: "Fark etmez" }].concat(state.meta.download_thresholds.map((n) => ({ value: n, label: `${n.toLocaleString("tr-TR")}+` })));
  fillSelect($("minDl"), dl, ""); fillSelect($("maxDl"), dl.slice(0), "");
  renderFilters();
  $("sourcesBox").innerHTML = state.meta.sources.map((s) => `<div><b>${esc(s.name)}</b><br><span class="muted">${esc(s.purpose)}</span><br><small>${esc(s.policy)}</small></div>`).join("<hr>")
    + `<p><small>${esc(state.meta.limits.search_is_disabled)}</small></p>`;
  $("datePreset").value = "none"; setDateDisplay();
  await loadRuns("");
  const runs = (await api("/api/runs")).runs;
  if (runs.length) { state.runId = runs[0].id; $("savedRuns").value = runs[0].id; await loadResults(); }
  const h = await api("/api/health");
  if (!h.ok) toast("Sunucu yanıt vermiyor.", true);
}

document.addEventListener("DOMContentLoaded", () => {
  init().catch((e) => { $("status").textContent = "Hata"; toast(e.message, true); });

  $("searchForm").addEventListener("submit", (e) => { e.preventDefault(); startSearch(buildParams()); });
  $("btnRerun").addEventListener("click", () => { if (!state.lastParams) return toast("Önce bir araştırma başlatın.", true); startSearch(buildParams("rerun")); });
  $("btnKw").addEventListener("click", async () => {
    try {
      const d = await api(`/api/keywords?niche=${encodeURIComponent($("niche").value)}&mode=${document.querySelector("input[name=mode]:checked").value}`);
      $("keywords").value = d.terms.map((t) => t.term).join(", ");
    } catch (err) { toast(err.message, true); }
  });
  $("datePreset").addEventListener("change", setDateDisplay);
  $("sort").addEventListener("change", () => { state.sort = $("sort").value; loadResults(); });
  $("limit").addEventListener("change", loadResults);
  $("includeUnknown").addEventListener("change", scheduleResults);
  ["dateFrom", "dateTo", "minDl", "maxDl", "minRating", "maxRating", "minReviews"].forEach((id) => $(id).addEventListener("change", scheduleResults));
  $("tableFilter").addEventListener("input", () => renderResults(state.results));
  $("savedRuns").addEventListener("change", async () => {
    if (!$("savedRuns").value) return;
    state.runId = Number($("savedRuns").value);
    const d = await api(`/api/runs/${state.runId}/results`, { method: "POST", body: { limit: 1 } });
    state.lastParams = d.run.params; await loadResults();
    toast(`Araştırma #${state.runId} yeniden açıldı.`);
  });
  $("btnView").addEventListener("click", () => { state.view = state.view === "table" ? "cards" : "table"; $("btnView").textContent = state.view === "table" ? "Kart görünümü" : "Tablo görünümü"; renderResults(state.results); });
  $("btnResetFilters").addEventListener("click", () => {
    document.querySelectorAll("[data-f]").forEach((el) => { if (el.type === "checkbox") el.checked = false; else if (el.tagName === "SELECT") el.value = el.querySelector("option").value; else el.value = ""; });
    ["minDl", "maxDl", "minRating", "maxRating", "minReviews", "dateFrom", "dateTo"].forEach((id) => { $(id).value = ""; });
    $("includeUnknown").checked = false; $("datePreset").value = "none"; setDateDisplay(); loadResults();
  });
  $("btnCsv").addEventListener("click", () => exportRun("csv"));
  $("btnJson").addEventListener("click", () => exportRun("json"));
  $("btnCompare").addEventListener("click", () => saveComparison());
  $("btnShowCmp").addEventListener("click", showComparisons);
  $("btnClose").addEventListener("click", () => { $("drawer").hidden = true; });
  $("btnCmpClose").addEventListener("click", () => { $("cmpModal").hidden = true; });
});

async function exportRun(fmt) {
  if (!state.runId) return toast("Önce bir araştırma yapın.", true);
  const res = await fetch(`/api/runs/${state.runId}/export`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ format: fmt, filters: fullFilters(), sort: state.sort, limit: 100000 }) });
  if (!res.ok) return toast("Dışa aktarma başarısız.", true);
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = `playscout-run-${state.runId}.${fmt}`; a.click();
  URL.revokeObjectURL(a.href);
}

async function saveComparison() {
  const list = [...state.compare];
  if (list.length < 2) return toast("Karşılaştırma için en az iki uygulama işaretleyin.", true);
  const name = prompt("Karşılaştırma adı:", `Karşılaştırma ${new Date().toLocaleDateString("tr-TR")}`);
  if (!name) return;
  try { await api("/api/comparisons", { method: "POST", body: { name, packages: list } }); toast("Karşılaştırma kaydedildi."); showComparisons(); }
  catch (e) { toast(e.message, true); }
}

async function showComparisons() {
  $("cmpModal").hidden = false;
  const { comparisons } = await api("/api/comparisons");
  const byPkg = Object.fromEntries((state.results || []).map((r) => [r.package, r]));
  const parts = comparisons.map((c) => {
    const rows = c.packages.map((p) => {
      const r = byPkg[p] || {};
      return `<tr><td>${esc(r.title || p)}</td><td>${esc(r.opportunity ?? "—")}</td><td>${r.rating ?? "—"}</td><td>${fmtDl(r.download_floor, r.download_label)}</td><td>${revChip(r.revenue_status)}</td><td>${esc(r.first_release_status === "verified" ? r.first_release_date : "doğrulanmadı")}</td><td>${esc(r.last_updated || "—")}</td></tr>`;
    }).join("");
    return `<div class="section"><h3>${esc(c.name)} <button class="ghost" data-del="${c.id}">Sil</button></h3>
      <div class="table-wrap"><table><thead><tr><th>Uygulama</th><th>Fırsat</th><th>Puan</th><th>İndirme</th><th>Gelir kanıtı</th><th>İlk yayın</th><th>Son güncelleme</th></tr></thead><tbody>${rows}</tbody></table></div>
      <small>Karşılaştırmadaki değerler son araştırma sonuçlarından gelir; bilgi yoksa "—" gösterilir.</small></div>`;
  }).join("");
  $("cmpContent").innerHTML = `<h2>Karşılaştırmalar</h2>${parts || '<p class="muted">Henüz kayıtlı karşılaştırma yok. Sonuçlarda uygulamaları işaretleyip "Karşılaştırmaya ekle" düğmesini kullanın.</p>'}`;
  $("cmpContent").querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
    await api(`/api/comparisons/${b.dataset.del}`, { method: "DELETE" }); showComparisons();
  }));
}
