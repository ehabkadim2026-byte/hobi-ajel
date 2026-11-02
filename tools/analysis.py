"""«تحليل خبري» — بطاقة تحليل محسوبة من بيانات الرصد نفسها (مجانية، بلا تخمين) للأحداث الكبيرة:
أخبار العراق أو الأخبار المهمة التي نشرتها 20 جهة مرصودة فأكثر خلال آخر 24 ساعة.

ما تحتويه البطاقة (كلها قابلة للتحقق من الروابط):
- من أطلق الخبر أولاً ضمن المرصود (أقدم ظهور، وليس بالضرورة المصدر الأول المؤكد)، وأول 5 ناشرين.
- سرعة الانتشار: كم دقيقة حتى بلغ 10 ثم 20 جهة، ومنحنى النشر بالساعة.
- توزيع الناشرين: قنوات تلغرام / مواقع / مصادر رسمية / Google News / إدخال يدوي.
- الروايات: حتى 3 صياغات مختلفة فعلاً للحدث نفسه مع ناشرها (لتمييز اختلاف الزاوية).
- إشارات: نفي أو تصحيح ظهر ضمن التغطية، وجود مصدر رسمي من عدمه، حالة التحقق.
- ما لم يتأكد: أسئلة مفتوحة تُستخرج آلياً (لا مصدر رسمي، مصادر مجهولة، روايات متعارضة).
- «قراءة تحريرية» نصية: تُضاف فقط عند تفعيل مفتاح Gemini، وتمر بحارس الحقائق، وتُوسم «صياغة آلية».
كثرة الناشرين = انتشار، لا تأكيد. والتفاعل لا يُسمّى رأياً عاماً.
"""
import re
from datetime import datetime

from marsad.textnorm import norm_ar
from tools import verify as V

MIN_SOURCES = 20


