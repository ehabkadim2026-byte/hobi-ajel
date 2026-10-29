"""التقرير الموثّق، التصدير CSV، بيانات اللوحة، صندوق التنبيهات، والنسخ الاحتياطي."""
import csv
import os
import json
import shutil
import sqlite3
from pathlib import Path

from . import core
from .core import LEVELS, ROOT, health, score_cluster
from .textnorm import iso, now_utc, to_baghdad

EXPORTS = ROOT / "exports"
BACKUPS = Path(os.environ.get("MARSAD_BACKUPS", ROOT / "data" / "backups"))


def _confidence(c, rows):
    kinds = {r["kind"] for r in rows}
    origin = rows[0]
    if "ادعاء من مصدر غير مسمى" in kinds and not c["verification"].startswith("مصدر رسمي"):
        return "منخفضة", "يستند إلى مصدر غير مسمّى ولم نجد تأكيداً رسمياً في المصادر المرصودة"
    if c["verification"].startswith("مصدر رسمي"):
        why = "صادر عن جهة رسمية؛ هذا يثبت صدور الكلام لا تحقق مضمونه"
        return ("متوسطة-عالية", why) if origin["date_confirmed"] else ("متوسطة", why + "، والتاريخ مُستنتج")
    if c["n_sources"] >= 2:
        return "متوسطة", f"ظهر لدى {c['n_sources']} جهات، لكن لم نتحقق أنها مستقلة عن بعضها"
    return "منخفضة-متوسطة", "جهة واحدة ولم يُفتح أصل مستقل"


def _unconfirmed(c, rows):
    gaps = []
    kinds = {r["kind"] for r in rows}
    if "ادعاء من مصدر غير مسمى" in kinds:
        gaps.append("هوية المصدر ودليل الادعاء")
    if "نقل عن إعلام أجنبي" in kinds:
        gaps.append("النص الأصلي في الوسيلة الأجنبية")
    if not all(r["date_confirmed"] for r in rows):
        gaps.append("تاريخ بعض المواد مُستنتج من الترتيب لا مؤكد")
    if c["n_sources"] == 1 and not c["verification"].startswith("مصدر رسمي"):
        gaps.append("مصدر مستقل ثانٍ")
    gaps.append("النص الكامل للأصل (الجمع يحفظ العنوان ومقتطفاً قصيراً فقط)")
    return gaps


def cluster_dossier(con, c):
    lvl, score, why, rows = score_cluster(con, c)
    rows = sorted(rows, key=lambda r: r["published_utc"] or "9")
    contrary = [r for r in rows if r["kind"] == "نفي/تصحيح"]
    conf, conf_why = _confidence(c, rows)
    return {
        "id": c["id"], "level": lvl, "score": score, "label": c["label"], "storyline": c["storyline"],
        "verification": c["verification"], "first": c["first_utc"], "last": c["last_utc"],
        "n_items": c["n_items"], "n_sources": c["n_sources"], "watchlists": json.loads(c["watchlists"] or "[]"),
        "why": why,
        "earliest_found": {"source": rows[0]["source_name"], "url": rows[0]["url"], "time": rows[0]["published_utc"],
                           "note": "أقدم ظهور عثرنا عليه داخل المصادر المرصودة — ليس بالضرورة المصدر الأول المؤكد"},
        "evidence": [{"source": r["source_name"], "url": r["url"], "time": r["published_utc"],
                      "date_confirmed": bool(r["date_confirmed"]), "kind": r["kind"], "title": r["title"],
                      "views": r["views"]} for r in rows],
        "unconfirmed": _unconfirmed(c, rows),
        "contrary": [{"source": r["source_name"], "url": r["url"], "title": r["title"]} for r in contrary],
        "confidence": conf, "confidence_why": conf_why,
    }


