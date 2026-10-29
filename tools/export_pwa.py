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


from marsad.textnorm import norm_ar  # noqa: E402

IRAQ_AR = [norm_ar(w) for w in ["العراق", "عراقي", "عراقية", "العراقيين", "بغداد", "البصرة", "الموصل", "أربيل", "اربيل", "كركوك", "النجف", "كربلاء",
           "السليمانية", "الأنبار", "الفلوجة", "سنجار", "دهوك", "نينوى", "ديالى", "صلاح الدين", "ذي قار", "الناصرية", "ميسان", "واسط", "بابل",
           "إقليم كردستان", "اقليم كوردستان", "السوداني", "الزيدي", "الحشد الشعبي", "الكاظمي",
           "مجلس النواب", "مجلس الوزراء", "الإطار التنسيقي", "مجلس القضاء الأعلى", "الدينار", "الزوراء", "القوة الجوية", "الطلبة", "الشرطة الاتحادية"]]
FOREIGN_AR = [norm_ar(w) for w in ["إسرائيل", "الإسرائيلي", "فلسطين", "الفلسطيني", "غزة", "الضفة", "لبنان", "اللبناني", "حزب الله", "سوريا", "السوري", "دمشق",
              "إيران", "الإيراني", "طهران", "تركيا", "التركي", "أنقرة", "السعودية", "الرياض", "الإمارات", "قطر", "الكويت", "الأردن", "مصر", "اليمن", "الحوثي",
              "واشنطن", "ترامب", "روسيا", "أوكرانيا", "الصين", "أوروبا", "فرنسا", "بريطانيا", "هرمز", "الخليج"]]
IRAQ_EN = re.compile(r"\b(Iraq|Iraqi|Iraqis|Baghdad|Kurdistan|Erbil|Basra|Mosul|Kirkuk|Najaf|Karbala|Sulaymaniyah|Anbar|Sinjar|Duhok)\b", re.I)
TOPICS = [
    ("أمن", "أمن أمني قصف انفجار اغتيال اعتقال القبض إرهاب داعش اشتباك الحشد الجيش الشرطة صاروخ مسيرة هجوم قتلى جرحى ضربة عملية عسكرية مسلحين عبوة",
     r"attack|killed|strike|militia|drone|rocket|security|army|troops|bomb|ISIS|Daesh|militant|explosion|arrest"),
    ("سياسة", "البرلمان مجلس النواب الحكومة رئيس الوزراء وزير انتخابات الكتلة تحالف رئاسة قانون سفير دبلوماسي زيارة اجتماع الإطار التنسيقي حزب نائب جلسة",
     r"parliament|minister|government|election|president|diplomat|envoy|talks|lawmaker|coalition|party|policy|sanction"),
    ("اقتصاد", "الدولار النفط الموازنة رواتب مصرف البنك المركزي أسعار تجارة استثمار صادرات الذهب الدينار الضرائب الكمارك برميل",
     r"oil|dollar|budget|bank|trade|economy|investment|exports|salaries|crude|market|price|dinar"),
    ("خدمات", "الكهرباء الماء المياه مجاري طرق مشاريع مشروع سد بلدية إعمار الإسكان النقل المطار جسر ماء الشرب انقطاع",
     r"electricity|water|infrastructure|housing|airport|project|power outage"),
    ("صحة", "صحة مستشفى وباء مرض طبي دواء كوليرا لقاح إصابات الأطباء علاج",
     r"health|hospital|disease|medical|cholera|vaccine|outbreak|patients"),
    ("تعليم", "التربية امتحانات جامعة طلاب مدارس الدوام التعليم العالي الطلبة نتائج القبول",
     r"school|university|students|education|exam"),
    ("ثقافة", "ثقافة مهرجان فن فنان كتاب معرض تراث آثار مسرح سينما شعر رواية متحف",
     r"culture|festival|art|artist|heritage|museum|film|book|archaeolog"),
    ("رياضة", "منتخب كرة الدوري مباراة نادي لاعب بطولة الاتحاد العراقي لكرة القدم أولمبي",
     r"football|soccer|match|league|team|player|sport|olympic|cup"),
    ("مجتمع", "عشائر عشيرة نزاع مناشدة حادث مروري غرق حريق زواج طلاق متظاهرين تظاهرة احتجاج مواطنين المرأة الأطفال",
     r"protest|tribe|women|children|refugees|displaced|society|rights"),
    ("طقس", "طقس أمطار درجات الحرارة الأنواء عاصفة غبار سيول", r"weather|rain|storm|flood|heat"),
]
TOPICS = [(n, [norm_ar(w) for w in ar.split()], re.compile(r"\b(" + en + r")", re.I)) for n, ar, en in TOPICS]


KURDISH = re.compile(r"[ەێۆڵڕڤ]")
ARABIC_CH = re.compile(r"[\u0600-\u06FF]")
INTERVIEW_RX = re.compile(r"\b(interview|Q&A|speaks to|in conversation|podcast)\b", re.I)
OPINION_RX = re.compile(r"\b(opinion|op-ed|column|commentary|editorial|view)\b", re.I)
ANALYSIS_RX = re.compile(r"\b(analysis|explainer|explained|why|how|what .* means|inside|the future of|strategy|lessons)\b", re.I)