def _t(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _kind(r):
    if r["platform"] == "manual":
        return "إدخال يدوي"
    if r["official"]:
        return "رسمي"
    u = (r["url"] or "").lower()
    if "news.google.com" in u:
        return "Google News"
    if "t.me/" in u or r["platform"] == "telegram":
        return "تلغرام"
    return "مواقع إخبارية"


def _words(t):
    return {w for w in norm_ar(t or "").split() if len(w) > 2}


def _excerpts(rows, k=4):
    out, seen = [], []
    for r in rows:
        t = " ".join((r["text"] or r["title"] or "").split())[:420]
        w = _words(t)
        if len(t) < 80 or any(len(w & x) / max(1, len(w | x)) > 0.5 for x in seen):
            continue
        seen.append(w)
        out.append({"source": r["source_name"], "text": t})
        if len(out) >= k:
            break
    return out


def eligible(n_sources, about_iraq, level):
    return (n_sources or 0) >= MIN_SOURCES and (about_iraq or level in ("عاجل", "مهم"))


def build(cid, title, irows, va, level, watch_names):
    rows = [r for r in irows if (r["published_utc"] or r["collected_utc"])]
    rows.sort(key=lambda r: r["published_utc"] or r["collected_utc"])
    seen, firsts = set(), []
    for r in rows:
        k = r["source_id"] or r["source_name"]
        if k in seen:
            continue
        seen.add(k)
        firsts.append(r)
    t0 = _t(firsts[0]["published_utc"] or firsts[0]["collected_utc"]) if firsts else None

    def reach(n):
        if len(firsts) < n or not t0:
            return None
        t = _t(firsts[n - 1]["published_utc"] or firsts[n - 1]["collected_utc"])
        return round((t - t0).total_seconds() / 60) if t else None

    kinds = {}
    for r in firsts:
        k = _kind(r)
        kinds[k] = kinds.get(k, 0) + 1
    hours = {}
    for r in rows:
        t = _t(r["published_utc"] or r["collected_utc"])
        if t:
            h = t.strftime("%Y-%m-%dT%H:00Z")
            hours[h] = hours.get(h, 0) + 1
    curve = sorted(hours.items())[-24:]
    # الروايات: صياغات مختلفة فعلاً (تشابه كلمات < 0.35 مع ما اختير)
    narratives = []
    for r in rows:
        t = (r["title"] or "").strip()
        if len(t) < 15:
            continue
        w = _words(t)
        if all(len(w & _words(x["title"])) / max(1, len(w | _words(x["title"]))) < 0.35 for x in narratives):
            narratives.append({"title": t[:200], "source": r["source_name"], "url": r["url"], "time": r["published_utc"] or r["collected_utc"]})
        if len(narratives) >= 3:
            break
    texts = [(r["title"] or "") + " " + (r["text"] or "")[:300] for r in rows]
    denial = [r for r, t in zip(rows, texts) if V.is_denial(r["title"] or "")]
    official = kinds.get("رسمي", 0)
    anon = sum(1 for t in texts if V.ANON_RX.search(t))
    open_q = []
    if not official:
        open_q.append("لا يوجد مصدر رسمي ضمن الجهات المرصودة نشر الخبر حتى الآن.")
    if anon and anon >= len(texts) * 0.3:
        open_q.append(f"{anon} من المواد تستند إلى «مصادر» غير مسمّاة.")
    if denial:
        open_q.append("ظهر نفي أو تصحيح ضمن التغطية — راجع الروايتين قبل التعامل مع الخبر كواقعة.")
    if va.get("vstatus") in ("غير متحقق", None):
        open_q.append("حالة التحقق: غير متحقق — الانتشار الواسع لا يعني التأكيد.")
    open_q.append("«أول ناشر» هنا هو أقدم ظهور ضمن ما نرصده، وقد يكون الأصل أقدم منه.")
    return {
        "id": cid, "title": title, "level": level, "vstatus": va.get("vstatus"), "vwhy": va.get("vwhy"),
        "n_sources": len(firsts), "n_items": len(rows),
        "first": {"source": firsts[0]["source_name"], "time": firsts[0]["published_utc"] or firsts[0]["collected_utc"], "url": firsts[0]["url"]} if firsts else None,
        "launchers": [{"source": r["source_name"], "time": r["published_utc"] or r["collected_utc"], "url": r["url"]} for r in firsts[:5]],
        "reach10_min": reach(10), "reach20_min": reach(20),
        "last_time": rows[-1]["published_utc"] or rows[-1]["collected_utc"] if rows else None,
        "kinds": dict(sorted(kinds.items(), key=lambda x: -x[1])), "curve": curve,
        "narratives": narratives,
        "denial": [{"title": (r["title"] or "")[:200], "source": r["source_name"], "url": r["url"]} for r in denial[:3]],
        "official": official, "people": watch_names[:6], "open": open_q, "reading": None,
        "excerpts": _excerpts(rows),
    }


ANA_PROMPT = ("أنت محلل سياسي عراقي رصين ومحايد في قناة إخبارية. اكتب «تحليلاً خبرياً» قصيراً (110–170 كلمة) عن الحدث التالي، "
              "مستنداً فقط إلى المعطيات المرفقة، بأربع فقرات قصيرة تبدأ بهذه العناوين حرفياً:\n"
              "ما الذي حدث:\nلماذا يهم:\nالروايات والمواقف:\nما لم يتأكد وما يُرتقب:\n"
              "قواعد صارمة: لا تضف أي رقم أو اسم أو واقعة غير موجودة في المعطيات؛ لا تتهم أي شخص أو جهة بفساد أو خيانة أو تضليل؛ "
              "لا تنحز لطرف؛ ميّز الواقعة من التصريح من الادعاء؛ عبّر عن التوقعات بصيغة احتمال (قد، يُحتمل) لا يقين؛ "
              "انتشار الخبر لا يعني صحته. بلا مقدمة ولا خاتمة ولا رموز.\n\nالمعطيات:\n")
ACCUSE = re.compile(r"(فاسد|فساد|خيان|عميل|عمالة|متورط|تضليل|كاذب|مرتزق|إرهابي)")


def write_reading(a):
    from tools.editorial import gemini, DIGITS
    facts = [f"العنوان: {a['title']}", f"عدد الجهات الناشرة المرصودة: {a['n_sources']}", f"حالة التحقق: {a.get('vstatus') or 'غير متحقق'} — {a.get('vwhy') or ''}"]
    if a.get("first"):
        facts.append(f"أقدم ظهور مرصود: {a['first'].get('source')} ({a['first'].get('time')})")
    facts.append("أنواع الناشرين: " + "، ".join(f"{k} {v}" for k, v in (a.get("kinds") or {}).items()))
    facts += [f"صياغة: «{n['title']}» — {n.get('source')}" for n in (a.get("narratives") or [])]
    facts += [f"نفي/تصحيح: «{n['title']}» — {n.get('source')}" for n in (a.get("denial") or [])]
    facts += [f"سؤال مفتوح: {q}" for q in (a.get("open") or [])]
    ftxt = "\n".join(facts)
    out = gemini(ANA_PROMPT + ftxt, max_tokens=600, temperature=0.3)
    if not out:
        return None
    out = out.strip()
    if not set(DIGITS.findall(out)) <= set(DIGITS.findall(ftxt)):
        return None  # رقم غير موجود في المعطيات
    if ACCUSE.search(out) and not ACCUSE.search(ftxt):
        return None  # لغة اتهام لم ترد في المصادر
    if not all(h in out for h in ("ما الذي حدث", "لماذا يهم")) or len(out.split()) < 70:
        return None
    return out


POSITIVE = re.compile(r"(افتتاح|يفتتح|إنجاز|انجاز|اكتمال|إكمال|ارتفاع|نمو|زيادة|توقيع|اتفاقية|مذكرة تفاهم|استثمار|إطلاق|اطلاق|تحسن|تحسّن|"
                      r"انخفاض البطالة|تشغيل|تأهيل|إعمار|اعمار|مشروع|جسر|محطة|مستشفى|مدرسة|تصدير|إيرادات|فائض|تعيين|تثبيت|منحة|دعم|شراكة|تعاون|"
                      r"رفع|تخفيض الأسعار|خفض|توسعة|إنتاج|انتاج|قياسي|ميغاواط|الطاقة الشمسية|تطوير|أول مرة|لأول مرة)")
NEGATIVE = re.compile(r"(مقتل|قتلى|انفجار|اغتيال|اعتقال|القبض|اشتباك|حريق|غرق|سرقة|فساد|اتهام|أزمة|ازمة|تظاهر|احتجاج|إضراب|عجز|انهيار|"
                      r"توقف|انقطاع|تحذير|كارثة|وفاة|إصابة|ينفي|نفي|تأجيل|رفض|خلاف)")
POS_PROMPT = ("أنت محلل اقتصادي وسياسي عراقي رصين. اكتب «تحليلاً خبرياً» قصيراً (90–150 كلمة) عن هذا التطور الإيجابي في العراق، "
              "بثلاث فقرات قصيرة تبدأ بهذه العناوين حرفياً:\nما الذي حدث:\nلماذا هو تطور إيجابي:\nما الذي يحتاجه ليكتمل أثره:\n"
              "قواعد صارمة: استند فقط إلى المعطيات المرفقة؛ لا تضف رقماً أو اسماً أو وعداً غير موجود؛ لا مبالغة ولا دعاية؛ "
              "اذكر بموضوعية ما يحتاجه التطور (تنفيذ، متابعة، شفافية) دون اتهام أحد. بلا مقدمة ولا رموز.\n\nالمعطيات:\n")


def pick_positive(news, exclude, now_iso_24h):
    pool = []
    for n in news:
        t = n.get("title") or ""
        if not (n.get("about_iraq") and n.get("origin") != "أجنبي") or n["id"] in exclude:
            continue
        if (n.get("latest_utc") or "") < now_iso_24h or n.get("ctype") == "تحليل/رأي":
            continue
        if not POSITIVE.search(t) or NEGATIVE.search(t):
            continue
        if n.get("topic") not in ("اقتصاد", "سياسة", "خدمات", "طاقة", "استثمار", "عام", None) and not re.search(r"اقتصا|استثمار|طاقة|نفط|كهرباء|مشروع", t):
            continue
        if (n.get("n_sources") or 1) < 3:
            continue
        pool.append(n)
    pool.sort(key=lambda n: (-(n.get("n_sources") or 1), n.get("vstatus") != "منسوب لمصدر رسمي"))
    return pool[0] if pool else None


def write_positive(n):
    from tools.editorial import gemini, DIGITS
    facts = f"العنوان: {n['title']}\nالنص: {(n.get('lead') or '')[:500]}\nعدد الجهات الناشرة: {n.get('n_sources')}\nحالة التحقق: {n.get('vstatus') or 'غير متحقق'}"
    out = gemini(POS_PROMPT + facts, max_tokens=500, temperature=0.3)
    if not out:
        return None
    out = out.strip()
    if not set(DIGITS.findall(out)) <= set(DIGITS.findall(facts)) or ACCUSE.search(out):
        return None
    if "ما الذي حدث" not in out or "إيجابي" not in out or len(out.split()) < 60:
        return None
    return out


# ───────────── «تداول غير مؤكد»: مؤشر نمط الانتشار ─────────────
# الغرض: أن يعرف الراصد أن الخبر منتشر لكنه غير مؤكد، وما مدى تشابه نمط انتشاره مع حملة منسّقة.
# هذا مؤشر آلي لنمط الانتشار فقط، وليس حكماً بوجود حملة أو تنسيق (تشابه النصوص وحده لا يثبت تنسيقاً).
SPREAD_MIN = 8


def spread_eligible(n_sources, va, official_any):
    vs = va.get("vstatus")
    return (n_sources or 0) >= SPREAD_MIN and (vs == "متنازع عليه" or (vs in (None, "غير متحقق") and not official_any))


def spread(cid, title, irows, va):
    rows = sorted([r for r in irows if (r["published_utc"] or r["collected_utc"])], key=lambda r: r["published_utc"] or r["collected_utc"])
    seen, firsts = set(), []
    for r in rows:
        k = r["source_id"] or r["source_name"]
        if k not in seen:
            seen.add(k)
            firsts.append(r)
    n = len(firsts)
    if n < SPREAD_MIN:
        return None
    ws = [_words(r["title"] or (r["text"] or "")[:200]) for r in firsts]
    # 1) نسخ ولصق: نسبة الجهات التي يطابق نصها (≥70%) نص جهة أخرى
    copy = sum(1 for i, w in enumerate(ws) if w and any(j != i and x and len(w & x) / len(w | x) >= 0.7 for j, x in enumerate(ws))) / n
    # 2) اندفاع: نسبة الجهات التي نشرت خلال أول 30 دقيقة من أول ظهور
    t0 = _t(firsts[0]["published_utc"] or firsts[0]["collected_utc"])
    burst = sum(1 for r in firsts if (_t(r["published_utc"] or r["collected_utc"]) - t0).total_seconds() <= 1800) / n if t0 else 0
    # 3) مصادر مجهولة: «مصدر مطلع/أمني…»
    texts = [(r["title"] or "") + " " + (r["text"] or "")[:300] for r in firsts]
    anon = sum(1 for t in texts if V.ANON_RX.search(t)) / n
    # 4) قنوات تلغرام غير رسمية من مجموع الناشرين
    tg = sum(1 for r in firsts if _kind(r) == "تلغرام") / n
    denial = sum(1 for r in rows if V.is_denial(r["title"] or ""))
    official = any(r["official"] for r in firsts)
    score = 100 * (0.30 * copy + 0.25 * burst + 0.15 * anon + 0.15 * tg + (0 if official else 0.15))  # +0.15 لغياب أي مصدر رسمي
    score = round(min(95, score))
    band = "مرتفع" if score >= 60 else "متوسط" if score >= 35 else "منخفض"
    why = []
    if copy >= 0.5:
        why.append(f"{round(copy * 100)}% من الجهات نشرت نصاً شبه متطابق")
    if burst >= 0.5:
        why.append(f"{round(burst * 100)}% من الجهات نشرت خلال أول نصف ساعة")
    if anon >= 0.3:
        why.append(f"{round(anon * 100)}% تستند إلى «مصادر» غير مسمّاة")
    if tg >= 0.6:
        why.append(f"{round(tg * 100)}% من الناشرين قنوات تلغرام")
    why.append("يوجد مصدر رسمي ضمن الناشرين (الخبر متنازع عليه)" if official else "لا يوجد مصدر رسمي ضمن الناشرين المرصودين")
    if denial:
        why.append(f"ظهر نفي أو تصحيح ({denial})")
    return {
        "id": cid, "title": title, "vstatus": va.get("vstatus") or "غير متحقق", "n_sources": n, "n_items": len(rows),
        "first": {"source": firsts[0]["source_name"], "time": firsts[0]["published_utc"] or firsts[0]["collected_utc"], "url": firsts[0]["url"]},
        "last_time": rows[-1]["published_utc"] or rows[-1]["collected_utc"],
        "score": score, "band": band,
        "parts": {"نص متطابق": round(copy * 100), "اندفاع أول 30 د": round(burst * 100), "مصادر مجهولة": round(anon * 100), "تلغرام": round(tg * 100)},
        "why": why, "denial": denial,
        "note": "مؤشر آلي لنمط الانتشار ضمن المصادر المرصودة، ليس حكماً بوجود حملة منظمة ولا بصحة الخبر أو كذبه.",
    }


# ───────────── وكيل التحليل الخبري: مقالتان يومياً عن أكثر خبرين تداولاً ─────────────
ART_MODELS = ["gemini-3.6-flash", "gemma-4-31b-it", "gemma-4-26b-a4b-it", "gemini-3.7-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
ART_HEADS = ("الخلاصة:", "السياق:", "القراءة:", "السيناريوهات المحتملة:", "ما لم يتأكد:")
ART_PROMPT = ("أنت كاتب تحليل خبري في قناة أخبار عراقية رصينة ومحايدة. اكتب مقالة تحليلية (230–330 كلمة) عن الحدث التالي "
              "مستنداً فقط إلى المعطيات والمقتطفات المرفقة. ابدأ بسطر «العنوان: …» (عنوان تحليلي جذاب من 6 إلى 12 كلمة، لا يكرر عنوان الخبر حرفياً)، "
              "ثم خمس فقرات تبدأ بهذه العناوين حرفياً كلٌّ في سطر جديد:\n" + "\n".join(ART_HEADS) + "\n"
              "قواعد صارمة: لا تضف أي رقم أو اسم أو تاريخ أو واقعة غير موجودة في المعطيات؛ لا تتهم أي شخص أو جهة بفساد أو خيانة أو تضليل؛ "
              "لا تنحز لطرف ولا تستخدم لغة تحريضية؛ ميّز الواقعة المؤكدة من التصريح المنسوب من الادعاء؛ السيناريوهات بصيغة احتمال (قد، يُحتمل) "
              "واثنان إلى ثلاثة سيناريوهات فقط؛ انتشار الخبر لا يعني صحته. لغة عربية فصحى سليمة واضحة، جمل قصيرة، بلا رموز تعبيرية ولا تنسيق Markdown.\n\nالمعطيات:\n")


def _facts(a):
    f = [f"عنوان الخبر: {a['title']}", f"عدد الجهات الناشرة ضمن المرصود: {a['n_sources']}",
         f"حالة التحقق: {a.get('vstatus') or 'غير متحقق'} — {a.get('vwhy') or ''}"]
    if a.get("first"):
        f.append(f"أقدم ظهور مرصود: {(a['first'].get('source') or '').split(' — ')[0]}")
    if a.get("reach10_min") is not None:
        m = a["reach10_min"]
        f.append(f"بلغ 10 جهات خلال {m} دقيقة" if m < 90 else f"بلغ 10 جهات خلال نحو {round(m / 60)} ساعة")
    f.append("أنواع الناشرين: " + "، ".join(f"{k} {v}" for k, v in (a.get("kinds") or {}).items()))
    f += [f"صياغة: «{n['title']}» — {n.get('source')}" for n in (a.get("narratives") or [])]
    f += [f"نفي/تصحيح: «{n['title']}» — {n.get('source')}" for n in (a.get("denial") or [])]
    f += [f"مقتطف من {e.get('source')}: {e['text']}" for e in (a.get("excerpts") or [])]
    f += [f"سؤال مفتوح: {q}" for q in (a.get("open") or [])]
    return "\n".join(f)


def write_article(a):
    """يرجع (العنوان، النص) أو None إذا فشل النموذج أو خالف قواعد الحقائق."""
    from tools import editorial as E
    ftxt = _facts(a)
    old = E.MODELS[:]
    try:
        E.MODELS[:] = ART_MODELS
        out = None
        for _ in range(2):
            out = _gem_long(ART_PROMPT + ftxt)
            if out:
                break
    finally:
        E.MODELS[:] = old
    if not out:
        return None
    out = re.sub(r"[*#_`]+", "", out).strip()
    m = re.search(r"العنوان\s*:\s*(.+)", out)
    if not m:
        return None
    title = m.group(1).strip().strip("«»\"")
    body = out[m.end():].strip()
    if not all(h in body for h in ("الخلاصة:", "القراءة:", "ما لم يتأكد:")) or not (150 <= len(body.split()) <= 420):
        return None
    if not set(E.DIGITS.findall(title + " " + body)) <= set(E.DIGITS.findall(ftxt)):
        return None
    if ACCUSE.search(title + body) and not ACCUSE.search(ftxt):
        return None
    if len(title.split()) > 14 or len(title) < 12:
        title = a["title"]
    return title, body


LAST_FINISH = [""]


def _gem_long(prompt):
    """نداء أطول (مهلة 60 ث) لنماذج الكتابة، بنفس سلسلة البدائل."""
    import json as _j
    import os as _o
    import urllib.request as _r
    from tools import editorial as E
    key = _o.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    for model in E.MODELS:
        if model in E._EXHAUSTED:
            continue
        body = _j.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.35, "maxOutputTokens": 8192}}).encode()
        req = _r.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", data=body,
                         headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with _r.urlopen(req, timeout=60) as r:
                d = _j.loads(r.read().decode())
            c0 = d["candidates"][0]
            txt = "".join(p.get("text", "") for p in c0.get("content", {}).get("parts", []) if not p.get("thought"))
            LAST_FINISH[0] = f"{model}:{c0.get('finishReason')}:{len(txt.split())}w"
            if c0.get("finishReason") not in (None, "STOP") or len(txt.split()) < 120:
                continue  # مقطوع أو قصير: النموذج التالي
            return txt
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", None) in (429, 404, 403):
                E._EXHAUSTED.add(model)
            continue
    return None


