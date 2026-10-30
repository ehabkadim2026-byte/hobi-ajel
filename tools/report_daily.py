"""التقرير الصباحي (7 صباحاً بغداد، مرة يومياً): HTML قابل للبحث + نص + PDF (إن توفر Chrome) ← يُنشر في التطبيق
pwa/reports/ ويُنسخ احتياطياً إلى إصدار «reports» على GitHub، ويُرسل PDF للمحررين بالخاص عبر البوت.

الأقسام: أهم أخبار العراق (حسب الاستقلالية والمستوى لا العدد وحده)، القضايا الصاعدة والمتراجعة (24 ساعة مقابل 24 قبلها)،
تصريحات الشخصيات والجهات المتابعة، أخبار تحتاج مراجعة (متنازع عليه / متداول غير متحقق / مصدر غير مسمى منتشر)،
وحدود الرصد. لا أرقام «رأي عام» ولا نسب تغطية عامة.
"""
import html
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from marsad import core  # noqa: E402
from marsad.textnorm import iso, now_utc  # noqa: E402
from tools import watch as W  # noqa: E402

PWA = ROOT / "pwa"
REP = PWA / "reports"
APP = "https://ehabkadim2026-byte.github.io/hobi-ajel/"
E = html.escape


def load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def bgt(i):
    if not i:
        return "—"
    d = datetime.fromisoformat(i.replace("Z", "+00:00")) + timedelta(hours=3)
    return d.strftime("%H:%M")


def rising(con, now, follow):
    """أحداث كل قضية/شخصية: آخر 24 ساعة مقابل الـ24 قبلها (من القاعدة، بعدد الأحداث لا النسخ)."""
    m = W.Matcher(follow)
    rows = con.execute("SELECT cluster_id, norm, title, collected_utc FROM items WHERE collected_utc >= ? AND cluster_id IS NOT NULL",
                       (iso(now - timedelta(hours=48)),)).fetchall()
    cur, prev = {}, {}
    cut = iso(now - timedelta(hours=24))
    for r in rows:
        hits = m.match(r["norm"] or "", r["title"] or "", [])
        for h in hits:
            (cur if r["collected_utc"] >= cut else prev).setdefault(h["id"], set()).add(r["cluster_id"])
    names = {f["id"]: f["name"] for f in follow}
    out = []
    for k in set(cur) | set(prev):
        a, b = len(cur.get(k, ())), len(prev.get(k, ()))
        out.append({"id": k, "name": names.get(k, k), "now": a, "before": b, "delta": a - b})
    has_prev = bool(prev)
    return sorted(out, key=lambda x: -x["delta"]), has_prev


