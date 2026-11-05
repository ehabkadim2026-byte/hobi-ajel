"""حلقة التعلّم من المشاهدات: نسجّل مشاهدات كل منشور في قناتنا (من صفحتها العامة)، ونحسب أسبوعياً أي المواضيع والساعات تجذب أكثر،
ثم نعطي الناشر «معامل اهتمام» محافظاً لكل موضوع (بين 0.6 و1.4) يستعمله فقط لترتيب الأولوية عند الزحام وفي المنوعات.
المشاهدات = مرات عرض المنشور وقت القياس، وليست أشخاصاً فريدين ولا «رأياً عاماً».
"""
import re
from datetime import datetime, timedelta, timezone

TOPICS = [
    ("أمني", r"(اعتقال|القبض|مقتل|قتلى|جرحى|إصابة|انفجار|اشتباك|هجوم|قصف|غارة|إرهاب|ارهاب|مخدرات|عصابة|الاستخبارات|الأمن الوطني|خلية الإعلام الأمني|الحشد|الجيش)"),
    ("رواتب ومعيشة", r"(رواتب|الرواتب|راتب|تمويل|السلف|المتقاعدين|التقاعد|الرعاية الاجتماعية|البطاقة التموينية|الحصة التموينية|منحة)"),
    ("تعليم", r"(التربية|التعليم|امتحانات|الامتحانات|الدور الثالث|الطلبة|القبول|الجامعات|دوام|عطلة|تعطيل)"),
    ("اقتصاد وأسعار", r"(الدولار|سعر صرف|البنك المركزي|النفط|الموازنة|الذهب|أسعار|الاستثمار|الكمارك|المنافذ)"),
    ("خدمات", r"(الكهرباء|الماء|المجاري|الطرق|المولدات|الأمطار|الامطار|السيول|البلدية|أمانة بغداد|الوقود|النفط الأبيض|الغاز)"),
    ("سياسة", r"(البرلمان|مجلس النواب|رئيس الوزراء|رئيس مجلس الوزراء|رئيس الجمهورية|الحكومة|وزير|الكتل|التحالف|الإطار|الانتخابات|مجلس الوزراء)"),
    ("قضاء ونزاهة", r"(القضاء|المحكمة|النزاهة|الحكم|السجن|اختلاس|فساد|استرداد)"),
    ("إقليمي ودولي", r"(إيران|ايران|سوريا|لبنان|إسرائيل|اسرائيل|غزة|تركيا|السعودية|الخليج|واشنطن|ترامب|روسيا)"),
    ("رياضة", r"(?<![\u0600-\u06FF])[وبل]?(المنتخب|الدوري|مباراة|نادي|بطولة|ملعب|اللاعب|المدرب)(?![\u0600-\u06FF])"),  # كلمة كاملة: «الدوريات/ينادي» ليست رياضة
    ("طقس", r"(الأنواء|الانواء|طقس|درجات الحرارة|غبار|عاصفة)"),
]
TOPICS = [(k, re.compile(v)) for k, v in TOPICS]
MIN_SAMPLE = 120  # لا نعدّل شيئاً قبل أن يتجمع عدد كافٍ من المنشورات الناضجة


def topic(title):
    for k, rx in TOPICS:
        if rx.search(title or ""):
            return k
    return "عام"


def record(sent, posts):
    """يحدّث سجل المشاهدات (آخر قيمة لكل منشور) — يُحفظ في tg_sent.json تحت _views (8 أيام)."""
    log = sent.setdefault("_views", {})
    for p in posts:
        k = str(p["msg"])
        e = log.get(k) or {"t": p["t"].isoformat(), "title": p["title"][:120], "kind": p["kind"], "topic": topic(p["title"]),
                           "brk": bool(p.get("brk"))}
        e["v"] = max(e.get("v", 0), p["views"])
        e["seen"] = datetime.now(timezone.utc).isoformat()
        log[k] = e
    cut = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    sent["_views"] = {k: v for k, v in log.items() if v["t"] >= cut}
    return sent["_views"]


def _med(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else 0


def analyse(log):
    """المنشورات الناضجة فقط (عمرها 20 ساعة فأكثر عند آخر قياس) — المشاهدات تستقر تقريباً بعد يوم."""
    mature = []
    for e in log.values():
        try:
            age = (datetime.fromisoformat(e["seen"]) - datetime.fromisoformat(e["t"])).total_seconds() / 3600
        except (KeyError, ValueError):
            continue
        if age >= 20 and e.get("v"):
            mature.append(e)
    allm = _med([e["v"] for e in mature]) or 1
    by_t, by_h, by_k = {}, {}, {}
    for e in mature:
        by_t.setdefault(e["topic"], []).append(e["v"])
        h = (datetime.fromisoformat(e["t"]) + timedelta(hours=3)).hour
        by_h.setdefault(h, []).append(e["v"])
        by_k.setdefault("عاجل" if e.get("brk") else e["kind"], []).append(e["v"])
    lift = {k: round(min(1.4, max(0.6, _med(v) / allm)), 2) for k, v in by_t.items() if len(v) >= 8}
    return {
        "n": len(mature), "median": allm, "active": len(mature) >= MIN_SAMPLE,
        "topics": {k: {"n": len(v), "median": _med(v), "lift": lift.get(k)} for k, v in sorted(by_t.items(), key=lambda kv: -_med(kv[1]))},
        "hours": {h: {"n": len(v), "median": _med(v)} for h, v in sorted(by_h.items())},
        "kinds": {k: {"n": len(v), "median": _med(v)} for k, v in by_k.items()},
        "lift": lift if len(mature) >= MIN_SAMPLE else {},
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def lift_of(sent, title):
    return (sent.get("_learn") or {}).get("lift", {}).get(topic(title), 1.0)


def weekly_report(a):
    if not a["n"]:
        return None
    L = [f"📈 ماذا يجذب متابعي القناة؟ (آخر 7 أيام، {a['n']} منشوراً ناضجاً، الوسيط {a['median']:,} مشاهدة)", "", "حسب الموضوع (وسيط المشاهدات):"]
    L += [f"• {k}: {v['median']:,} ({v['n']} منشور)" + (f" — معامل {v['lift']}" if v.get("lift") else "") for k, v in list(a["topics"].items())[:10]]
    hs = sorted(((v["median"], h) for h, v in a["hours"].items() if v["n"] >= 5), reverse=True)
    if hs:
        L += ["", "أفضل الساعات (بغداد): " + "، ".join(f"{h}:00 ({m:,})" for m, h in hs[:4]),
              "أضعف الساعات: " + "، ".join(f"{h}:00 ({m:,})" for m, h in hs[-3:])]
    L += ["", "حسب النوع: " + "، ".join(f"{k} {v['median']:,}" for k, v in a["kinds"].items() if v["n"] >= 5)]
    L.append("\n" + ("التعديل التلقائي مفعّل: المواضيع الأعلى اهتماماً تأخذ أولوية عند الزحام وفي المنوعات (العاجل لا يتأثر)."
                     if a["active"] else f"التعديل التلقائي يبدأ بعد تجمّع {MIN_SAMPLE} منشوراً ناضجاً."))
    L.append("المشاهدات مرات عرض وليست أشخاصاً فريدين.")
    return "\n".join(L)