def data_reading(a):
    """بديل بلا نموذج لغوي: قراءة في بيانات التغطية نفسها (حقائق محسوبة فقط، بلا آراء)."""
    short = " ".join(a["title"].split(":")[-1].split()[:9])
    title = f"قراءة في التغطية: {short}"
    k = a.get("kinds") or {}
    parts = [f"الخلاصة: «{a['title']}» كان من أكثر الأحداث العراقية تداولاً اليوم، إذ نشرته {a['n_sources']} جهة ضمن المصادر التي نرصدها."]
    ctx = []
    if a.get("first"):
        ctx.append(f"أقدم ظهور رصدناه كان لدى {(a['first'].get('source') or '').split(' — ')[0]}")
    if a.get("reach10_min") is not None:
        m = a["reach10_min"]
        ctx.append(f"وبلغ عشر جهات خلال {m} دقيقة" if m < 90 else f"وبلغ عشر جهات خلال نحو {round(m / 60)} ساعة")
    if ctx:
        parts.append("السياق: " + "، ".join(ctx) + ".")
    if k:
        parts.append("القراءة: توزّع الناشرون بين " + "، ".join(f"{n} ({v})" for n, v in k.items()) + "."
                     + (" ولا يوجد مصدر رسمي بين الناشرين حتى الآن." if not a.get("official") else " ومن بين الناشرين جهة رسمية واحدة على الأقل."))
    if len(a.get("narratives") or []) > 1:
        parts.append("الصياغات المتداولة: " + " / ".join(f"«{n['title'][:110]}»" for n in a["narratives"][:3]))
    if a.get("denial"):
        parts.append("ظهر نفي أو تصحيح ضمن التغطية: «" + a["denial"][0]["title"][:140] + "».")
    parts.append("ما لم يتأكد: " + " ".join((a.get("open") or [])[:3]))
    return title, "\n\n".join(parts)


