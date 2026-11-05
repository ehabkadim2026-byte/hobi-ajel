"""لوحة السَّبق: لكل منشور في قناتنا (الجولة الرئيسية والمسار السريع معاً) نقارن وقت نشره الفعلي بأول نشر للخبر نفسه لدى المنافسين.

- منشوراتنا وأوقاتها الحقيقية من صفحة القناة العامة (t.me/s/…)، تُطابق مع أحداث الرصد ببصمة العنوان.
- وقت المنافس = أقدم وقت نشر للحدث لدى مصادر config/competitors.json (تلغرام ومواقع مباشرة فقط).
- سبب التأخر: إذا رصدنا الخبر قبل المنافس ونشرنا بعده = «تأخر النشر عندنا»؛ وإذا لم نرصده إلا بعده = «مصدر الخبر لم يُرصد مبكراً».
- «فاتنا»: أحداث عراقية كبيرة (15 جهة فأكثر، عاجل/مهم) لم ننشرها.
الناتج pwa/scoop.json + تقرير يومي للمحررين بالخاص (11 مساءً بغداد) يبدأ بسطر «📊 أداء اليوم» (kpi). يقرأ فقط، لا ينشر في القناة.
"""
import html as H
import json
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import tg_push as T  # noqa: E402

CFG = json.loads((ROOT / "config" / "competitors.json").read_text(encoding="utf-8"))["groups"]
SRC2NAME = {s: g for g, ids in CFG.items() for s in ids}
UA = {"User-Agent": "Mozilla/5.0"}
LAST_POSTS = []


