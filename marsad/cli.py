"""واجهة الأوامر: python3 -m marsad.cli <أمر>"""
import argparse
import json
import sys
from pathlib import Path

from . import core, report
from .notify import deliver
from .textnorm import to_baghdad


def collect_all(con, limit, priority_only, workers=6):
    """جمع خادمي مباشر (يحتاج شبكة مفتوحة). يحترم حدود الطلبات بتوقف بين المصادر، ويسجل كل فشل كنقطة عمى."""
    from datetime import datetime, timezone
    from .collect import collect_source
    q = "SELECT * FROM sources WHERE method IN ('rss','telegram_preview') AND status NOT IN ('مستبعد')"
    rows = [dict(r) for r in con.execute(q)]
    if priority_only:
        rows = [r for r in rows if r.get("frequency") == "ساعي"]
    rows = rows[:limit]
    last = {}
    for r in con.execute("SELECT source_id, url FROM items WHERE platform='telegram'"):
        n = int(r["url"].rstrip("/").split("/")[-1])
        last[r["source_id"]] = max(last.get(r["source_id"], 0), n)
    batch = {"batch_id": datetime.now(timezone.utc).strftime("srv%Y%m%d%H%M"), "items": [], "failed": []}
    from concurrent.futures import ThreadPoolExecutor

    def one(s):
        try:
            return s, collect_source(s, last), None
        except Exception as e:  # noqa: BLE001
            return s, [], str(e)[:200]
    # جمع متوازٍ بعدد عمال محدود حتى لا نُثقل على تلغرام (حد الطلبات)؛ كل فشل يُسجل نقطة عمى
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for s, items, err in ex.map(one, rows):
            batch["items"] += items
            if err:
                batch["failed"].append({"source_id": s["id"], "reason": err})
    out = core.ROOT / "data" / "inbox" / (batch["batch_id"] + ".json")
    out.write_text(json.dumps(batch, ensure_ascii=False), encoding="utf-8")
    return core.ingest_batch(con, batch)


def main(argv=None):
    p = argparse.ArgumentParser(prog="marsad")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    s = sub.add_parser("sources"); s.add_argument("path", nargs="?", default=str(core.CONFIG / "sources.json"))
    s = sub.add_parser("ingest"); s.add_argument("paths", nargs="+")
    sub.add_parser("process")
    s = sub.add_parser("collect"); s.add_argument("--limit", type=int, default=40)
    s.add_argument("--priority-only", action="store_true")
    s = sub.add_parser("search"); s.add_argument("q", nargs="?", default="")
    for a in ("--platform", "--source", "--watchlist", "--since", "--until", "--verification"):
        s.add_argument(a)
    sub.add_parser("health")
    sub.add_parser("report")
    s = sub.add_parser("notify"); s.add_argument("--deliver", action="store_true")
    sub.add_parser("backup")
    s = sub.add_parser("restore"); s.add_argument("path")
    s = sub.add_parser("feedback"); s.add_argument("item"); s.add_argument("label"); s.add_argument("--note")
    a = p.parse_args(argv)
    con = core.connect()

    if a.cmd == "init":
        print("قاعدة البيانات جاهزة:", core.DB_PATH)
    elif a.cmd == "sources":
        print("مصادر مسجلة/محدثة:", core.import_sources(con, a.path))
    elif a.cmd == "ingest":
        for path in a.paths:
            for f in sorted(Path(path).glob("*.json")) if Path(path).is_dir() else [Path(path)]:
                print(f.name, core.ingest_batch(con, json.loads(f.read_text(encoding="utf-8"))))
    elif a.cmd == "collect":
        print(collect_all(con, a.limit, a.priority_only))
    elif a.cmd == "process":
        print("أخبار مجمّعة:", core.cluster_items(con))
        for lvl, label, new in core.generate_alerts(con):
            print(f"تنبيه [{lvl}] {label} — {new}")
        report.build_report(con)
        print("CSV:", report.export_csv(con))
        print("PDF:", report.export_pdf() or "غير متاح (wkhtmltopdf غير مثبت)")
        report.write_outbox(con)
        print("اللوحة:", report.build_dashboard(con))
        print("نسخة احتياطية:", report.backup())
    elif a.cmd == "search":
        rows = core.search(con, a.q, a.platform, a.source, a.watchlist, a.since, a.until, a.verification)
        for r in rows:
            print(f"{to_baghdad(r['published_utc'])} | {r['source_name']} | {r['title'][:90]} | {r['url']}")
        print(f"— {len(rows)} نتيجة داخل الأرشيف المرصود فقط")
    elif a.cmd == "health":
        for h in core.health(con):
            print(f"{h['state']:<16} {h['platform']:<10} {h['name']}  آخر نجاح: {to_baghdad(h['last_success'])}")
    elif a.cmd == "report":
        report.build_report(con); print(report.EXPORTS / "report.md")
    elif a.cmd == "notify":
        print(deliver(con, dry_run=not a.deliver))
    elif a.cmd == "backup":
        print(report.backup())
    elif a.cmd == "restore":
        print(report.restore(a.path))
    elif a.cmd == "feedback":
        con.execute("INSERT INTO feedback(item_id,label,note,at_utc) VALUES(?,?,?,datetime('now'))",
                    (a.item, a.label, a.note)); con.commit(); print("سُجّل")
    return 0


if __name__ == "__main__":
    sys.exit(main())
