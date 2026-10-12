"""Örnek araştırmayı YEREL FİKSTÜRLERDEN üretir (ağ kullanmaz).

Girdiler: tests/fixtures (2026-10-12 tarihinde Play/AppBrain sayfa değerlerinden türetilmiş sentetik HTML).
Çıktılar: examples/sample_run.json, examples/sample_export.csv, data/demo.db (git dışı).
Kullanım: python examples/make_demo.py
"""
import json
import pathlib
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playscout import db, exporter, pipeline, server  # noqa: E402
from tests.helpers import FakeOpener  # noqa: E402
from tests.test_pipeline import make_fetcher, routes  # noqa: E402

TODAY = date(2026, 10, 12)


def main():
    demo = ROOT / "data" / "demo.db"
    if demo.exists():
        demo.unlink()
    conn = db.connect(demo)
    params = {"niche": "AI photo editor", "mode": "discovery",
              "seeds": "com.photoroom.app\ncom.google.android.apps.photos",
              "filters": {}, "max_candidates": 10}
    res = pipeline.run_search(conn, params, fetcher=make_fetcher(conn, FakeOpener(routes())),
                              today=TODAY)
    body = server.run_results(conn, res["run_id"], {"filters": params["filters"], "limit": 50})
    out_json = ROOT / "examples" / "sample_run.json"
    out_json.write_text(exporter.views_to_json(body["results"], run=body["run"], filters=params["filters"],
                                               explain=body["filter_explanation"]), encoding="utf-8")
    (ROOT / "examples" / "sample_export.csv").write_text(exporter.views_to_csv(body["results"]), encoding="utf-8-sig")
    print("run", res["run_id"], res["status"], json.dumps(res["stats"], ensure_ascii=False)[:400])
    print("counts", body["counts"], "shortfall", (body["shortfall"] or {}).get("message"))


if __name__ == "__main__":
    main()