def _dt(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def is_iraqi(title):
    """المقياس الصادق: علامة عراقية صريحة أو خبر جهة رسمية محلية بلا علامة أجنبية — لا يكفي غياب اسم دولة أجنبية."""
    return T.iraq_strict(title) or T.iraq_domestic(title)


def own_posts(hours=26):
    ch = T.CHANNEL.rstrip("/").split("/")[-1]
    now = datetime.now(timezone.utc)
    out, before = [], ""
    for _ in range(8):
        page = urllib.request.urlopen(urllib.request.Request(f"https://t.me/s/{ch}{before}", headers=UA), timeout=20).read().decode("utf-8", "replace")
        blocks = page.split('class="tgme_widget_message_wrap')[1:]
        if not blocks:
            break
        got = []
        for b in blocks:
            pid = re.search(rf'data-post="{ch}/(\d+)"', b)
            t = re.search(r'<time[^>]+datetime="([^"]+)"', b)
            tx = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', b, re.S)
            v = re.search(r'tgme_widget_message_views">([^<]+)<', b)
            if not (pid and t and tx):
                continue
            text = H.unescape(re.sub(r"<br\s*/?>", "\n", tx.group(1)))
            text = re.sub(r"<[^>]+>", "", text)
            first = next((ln.strip() for ln in text.split("\n") if len(ln.split()) >= 4), "")
            first = re.sub(r"^\W*(🔴|🔄|🧭|🌱)?\s*(عاجل|تحديث|تحليل خبري)?\s*[|:]?\s*", "", first)
            vs = (v.group(1).strip().upper() if v else "0")
            try:
                views = int(float(vs.rstrip("KM")) * (1000 if vs.endswith("K") else 1_000_000 if vs.endswith("M") else 1))
            except ValueError:
                views = 0
            got.append({"msg": int(pid.group(1)), "t": datetime.fromisoformat(t.group(1)), "title": first[:200], "views": views,
                        "brk": "عاجل |" in text[:40],
                        "kind": "تحليل" if "تحليل خبري" in text[:40] else "تحديث" if "تحديث |" in text[:30] else "منوعات" if "#منوعات" in text else "خبر"})
        out += got
        if not got or min(p["t"] for p in got) < now - timedelta(hours=hours):
            break
        before = f"?before={min(p['msg'] for p in got)}"
    return [p for p in out if p["t"] >= now - timedelta(hours=hours)]


def build(db_path=None):
    from marsad import core
    now = datetime.now(timezone.utc)
    news = json.loads((ROOT / "pwa" / "news.json").read_text(encoding="utf-8"))
    T.build_idf([x.get("title") or "" for x in news])
    sigs = [(T.title_sig(n.get("title") or ""), n) for n in news]
    con = core.connect(db_path) if db_path else core.connect()
    con.row_factory = sqlite3.Row
    posts = own_posts()
    LAST_POSTS[:] = posts
    rows, matched = [], set()
    comp_ids = list(SRC2NAME)
    q = ",".join("?" * len(comp_ids))
    for p in sorted(posts, key=lambda x: x["t"]):
        if p["kind"] in ("تحليل", "تحديث") or not p["title"]:
            continue
        ps = T.title_sig(p["title"])
        hits = [n for s, n in sigs if T.same_story(ps, {"w": sorted(s[0]), "d": sorted(s[1])})]
        if not hits:
            rows.append({"title": p["title"], "our": p["t"].isoformat(), "msg": p["msg"], "views": p["views"], "status": "غير مطابق"})
            continue
        n = max(hits, key=lambda x: x.get("n_sources") or 1)
        matched.add(n["id"])
        lo = (p["t"] - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")  # الحدث الواحد قد يضم مواد أقدم مدمجة: نقارن بنافذة 3 ساعات قبل منشورنا
        comp = con.execute(f"SELECT source_id, MIN(COALESCE(published_utc, collected_utc)) t FROM items WHERE cluster_id=? AND source_id IN ({q}) "
                           "AND COALESCE(published_utc, collected_utc) >= ? GROUP BY source_id", [n["id"]] + comp_ids + [lo]).fetchall()
        det = con.execute("SELECT MIN(collected_utc) FROM items WHERE cluster_id=? AND collected_utc >= ?", (n["id"], lo)).fetchone()[0]
        firsts = sorted(((_dt(r["t"]), SRC2NAME[r["source_id"]]) for r in comp if _dt(r["t"])), key=lambda x: x[0])
        row = {"id": n["id"], "title": p["title"], "our": p["t"].isoformat(), "msg": p["msg"], "views": p["views"], "kind": p["kind"],
               "n_sources": n.get("n_sources"), "detected": det}
        if not firsts:
            row.update({"status": "انفراد", "note": "لم ينشره أي منافس مرصود"})
        else:
            ct, cname = firsts[0]
            d = (p["t"] - ct).total_seconds() / 60
            row.update({"comp": cname, "comp_t": ct.isoformat(), "delta_min": round(d, 1),
                        "status": "سبقنا" if d < -1 else "متقارب" if d <= 2 else "تأخرنا"})
            if d > 2:
                row["foreign"] = not is_iraqi(p["title"])  # تأخر في خبر غير عراقي: لا يُقاس عليه سبق قناة أخبار العراق
                dt_det = _dt(det)
                row["why"] = ("تأخر النشر عندنا (رصدناه قبل المنافس)" if dt_det and dt_det <= ct
                              else "مصدر الخبر لم يُرصد مبكراً")
            row["beat"] = [c for t, c in firsts if t > p["t"]][:6]
        rows.append(row)
    missed = []
    for n in news:
        if n["id"] in matched or not n.get("about_iraq") or (n.get("n_sources") or 1) < 15:
            continue
        if n.get("level") not in ("عاجل", "مهم") and not n.get("source_flag"):
            continue
        if (n.get("first_utc") or "") < (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M"):
            continue
        if not is_iraqi(n.get("title") or ""):
            continue  # خبر أجنبي (الانتخابات الأمريكية…) ليس «فاتنا»: القناة لا تنشره أصلاً (تحليل السبق 2026-11-04)
        missed.append({"id": n["id"], "title": n["title"][:160], "n_sources": n.get("n_sources"), "first": n.get("first_utc")})
    missed.sort(key=lambda x: -(x["n_sources"] or 0))
    cmp = [r for r in rows if r.get("status") in ("سبقنا", "متقارب", "تأخرنا")]
    summ = {k: sum(1 for r in rows if r.get("status") == k) for k in ("سبقنا", "متقارب", "تأخرنا", "انفراد", "غير مطابق")}
    summ["فاتنا"] = len(missed)
    summ["تأخرنا_غير_عراقي"] = sum(1 for r in rows if r.get("status") == "تأخرنا" and r.get("foreign"))
    deltas = sorted(r["delta_min"] for r in cmp)
    summ["median_delta_min"] = deltas[len(deltas) // 2] if deltas else None
    by = {}
    for r in cmp:
        b = by.setdefault(r["comp"], {"first_vs_us": 0, "n": 0})
        b["n"] += 1
        b["first_vs_us"] += r["status"] == "تأخرنا"
    why = {}
    for r in rows:
        if r.get("why"):
            why[r["why"]] = why.get(r["why"], 0) + 1
    out = {"updated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "summary": summ, "why": why, "beaten_by": by,
           "rows": rows[-250:], "missed": missed[:40]}  # كل صفوف اليوم: سقف 120 كان يُسقط أقدم 4 «تأخرنا» و8 «فاتنا» من التحليل
    (ROOT / "pwa" / "scoop.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def _median(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def kpi(o, posts=None, fast=None, main=None, con=None, now=None):
    """سطر الأداء اليومي للمالك (أعلى تقرير 11 مساءً): من بيانات السبق نفسها + بصمات المسارين على إصدار fastlane.
    نسبة السبق = «سبقنا» من الأخبار المشتركة مع المنافسين اليوم (سبقنا+متقارب+تأخرنا، بلا التأخر في خبر غير عراقي كما في لوحة السبق).
    وقت النشر بعد المصدر: المسار السريع من lag_min المسجل لحظة النشر، والجولة = وقت النشر − أقدم نشر لعنقود الخبر (نافذة 3 ساعات)."""
    now = now or datetime.now(timezone.utc)
    bgd = now + timedelta(hours=3)
    day0 = datetime(bgd.year, bgd.month, bgd.day, tzinfo=timezone.utc) - timedelta(hours=3)
    rows = [r for r in o.get("rows", []) if (_dt(r.get("our")) or now) >= day0]
    shared = [r for r in rows if r.get("status") in ("سبقنا", "متقارب") or (r.get("status") == "تأخرنا" and not r.get("foreign"))]
    win = sum(1 for r in shared if r["status"] == "سبقنا")
    pct = round(100 * win / len(shared)) if shared else None
    t0 = day0.timestamp()
    fl = [x["lag_min"] for x in (fast or []) if x.get("ts", 0) >= t0 and isinstance(x.get("lag_min"), (int, float)) and x["lag_min"] >= 0]
    ml = []
    if con is not None:
        for x in main or []:
            cid = str(x.get("id") or "")
            if x.get("ts", 0) < t0 or not cid.startswith("c_"):
                continue
            ts = datetime.fromtimestamp(x["ts"], timezone.utc)
            try:
                f = con.execute("SELECT MIN(COALESCE(published_utc, collected_utc)) FROM items WHERE cluster_id=? AND COALESCE(published_utc, collected_utc) >= ?",
                                (cid, (ts - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ"))).fetchone()[0]
            except Exception:  # noqa: BLE001
                f = None
            d = _dt(f)
            if d and 0 <= (ts - d).total_seconds() <= 3 * 3600:
                ml.append((ts - d).total_seconds() / 60)
    allm = _median(fl + ml)
    fm, mm = _median(fl), _median(ml)
    n_posts = sum(1 for p in (posts or []) if p["t"] >= day0) if posts else sum(1 for x in (fast or []) + (main or []) if x.get("ts", 0) >= t0)
    na = "—"
    return (f"📊 أداء اليوم: سبقنا {f'{pct}%' if pct is not None else na} من الأخبار المشتركة مع المنافسين ({win}/{len(shared)})"
            f" | وسيط وقت النشر بعد المصدر {f'{round(allm, 1)} دقيقة' if allm is not None else na}"
            f" (المسار السريع {f'{round(fm * 60)}ث' if fm is not None else na}، الجولة {f'{round(mm)}د' if mm is not None else na})"
            f" | فاتنا {o.get('summary', {}).get('فاتنا', 0)} خبر عراقي مهم | منشورات اليوم {n_posts}")


def report(o):
    s = o["summary"]
    L = [f"🏁 تقرير السبق — آخر 24 ساعة",
         f"سبقنا المنافسين: {s['سبقنا']} · متقارب (±2 د): {s['متقارب']} · تأخرنا: {s['تأخرنا']} · انفراد: {s['انفراد']} · فاتنا: {s['فاتنا']}"]
    if s.get("median_delta_min") is not None:
        L.append(f"الفارق الوسيط عن أول منافس: {s['median_delta_min']} دقيقة (السالب = سبقناهم)")
    if o["why"]:
        L.append("أسباب التأخر: " + "، ".join(f"{k} ({v})" for k, v in o["why"].items()))
    top = sorted(o["beaten_by"].items(), key=lambda kv: -kv[1]["first_vs_us"])[:4]
    if top and top[0][1]["first_vs_us"]:
        L.append("أكثر من سبقنا: " + "، ".join(f"{k} ({v['first_vs_us']})" for k, v in top if v["first_vs_us"]))
    late = sorted([r for r in o["rows"] if r.get("status") == "تأخرنا"], key=lambda r: -r["delta_min"])[:5]
    if late:
        L += ["", "أكبر تأخر:"] + [f"• +{int(r['delta_min'])} د عن {r['comp']} — {r['title'][:80]}" for r in late]
    win = sorted([r for r in o["rows"] if r.get("status") == "سبقنا"], key=lambda r: r["delta_min"])[:3]
    if win:
        L += ["", "أبرز سبق:"] + [f"• {int(-r['delta_min'])} د قبل {r['comp']} — {r['title'][:80]}" for r in win]
    if o["missed"]:
        L += ["", "أخبار كبيرة فاتتنا:"] + [f"• {m['title'][:90]} ({m['n_sources']} جهة)" for m in o["missed"][:5]]
    L.append("\nملاحظة: التوقيت من صفحات القنوات العامة ومواقع المنافسين كما رصدناها؛ المنافس قد يكون نشر قبل ذلك في منصة أخرى.")
    return "\n".join(L)


def main():
    import os
    o = build()
    s = o["summary"]
    print(f"::notice title=scoop::{json.dumps(s, ensure_ascii=False)} why={json.dumps(o['why'], ensure_ascii=False)}")
    bgd = datetime.now(timezone.utc) + timedelta(hours=3)
    sent = T.load(T.SENT, {})
    token = os.environ.get("MARSAD_TG_BOT_TOKEN", "").strip()
    # حلقة التعلّم: تسجيل المشاهدات كل جولة، وتحديث معاملات الاهتمام مرة كل ساعة، وتقرير أسبوعي للمحررين (الجمعة 10 مساءً)
    from tools import learn as LN
    log = LN.record(sent, LAST_POSTS)
    if (sent.get("_learn") or {}).get("updated", "")[:13] != datetime.now(timezone.utc).strftime("%Y-%m-%dT%H"):
        sent["_learn"] = LN.analyse(log)
        (ROOT / "pwa" / "learn.json").write_text(json.dumps(sent["_learn"], ensure_ascii=False), encoding="utf-8")
        print(f"::notice title=learn::{json.dumps({'n': sent['_learn']['n'], 'active': sent['_learn']['active'], 'lift': sent['_learn']['lift']}, ensure_ascii=False)}")
    wk = bgd.strftime("%G-W%V")
    if token and bgd.weekday() == 4 and bgd.hour == 22 and sent.get("_learn_week") != wk:
        r = LN.weekly_report(sent["_learn"])
        for c in (sent.get("_editor_chats") or {}).values():
            try:
                if r:
                    T.api(token, "sendMessage", chat_id=c, text=r[:4000], disable_web_page_preview="true")
            except Exception:  # noqa: BLE001
                pass
        sent["_learn_week"] = wk
    T.SENT.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")
    if token and bgd.hour == 23 and sent.get("_scoop_day") != bgd.strftime("%Y-%m-%d"):
        try:  # سطر الأداء اليومي أعلى التقرير نفسه (رسالة واحدة، حارس _scoop_day نفسه)؛ فشله لا يمنع التقرير
            from marsad import core
            head = kpi(o, LAST_POSTS, T.fastlane_sigs(), T.fastlane_sigs("main_sigs.json"), core.connect())
            print(f"::notice title=kpi::{head}")
        except Exception as e:  # noqa: BLE001
            head = ""
            print("::warning title=kpi::", type(e).__name__, str(e)[:150])
        try:  # سطر الضبط الذاتي للمسار السريع (tools/auto_tune.py)
            from tools import auto_tune as AT
            head = "\n".join(x for x in (head, AT.summary_line(T.fastlane_sigs(AT.ASSET))) if x)
        except Exception:  # noqa: BLE001
            pass
        text = (head + "\n\n" + report(o)) if head else report(o)
        for c in (sent.get("_editor_chats") or {}).values():
            try:
                T.api(token, "sendMessage", chat_id=c, text=text[:4000], disable_web_page_preview="true")
            except Exception:  # noqa: BLE001
                pass
        sent["_scoop_day"] = bgd.strftime("%Y-%m-%d")
        T.SENT.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
