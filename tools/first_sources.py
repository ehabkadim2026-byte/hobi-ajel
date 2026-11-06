"""من يسبقنا؟ تحليل للقراءة فقط (لا ينشر).

1) للأحداث العراقية الكبيرة خلال آخر 72 ساعة (6 جهات فأكثر): أقدم مصدر نشرها بين ما نجمعه، وهل هو ضمن المسار السريع.
   المصدر الأول الذي لا يراقبه المسار السريع = مرشح للإضافة (نلتقطه بثوانٍ بدل جولة الـ10 دقائق).
2) قنوات تلغرام يذكرها الآخرون (روابط t.me و@) ولسنا نتابعها أصلاً = مصادر خارج رادارنا.
الناتج: سطور notice في السجل + data/first_sources.json.
"""
import collections
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import tg_push as T  # noqa: E402

HOURS, MIN_SRC = 72, 6


def handles():
    fl = json.loads((ROOT / "config" / "fastlane.json").read_text(encoding="utf-8"))
    fast = {h.lower() for k in ("channels", "breaking", "hot", "agency", "intl") for h in (fl.get(k) or []) if isinstance(h, str)}
    fast_rss = {re.sub(r"^https?://(www\.)?", "", (r.get("url") if isinstance(r, dict) else r) or "").split("/")[0].lower()
                for r in (fl.get("rss") or [])}
    src = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))["sources"]
    known = {s["id"].split(":", 1)[1].lower() for s in src if s["id"].startswith("telegram:")}
    return fast, fast_rss, known | fast


def main():
    fast, fast_rss, known = handles()
    db = sqlite3.connect(ROOT / "data" / "marsad.db")
    db.row_factory = sqlite3.Row
    since = (datetime.now(timezone.utc) - timedelta(hours=HOURS)).strftime("%Y-%m-%dT%H:%M")
    cl = db.execute("SELECT id, title, n_sources FROM clusters WHERE last_utc >= ? AND n_sources >= ?", (since, MIN_SRC)).fetchall()
    first = collections.Counter()
    first_out = collections.Counter()
    names, examples = {}, collections.defaultdict(list)
    lead = []
    for c in cl:
        t = c["title"] or ""
        if not T.iraq_title(t):
            continue
        rows = db.execute("SELECT source_id, source_name, platform, published_utc, url FROM items WHERE cluster_id=? AND published_utc IS NOT NULL "
                          "ORDER BY published_utc LIMIT 2", (c["id"],)).fetchall()
        if not rows:
            continue
        r = rows[0]
        sid = r["source_id"] or ""
        key = sid.split(":", 1)[1].lower() if ":" in sid else sid.lower()
        dom = re.sub(r"^https?://(www\.)?", "", r["url"] or "").split("/")[0].lower()
        in_fast = key in fast or (r["platform"] == "rss" and dom in fast_rss)
        first[sid] += 1
        names[sid] = r["source_name"]
        if not in_fast:
            first_out[sid] += 1
            if len(examples[sid]) < 2:
                examples[sid].append(t[:70])
        gap = None
        if len(rows) > 1:
            try:
                gap = (datetime.fromisoformat(rows[1]["published_utc"].replace("Z", "+00:00")) -
                       datetime.fromisoformat(r["published_utc"].replace("Z", "+00:00"))).total_seconds() / 60
            except Exception:  # noqa: BLE001
                pass
        lead.append({"sid": sid, "in_fast": in_fast, "lead_min": gap, "n": c["n_sources"]})
    # قنوات يذكرها الآخرون ولسنا نتابعها
    ment = collections.Counter()
    for (txt,) in db.execute("SELECT text FROM items WHERE platform='telegram' AND published_utc >= ?", (since,)):
        for h in set(re.findall(r"(?:t\.me/|@)([A-Za-z][A-Za-z0-9_]{4,31})", txt or "")):
            hl = h.lower()
            if hl not in known and not hl.endswith("bot") and hl not in ("joinchat", "share", "s", "c", "addlist", "akamedia_iq"):
                ment[hl] += 1
    tot = sum(first.values())
    out = {"hours": HOURS, "events": tot, "first_in_fast": tot - sum(first_out.values()),
           "first_outside_fast": [{"sid": s, "name": names.get(s), "n": n, "ex": examples[s]} for s, n in first_out.most_common(25)],
           "first_all": [{"sid": s, "name": names.get(s), "n": n} for s, n in first.most_common(25)],
           "mentioned_unknown": ment.most_common(40)}
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "first_sources.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"::notice title=first::أحداث {tot}، أولها ضمن المسار السريع {out['first_in_fast']}")
    for x in out["first_outside_fast"]:
        print(f"::notice title=first-outside::{x['n']} | {x['sid']} | {x['name']} | {' ؛ '.join(x['ex'])}")
    for h, n in out["mentioned_unknown"]:
        print(f"::notice title=mentioned::{n} | {h}")


if __name__ == "__main__":
    main()