def build_report(con, title="موجز مرصد هوبي", min_level="متابعة"):
    now = now_utc()
    dossiers = [cluster_dossier(con, c) for c in con.execute("SELECT * FROM clusters")]
    dossiers.sort(key=lambda d: (LEVELS.index(d["level"]), -(d["score"]), d["last"] or ""))
    keep = [d for d in dossiers if LEVELS.index(d["level"]) <= LEVELS.index(min_level)]
    h = health(con)
    n_items = con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    lines = [f"# {title}", f"آخر تحديث: {to_baghdad(iso(now))} (بتوقيت بغداد)", "",
             "## الخلاصة"]
    by = {l: [d for d in dossiers if d["level"] == l] for l in LEVELS}
    lines.append(f"- {n_items} مادة في الأرشيف، مجمّعة في {len(dossiers)} خبراً: "
                 + "، ".join(f"{l} {len(v)}" for l, v in by.items()) + ".")
    for d in keep[:5]:
        lines.append(f"- **{d['level']}** — {d['label']} ({d['verification']}).")
    lines += ["", "## الأحداث"]
    for d in keep:
        lines += [f"### [{d['level']}] {d['label']}",
                  f"- **ماذا نعرف؟** {d['label']} — {d['n_items']} مادة من {d['n_sources']} جهة، "
                  f"من {to_baghdad(d['first'])} إلى {to_baghdad(d['last'])}.",
                  "- **ما الدليل؟**"]
        for e in d["evidence"][:6]:
            mark = "" if e["date_confirmed"] else " (تاريخ مُستنتج)"
            lines.append(f"  - [{e['source']}]({e['url']}) — {to_baghdad(e['time'])}{mark} — {e['kind']}")
        lines.append(f"- **أقدم ظهور عثرنا عليه:** {d['earliest_found']['source']} — لا يعني أنه المصدر الأول المؤكد.")
        lines.append("- **ما لم يتأكد:** " + "؛ ".join(d["unconfirmed"]) + ".")
        lines.append("- **رواية مخالفة أو تصحيح:** " + (
            "؛ ".join(f"[{x['source']}]({x['url']})" for x in d["contrary"]) if d["contrary"]
            else "لم نجد ضمن المصادر المرصودة (هذا لا ينفي وجودها)."))
        lines.append(f"- **درجة الثقة:** {d['confidence']} — {d['confidence_why']}.")
        lines.append(f"- **لماذا هذا المستوى:** {'، '.join(d['why']) or '—'}.")
        lines.append("")
    lines += ["## حدود التغطية"]
    working = [x for x in h if x["state"] == "يعمل"]
    lines.append(f"- مصادر جُمعت بنجاح في هذه الدورة: {len(working)} من {len(h)} مسجلة.")
    bad = [x for x in h if x["state"] in ("متوقف", "فشل مؤقت", "قديم (>48 ساعة)")]
    if bad:
        lines.append("- مصادر فشلت أو قديمة: " + "، ".join(f"{x['name']} ({x['state']})" for x in bad[:15]) + ".")
    unread = [x for x in h if x["state"] in ("غير مقروء", "يحتاج ربطاً", "بانتظار قرار")]
    lines.append(f"- مصادر مسجلة غير مقروءة آلياً (فيسبوك/X/إنستغرام وغيرها): {len(unread)} — «لم نجد خبراً» لا يعني "
                 "«لم يُنشر»، بل قد يعني «لم نتمكن من فحص المصدر».")
    lines.append("- التصنيف (نوع المادة، المستوى) آلي ويحتاج قراءة بشرية قبل البناء عليه.")
    EXPORTS.mkdir(exist_ok=True)
    (EXPORTS / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return dossiers


def export_csv(con, path=None):
    path = Path(path or EXPORTS / "items.csv")
    rows = con.execute("SELECT i.id, i.platform, i.source_name, i.url, i.published_utc, i.date_confirmed, "
                       "i.collected_utc, i.title, i.kind, i.views, i.watchlists, i.cluster_id, c.verification "
                       "FROM items i LEFT JOIN clusters c ON c.id=i.cluster_id ORDER BY i.published_utc DESC").fetchall()
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["المعرّف", "المنصة", "المصدر", "الرابط", "وقت النشر (بغداد)", "التاريخ مؤكد", "وقت الجمع (بغداد)",
                    "العنوان", "نوع المادة (آلي)", "المشاهدات وقت القياس", "ملفات الرصد", "الخبر", "حالة التحقق"])
        for r in rows:
            w.writerow([r["id"], r["platform"], r["source_name"], r["url"], to_baghdad(r["published_utc"]),
                        "نعم" if r["date_confirmed"] else "لا (مُستنتج)", to_baghdad(r["collected_utc"]),
                        r["title"], r["kind"], r["views"] or "غير متوفر", r["watchlists"], r["cluster_id"],
                        r["verification"]])
    return path, len(rows)