# ───────────── «قراءة هسة وصل»: رأي تحريري بأسلوب محلل الاستوديو، بزاوية إيجابية بنّاءة للعراق ─────────────
OP_HEADS = ("رأينا:", "ماذا يعني للعراق:", "ماذا يعني للمواطن:", "الفرصة والخطوة التالية:", "ما ننتظره:")
OP_PROMPT = ("أنت محلل سياسي واقتصادي عراقي في استوديو قناة إخبارية عراقية، تعلّق على الخبر التالي كما يفعل المحللون على الشاشة: "
             "رأي واضح، قراءة لمعناه وأثره، لا سرد لمن نشره ولا كم مرة نُشر. اكتب «قراءة هسة وصل» (200–300 كلمة) بزاوية إيجابية بنّاءة "
             "لمصلحة العراق والمواطن: أبرز الفرصة والمكسب وما يجعل الخطوة تنجح، بواقعية ودون تهويل أو دعاية. "
             "ابدأ بسطر «العنوان: …» (عنوان رأي جذاب من 6 إلى 11 كلمة)، ثم خمس فقرات قصيرة تبدأ بهذه العناوين حرفياً كلٌّ في سطر جديد:\n"
             + "\n".join(OP_HEADS) + "\n"
             "قواعد صارمة: لا تضف أي رقم أو اسم شخص أو تاريخ أو وعد غير موجود في المعطيات؛ لا تمدح ولا تهاجم أي شخصية أو حزب أو كتلة بالاسم — "
             "المصلحة هي العراق والمواطن لا الأشخاص؛ لا تتهم أحداً؛ إن كان في الخبر جانب ناقص فاذكر ما يحتاجه ليكتمل بصيغة بنّاءة؛ "
             "التوقعات بصيغة احتمال؛ لا تنكر أي واقعة سلبية في المعطيات. عربية فصحى سلسة قريبة من لغة الشاشة، جمل قصيرة، بلا رموز تعبيرية ولا تنسيق Markdown.\n\nالمعطيات:\n")
