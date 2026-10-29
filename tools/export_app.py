"""يصدّر أخبار آخر 48 ساعة من الأرشيف إلى وثائق تطبيق «هوبي عاجل» (خبر واحد لكل حدث مع مصادره).
الناتج: exports/app_docs/batch_N.json (كل ملف ≤ 50 كتابة) تُرسل بأداة ArtifactData batch."""
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from marsad import core  # noqa: E402
from marsad.report import cluster_dossier  # noqa: E402
from marsad.textnorm import iso, now_utc  # noqa: E402

HOURS = 48


def status_of(d):
    v = d["verification"]
    kinds = {e["kind"] for e in d["evidence"]}
    if "ادعاء من مصدر غير مسمى" in kinds and not v.startswith("مصدر رسمي"):
        return "غير مؤكد", "مصدر غير مسمّى"
    if v.startswith("مصدر رسمي"):
        return "مؤكد", "صادر عن الجهة الرسمية نفسها"
    if d["n_sources"] >= 2 and "نقل عن إعلام أجنبي" not in kinds:
        return "متطابق لدى جهتين", f"منشور لدى {d['n_sources']} جهات، قد تنقل عن بعضها"
    if v.startswith("وكالة/إعلام رسمي"):
        return "غير مؤكد", "وكالة رسمية تنقل، والجهة المُصدِرة لم تُفتح"
    return "غير مؤكد", "جهة واحدة"


def main():
    con = core.connect()
    now = now_utc()
    since = iso(now - timedelta(hours=HOURS))
    docs = []
    for c in con.execute("SELECT * FROM clusters WHERE last_utc >= ?", (since,)):
        d = cluster_dossier(con, c)
        st, basis = status_of(d)
        ev = sorted(d["evidence"], key=lambda e: e["time"] or "")
        latest = max((e["time"] for e in ev if e["time"]), default=None)
        docs.append({"id": c["id"], "data": {
            "title": d["label"], "status": st, "basis": basis, "level": d["level"],
            "first_utc": d["first"], "latest_utc": latest,
            "date_confirmed": all(e["date_confirmed"] for e in ev),
            "sources": [{"name": e["source"], "url": e["url"], "time": e["time"], "confirmed": e["date_confirmed"]}
                        for e in ev][:6],
            "n_sources": d["n_sources"], "watchlists": d["watchlists"]}})
    out = ROOT / "exports" / "app_docs"
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.json"):
        f.unlink()
    writes = [{"op": "set", "collection": "news", "doc_id": x["id"], "data": x["data"]} for x in docs]
    meta = {"updated_utc": iso(now), "window_hours": HOURS, "stories": len(docs),
            "sources_checked": sorted({s["name"] for x in docs for s in x["data"]["sources"]}),
            "note": "تحديث يدوي من المحادثة. الرصد كل 10 دقائق غير مفعّل بعد."}
    writes.append({"op": "set", "collection": "meta", "doc_id": "status", "data": meta})
    for i in range(0, len(writes), 50):
        (out / f"batch_{i // 50 + 1}.json").write_text(json.dumps(writes[i:i + 50], ensure_ascii=False), encoding="utf-8")
    from collections import Counter
    print(len(docs), "خبراً؛", Counter(x["data"]["status"] for x in docs), "؛ ملفات:", len(list(out.glob('*.json'))))


if __name__ == "__main__":
    main()
