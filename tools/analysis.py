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
