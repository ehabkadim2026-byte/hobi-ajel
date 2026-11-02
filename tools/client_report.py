"""تقرير المرصد المخصص لجهة/شخصية/موضوع (خدمة مدفوعة): ملخص الإشارات خلال فترة، أبرز الأحداث وأول ناشر، توزيع الناشرين،
التصريحات المنسوبة، الادعاءات المتداولة غير المؤكدة ومؤشر انتشارها، وحدود التغطية. يُولّد من قاعدة الرصد مباشرة.

الاستعمال: python3 -m tools.client_report --watch nasr --days 7 --out data/report_nasr.html
لا يُنشر على موقع التطبيق العام؛ يُرسل للمحررين/العميل فقط. لا يستنتج مشاعر الجمهور ولا «رأياً عاماً»، ولا يتهم أحداً.
"""
import argparse
import html as H
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
AR_M = ["كانون الثاني", "شباط", "آذار", "نيسان", "أيار", "حزيران", "تموز", "آب", "أيلول", "تشرين الأول", "تشرين الثاني", "كانون الأول"]


def _dt(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def bgd(s, fmt="dt"):
    d = _dt(s) if isinstance(s, str) else s
    if not d:
        return "—"
    d = d + timedelta(hours=3)
    return f"{d.day} {AR_M[d.month - 1]}" if fmt == "d" else f"{d.day} {AR_M[d.month - 1]} · {d:%H:%M}"


def kind_of(r):
    if r["official"]:
        return "رسمي"
    u = (r["url"] or "").lower()
    if "news.google.com" in u:
        return "Google News"
    if r["platform"] == "telegram" or "t.me/" in u:
        return "تلغرام"
    return "مواقع إخبارية"


def clean_src(n):
    return re.sub(r"\s*[—-]\s*(telegram|RSS|يوتيوب)$", "", n or "", flags=re.I).strip()


def collect(con, wl, end, days):
    start, prev = end - timedelta(days=days), end - timedelta(days=2 * days)
    terms = wl.get("terms") or []
    like = " OR ".join(["i.watchlists LIKE ?"] + ["i.title LIKE ?" for _ in terms] + ["i.text LIKE ?" for _ in terms])
    args = [f"%{wl['id']}%"] + [f"%{t}%" for t in terms] * 2
    q = (f"SELECT i.*, s.official, s.category FROM items i LEFT JOIN sources s ON s.id=i.source_id "
         f"WHERE ({like}) AND i.collected_utc >= ? AND i.collected_utc < ?")
    cur = con.execute(q, args + [start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")]).fetchall()
    from marsad.textnorm import norm_ar
    exc = [norm_ar(x) for x in wl.get("exclude", [])]
    strong = [norm_ar(x) for x in wl.get("strong", [])]
    amb = {norm_ar(k): [norm_ar(c) for c in v] for k, v in (wl.get("ambiguous") or {}).items()}

    def keep(r):
        t = norm_ar((r["title"] or "") + " " + (r["text"] or ""))
        if any(x in t for x in exc):
            return False  # أسماء متشابهة لأشخاص آخرين
        if not strong and not amb:
            return True
        if any(x in t for x in strong):
            return True
        return any(k in t and any(c in t for c in ctx) for k, ctx in amb.items())  # اللقب وحده لا يكفي إلا مع سياق يميّز الشخص
    cur = [r for r in cur if keep(r)]
    old = con.execute(f"SELECT COUNT(*) FROM items i WHERE ({like}) AND i.collected_utc >= ? AND i.collected_utc < ?",
                      args + [prev.strftime("%Y-%m-%dT%H:%M:%SZ"), start.strftime("%Y-%m-%dT%H:%M:%SZ")]).fetchone()[0]
    return cur, old, start


def build(watch_id, days=7, db=None, end=None):
    from marsad import core
    from tools import analysis as A, verify as V
    wls = {w["id"]: w for w in json.loads((ROOT / "config" / "watchlists.json").read_text(encoding="utf-8"))["watchlists"]}
    wl = wls[watch_id]
    con = core.connect(db) if db else core.connect()
    con.row_factory = sqlite3.Row
    if end is None:
        end = _dt(con.execute("SELECT MAX(collected_utc) FROM items").fetchone()[0]) or datetime.now(timezone.utc)
    rows, old_n, start = collect(con, wl, end, days)
    srcs = Counter(clean_src(r["source_name"]) for r in rows)
    kinds = Counter(kind_of(r) for r in rows)
    per_day = Counter((_dt(r["published_utc"] or r["collected_utc"]) + timedelta(hours=3)).strftime("%Y-%m-%d") for r in rows if _dt(r["published_utc"] or r["collected_utc"]))
    days_l = [((end - timedelta(days=days - 1 - k)) + timedelta(hours=3)).strftime("%Y-%m-%d") for k in range(days)]
    by_c = {}
    for r in rows:
        by_c.setdefault(r["cluster_id"], []).append(r)
    events = []
    for cid, rs in by_c.items():
        c = con.execute("SELECT * FROM clusters WHERE id=?", (cid,)).fetchone()
        allr = con.execute("SELECT i.*, s.official, s.category FROM items i LEFT JOIN sources s ON s.id=i.source_id WHERE i.cluster_id=? "
                           "ORDER BY COALESCE(i.published_utc, i.collected_utc)", (cid,)).fetchall()
        first = allr[0] if allr else rs[0]
        va = V.assess([dict(x) for x in allr], None)
        from tools.editorial import pick_best, clean_headline
        cands = [x["title"] or "" for x in allr if x["title"] and "http" not in (x["title"] or "") and "تحية" not in (x["title"] or "")]
        title = clean_headline(pick_best(cands or [x["title"] or "" for x in rs]))
        events.append({"id": cid, "title": re.sub(r"^[\W_]+", "", title)[:180], "n_sources": len({x["source_id"] for x in allr}),
                       "mentions": len(rs), "first_src": clean_src(first["source_name"]), "first_t": first["published_utc"] or first["collected_utc"],
                       "url": first["url"], "vstatus": va.get("vstatus") or "غير متحقق", "official": any(x["official"] for x in allr),
                       "denial": any(V.is_denial(x["title"] or "") for x in allr), "rows": allr})
    from tools import tg_push as T
    events = [e for e in events if T.iraq_title(e["title"]) and not T.far_title(e["title"])]  # تقرير عراقي: لا أخبار أجنبية بلا صلة
    events.sort(key=lambda e: (-e["n_sources"], e["first_t"] or ""))
    quotes, seenq = [], set()
    if wl.get("strong"):  # ملف شخصية: «الاسم: النص»
        names = [t for t in wl["strong"] + list((wl.get("ambiguous") or {}).keys())]
        qrx = re.compile(r"^\W*(?:[^:]{0,40}?)(" + "|".join(map(re.escape, names)) + r")[^:]{0,40}:\s*(.{20,220})")
        pool = rows
    else:  # ملف موضوع: تصريحات الجهات الرسمية «الجهة: النص»
        qrx = re.compile(r"^\W*([^:«»]{3,40}):\s*(.{20,220})")
        pool = [r for r in rows if r["official"]]
    for r in sorted(pool, key=lambda r: r["published_utc"] or r["collected_utc"] or ""):
        t = " ".join((r["title"] or "").split())
        m = qrx.match(t)
        if m and len(m.group(2).split()) >= 5:
            k = m.group(2)[:50]
            if k not in seenq:
                seenq.add(k)
                who = m.group(1).strip() if not wl.get("strong") else ""
                quotes.append({"text": m.group(2).strip(" «»\"•"), "src": (who + " — " if who else "") + clean_src(r["source_name"]),
                               "t": r["published_utc"] or r["collected_utc"], "url": r["url"]})
    claims = []
    for e in events:
        if e["vstatus"] in ("غير متحقق", "متنازع عليه") and not e["official"] and e["n_sources"] >= 4 and len(e["title"].split()) >= 6:
            sp = A.spread(e["id"], e["title"], e["rows"], {"vstatus": e["vstatus"]}) if e["n_sources"] >= A.SPREAD_MIN else None
            claims.append({**{k: e[k] for k in ("title", "n_sources", "first_src", "first_t", "url", "vstatus", "denial")},
                           "score": sp["score"] if sp else None, "band": sp["band"] if sp else None})
    actions = []
    if claims:
        actions.append(f"مراجعة {len(claims)} رواية متداولة بلا مصدر رسمي قبل التعامل معها كواقعة، ومتابعة ما إذا صدر تأكيد أو نفي.")
    if any(c.get("band") == "مرتفع" for c in claims):
        actions.append("رواية واحدة على الأقل بنمط انتشار مرتفع التشابه مع الحملات المنسّقة: يوصى بالتحقق من مصدرها الأول قبل أي رد.")
    if any(e["denial"] for e in events):
        actions.append("ظهر نفي أو تصحيح ضمن التغطية: مقارنة الروايتين وتوثيق التسلسل الزمني.")
    top_src = srcs.most_common(1)
    if top_src and rows and top_src[0][1] / len(rows) > 0.25:
        actions.append(f"«{top_src[0][0]}» وحده نشر {round(100 * top_src[0][1] / len(rows))}% من الإشارات: تنويع المصادر عند قراءة الصورة.")
    if not actions:
        actions.append("لا توجد ادعاءات متداولة غير مؤكدة بحجم يستدعي متابعة خاصة خلال الفترة.")
    n_sources_total = con.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    return {"wl": wl, "start": start, "end": end, "days": days, "rows": rows, "old_n": old_n, "srcs": srcs, "kinds": kinds,
            "per_day": [(d, per_day.get(d, 0)) for d in days_l], "events": events[:12], "n_events": len(events), "quotes": quotes[:8],
            "claims": claims[:6], "actions": actions, "n_sources_total": n_sources_total}


CSS = """
:root{--paper:#f6f8fb;--card:#ffffff;--ink:#0d1b33;--muted:#5d6b82;--line:#dde3ec;--accent:#0e5a8a;--accent-soft:#e3eef7;--warn:#b26a00;--warn-soft:#fbf0dc;--crit:#b3261e;--crit-soft:#fbe7e5;--ok:#1f7a4d;--ok-soft:#e2f3ea;--bar:#0e5a8a;
--display:"Readex Pro","Segoe UI",Tahoma,sans-serif;--body:"IBM Plex Sans Arabic","Segoe UI",Tahoma,sans-serif;--num:"IBM Plex Mono",ui-monospace,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#0b1322;--card:#111c30;--ink:#e6ecf5;--muted:#9aa8bf;--line:#22314b;--accent:#6fb4e6;--accent-soft:#16304a;--warn:#f0b35a;--warn-soft:#3a2a10;--crit:#f2877f;--crit-soft:#3d1a18;--ok:#6fd3a0;--ok-soft:#123326;--bar:#6fb4e6;color-scheme:dark}}
:root[data-theme="dark"]{--paper:#0b1322;--card:#111c30;--ink:#e6ecf5;--muted:#9aa8bf;--line:#22314b;--accent:#6fb4e6;--accent-soft:#16304a;--warn:#f0b35a;--warn-soft:#3a2a10;--crit:#f2877f;--crit-soft:#3d1a18;--ok:#6fd3a0;--ok-soft:#123326;--bar:#6fb4e6;color-scheme:dark}
body{background:var(--paper);color:var(--ink);font-family:var(--body);font-size:15px;line-height:1.75;margin:0}
.wrap{max-width:980px;margin:0 auto;padding-block:28px 56px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));display:grid;gap:26px}
header{display:grid;gap:6px;border-bottom:2px solid var(--ink);padding-bottom:16px}
.eyebrow{font-family:var(--display);font-size:12px;letter-spacing:.06em;color:var(--accent);font-weight:600}
h1{font-family:var(--display);font-size:clamp(24px,4.4vw,34px);line-height:1.3;margin:0;text-wrap:balance;font-weight:700}
h2{font-family:var(--display);font-size:19px;margin:0 0 10px;font-weight:600;text-wrap:balance}
.meta{color:var(--muted);font-size:13px;display:flex;flex-wrap:wrap;gap:6px 18px}
.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;display:grid;gap:2px}
.kpi b{font-family:var(--num);font-size:28px;font-weight:600;font-variant-numeric:tabular-nums}
.kpi span{color:var(--muted);font-size:13px}
.delta{font-family:var(--num);font-size:12px}
.up{color:var(--accent)}.down{color:var(--muted)}
section{display:grid;gap:8px;min-width:0}
.grid2{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:22px}
.panel{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;min-width:0}
.tbl{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14px}
th{font-family:var(--display);font-weight:600;font-size:12px;color:var(--muted);text-align:right;border-bottom:1px solid var(--line);padding:8px 6px;letter-spacing:.02em}
td{border-bottom:1px solid var(--line);padding:10px 6px;vertical-align:top}
td.n{font-family:var(--num);font-variant-numeric:tabular-nums;white-space:nowrap}
a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:3px}
a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.st{display:inline-block;font-size:12px;border-radius:99px;padding:1px 9px;white-space:nowrap;font-weight:600}
.s-ok{background:var(--ok-soft);color:var(--ok)}.s-warn{background:var(--warn-soft);color:var(--warn)}.s-crit{background:var(--crit-soft);color:var(--crit)}.s-n{background:var(--accent-soft);color:var(--accent)}
.bars{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;gap:8px;align-items:end;height:150px;padding-top:8px}
.bar{display:grid;gap:4px;justify-items:center;align-content:end;height:100%}
.bar i{display:block;width:70%;background:var(--bar);border-radius:4px 4px 0 0;min-height:2px}
.bar small{font-size:11px;color:var(--muted);white-space:nowrap}
.bar em{font-style:normal;font-family:var(--num);font-size:12px}
.mix{display:grid;gap:8px}
.mix div{display:grid;grid-template-columns:110px minmax(0,1fr) 40px;gap:10px;align-items:center;font-size:13px}
.mix .tr{height:8px;background:var(--accent-soft);border-radius:99px;overflow:hidden}.mix .tr i{display:block;height:100%;background:var(--bar)}
.mix .n{font-family:var(--num);text-align:left}
blockquote{margin:0;padding:10px 14px;border-right:3px solid var(--accent);background:var(--accent-soft);border-radius:0 8px 8px 0;font-size:14px}
blockquote small{display:block;color:var(--muted);font-size:12px;margin-top:4px}
.quotes{display:grid;gap:10px}
ol.actions{margin:0;padding-right:20px;display:grid;gap:6px}
.limits{font-size:13px;color:var(--muted);border-top:1px solid var(--line);padding-top:14px}
@media (max-width:720px){.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.grid2{grid-template-columns:minmax(0,1fr)}.mix div{grid-template-columns:90px minmax(0,1fr) 34px}}
"""


def render(d, fragment=False):
    e = H.escape
    wl, rows = d["wl"], d["rows"]
    n, old = len(rows), d["old_n"]
    delta = (f'<span class="delta {"up" if n >= old else "down"}">{"▲" if n >= old else "▼"} {abs(round(100 * (n - old) / old))}% عن الفترة السابقة</span>'
             if old else '<span class="delta down">لا بيانات للفترة السابقة</span>')
    mx = max([c for _, c in d["per_day"]] or [1]) or 1
    bars = "".join(f'<div class="bar"><em>{c}</em><i style="height:{max(2, round(c / mx * 100))}%"></i><small>{bgd(datetime.fromisoformat(dd + "T09:00:00+03:00").astimezone(timezone.utc), "d")}</small></div>'
                   for dd, c in d["per_day"])
    tot_k = sum(d["kinds"].values()) or 1
    mix = "".join(f'<div><span>{e(k)}</span><span class="tr"><i style="width:{round(v / tot_k * 100)}%"></i></span><span class="n">{v}</span></div>'
                  for k, v in d["kinds"].most_common())
    topsrc = "".join(f'<div><span>{e(k[:18])}</span><span class="tr"><i style="width:{round(v / max(1, d["srcs"].most_common(1)[0][1]) * 100)}%"></i></span><span class="n">{v}</span></div>'
                     for k, v in d["srcs"].most_common(6))
    cls = {"مؤيد بمصادر مستقلة": "s-ok", "منسوب لمصدر رسمي": "s-n", "متنازع عليه": "s-warn", "ثبت عدم صحته": "s-crit"}
    ev = "".join(f'<tr><td><a href="{e(x["url"] or "#")}" target="_blank" rel="noopener">{e(x["title"])}</a></td><td class="n">{x["n_sources"]}</td>'
                 f'<td>{e(x["first_src"][:22])}<br><small style="color:var(--muted)">{bgd(x["first_t"])}</small></td>'
                 f'<td><span class="st {cls.get(x["vstatus"], "s-warn")}">{e(x["vstatus"])}</span></td></tr>' for x in d["events"])
    qs = "".join(f'<blockquote>«{e(q["text"])}»<small>{e(q["src"])} · {bgd(q["t"])} · <a href="{e(q["url"] or "#")}" target="_blank" rel="noopener">المصدر</a></small></blockquote>'
                 for q in d["quotes"]) or '<p style="color:var(--muted)">لم تُرصد تصريحات منسوبة بصيغة «الاسم: …» خلال الفترة.</p>'
    cl = "".join(f'<tr><td><a href="{e(c["url"] or "#")}" target="_blank" rel="noopener">{e(c["title"])}</a></td><td class="n">{c["n_sources"]}</td>'
                 f'<td>{e(c["first_src"][:22])}</td><td>{(str(c["score"]) + "% · " + c["band"]) if c["score"] is not None else "عينة صغيرة"}</td>'
                 f'<td>{"نعم" if c["denial"] else "—"}</td></tr>' for c in d["claims"])
    claims_html = (f'<div class="tbl"><table><thead><tr><th>الرواية</th><th>جهات</th><th>أول ناشر مرصود</th><th>مؤشر نمط الانتشار</th><th>نفي؟</th></tr></thead><tbody>{cl}</tbody></table></div>'
                   '<p style="font-size:13px;color:var(--muted);margin:0">المؤشر يقيس تشابه نمط الانتشار مع الحملات المنسّقة (نص متطابق، اندفاع، مصادر مجهولة، غياب مصدر رسمي)، وهو أولوية تحقق لا حكم بوجود حملة ولا بصحة الرواية.</p>'
                   if d["claims"] else '<p style="color:var(--muted)">لا توجد روايات متداولة غير مؤكدة بحجم يذكر خلال الفترة.</p>')
    acts = "".join(f"<li>{e(a)}</li>" for a in d["actions"])
    title = f"تقرير المرصد — {wl['name'].split('(')[0].strip()}"
    body = f"""<title>مرصد {e(wl['name'].split('(')[0].split('/')[0].strip())}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500;600&family=IBM+Plex+Sans+Arabic:wght@400;500;600&family=Readex+Pro:wght@500;600;700&display=swap">
<style>{CSS}</style>
<div class="wrap" dir="rtl" lang="ar">
<header>
  <span class="eyebrow">مرصد هوبي · تقرير متابعة مخصص</span>
  <h1>{e(title)}</h1>
  <div class="meta"><span>الفترة: {bgd(d["start"])} — {bgd(d["end"])} (توقيت بغداد)</span><span>مصادر المرصد: {d["n_sources_total"]} مصدراً</span><span>المصطلحات: {e("، ".join(wl.get("terms", [])))}</span></div>
</header>
<div class="kpis">
  <div class="kpi"><b>{n}</b><span>إشارة خلال {d["days"]} أيام</span>{delta}</div>
  <div class="kpi"><b>{len(d["srcs"])}</b><span>جهة ناشرة مختلفة</span></div>
  <div class="kpi"><b>{d["n_events"]}</b><span>حدث/قصة مستقلة</span></div>
  <div class="kpi"><b>{len(d["claims"])}</b><span>رواية متداولة غير مؤكدة</span></div>
</div>
<div class="grid2">
  <section class="panel"><h2>الإشارات يومياً</h2><div class="bars" role="img" aria-label="عدد الإشارات لكل يوم">{bars}</div></section>
  <section class="panel"><h2>من نشر</h2><div class="mix">{mix}</div><h2 style="margin-top:14px">أكثر الجهات نشراً</h2><div class="mix">{topsrc}</div></section>
</div>
<section><h2>أبرز الأحداث</h2><div class="panel tbl"><table><thead><tr><th>الحدث</th><th>جهات</th><th>أول ناشر مرصود</th><th>حالة التحقق</th></tr></thead><tbody>{ev}</tbody></table></div></section>
<section><h2>تصريحات منسوبة</h2><div class="quotes">{qs}</div></section>
<section><h2>روايات متداولة غير مؤكدة</h2><div class="panel">{claims_html}</div></section>
<section><h2>إجراءات بحثية مقترحة</h2><div class="panel"><ol class="actions">{acts}</ol></div></section>
<p class="limits">حدود التغطية: التقرير يشمل المصادر المرصودة فقط (تلغرام العام، المواقع، Google News) ولا يشمل فيسبوك وX والمجموعات الخاصة. «أول ناشر» هو أقدم ظهور ضمن ما نرصده وقد يكون الأصل أقدم. عدد الإشارات يقيس حجم التغطية لا الرأي العام، وكثرة الناشرين لا تعني صحة الخبر. لا يتضمن التقرير أحكاماً على النوايا أو اتهامات.</p>
</div>"""
    return body if fragment else f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{body.split("<style>")[0]}<style>{CSS}</style></head><body>{body.split("</style>", 1)[1]}</body></html>'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", required=True)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default=None)
    ap.add_argument("--fragment", action="store_true")
    a = ap.parse_args()
    d = build(a.watch, a.days)
    out = Path(a.out or ROOT / "data" / f"report_{a.watch}.html")
    out.parent.mkdir(exist_ok=True)
    out.write_text(render(d, a.fragment), encoding="utf-8")
    print(f"::notice title=client_report::{a.watch} {len(d['rows'])} إشارة، {d['n_events']} حدث → {out}")


if __name__ == "__main__":
    main()