def write_outbox(con):
    lines = ["# صندوق التنبيهات الصادر (محلي — التوصيل غير مفعّل)", ""]
    for a in con.execute("SELECT * FROM alerts ORDER BY id DESC"):
        b = json.loads(a["body"])
        lines += [f"## [{a['level']}] {'تحديث' if a['is_update'] else 'جديد'} — {b['ماذا حدث']}",
                  f"- متى: {to_baghdad(b['متى'])} | أُنشئ التنبيه: {to_baghdad(a['created_utc'])}",
                  f"- لماذا يستحق الانتباه: {b['لماذا يستحق الانتباه']}",
                  f"- المصدر: [{b['المصدر']}]({b['الرابط']})",
                  f"- درجة التحقق: {b['درجة التحقق']}",
                  f"- الجديد مقارنة بالسابق: {b['الجديد']}",
                  f"- الإجراء البحثي المقترح: {b['الإجراء البحثي المقترح']}", ""]
    (EXPORTS / "alerts_outbox.md").write_text("\n".join(lines), encoding="utf-8")


def dashboard_data(con):
    dossiers = [cluster_dossier(con, c) for c in con.execute("SELECT * FROM clusters")]
    dossiers.sort(key=lambda d: (LEVELS.index(d["level"]), -(d["score"])))
    items = [dict(r) for r in con.execute(
        "SELECT i.id, i.platform, i.source_id, i.source_name, i.url, i.published_utc, i.date_confirmed, i.title, "
        "i.kind, i.views, i.watchlists, i.cluster_id, i.stale, c.verification FROM items i "
        "LEFT JOIN clusters c ON c.id=i.cluster_id ORDER BY i.published_utc DESC")]
    alerts = [dict(r) for r in con.execute("SELECT * FROM alerts ORDER BY id DESC")]
    wl = json.loads((ROOT / "config" / "watchlists.json").read_text(encoding="utf-8"))["watchlists"]
    data = {"generated_utc": iso(now_utc()), "items": items, "events": dossiers, "alerts": alerts,
            "health": health(con), "watchlists": wl}
    (EXPORTS / "dashboard_data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def build_dashboard(con):
    data = dashboard_data(con)
    tpl = (ROOT / "dashboard" / "template.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    out = EXPORTS / "dashboard.html"
    out.write_text(html, encoding="utf-8")
    return out


def backup(keep=14):
    BACKUPS.mkdir(parents=True, exist_ok=True)
    dest = BACKUPS / f"marsad_{now_utc().strftime('%Y%m%d_%H%M%S')}.db"
    src = sqlite3.connect(str(core.DB_PATH))
    dst = sqlite3.connect(str(dest))
    src.backup(dst)
    dst.close(); src.close()
    for old in sorted(BACKUPS.glob("marsad_*.db"))[:-keep]:
        old.unlink()
    return dest


def restore(path):
    shutil.copyfile(path, core.DB_PATH)
    return core.DB_PATH


def export_pdf(md_path=None, out=None):
    """تصدير التقرير PDF عبر wkhtmltopdf إن وُجد (اختياري؛ الحزمة تعمل بدونه)."""
    import shutil as _sh
    import subprocess
    md_path = Path(md_path or EXPORTS / "report.md")
    out = Path(out or EXPORTS / "report.pdf")
    if not _sh.which("wkhtmltopdf"):
        return None
    try:
        import markdown
        body = markdown.markdown(md_path.read_text(encoding="utf-8"))
    except ImportError:
        import html as _h
        body = "<pre>" + _h.escape(md_path.read_text(encoding="utf-8")) + "</pre>"
    html_path = out.with_suffix(".html")
    html_path.write_text(
        "<html dir='rtl' lang='ar'><head><meta charset='utf-8'><style>"
        "body{font-family:'DejaVu Sans',FreeSerif,sans-serif;font-size:11pt;line-height:1.6;margin:18mm}"
        "h1{font-size:18pt}h2{font-size:14pt;border-bottom:1px solid #999}h3{font-size:12pt;margin-top:14pt}"
        "a{color:#1f5f8b}</style></head><body>" + body + "</body></html>", encoding="utf-8")
    subprocess.run(["wkhtmltopdf", "--quiet", "--encoding", "utf-8", str(html_path), str(out)], check=False)
    html_path.unlink(missing_ok=True)
    return out if out.exists() else None
