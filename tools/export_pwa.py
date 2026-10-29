"""يكتب pwa/news.json و pwa/meta.json من الأرشيف (آخر 72 ساعة) لنسخة الهاتف المستقلة من «هوبي عاجل»."""
import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from marsad import core  # noqa: E402
from marsad.report import cluster_dossier  # noqa: E402
from marsad.textnorm import iso, now_utc  # noqa: E402
from tools.export_app import status_of  # noqa: E402


import re  # noqa: E402

URL_RX = re.compile(r"https?://\S+|t\.me/\S+|www\.\S+")
SIG_RX = re.compile(r"(الدائرة الاعلامية|المكتب الاعلامي|المكتب الإعلامي|الدائرة الإعلامية|تابعونا|للاشتراك|رابط القناة)")
FLAG_RX = re.compile(r"(^|\s|[🔴🚨⭕️🔻])عاجل")


def clean_title(label, texts):
    """عنوان مقروء: يتجاهل الروابط وتواقيع القنوات، ويأخذ أول سطر له معنى."""
    def ok(line):
        line = URL_RX.sub("", line).strip(" -–|:🔻🔴📌⭕️🚨•")
        return line if len(line) >= 20 and not (SIG_RX.search(line) and len(line) < 45) else ""
    if ok(label or ""):
        return ok(label)
    for t in texts:
        for line in (t or "").split("\n"):
            if ok(line):
                return ok(line)[:200]
    joined = URL_RX.sub("", " ".join((texts[0] if texts else label or "").split())).strip()
    return (joined or label or "")[:200]


def main(hours=72):
    con = core.connect()
    now = now_utc()
    out = []
    for c in con.execute("SELECT * FROM clusters WHERE last_utc >= ?", (iso(now - timedelta(hours=hours)),)):
        d = cluster_dossier(con, c)
        st, basis = status_of(d)
        ev = sorted(d["evidence"], key=lambda e: e["time"] or "")
        texts = [r[0] or "" for r in con.execute("SELECT COALESCE(text, title) FROM items WHERE cluster_id=? ORDER BY published_utc", (c["id"],))]
        level = d["level"]
        if level not in ("عاجل", "مهم") and any(FLAG_RX.search(t[:80]) for t in texts):
            level = "مهم"  # المصدر نفسه وسمه «عاجل»
        regs = {r[0] or "" for r in con.execute("SELECT s.region FROM items i JOIN sources s ON s.id=i.source_id WHERE i.cluster_id=?", (c["id"],))}
        scope = "إقليمي" if regs and all(r.startswith("إقليمي") for r in regs) else "العراق"
        out.append({"id": c["id"], "title": clean_title(d["label"], texts), "status": st, "basis": basis, "level": level, "scope": scope,
                    "first_utc": d["first"], "latest_utc": max((e["time"] for e in ev if e["time"]), default=None),
                    "date_confirmed": all(e["date_confirmed"] for e in ev), "n_sources": d["n_sources"],
                    "sources": [{"name": e["source"], "url": e["url"], "time": e["time"]} for e in ev][:6]})
    out.sort(key=lambda x: x["latest_utc"] or "", reverse=True)
    pwa = ROOT / "pwa"
    (pwa / "news.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    hl = core.health(con, now)
    ok = [h["name"] for h in hl if h["state"] == "يعمل"]
    cnt = dict(con.execute("SELECT source_id, COUNT(*) FROM items WHERE published_utc >= ? GROUP BY source_id", (iso(now - timedelta(hours=24)),)).fetchall())
    act = {r[0] for r in con.execute("SELECT id FROM sources WHERE method IN ('rss','telegram_preview')")}
    (pwa / "health.json").write_text(json.dumps([{"name": h["name"], "state": h["state"], "items_24h": cnt.get(h["id"], 0), "last_success": h["last_success"], "error": h["last_error"]}
                                                 for h in hl if h["id"] in act], ensure_ascii=False), encoding="utf-8")
    (pwa / "meta.json").write_text(json.dumps({"updated_utc": iso(now), "stories": len(out), "sources_ok": len(ok)},
                                              ensure_ascii=False), encoding="utf-8")
    print(len(out), "خبراً في pwa/news.json")


if __name__ == "__main__":
    main()