OP_NEG = re.compile(r"(مقتل|قتلى|شهداء|استشهاد|جرحى|انفجار|اغتيال|اعتقال|القبض|اشتباك|قصف|هجوم|حريق|غرق|سرقة|احتيال|اختلاس|فساد|السجن|"
                    r"إعدام|اتهام|كارثة|وفاة|إصابة|جريمة|مخدرات|إرهاب|ارهاب|تظاهر|احتجاج|إضراب)")


def op_facts(a):
    f = [f"الخبر: {a['title']}", f"حالة التحقق: {a.get('vstatus') or 'غير متحقق'}"]
    f += [f"صياغة أخرى للخبر: «{n['title']}»" for n in (a.get("narratives") or [])[:3]]
    f += [f"نفي/تصحيح ظهر: «{n['title']}»" for n in (a.get("denial") or [])[:2]]
    f += [f"من نص الخبر: {e['text']}" for e in (a.get("excerpts") or [])[:4]]
    return "\n".join(f)


def op_eligible(a):
    return not OP_NEG.search(a.get("title") or "") and not any(OP_NEG.search(n.get("title") or "") for n in (a.get("narratives") or [])[:2])


def write_opinion(a):
    """يرجع (العنوان، النص) أو None — بلا بديل آلي: إن فشل النموذج أو الحارس لا يُنشر شيء في هذه الجولة."""
    from tools import editorial as E
    ftxt = op_facts(a)
    old = E.MODELS[:]
    try:
        E.MODELS[:] = ART_MODELS
        out = _gem_long(OP_PROMPT + ftxt)
    finally:
        E.MODELS[:] = old
    if not out:
        return None
    out = re.sub(r"[*#_`]+", "", out).strip()
    m = re.search(r"العنوان\s*:\s*(.+)", out)
    if not m:
        return None
    title, body = m.group(1).strip().strip("«»\""), out[m.end():].strip()
    if not all(h in body for h in ("رأينا:", "ماذا يعني للمواطن:", "الفرصة والخطوة التالية:")) or not (140 <= len(body.split()) <= 380):
        return None
    if not set(E.DIGITS.findall(title + " " + body)) <= set(E.DIGITS.findall(ftxt)):
        return None
    if ACCUSE.search(title + body) and not ACCUSE.search(ftxt):
        return None
    if re.search(r"(نشرت|نقلت|تداولت)\s+\S*\s*(جهة|جهات|وسائل|منصات)", body):
        body = body  # تذكير: ليس قراءة انتشار؛ الحارس الرقمي يكفي
    if len(title.split()) > 13 or len(title) < 10:
        title = a["title"]
    return title, body