def topic_of(norm_text, en_text):
    best, score = "عام", 0
    for name, words, rx in TOPICS:
        sc = sum(1 for w in words if w and w in norm_text) + len(rx.findall(en_text or ""))
        if sc > score:
            best, score = name, sc
    return best


def main(hours=24):
    con = core.connect()
    now = now_utc()
    out = []
    try:
        tr = json.loads((ROOT / "data" / "translations.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        tr = {}
    # أخبار اليوم فقط (منتصف ليل بغداد)، حتى لا يظهر خبر قديم
    bg = now + timedelta(hours=3)
    day_start = iso(bg.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=3))
    for c in con.execute("SELECT * FROM clusters WHERE last_utc >= ?", (iso(now - timedelta(days=7)),)):
        d = cluster_dossier(con, c)
        st, basis = status_of(d)
        ev = sorted(d["evidence"], key=lambda e: e["time"] or "")
        texts = [r[0] or "" for r in con.execute("SELECT COALESCE(text, title) FROM items WHERE cluster_id=? ORDER BY published_utc", (c["id"],))]
        level = d["level"]
        if level != "عاجل" and any(FLAG_RX.search(t[:80]) for t in texts):
            # المصدر نفسه وسمه «عاجل»: يصير عاجلاً، إلا إذا كانت القناة مجمّعاً يسمي كل شي عاجل (اسمها فيه «عاجل»)
            names = [e["source"] or "" for e in ev]
            level = "مهم" if all("عاجل" in n for n in names) else "عاجل"
        regs = {r[0] or "" for r in con.execute("SELECT s.region FROM items i JOIN sources s ON s.id=i.source_id WHERE i.cluster_id=?", (c["id"],))}
        origins = {"أجنبي" if r.startswith("أجنبي") else "عربي" if r.startswith("إقليمي") else "عراقي" for r in regs} or {"عراقي"}
        origin = "عراقي" if "عراقي" in origins else "عربي" if "عربي" in origins else "أجنبي"
        alltext = " ".join(texts) + " " + (d["label"] or "")
        ntext = norm_ar(alltext)
        iraq_kw = any(w in ntext for w in IRAQ_AR) or bool(IRAQ_EN.search(alltext))
        foreign_kw = any(w in ntext for w in FOREIGN_AR)
        about_iraq = iraq_kw or (origin == "عراقي" and not foreign_kw)
        if origin == "أجنبي" and not iraq_kw:
            continue  # الإعلام الأجنبي: ما يخص العراق فقط
        scope = ("أجنبي" if regs and all(r.startswith("أجنبي") for r in regs)
                 else "إقليمي" if regs and all(r.startswith("إقليمي") or r.startswith("أجنبي") for r in regs) else "العراق")
        latest = max((e["time"] for e in ev if e["time"]), default=None)
        is_analysis_src = any(r.startswith("أجنبي — تحليل") for r in regs)
        if not latest or latest < iso(now - timedelta(days=7 if is_analysis_src else 1)):
            continue
        if len(KURDISH.findall(alltext)) >= 3:
            continue  # المحتوى الكردي لا يُعرض (لا توجد ترجمة كردي→عربي مجانية موثوقة حالياً)
        title = clean_title(d["label"], texts)
        title_ar = tr.get(title) or tr.get((d["label"] or "").strip())
        if not ARABIC_CH.search(title_ar or title):
            continue  # لا نعرض عنواناً غير مترجم للعربية
        en = title if title_ar else ""
        kind = None
        if origin == "أجنبي":
            kind = ("مقابلة" if INTERVIEW_RX.search(en) else "رأي" if OPINION_RX.search(en)
                    else "تحليل" if (is_analysis_src or ANALYSIS_RX.search(en)) else None)
        if is_analysis_src and not kind:
            kind = "تحليل"
        if latest < iso(now - timedelta(days=1)) and not kind:
            continue
        collected = con.execute("SELECT MIN(collected_utc) FROM items WHERE cluster_id=?", (c["id"],)).fetchone()[0]
        out.append({"id": c["id"], "title": title_ar or title, "title_orig": title if title_ar else None, "status": st, "basis": basis, "level": level, "scope": scope, "origin": origin, "about_iraq": about_iraq, "kind": kind,
                    "topic": topic_of(ntext + " " + norm_ar(title_ar or ""), alltext),
                    "collected_utc": collected, "first_utc": d["first"], "latest_utc": latest,
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
    (pwa / "meta.json").write_text(json.dumps({"updated_utc": iso(now), "stories": len(out), "sources_ok": len(ok),
                                               "sections": {"iraq": sum(1 for o in out if o["about_iraq"]),
                                                            "region": sum(1 for o in out if not o["about_iraq"] and o["origin"] != "أجنبي"),
                                                            "arab_on_iraq": sum(1 for o in out if o["about_iraq"] and o["origin"] == "عربي"),
                                                            "foreign_on_iraq": sum(1 for o in out if o["origin"] == "أجنبي"),
                                                            "translated": sum(1 for o in out if o.get("title_orig")), "analysis": sum(1 for o in out if o.get("kind")),
                                                            "urgent": sum(1 for o in out if o["level"] == "عاجل"), "important": sum(1 for o in out if o["level"] == "مهم")}},
                                              ensure_ascii=False), encoding="utf-8")
    print(len(out), "خبراً في pwa/news.json")


if __name__ == "__main__":
    main()