def build(now):
    con = core.connect()
    news = load(PWA / "news.json", [])
    metrics = load(PWA / "metrics.json", {})
    follow = W.load()
    day = [n for n in news if n.get("latest_utc") and n["latest_utc"] >= iso(now - timedelta(hours=24))]
    iq = [n for n in day if n.get("about_iraq") and n.get("origin") != "أجنبي"]
    rank = {"عاجل": 3, "مهم": 2, "متابعة": 1}
    vs_rank = {"مؤيد بمصادر مستقلة": 3, "منسوب لمصدر رسمي": 2, "غير متحقق": 1, "متنازع عليه": 1, "ثبت عدم صحته": 0}
    top = sorted(iq, key=lambda n: (-(3 if n.get("source_flag") else rank.get(n.get("level"), 0)), -(n.get("independent") or 1),
                                    -vs_rank.get(n.get("vstatus"), 1), -(n.get("n_sources") or 1)))[:12]
    rise, has_prev = rising(con, now, follow)
    kinds = {f["id"]: f.get("kind") for f in follow}
    persons = [n for n in day if any(kinds.get(w["id"]) in ("person", "institution") for w in n.get("watch") or [])]
    persons = sorted(persons, key=lambda n: n.get("latest_utc") or "", reverse=True)
    persons = sorted(persons, key=lambda n: not any(w.get("prov") == "رصد مباشر" for w in n["watch"]))[:20]
    review = [n for n in day if n.get("vstatus") == "متنازع عليه"]
    review += [n for n in day if n.get("vstatus") == "غير متحقق" and (n.get("n_sources") or 1) >= 3 and n not in review]
    review += [n for n in day if n.get("cited") == "مصدر غير مسمى" and (n.get("n_sources") or 1) >= 2 and n not in review]
    review = review[:15]
    names = {f["id"]: f["name"] for f in follow}
    bgd = now + timedelta(hours=3)
    title = f"التقرير الصباحي — هوبي عاجل — {bgd.strftime('%Y/%m/%d')}"

    def li(n, extra=""):
        s = (n.get("sources") or [{}])[0]
        u = s.get("url") or ""
        return (f"<li><b>{E(n['title'])}</b>{' <i>(ترجمة آلية)</i>' if n.get('title_orig') else ''}<br><small>{E((s.get('name') or '').replace(' — telegram', ''))} · "
                f"{bgt(n.get('latest_utc'))} بغداد · {E(n.get('vstatus') or '')} · {n.get('n_sources') or 1} جهة{extra}"
                f"{f' · <a href={chr(34)}{E(u, True)}{chr(34)}>المصدر</a>' if u else ''}</small></li>")

    sec = []
    sec.append("<h2>١. أهم أخبار العراق (24 ساعة)</h2><ol>" + "".join(li(n) for n in top) + "</ol>" if top else "<h2>١. أهم أخبار العراق</h2><p>لا أحداث.</p>")
    if has_prev:
        up = [r for r in rise if r["delta"] > 0][:8]
        down = [r for r in sorted(rise, key=lambda x: x["delta"]) if r["delta"] < 0][:5]
        sec.append("<h2>٢. القضايا والشخصيات الصاعدة</h2><table><tr><th>القائمة</th><th>آخر 24 س</th><th>الـ24 قبلها</th><th>الفرق</th></tr>"
                   + "".join(f"<tr><td>{E(r['name'])}</td><td>{r['now']}</td><td>{r['before']}</td><td>+{r['delta']}</td></tr>" for r in up) + "</table>"
                   + ("<p><b>متراجعة:</b> " + "، ".join(f"{E(r['name'])} ({r['delta']})" for r in down) + "</p>" if down else ""))
    else:
        sec.append("<h2>٢. القضايا الصاعدة</h2><p>لا تتوفر بعد بيانات 48 ساعة للمقارنة (الأرشيف بدأ حديثاً). العدد الحالي: "
                   + "، ".join(f"{E(r['name'])} {r['now']}" for r in sorted(rise, key=lambda x: -x["now"])[:8]) + "</p>")
    sec.append("<h2>٣. تصريحات الشخصيات والجهات المتابعة</h2>" + ("<ol>" + "".join(
        li(n, " · " + "، ".join(f"{E(names.get(w['id'], w['id']))} ({E(w.get('prov') or '')})" for w in n["watch"] if kinds.get(w["id"]) != "topic")) for n in persons) + "</ol>"
        if persons else "<p>لا تصريحات مرصودة.</p>"))
    sec.append("<h2>٤. أخبار تحتاج مراجعة</h2>" + ("<ol>" + "".join(li(n, f" · {E(n.get('vwhy') or '')}") for n in review) + "</ol>" if review else "<p>لا شيء.</p>"))
    s = metrics.get("sources", {})
    ref = metrics.get("reference") or {}
    lat = (metrics.get("latency") or {}).get("by_type") or {}
    sec.append("<h2>٥. حدود الرصد وصحة المنظومة</h2><ul>"
               f"<li>المصادر: {s.get('working', '—')} تعمل من {s.get('enabled', '—')} مفعّلة ({s.get('registered', '—')} مسجّلة)؛ {s.get('failing', '—')} متوقفة؛ {s.get('silent_24h', '—')} صامتة 24 ساعة.</li>"
               + "".join(f"<li>زمن الوصول الوسيط — {E(k)}: {v['median_min']} د (n={v['n']})</li>" for k, v in lat.items() if v)
               + (f"<li>العينة المرجعية اليومية: التقطنا {ref.get('captured')} من {ref.get('n')} خبراً من «أبرز أخبار العراق» في Google News.</li>" if ref.get("n") else "")
               + "<li>فيسبوك وX وتيك توك غير مرصودة مباشرة؛ نتابع النقل عنها والإدخال اليدوي. البث التلفزيوني غير مرصود حالياً.</li>"
               "<li>الحالات: «منسوب لمصدر رسمي» يثبت التصريح لا صحة مضمونه؛ كثرة الجهات تعني انتشاراً لا تأكيداً.</li></ul>")
    ops = load(PWA / "ops.json", {})
    incs = [i for i in ops.get("incidents", []) if i.get("at", "") >= iso(now - timedelta(hours=24))]
    from collections import Counter as _C
    kinds = _C(i["kind"] for i in incs)
    disc = ops.get("discovery") or {}
    ch = ops.get("chain") or {}
    sec.append("<h2>٦. استقرار المنظومة ونمو المصادر (24 ساعة)</h2><ul>"
               f"<li>الأعطال المسجلة: {len(incs)}" + (" — " + "، ".join(f"{E(k)} ×{v}" for k, v in kinds.most_common()) if incs else "") + "</li>"
               + "".join(f"<li><b>متكرر:</b> {E(k)} حدث {v} مرات — يحتاج معالجة جذرية لا إعادة تشغيل فقط.</li>" for k, v in kinds.items() if v >= 3)
               + f"<li>جولات آخر ساعة: {ch.get('runs_1h', '—')} · متوسط الجولة {ch.get('avg_run_s', '—')} ث · مصادر معزولة: {(ops.get('sources') or {}).get('isolated', '—')} · توقف غير طبيعي: {(ops.get('sources') or {}).get('stalled_abnormal', '—')}</li>"
               f"<li>محرك الاكتشاف: أضاف {len(disc.get('added') or [])} مصدراً حتى الآن؛ {len(disc.get('review') or [])} بانتظار المراجعة.</li></ul>")
    body = "\n".join(sec)
    font_local = (Path.home() / "fonts" / "NotoKufiArabic.ttf")
    css = ("@font-face{font-family:K;src:url('" + (font_local.as_uri() if font_local.exists() else "") + "')}"
           "body{font-family:K,'Noto Kufi Arabic','Noto Naskh Arabic',Tahoma,sans-serif;direction:rtl;max-width:820px;margin:24px auto;padding:0 16px;color:#111;line-height:1.7;font-size:14px}"
           "h1{font-size:20px;border-bottom:3px solid #c8102e;padding-bottom:6px}h2{font-size:16px;margin-top:22px;color:#0b2545}li{margin:6px 0}small{color:#555}"
           "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:4px 8px;text-align:right}a{color:#1d5f94}"
           "@media (prefers-color-scheme:dark){body{background:#0f1420;color:#eee}small{color:#aab}h2{color:#9cc3ff}td,th{border-color:#334}a{color:#7db6e6}}")
    doc = (f"<!doctype html><html lang='ar' dir='rtl'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
           f"<title>{E(title)}</title><link rel='stylesheet' href='https://fonts.googleapis.com/css2?family=Noto+Kufi+Arabic:wght@400;700&display=swap'><style>{css}</style></head>"
           f"<body><h1>{E(title)}</h1><p><small>أُعدّ آلياً {bgd.strftime('%H:%M')} بتوقيت بغداد من المصادر المرصودة فقط. التفاصيل والمصادر: <a href='{APP}'>{APP}</a></small></p>{body}</body></html>")
    import re as _re
    txt = _re.sub(r"<li>", "• ", _re.sub(r"</(h2|li|p|tr)>", "\n", body))
    txt = html.unescape(_re.sub(r"<[^>]+>", " ", txt))
    txt = title + "\n\n" + "\n".join(" ".join(l.split()) for l in txt.split("\n") if l.strip())
    return title, doc, txt


