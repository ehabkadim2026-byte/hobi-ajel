"""واجهة الأوامر: python3 -m marsad.cli <أمر>"""
import argparse
import json
import re
import sys
from pathlib import Path

from . import core, report
from .notify import deliver
from .textnorm import to_baghdad


DEFAULT_PRIORITY = {"قنوات تلغرام": 1, "إعلام عربي وإقليمي": 1, "وكالات ومواقع": 1, "منصات خبرية عراقية": 2, "مواقع عراقية": 2,
                    "صحافة أجنبية": 2, "وكالات عالمية": 2, "تحليل أجنبي": 3, "الحشد الشعبي": 1}


def source_priorities():
    """أولوية كل مصدر: من حقل priority في السجل، أو من فئته، مع تجاوزات config/overrides.json (تعطيل/أولوية)."""
    cfg = json.loads((core.CONFIG / "sources.json").read_text(encoding="utf-8"))["sources"]
    try:
        ov = json.loads((core.CONFIG / "overrides.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        ov = {}
    pr = {}
    for s in cfg:
        p = s.get("priority") or (1 if s.get("method") == "telegram_preview" else DEFAULT_PRIORITY.get(s.get("category"), 2))
        pr[s["id"]] = int(p)
    keymap = {s["url"]: s["id"] for s in cfg}
    for k, v in (ov.get("priority") or {}).items():
        pr[keymap.get(k, k)] = int(v)
    pr["_disabled"] = {keymap.get(k, k) for k in (ov.get("disabled") or [])}
    return pr


# جهات مستبعدة بقرار ثابت من إيهاب: لا تُجمع أبداً حتى لو بقيت بقاعدة البيانات أو أضافها محرك الاكتشاف
EXCLUDED_SRC = re.compile(r"(نجباء|النجباء|كتائب حزب الله|عصائب|العصائب|قناة العهد|alahad|حركة حقوق|المنار|almanar|تسنيم|tasnim|وكالة فارس|farsnews|"
                          r"nujaba|kataib|asaib|pkk|بي كي كي|صابرين|sabren|sabereen|المعلومة|almaalomah|حماس|hamas|حزب الله)", re.I)


def clean_source_name(r):
    """اسم المصدر لازم يكون اسم جهة، مو عنوان خبر (بعض المواقع تضع آخر عنوان باسم الخلاصة)."""
    name = r.get("name") or ""
    base, _, suf = name.rpartition(" — ")
    base = base or name
    if base.strip().lower() not in ("t.me", "telegram.me") and not re.search(r"[ەێۆڵڕڤ]", base) and len(base.split()) <= 6 and not re.search(r"[.!؟?:«»\"]|\b(تعدم|يعلن|تعلن|يستقيل|مقتل|قتلى)\b", base):
        return name
    hl = re.compile(r"[.!؟?:«»\"]|\b(تعدم|يعلن|تعلن|يستقيل|مقتل|قتلى)\b")
    if not re.search(r"[ەێۆڵڕڤ]", base) and not hl.search(base) and base.strip().lower() not in ("t.me", "telegram.me"):
        # اسم جهة رسمي طويل من السجل («رئيس مجلس الوزراء علي فالح الزيدي (القناة الرسمية)»): يُختصر لا يُستبدل بـ«t.me» (3003، فحص 2)
        short = re.sub(r"\s{2,}", " ", re.sub(r"\([^)]*\)|[/|]", " ", base)).strip()
        w = short.split()[:6]
        while w and w[-1] in ("في", "من", "على", "و", "عن", "إلى", "الى", "-", "–"):
            w.pop()
        if len(w) >= 2:
            return " ".join(w) + (f" — {suf}" if suf else "")
    from urllib.parse import urlsplit
    dom = urlsplit(r.get("url") or "").netloc.replace("www.", "") or r["id"].split("/")[-1]
    if dom in ("t.me", "telegram.me"):  # قناة تلغرام: معرّفها لا «t.me» (3003 «📌 المصدر: t.me»، فحص 2)
        dom = "@" + (r.get("url") or r["id"]).rstrip("/").split("/")[-1]
    return f"{dom} — {suf or 'RSS'}"


def gate_sources(con, rows):
    """فلتر صارم قبل الجمع: المصدر لازم يكون بالسجل (sources.json) أو أضافه محرك الاكتشاف، وغير مستبعد، واسمه سليم.
    المحذوف من السجل ما يُجمع (حالة صابرين والمعلومة 04/11 بقت تُجمع من القاعدة بعد حذفها من السجل)."""
    try:
        cfg_ids = {s["id"] for s in json.loads((core.CONFIG / "sources.json").read_text(encoding="utf-8"))["sources"]}
    except Exception:  # noqa: BLE001
        return rows
    keep = []
    for r in rows:
        where = f"{r.get('name') or ''} " + ("" if "news.google.com" in (r.get("url") or r["id"]) else f"{r['id']} {r.get('url') or ''}")
        if EXCLUDED_SRC.search(where) or (r["id"] not in cfg_ids and r.get("added_by") != "محرك الاكتشاف"):
            continue  # لا يُجمع (بدون تغيير حالته بالقاعدة، حتى يرجع تلقائياً إذا رجع للسجل)
        fixed = clean_source_name(r)
        if fixed != r.get("name"):
            con.execute("UPDATE sources SET name=? WHERE id=?", (fixed, r["id"]))
            con.execute("UPDATE items SET source_name=? WHERE source_id=?", (fixed, r["id"]))
            r["name"] = fixed
        keep.append(r)
    try:  # مواد Google News المجموعة سابقاً: اسم ناشر كردي/عنوان يُصحَّح، وناشر مستبعد («المعلومة» عبر بحث عام) يُحذف (فحصا 2 و3)
        from .collect import _gn_outlet
        for (nm,) in con.execute("SELECT DISTINCT source_name FROM items WHERE source_name LIKE '%(عبر Google News)' "
                                 "AND collected_utc >= strftime('%Y-%m-%dT%H:%M:%SZ','now','-2 days')").fetchall():
            base = nm[: -len(" (عبر Google News)")]
            if EXCLUDED_SRC.search(base):
                con.execute("DELETE FROM items WHERE source_name=?", (nm,))
            elif _gn_outlet(base) != base:
                con.execute("UPDATE items SET source_name=? WHERE source_name=?", (_gn_outlet(base) + " (عبر Google News)", nm))
    except Exception:  # noqa: BLE001
        pass
    con.commit()
    return keep


def collect_all(con, limit, priority_only, workers=10):
    """جمع خادمي مباشر (يحتاج شبكة مفتوحة). يحترم حدود الطلبات بتوقف بين المصادر، ويسجل كل فشل كنقطة عمى."""
    from datetime import datetime, timezone, timedelta
    from .collect import collect_source
    import time as _t
    q = "SELECT * FROM sources WHERE method IN ('rss','telegram_preview') AND status NOT IN ('مستبعد')"
    rows = [dict(r) for r in con.execute(q)]
    rows = gate_sources(con, rows)
    if priority_only:
        rows = [r for r in rows if r.get("frequency") == "ساعي"]
    # جدولة متفاوتة حسب الأولوية (من config/sources.json + config/overrides.json، بلا تعديل كود):
    # أولوية 1 كل جولة، 2 كل جولتين، 3 كل 6 جولات. المصدر المتوقف (3 إخفاقات) يُعاد فحصه كل 10 جولات فقط.
    pr = source_priorities()
    run_no = int(_t.time() // 90)
    every = {1: 1, 2: 2, 3: 6}
    def due(r):
        if r["id"] in pr.get("_disabled", set()):
            return False
        # Circuit Breaker بتراجع أُسّي: مصدر كثير الأعطال يُعزل ويُجرَّب بفواصل متزايدة (نصف مفتوح)، حتى لا يهدر وقت الجولة
        f = r.get("consecutive_failures") or 0
        if f >= 10 and run_no % 160:
            return False
        if f >= 6 and run_no % 40:
            return False
        if f >= 3 and run_no % 10:
            return False
        return run_no % every.get(pr.get(r["id"], 2), 2) == 0
    # إصلاح ذاتي: إذا رصد مركز العمليات «الجولات تعمل والجمع متوقف»، تجمع هذه الجولة كل المصادر مرة واحدة
    ops_p = core.ROOT / "data" / "ops_state.json"
    try:
        ops = json.loads(ops_p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        ops = {}
    force_full = bool(ops.get("force_full"))
    if force_full:
        ops["force_full"] = False
        ops_p.write_text(json.dumps(ops, ensure_ascii=False), encoding="utf-8")
        rows = [r for r in rows if r["id"] not in pr.get("_disabled", set())][:max(limit, 600)]
    else:
        rows = [r for r in rows if due(r)][:limit]
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
    batch["ok"] = []
    # استرجاع الفائت: إذا مضى على آخر جمع ناجح أكثر من 10 دقائق (انقطاع)، نقرأ صفحات تلغرام أكثر لاسترجاع ما فات
    from . import collect as _c
    lastrun = con.execute("SELECT MAX(collected_utc) FROM items").fetchone()[0]
    gap_min = (datetime.now(timezone.utc) - datetime.fromisoformat(lastrun.replace("Z", "+00:00"))).total_seconds() / 60 if lastrun else 0
    _c.CATCHUP_PAGES = 10 if (gap_min > 10 or force_full) else 3
    # مهلة كلية للجمع: مصدر بطيء أو معلق لا يوقف الجولة؛ ما لم يكتمل يُسجل فشلاً مؤقتاً ويُجرب بالجولة الجاية
    # خيوط daemon: عند انتهاء المهلة نكمل فوراً ولا ينتظر البرنامج المصادر المعلّقة عند الخروج (كان يطيل الجولة دقائق)
    import queue as _q
    import threading
    jobs, results = _q.Queue(), _q.Queue()
    for s in rows:
        jobs.put(s)

    def worker():
        while True:
            try:
                s = jobs.get_nowait()
            except _q.Empty:
                return
            results.put(one(s))
    for _ in range(workers):
        threading.Thread(target=worker, daemon=True).start()
    deadline = 50 if gap_min <= 10 else 120
    end = _t.time() + deadline
    done_ids = set()
    while len(done_ids) < len(rows) and _t.time() < end:
        try:
            s, items, err = results.get(timeout=max(0.1, end - _t.time()))
        except _q.Empty:
            break
        done_ids.add(s["id"])
        batch["items"] += items
        if err:
            batch["failed"].append({"source_id": s["id"], "reason": err})
        else:
            batch["ok"].append(s["id"])
    unstarted = set()
    while True:  # ما لم يبدأ أصلاً يُترك للجولة الجاية بلا احتسابه فشلاً
        try:
            unstarted.add(jobs.get_nowait()["id"])
        except _q.Empty:
            break
    for s in rows:
        if s["id"] not in done_ids and s["id"] not in unstarted:
            batch["failed"].append({"source_id": s["id"], "reason": f"مهلة الجولة ({deadline} ث) — عُزل مؤقتاً"})
    batch["gap_min"] = round(gap_min, 1)
    print(f"run {run_no}: fetched {len(rows)} sources, {len(batch['failed'])} failed, {len(batch['items'])} items")
    print(f"::notice title=collect::{json.dumps({'sources': len(rows), 'failed': len(batch['failed']), 'items': len(batch['items']), 'gap_min': batch['gap_min'], 'catchup_pages': _c.CATCHUP_PAGES, 'timeouts': sum(1 for f in batch['failed'] if 'مهلة' in f['reason']), 'backfilled_older_than_5m': sum(1 for it in batch['items'] if it.get('published_utc') and str(it['published_utc']) > (lastrun or '') and str(it['published_utc']) < (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M:%SZ'))}, ensure_ascii=False)}")
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
