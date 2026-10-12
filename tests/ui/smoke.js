let JSDOM;
try { ({ JSDOM } = require("jsdom")); } catch (e) { console.log("jsdom yok: npm install --prefix tests/ui jsdom@24 çalıştırın"); process.exit(0); }
const BASE = process.env.PLAYSCOUT_URL || "http://127.0.0.1:8000";
(async () => {
  const dom = await JSDOM.fromURL(BASE + "/", {
    runScripts: "dangerously", resources: "usable", pretendToBeVisual: true,
    beforeParse(window) {
      window.fetch = (url, opts) => fetch(new URL(url, BASE).toString(), opts);
      window.prompt = () => "x";
      window.scrollTo = () => {};
      window.URL.createObjectURL = () => "blob:x";
      window.addEventListener("error", (e) => console.log("PAGE ERROR:", e.message));
    },
  });
  const w = dom.window, d = w.document;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  await wait(1500);
  const errs = [];
  console.log("version:", d.getElementById("ver").textContent, "| status:", d.getElementById("status").textContent);
  console.log("runs select options:", d.querySelectorAll("#savedRuns option").length);
  console.log("counts:", d.getElementById("counts").textContent.replace(/\s+/g, " ").trim().slice(0, 240));
  const rows = d.querySelectorAll("#resultsView tbody tr");
  console.log("table rows:", rows.length, "first:", rows[0] && rows[0].textContent.replace(/\s+/g, " ").slice(0, 160));
  // filter: iap only
  const iap = d.querySelector('[data-f="has_iap"]'); iap.checked = true; iap.dispatchEvent(new w.Event("change"));
  await wait(900);
  console.log("after IAP filter counts:", d.getElementById("counts").textContent.replace(/\s+/g, " ").trim().slice(0, 200));
  iap.checked = false; iap.dispatchEvent(new w.Event("change")); await wait(900);
  // date preset 6 -> Photoroom (2020) eliminated: shortfall expected
  const dp = d.getElementById("datePreset"); dp.value = "6"; dp.dispatchEvent(new w.Event("change"));
  d.getElementById("minDl").value = "1000000"; d.getElementById("minDl").dispatchEvent(new w.Event("change"));
  await wait(900);
  console.log("6m+1M counts:", d.getElementById("counts").textContent.replace(/\s+/g, " ").slice(0, 200));
  console.log("shortfall:", d.getElementById("shortfall").hidden ? "(hidden)" : d.getElementById("shortfall").textContent.slice(0, 160));
  console.log("explain:", d.getElementById("explain").textContent.replace(/\s+/g, " ").slice(0, 200));
  // reset
  d.getElementById("btnResetFilters").click(); await wait(900);
  // open detail
  const btn = d.querySelector('[data-open="com.photoroom.app"]');
  btn.click(); await wait(1200);
  const dc = d.getElementById("drawerContent").textContent.replace(/\s+/g, " ");
  console.log("drawer has title:", dc.includes("Photoroom: AI Photo Editor"), "| revenue section:", dc.includes("Gelir kanıtı"), "| sources:", dc.includes("AppBrain uygulama sayfası"));
  console.log("drawer excerpt:", dc.slice(0, 260));
  // card view
  d.getElementById("btnView").click(); await wait(300);
  console.log("cards:", d.querySelectorAll("#resultsView .card").length);
  // sort by clicking header
  d.getElementById("btnView").click(); await wait(300);
  d.querySelector('th[data-k="rating"]').click(); await wait(200);
  console.log("sorted OK rows:", d.querySelectorAll("#resultsView tbody tr").length, "header:", d.querySelector('th[data-k="rating"]').textContent);
  d.querySelector('th[data-k="title"]').click(); await wait(200);
  console.log("re-sorted; open button still bound:", !!d.querySelector('[data-open="com.photoroom.app"]'));
  const ob = d.querySelector('[data-open="com.photoroom.app"]'); ob.click(); await wait(800);
  console.log("drawer after resort:", d.getElementById("drawerContent").textContent.includes("Gelir kanıtı"));
  d.getElementById("btnClose").click();
  // compare & comparisons modal
  d.querySelector('[data-cmp="com.photoroom.app"]').click(); await wait(100);
  console.log("cmp count:", d.getElementById("cmpCount").textContent);
  console.log("done");
  process.exit(0);
})().catch((e) => { console.error("SMOKE FAIL", e); process.exit(1); });