def pdf(html_path, pdf_path):
    for b in ("google-chrome", "chromium", "chromium-browser"):
        if shutil.which(b):
            r = subprocess.run([b, "--headless=new", "--no-sandbox", "--disable-gpu", "--allow-file-access-from-files",
                                f"--print-to-pdf={pdf_path}", "--no-pdf-header-footer", html_path.as_uri()], capture_output=True, text=True, timeout=90)
            return pdf_path.exists() and pdf_path.stat().st_size > 2000, (r.stderr or "")[-200:]
    return False, "لا يوجد متصفح للطباعة"


def main(force=False):
    now = now_utc()
    bgd = now + timedelta(hours=3)
    d = bgd.strftime("%Y-%m-%d")
    REP.mkdir(parents=True, exist_ok=True)
    idx = load(REP / "index.json", [])
    done = any(x["day"] == d for x in idx)
    if not force and (done or bgd.hour < 7) and idx:
        return
    if done and not force:
        return
    title, doc, txt = build(now)
    hp, tp, pp = REP / f"{d}.html", REP / f"{d}.txt", REP / f"{d}.pdf"
    hp.write_text(doc, encoding="utf-8")
    tp.write_text(txt, encoding="utf-8")
    ok, err = pdf(hp, pp)
    idx = [x for x in idx if x["day"] != d] + [{"day": d, "title": title, "html": hp.name, "txt": tp.name, "pdf": pp.name if ok else None,
                                                  "at_utc": iso(now)}]
    idx = sorted(idx, key=lambda x: x["day"])[-60:]
    (REP / "index.json").write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    keep = {x["html"] for x in idx} | {x["txt"] for x in idx} | {x["pdf"] for x in idx if x["pdf"]} | {"index.json"}
    for f in REP.iterdir():
        if f.name not in keep:
            f.unlink()
    # نسخة احتياطية على Releases
    try:
        if subprocess.run(["gh", "release", "view", "reports"], capture_output=True).returncode != 0:
            subprocess.run(["gh", "release", "create", "reports", "--title", "التقارير الصباحية", "--notes", "تقرير يومي HTML/TXT/PDF", "--prerelease"], capture_output=True)
        subprocess.run(["gh", "release", "upload", "reports", str(hp), str(tp)] + ([str(pp)] if ok else []) + ["--clobber"], capture_output=True)
    except Exception:  # noqa: BLE001
        pass
    # إرسال للمحررين بالخاص
    sent_tg = 0
    token = os.environ.get("MARSAD_TG_BOT_TOKEN", "").strip()
    if token:
        from tools.tg_push import api, load as tload, SENT
        chats = list((tload(SENT, {}).get("_editor_chats") or {}).values())
        for c in chats:
            try:
                cap = f"🗞 {title}\nالنسخة القابلة للبحث: {APP}reports/{hp.name}"
                if ok:
                    api(token, "sendDocument", files={"document": (pp.name, pp.read_bytes(), "application/pdf")}, chat_id=c, caption=cap)
                else:
                    api(token, "sendMessage", chat_id=c, text=cap)
                sent_tg += 1
            except Exception as e:  # noqa: BLE001
                print("::warning title=report tg::", type(e).__name__, str(e).replace(token, "***")[:120])
    print(f"::notice title=report::{json.dumps({'day': d, 'pdf': ok, 'pdf_err': None if ok else err, 'bytes_html': hp.stat().st_size, 'sent_tg': sent_tg}, ensure_ascii=False)}")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
