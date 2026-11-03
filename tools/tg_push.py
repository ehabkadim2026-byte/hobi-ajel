"""إرسال العاجل والمهم عن العراق والحشد إلى قناة/مجموعة تلغرام خاصة بالفريق، وموجز يومي الساعة 8 صباحاً بتوقيت بغداد.

التفعيل: سرّ MARSAD_TG_BOT_TOKEN في إعدادات GitHub (لا يوضع في الكود أو المحادثة).
معرّف القناة: MARSAD_TG_CHAT_ID (اختياري). إن لم يوجد، يكتشفه تلقائياً من آخر قناة/مجموعة أُضيف لها البوت مشرفاً
وكُتبت فيها رسالة، ويحفظه في data/tg_chat.json (مخبأ مع قاعدة البيانات).
كل حدث يُرسل مرة واحدة، ويُعاد فقط عند تطور جوهري (ارتفاع المستوى أو زيادة الجهات اثنتين فأكثر).
الحالة تُكتب في pwa/tg_status.json بلا توكن ولا معرّفات.
"""
import html as H
import json
import re
import os
import uuid
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PWA = ROOT / "pwa"
SENT = DATA / "tg_sent.json"
CHAT = DATA / "tg_chat.json"
STATUS = PWA / "tg_status.json"
APP_URL = "https://ehabkadim2026-byte.github.io/hobi-ajel/"
MAX_PER_RUN = 15
DEBUG = []
CHANNEL = "https://t.me/hassawassal"
RANK = {"عاجل": 3, "مهم": 2, "متابعة": 1}
MAX_PER_HOUR = 12
REGION_MIN_SOURCES = 12
REGION_PER_HOUR = 3


def api(token, method, files=None, **params):
    if files:  # multipart لرفع صورة البطاقة
        b = uuid.uuid4().hex
        body = b""
        for k, v in params.items():
            body += f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        for k, spec in files.items():
            fn, data = spec[0], spec[1]
            ctype = spec[2] if len(spec) > 2 else "image/jpeg"
            body += f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fn}\"\r\nContent-Type: {ctype}\r\n\r\n".encode() + data + b"\r\n"
        body += f"--{b}--\r\n".encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    else:
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=urllib.parse.urlencode(params).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def load(p, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def bg(iso):
    if not iso:
        return ""
    d = datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(hours=3)
    return d.strftime("%H:%M")


def src(n):
    s = (n.get("sources") or [{}])[0]
    name = (s.get("name") or "").replace(" — telegram", "").replace(" — RSS", "").replace(" (عبر Google News)", "")
    return name, s.get("url") or ""


def rank(n):
    return 3 if n.get("source_flag") else RANK.get(n.get("level"), 0)


_SIGS = {}
FRESH_MIN = 15  # خبر نشرته أي جهة مرصودة قبل أكثر من 15 دقيقة لا يُنشر (طلب إيهاب 2026-11-03)
SEC_RX = re.compile(r"(خلية الإعلام الأمني|الإعلام الأمني|قيادة العمليات|عمليات بغداد|الاستخبارات|جهاز الأمن الوطني|مكافحة الإرهاب|داعش|إرهابي|ارهابي|"
                    r"عبوة|انفجار|تفجير|اشتباك|هجوم|استهداف|قصف|طائرة مسيرة|مسيّرة|اغتيال|اختطاف|مقتل|استشهاد|القبض على|اعتقال|تسلل|صاروخ|إطلاق نار|اطلاق نار)")
SURGE_MIN = 5  # 5 جهات مختلفة خلال 20 دقيقة = خبر يتصاعد الآن


def surging(n):
    return (n.get("surge_n") or 0) >= SURGE_MIN


OFFICIAL_RX = re.compile(r"(رئاسة الوزراء|مجلس الوزراء|خلية الإعلام الأمني|وزارة|الحكومة|مجلس النواب|القضاء|مفوضية|البنك المركزي|رئاسة الجمهورية|قيادة العمليات)")


def importance(n):
    """درجة أهمية (لا «كم» بل «نوع»): مستوى الخبر، سرعة انتشاره الآن، مصدر رسمي، تعدد الجهات المستقلة، وحدث فعلي لا تصريح."""
    import math
    t = n.get("title") or ""
    sc = rank(n) * 2.0 + math.log2(1 + (n.get("independent") or n.get("n_sources") or 1))
    sc += 2.5 if surging(n) else (1.0 if n.get("escalating") else 0)
    sc += 1.0 if OFFICIAL_RX.search(t) else 0
    sc += 2.5 if SEC_RX.search(t) and iraq_strict(t) else 0  # الأمني العراقي أولاً
    sc += 1.0 if EVENT_RX.search(t) else 0
    sc -= 1.5 if ROUTINE_RX.search(t) else 0
    sc -= 1.0 if STATEMENT_RX.search(t) and not OFFICIAL_RX.search(t) else 0
    return round(sc, 2)


IRAQ_T = None


def _markers():
    global IRAQ_T
    if IRAQ_T is None:
        from tools.export_pwa import IRAQ_AR, FOREIGN_AR
        from marsad.textnorm import norm_ar
        extra_f = [norm_ar(w) for w in ["حمص", "حلب", "إدلب", "ادلب", "دير الزور", "خانيونس", "خان يونس", "رفح", "بيروت", "الجنوب اللبناني", "صنعاء", "عدن",
                                         "اليمنية", "اليمني", "السورية", "اللبنانية", "الإسرائيلية", "الاسرائيلي", "الاحتلال", "نتنياهو", "تل أبيب",
                                         "بولندا", "البولندي", "المجر", "أوربان", "كييف", "موسكو", "بوتين", "زيلينسكي", "الأوكرانية", "الروسية", "الكرملين",
                                         "السودان", "الخرطوم", "ليبيا", "تونس", "المغرب", "الجزائر", "باكستان", "الهند", "أفغانستان", "طالبان", "كوريا", "اليابان", "ألمانيا",
                                         "الخليل", "رام الله", "نابلس", "جنين", "الضفة", "غزة", "القدس", "الكنيست", "الليكود", "الحريديم", "الدعم السريع",
                                         "سيستان", "بلوشستان", "فلوريدا", "كولورادو", "أريزونا", "كاليفورنيا", "تكساس", "ترامب", "ترمب", "البيت الأبيض",
                                         "الأمريكي", "الأمريكية", "الأميركي", "الأميركية", "الكونغرس", "مجلس الشيوخ", "الجمهوريين", "الديمقراطيين"]]  # «مجلس النواب الأمريكي» مرّ عراقياً (تدقيق 2878)
        extra_i = [norm_ar(w) for w in ["الرافدين", "كوردستان", "كردستان", "الكرد", "الأكراد", "حكومة الإقليم", "النزاهة", "المنافذ", "الرواتب",
                                         "التربية النيابية", "النيابية", "النائب", "النائبة", "المحافظة", "محافظ", "المرسومي", "الحلبوسي", "المالكي", "الصدر",
                                         "الحكيم", "العبادي", "بارزاني", "طالباني", "الحشد", "خلية الإعلام الأمني", "الداخلية", "البنك المركزي"]]
        IRAQ_T = (IRAQ_AR + extra_i, FOREIGN_AR + extra_f)
    return IRAQ_T


FAR = None


def far_title(title):
    """خبر بعيد عن الشرق الأوسط (روسيا/أوكرانيا/أوروبا/آسيا البعيدة) ولا يذكر العراق ولا المنطقة."""
    global FAR
    from marsad.textnorm import norm_ar
    if FAR is None:
        FAR = [norm_ar(w) for w in ["روسيا", "الروسية", "الروسي", "موسكو", "بوتين", "الكرملين", "أوكرانيا", "الأوكرانية", "الأوكراني", "كييف", "زيلينسكي",
                                     "بولندا", "البولندي", "المجر", "أوربان", "ألمانيا", "فرنسا", "بريطانيا", "إيطاليا", "إسبانيا", "أوروبا", "الأوروبي",
                                     "الصين", "اليابان", "كوريا", "الهند", "باكستان", "أفغانستان", "طالبان", "أستراليا", "البرازيل", "المكسيك", "كندا",
                                     "السودان", "الخرطوم", "دارفور", "الفاشر", "حلفا", "ليبيا", "تونس", "الجزائر", "المغرب", "فلوريدا", "كاليفورنيا", "تكساس", "نيويورك", "شيكاغو", "الدوري الإسباني", "برشلونة", "ريال مدريد"]]
    t = " " + norm_ar(title or "") + " "
    return any(w in t for w in FAR)


IQ_GENERIC = None
AMBIG = [("الجيش السوداني", "السودان"), ("مجلس الوزراء السوداني", "السودان"), ("وزير الخارجية السوداني", "السودان"), ("الرئيس السوداني", "السودان"),
         ("الشعب السوداني", "السودان"), ("الحكومة السودانية", "السودان"), ("السودانية", "السودان"), ("مجلس السيادة", "السودان")]


def _clean_ambig(t):
    from marsad.textnorm import norm_ar
    for a, b in AMBIG:
        t = t.replace(norm_ar(a), norm_ar(b))
    return t


def iraq_strict(title):
    """للمسار العراقي: علامة عراقية صريحة مطلوبة. الكلمات العامة (محافظ، مجلس الوزراء، النائب…) لا تكفي إذا وُجدت علامة أجنبية،
    ولا يكفي غياب الدول الأجنبية وحده (فلوريدا، الليكود… كانت تمر كأخبار عراقية)."""
    global IQ_GENERIC
    from marsad.textnorm import norm_ar
    iq, fr = _markers()
    if IQ_GENERIC is None:
        IQ_GENERIC = {norm_ar(w) for w in ["محافظ", "المحافظة", "النائب", "النائبة", "النيابية", "الداخلية", "الرواتب", "المنافذ", "النزاهة",
                                           "البنك المركزي", "الحكيم", "الصدر", "العبادي", "مجلس الوزراء", "مجلس النواب", "الطلبة", "الدينار"]}
    t = _clean_ambig(" " + norm_ar(title or "") + " ")
    hits = [w for w in iq if w and w in t]
    if not hits:
        return False
    if any(w and w in t for w in fr) or far_title(title):
        return any(w not in IQ_GENERIC for w in hits)
    return True


def iraq_title(title):
    """فحص على مستوى العنوان نفسه: عنوان فيه بلد/جهة أجنبية بلا أي إشارة عراقية = خبر غير عراقي (لا يُنشر بقناة أخبار العراق)."""
    from marsad.textnorm import norm_ar
    iq, fr = _markers()
    t = _clean_ambig(" " + norm_ar(title or "") + " ")
    has_iq = any(w and w in t for w in iq)
    has_fr = any(w and w in t for w in fr)
    return has_iq or not has_fr


JUNK = re.compile(r"^[#\s\W]*$|^(?:#\S+\s*)+$")
# ترويج قنوات ومناشدات ومنوعات: ليست أخباراً للقناة
PROMO_RX = re.compile(r"(تابعونا|اشترك|انضموا|رابط القناة|قناتنا|ميمز|ميمات|نكت|مسابقة|سحب على|هدية|كود خصم|إعلان ممول|"
                      r"قناة\s+\S+\s+(?:توفر|تطلق|تقدم)|مناشدة|يناشد|تناشد|نناشد|صباح الخير|مساء الخير|جمعة مباركة)")
ME_RX = None
# أخبار إقليمية روتينية لا تخص جمهور قناة عراقية: أسواق الأسهم، رياضة، طقس دول أخرى
MINOR_RX = re.compile(r"(مؤشر السوق|البورصة|الأسهم|سوق الأسهم|تداول السعودية|الدوري|مباراة|المنتخب السعودي|المنتخب المصري|كأس الخليج|حالة الطقس)")


def me_title(title):
    """إشارة إيجابية للشرق الأوسط: بلد أو جهة أو مدينة من المنطقة صراحة (لا يكفي غياب الدول البعيدة)."""
    global ME_RX
    from marsad.textnorm import norm_ar
    if ME_RX is None:
        ws = ["إيران", "الإيراني", "الإيرانية", "طهران", "عراقجي", "خامنئي", "بزشكيان", "سوريا", "السوري", "السورية", "دمشق", "الشرع", "لبنان", "اللبناني",
              "بيروت", "إسرائيل", "الإسرائيلي", "الإسرائيلية", "نتنياهو", "تل أبيب", "غزة", "الضفة", "فلسطين", "الفلسطيني", "تركيا", "التركي", "التركية",
              "أنقرة", "أردوغان", "السعودية", "السعودي", "الرياض", "بن سلمان", "الإمارات", "الإماراتي", "أبوظبي", "دبي", "قطر", "القطري", "الدوحة",
              "الكويت", "الكويتي", "البحرين", "عمان", "مسقط", "الأردن", "الأردني", "عمّان", "مصر", "المصري", "القاهرة", "السيسي", "اليمن", "اليمني",
              "الحوثي", "صنعاء", "الخليج", "هرمز", "البحر الأحمر", "أوبك", "برنت"]
        ME_RX = [norm_ar(w) for w in ws]
    t = " " + norm_ar(title or "") + " "
    return any(w in t for w in ME_RX)


VARIETY = [("رياضة", re.compile(r"(المنتخب العراقي|منتخبنا|أسود الرافدين|الدوري العراقي|دوري نجوم العراق|الزوراء|القوة الجوية|الشرطة الرياضي|نادي الطلبة|نادي الكرخ|اتحاد الكرة|كأس العراق|الأولمبية العراقية|بطولة|ملعب|مدرب)")),
           ("طقس", re.compile(r"(الأنواء الجوية|الانواء الجوية|طقس|أمطار|امطار|درجات الحرارة|موجة حر|موجة برد|غبار|عاصفة|سيول)")),
           ("ثقافة", re.compile(r"(معرض|مهرجان|فيلم|مسرح|كتاب|تراث|آثار|اثار|متحف|فنان|فنانة|شاعر|موسيقى|سياحة|سياحي)")),
           ("تقنية", re.compile(r"(تطبيق|الإنترنت|الانترنت|الذكاء الاصطناعي|منصة إلكترونية|بوابة أور|إلكتروني|الكتروني|اتصالات|الجيل الخامس)")),
           ("صحة", re.compile(r"(مستشفى|لقاح|طبي|علاج|عملية جراحية|دواء|أدوية)")),
           ("أسعار", re.compile(r"(سعر الدولار|أسعار الدولار|سعر صرف|أسعار الذهب|سعر الذهب|أسعار الطماطم|أسعار المواد)"))]
VARIETY_MAX_DAY, VARIETY_GAP = 8, 75 * 60


VARIETY_NO = re.compile(r"(اعتقال|القبض|مقتل|قتلى|جرحى|إصابة|اصابة|مشاجرة|حريق|انفجار|اشتباك|حادث|غرق|محتجز|وفاة|جثة|اغتيال|هجوم|قصف|إرهاب|ارهاب|إطفاء|توقف تغطية|إيقاف شبكة)")


def variety_kind(n):
    t = n.get("title") or ""
    if VARIETY_NO.search(t):
        return None
    for k, rx in VARIETY:
        if rx.search(t):
            return k
    return None


def worthy(n, now):
    """قناة «هسة وصل» = أخبار العراق: عاجل ومهم العراق والحشد فقط، بعنوان صالح، وليس رأياً."""
    seen = n.get("collected_utc")
    if not seen or datetime.fromisoformat(seen.replace("Z", "+00:00")) < now - timedelta(minutes=12):
        return False
    first = n.get("first_utc")  # أول نشر للخبر لدى أي مصدر مرصود: إذا انتشر قبل أكثر من 25 دقيقة فهو ليس «جديداً» للقناة
    if first and datetime.fromisoformat(first.replace("Z", "+00:00")) < now - timedelta(minutes=FRESH_MIN):
        return False
    t = n.get("title") or ""
    from tools.editorial import clean_headline
    ct = clean_headline(t)
    if JUNK.match(ct or "") or len((ct or "").split()) < 6 or PROMO_RX.search(ct) or ct.lstrip().startswith(("•", "-", "▪")):
        return False
    if n.get("ctype") == "تحليل/رأي" or low_value(ct) or incomplete(ct) or (PRESS_RX.search(ct) and (n.get("n_sources") or 1) < 4):
        return False
    if (n.get("about_iraq") or n.get("pmf")) and iraq_strict(t) and n.get("origin") != "أجنبي":
        if ROUTINE_RX.search(ct) and n.get("level") != "عاجل" and (n.get("n_sources") or 1) < 6:
            return False  # استقبالات ولقاءات وجولات روتينية: لا تُنشر إلا إذا تداولتها 6 جهات فأكثر
        return bool(n.get("source_flag")) or n.get("level") in ("عاجل", "مهم") or surging(n)
    return is_regional(n)


# عناوين ليست أخباراً: أسئلة رأي وتحليل، مسلسلات، فتاوى، توعية، مقالات رأي
LOWVAL_RX = re.compile(r"(؟\s*$|\?\s*$|مسلسل|الحلقة|حلقة|تعترف لوالد|ما حكم|حكم إعطاء|زكاة|فتوى|اليوم الدولي|اليوم العالمي|رحلة تبدأ بتجربة|"
                       r"^بالرغم من|^في كف|يشتكي من|حلاق|فكريات|نرسل لكم|عناوين جريدة|صباحكم|مساءكم|تصفح جريدة|تصفح العدد|عدد اليوم|"
                       r"^بسم الله|صدق الله|الرصد اليومي|لبرنامج|في برنامج|ضيف برنامج|\|\s*\S+(?:\s+\S+){0,3}\s+مع\s+\S+|الميدان مع|"
                       r"^(?:الإرهابي|الارهابي|المجرم|الفاسد|العميل|الخائن)\s+\S+|^كتب\s+[^:]{2,30}:|^(?:[^:]{2,25}:\s*)?(?:لماذا|ماذا|هل|كيف)\s|تنشر قائمة|«[^»]{2,25}»\s*(?:تكشف|تنفرد|ترصد|تنشر)|^(?:أكد|اكد|أكدت|اكدت|يؤكد|تؤكد)\s[^:،]{0,90}?\s(?:على\s+)?أهمية\s)")  # «أكد فلان أهمية تعزيز…» تصريح عام بلا واقعة (تدقيق 2866)  # ترويج الوسيلة لتقريرها «المعلومة» تكشف (تدقيق 2839)؛ مقال رأي «كتب فلان:» وعنوان سؤال «مراسلنا: لماذا…؟» وقوائم الأسعار (تدقيق 2827، 2829، 2823)
# عرض صحف ومواقع ومقالات: «صحيفة الشرق الأوسط: …»، «موقع الحرة: …»، «وكالة الأنباء الإيرانية: …» — ليست خبراً أولياً
PRESS_RX = re.compile(r"^(?:صحيفة|جريدة|موقع|مجلة|وكالة\s+الأنباء\s+(?:الإيرانية|الإسرائيلية|التركية)|وسائل إعلام|إعلام)\s+[^:]{2,40}:")


# عناوين باللهجة العراقية العامية (منشورات مدونين وصفحات تعليق): القناة تنشر بالفصحى فقط — طلب إيهاب 2026-11-03
DIALECT_STRONG = re.compile(r"(?<![\w])(شنو|شلون|اشلون|ماكو|اكو|أكو|هواية|ديگول|يگول|گال|گالوا|گاعد|كاعد|ديصير|ديروح|دنروح|شكد|شگد|اشكد|يمعود|لعد|چان|چذي|هيچ|هيج|"
                            r"اكدر|يكدر|نكدر|مايكدر|ماكدر|عدهم|عدنا|ماعدنا|ماعدهم|كلش|ديسوون|يسوون|سوّوا|سوو|ديحچي|يحچي|حچي|دنشوف|دشوف|هسه|هسا|"
                            r"بلكي|خوش|شبيك|شبيه|ولك|يابه|اغاتي|عيوني|اخوية|تره|ترا|ويه|وياهم|وياه)(?![\w])")
DIALECT_WEAK = re.compile(r"(?<![\w])(مو|بس|زين|راح|دا|هم|شي|لو|ليش|جان|هاي|هذول|هاذ|هذا الشي)(?![\w])")


def dialect(t):
    t = re.sub(r"هسة?\s*وصل", "", t or "")
    return bool(DIALECT_STRONG.search(t)) or len(DIALECT_WEAK.findall(t)) >= 3


def low_value(t):
    """عنوان ليس خبراً: سؤال/برنامج/فتوى/عرض صحف/شعار (فقرات بنقاط تعليق بلا فعل)، أو مكتوب بالعامية."""
    t = (t or "").strip()
    if LOWVAL_RX.search(t) or dialect(t):
        return True
    m = re.match(r"^([^:…]{2,40}?)\s*(?:…|\.\.\.)", t)
    if m and len(m.group(1).split()) <= 3 and not VERB_RX.search(m.group(1)):
        return True  # «القائم وحصيبة… انتصارٌ حاسم» / «سلاح الفصائل… اتفاق بنهايات مفتوحة»: شعار أو مقال تحليلي لا خبر (تدقيق 2815، 2783)
    return t.count("…") + t.count("...") >= 2 and not VERB_RX.search(t)
ROUTINE_RX = re.compile(r"(يستقبل|استقبل|یستقبل|يبحث مع|بحث مع|يلتقي|التقى|يزور|(?<![\w])زار(?![\w])|جولة ميدانية|يتابع|يترأس|ترأس|يستعرض|تستعرض|يشيد|تشيد|يهنئ|يعزي|"
                        r"لترؤس|يترؤس|حملة تشجير|تحتفي|يحتفي|ورشة|ندوة|مؤتمر صحفي مشترك|قسم الشرف|(?:يردد|يرددون|ردد|رددوا)\s+(?:ال)?قسم|^(?:بحث|يبحث|تبحث|ناقش|يناقش|تناقش)\s)")
ROLE_START = re.compile(r"^(رئيس|نائب|وزير|وزيرة|محافظ|مستشار|مدير|وكيل|قائد|المتحدث|الناطق|السفير|عضو)")
VERB_RX = re.compile(r"(يعلن|تعلن|أعلن|اعلن|أعلنت|يؤكد|تؤكد|أكد|اكد|يوجه|وجه|يقرر|قرر|يكشف|كشف|يحذر|حذر|ينفي|نفى|يطالب|طالب|يدعو|دعا|"
                     r"يصل|وصل|يستقبل|يبحث|يلتقي|يزور|قال|يقول|يصدر|أصدر|يفتتح|افتتح|يوافق|وافق|يصوت|صوت|:)")


def incomplete(t):
    """عنوان مبتور: ينتهي بحرف جر/كلمة معلّقة، أو اسم ومنصب فقط بلا فعل («نائب رئيس الوزراء لشؤون الخدمات فلان»)."""
    w = (t or "").rstrip(" .،…").split()
    if not w:
        return True
    if w[-1] in ("في", "من", "على", "إلى", "الى", "عن", "مع", "واقع", "بشأن", "حول", "الى", "و", "أو", "التي", "الذي", "بعد", "قبل", "ضد", "عبر"):
        return True
    if re.search(r"\sلـ\s*\S+(?:\s+\S+)?$", t.strip()) or re.search(r"(?:لـ|ل)(?:قناة|وكالة|موقع|برنامج)\s*\S*$", t.strip()):
        return True  # «النائب فلان لـ ntv عراق» = اسم المتحدث بلا تصريحه
    if re.search(r"(?:^|\s)(?:في|من|إلى|الى|بين)\s+و(?:أربيل|اربيل|البصرة|بغداد|النجف|كربلاء|الموصل|السليمانية|دهوك|كركوك|الأنبار|ديالى)", t) or \
            re.search(r"(?:^|\s)محافظة\s+(?:جراء|بعد|إثر|اثر|خلال|بسبب)\s|(?:^|\s)محافظة\s*$", t):
        return True  # اسم المحافظة سقط: «يتراجع في وأربيل»، «اختناق في محافظة جراء تسرب» (تدقيق 2824، 2833)
    if re.search(r"\d+\s*%\s*(?:من|في)\s+و\S", t):
        return True  # المعدود سقط بعد النسبة: «تأخير يضرب 91% من وتحذيرات…» (تدقيق 2855)
    return bool(ROLE_START.search(t)) and not VERB_RX.search(t) and len(w) <= 12


def is_regional(n):
    """الشرق الأوسط والمنطقة: فقط المهم والمتداول على نطاق واسع (عاجل/مهم ونشرته 5 جهات فأكثر)، لا الأخبار البعيدة عن المنطقة."""
    t = n.get("title") or ""
    if iraq_title(t) and (n.get("about_iraq") or n.get("pmf")):
        return False
    if far_title(t) or not me_title(t) or MINOR_RX.search(t):
        return False
    if STATEMENT_RX.search(t) or PRESS_RX.search(t) or not EVENT_RX.search(t):
        return False  # الإقليمي = حدث كبير (ضربة، انفجار، هجوم) لا تصريح ترمب أو وزير خارجية أو عرض صحيفة
    return (bool(n.get("source_flag")) or n.get("level") in ("عاجل", "مهم")) and (n.get("n_sources") or 1) >= REGION_MIN_SOURCES


def meta_line(n):
    name, _ = src(n)
    meta = [name, bg(n.get("latest_utc")) + " بغداد", n.get("status") or "غير مؤكد"]
    if (n.get("n_sources") or 1) > 1:
        meta.append(f"{n['n_sources']} جهات")
    if n.get("pmf"):
        meta.append("الحشد الشعبي")
    return " · ".join(x for x in meta if x)


def is_breaking(n):
    """عاجل: خبر عراقي عاجل، أو خبر إقليمي عاجل كبير جداً (8 جهات فأكثر). لا يكفي تكرار النشر وحده."""
    if rank(n) < 3:
        return False
    if NOT_URGENT_RX.search(n.get("title") or "") or low_value(n.get("title") or ""):
        return False  # خدمات وإعلانات وتصريحات بروتوكولية: تُنشر خبراً عادياً بلا شارة «عاجل»
    if iraq_strict(n.get("title") or "") and (n.get("about_iraq") or n.get("pmf")):
        return True
    t = n.get("title") or ""
    return (not far_title(t) and me_title(t) and (n.get("n_sources") or 1) >= 25 and bool(EVENT_RX.search(t)) and not STATEMENT_RX.search(t))


NOT_URGENT_RX = re.compile(r"(تصفح|جريدة|السلف|سلفة|التقديم|استمارة|نتائج القبول|المنحة|يوجه بفتح|قاعة|نسخة متميزة|أسعار خام|سعر خام|"
                           r"نقل الطلبة|استضافة ونقل|المقبولين|مرصد|لإنصاف|إتلاف|اتلاف|المحجوزة|^مرور\s|مديرية المرور|إنصاف|توجيهات|ضعف عام|تطبيق|سعر الدولار|أسعار الدولار|اسعار الدولار|صرف الدولار|الدولار ا?أ?مام|أسعار الذهب|اسعار الذهب|سعر الذهب|سعر المثقال|يهنئ|يعزي|يستقبل|استقبل|يلتقي|التقى|يشيد|الأنواء|طقس|درجات الحرارة)")
EVENT_RX = re.compile(r"(مقتل|قتلى|انفجار|انفجارات|قصف|غارة|غارات|هجوم|اغتيال|زلزال|اشتباكات|سقوط صاروخ|صواريخ|إغلاق مضيق|اجتياح|حرب)")
STATEMENT_RX = re.compile(r"^[^:]{2,40}:|(يؤكد|أكد|يقول|قال|يرى|يعتبر|صرح|يصرح|يشير)")


VAGUE_RX = re.compile(r"(شاهد|بالفيديو|بالصور|فيديو|التفاصيل|تفاصيل|إليكم|اليكم|هذا ما|ماذا|لماذا|كيف|هكذا|إليك|اليك|تعرف|الكشف عن|كشف عن|مفاجأة|\?|؟|…|\.\.\.?$)")


def is_vague(title):
    """عنوان مبهم لا يكفي وحده: قصير، أو بصيغة «شاهد/التفاصيل/ماذا…»، أو ينتهي بنقطتين."""
    t = (title or "").strip()
    words = len(t.split())
    return words < 7 or bool(VAGUE_RX.search(t)) or t.endswith(":")


def detail_url(n):
    """أفضل رابط تفاصيل للجمهور: مقال موقع مباشر، ثم منشور تلغرام، ثم رابط Google News (يحوّل للمقال)."""
    urls = [s.get("url") or "" for s in (n.get("sources") or [])]
    for test in (lambda u: u.startswith("http") and "t.me/" not in u and "news.google.com" not in u and "hobi-ajel.local" not in u,
                 lambda u: "t.me/" in u,
                 lambda u: "news.google.com" in u):
        for u in urls:
            if test(u):
                return u
    return ""


def _sstem(w):
    """تجريد لواحق خفيف للمطابقة فقط: عقارات=عقار، تلاعبوا=تلاعب، الموظفين=موظف."""
    for suf in ("ات", "ون", "ين", "وا", "ها", "هم", "يه", "ية"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    if len(w) > 4 and w[-1] in "هي":
        return w[:-1]
    return w


ACTORS = ["الزيدي", "رئيس مجلس الوزراء", "رئيس الوزراء", "رئيس الجمهورية", "رئيس مجلس النواب", "مجلس القضاء", "القضاء الأعلى", "البنك المركزي",
          "النزاهة", "خلية الإعلام الأمني", "الداخلية", "الدفاع", "الخارجية", "النفط", "الكهرباء", "التربية", "المالية", "الصحة", "التقاعد",
          "مصرف الرافدين", "الأنواء", "عراقجي", "الحرس الثوري", "حكومة الإقليم", "الحشد", "مكافحة الإرهاب", "العمليات المشتركة", "المنافذ", "الكمارك"]
_ACT = []


def lead_key(title):
    """الجهة/الشخص المتصدر للعنوان — لسقف المنشورات المتتالية عن الجهة نفسها. أولاً جهة معروفة في أول العنوان، ثم «الجهة: …»، ثم أول كلمتين."""
    from tools.tg_card import split_kicker
    from tools.editorial import clean_headline
    from marsad.textnorm import norm_ar
    if not _ACT:
        _ACT.extend(norm_ar(a) for a in ACTORS)
    t = norm_ar(clean_headline(title or ""))
    head = " ".join(t.split()[:6])
    for a in _ACT:
        if a in head:
            return a
    k, _ = split_kicker(t)
    w = (k or t).split()
    return " ".join(w[-2:] if k else w[:2])


def title_sig(t):
    """بصمة العنوان: جذور الكلمات المضمونية + الأرقام — لكشف الخبر نفسه بصياغة أخرى من جهة ثانية."""
    from tools.editorial import _stem, DIGITS, clean_headline, STYLE_OK
    t = clean_headline(t or "")
    t = re.sub(r"\s+[-–|]\s+[^-–|:]{2,25}$", "", t)  # توقيع المصدر آخر العنوان («- الواجهة»)
    words = {_sstem(_stem(w)) for w in t.split()}
    stop = {_sstem(_stem(w)) for w in STYLE_OK}
    return ({w for w in words if len(w) >= 3 and w not in stop}, set(DIGITS.findall(t)))


IDF = {}
RARE = 5.0
GENERIC = set()


def _generic():
    from tools.editorial import _stem
    return {_stem(w) for w in """جاري رفع اطلاق إطلاق تمويل يبحث بحث يبحثان يستقبل استقبل يلتقي التقى لقاء وزير وزيرة سفير السفير رئيس يعلن أعلن تعلن أعلنت
يؤكد أكد أكدت مدير عام العامة دائرة شركة الشركة وزارة محافظ مجلس لجنة يزور زار زيارة اجتماع يترأس ترأس بشأن ملف عن جديد جديدة
شهر لشهر الشهر تشرين كانون شباط آذار نيسان أيار حزيران تموز آب أيلول الثاني الأول الماضي المقبل اليوم أمس غدا العام عام لعام السنة
الواجهة عاجل العراق العراقية العراقي بغداد""".split()}


def build_idf(titles):
    """ندرة كل كلمة بين عناوين اليوم: الكلمات النادرة (أسماء، أماكن، أرقام، موضوع محدد) تحدد «نفس الخبر» أكثر من الشائعة."""
    import math
    if not GENERIC:
        GENERIC.update(_generic())
    df = {}
    for t in titles:
        for w in title_sig(t)[0]:
            df[w] = df.get(w, 0) + 1
    n = max(1, len(titles))
    IDF.clear()
    IDF.update({w: math.log((n + 1) / (c + 0.5)) for w, c in df.items()})
    for g in GENERIC:  # أفعال وصفات إخبارية شائعة لا تميّز الخبر (يبحث، جاري رفع، وزير…)
        if g in IDF:
            IDF[g] = min(IDF[g], 2.5)


def same_story(sig, prev):
    w, d = sig
    pw = set(prev.get("w") if isinstance(prev, dict) else prev[0])
    pd = set(prev.get("d") if isinstance(prev, dict) else prev[1])
    if not w or not pw:
        return False
    shared0 = w & pw
    if len(shared0) / len(w | pw) >= 0.7:
        return True  # نفس الصياغة تقريباً = نفس الخبر حتى لو اختلف رقم (تحديث يُنشر كرد لا كمنشور جديد)
    if d and pd and not (d & pd) and len(d) == len(pd) == 1 and min(len(w), len(pw)) >= 6:
        return False  # رقم مختلف بنفس الصياغة (حصيلة جديدة، هزة أخرى) = خبر مختلف
    shared = w & pw
    j = len(shared) / len(w | pw)
    dd = {x for x in d & pd if not re.fullmatch(r"(19|20)\d\d", x)}  # السنة (2026، 2027) ليست رقماً مميزاً للخبر
    if IDF and dd and sum(1 for x in shared if IDF.get(x, 6.0) >= RARE) >= 2:
        return True  # رقم مشترك + كلمتان نادرتان مشتركتان = الخبر نفسه بصياغة أخرى (حكم السجن نفسه نزل 4 مرات)
    if j >= 0.45 or (bool(d & pd) and j >= 0.3):
        return True
    if len(shared) >= 6 and len(shared) / min(len(w), len(pw)) >= 0.7:
        return True  # أغلب كلمات العنوان الأقصر موجودة في الأطول = الخبر نفسه حتى لو كانت كلماته شائعة اليوم (رواتب موظفي كردستان 2886=2887)
    if IDF:  # تشابه موزون بالندرة: نفس الأسماء والمفردات النادرة بصياغة مختلفة
        idf = lambda x: IDF.get(x, 6.0)
        sw = sum(idf(x) for x in shared)
        rare = sum(1 for x in shared if idf(x) >= RARE)  # كلمتان نادرتان مشتركتان على الأقل (اسم/مكان/موضوع محدد)
        if rare >= 4 and rare >= 0.8 * len(shared):
            return True  # أربع مفردات نادرة مشتركة وأغلب المشترك نادر (مهرب، غرق، أطفال، تركيا) = الحدث نفسه بصياغة أخرى (تدقيق 2859=2840)
        return rare >= 2 and len(shared) >= 3 and sw / max(1e-6, min(sum(idf(x) for x in w), sum(idf(x) for x in pw))) >= 0.38
    return len(shared) / min(len(w), len(pw)) >= 0.7 and len(shared) >= 4


SOUND_RX = re.compile(r"(انفجار|إنفجار|انفجارات|إنفجارات|دوي|قصف|غارة|غارات|طيران|طيرات|استهداف|صوت)")


DOLLAR_RX = re.compile(r"(?:سعر|أسعار|اسعار)\s+(?:صرف\s+)?الدولار|صرف الدولار|الدولار\s+(?:أمام|امام|مقابل)\s+الدينار|بورصات? (?:بغداد|الكفاح|الحارثية)")
INCIDENT_RX = re.compile(r"(اختناق|تسمم|تسرب|حريق|غرق|انهيار|صعق|دهس|سقوط)")


def topic_dup(title, prev, now_ts):
    """أسعار الدولار مرة كل 3 ساعات (2823، 2824، 2825، 2835 خلال ساعة)، والحادث نفسه بصياغة أخرى خلال 6 ساعات:
    كلمتا حادث مشتركتان + كلمة مضمونية أخرى («اختناق طلبة مدرسة بتسرب غاز» 2822 ثم «إصابة 52 طالبة… تسرب غاز» 2833)."""
    t = title or ""
    if DOLLAR_RX.search(t):
        return any(x.get("ts", 0) >= now_ts - 3 * 3600 and DOLLAR_RX.search(x.get("title") or "") for x in prev)
    inc = set(INCIDENT_RX.findall(t))
    if not inc:
        return False
    w = title_sig(t)[0]
    for x in prev:
        pt = x.get("title") or ""
        if x.get("ts", 0) >= now_ts - 6 * 3600 and len(inc & set(INCIDENT_RX.findall(pt))) >= 2 and len((w & title_sig(pt)[0]) - set(INCIDENT_RX.findall(pt))) >= 2:
            return True
    return False


def sec_dup(title, prev, now_ts, hours=2):
    """بلاغات الانفجار/القصف في المحافظة نفسها خلال ساعتين = حدث واحد مهما اختلفت الصياغة
    (ديالى: «سماع انفجار» ثم «دوي انفجارات مصدرها مجهول»، صلاح الدين: «قصف جوي» ثم «سمعنا صوت طيرات» — تدقيق 2820، 2817)."""
    if topic_dup(title, prev, now_ts):
        return True
    if not SOUND_RX.search(title or ""):
        return False
    tags = set(province_tags(title)) - {"#بغداد"}
    if not tags:
        return False
    for x in prev:
        pt = x.get("title") or ""
        if x.get("ts", 0) >= now_ts - hours * 3600 and SOUND_RX.search(pt) and tags & set(province_tags(pt)):
            return True
    return False


def is_important(n):
    return is_breaking(n) or n.get("level") in ("عاجل", "مهم")


def headline(n):
    """وكيل التحرير: للخبر المهم الذي لدينا نصه نكتب عنواناً + جملة مقدمة (Gemini بحارس حقائق)؛ وإلا العنوان المحرر في التطبيق."""
    if "_hl" not in n:
        from tools.editorial import clean_headline, agent_write, os_key
        if n.get("lead") and os_key():
            n["_hl"], n["_lead"] = agent_write(n["title"], n["lead"])
        else:
            n["_hl"] = clean_headline(n["title"])
            n["_lead"] = ""
    return n["_hl"]


PROVINCES = ["بغداد", "البصرة", "نينوى", "الموصل", "أربيل", "كركوك", "النجف", "كربلاء", "السليمانية", "الأنبار", "ديالى", "صلاح الدين",
             "ذي قار", "بابل", "ميسان", "واسط", "دهوك", "المثنى", "الديوانية", "حلبجة", "الفلوجة", "سنجار"]
TAG_OF = {"الموصل": "نينوى", "الفلوجة": "الأنبار", "سنجار": "نينوى"}


def province_tags(title):
    from marsad.textnorm import norm_ar
    t = " " + norm_ar(title or "") + " "
    tags = []
    for p in PROVINCES:
        if norm_ar(p) in t:
            tag = "#" + TAG_OF.get(p, p).replace(" ", "_")
            if tag not in tags:
                tags.append(tag)
    return tags[:2]


def src_label(n):
    name, _ = src(n)
    name = re.sub(r"\s*[—-]\s*(telegram|RSS|يوتيوب)$", "", name or "", flags=re.I).strip()
    if not name or name.startswith("إدخال يدوي") or "Google News" in name:
        return ""
    return name[:50]


def verify_line(n):
    """سطر التحقق المهني: ما الذي نعرفه عن موثوقية الخبر وقت النشر (لا يعني كثرة النشر صحته)."""
    st = n.get("vstatus") or ""
    if st == "ثبت عدم صحته":
        return "❌ التحقق: ثبت عدم صحته"
    if n.get("source_flag") or (n.get("status") or "").startswith("مؤكد") or st == "منسوب لمصدر رسمي":
        return "✅ التحقق: صادر عن جهة رسمية"
    ind = n.get("independent") or 0
    if st == "مؤيد بمصادر مستقلة" or ind >= 2:
        return f"☑️ التحقق: متطابق لدى {max(ind, 2)} جهات مستقلة"
    if st == "متنازع عليه":
        return "⚠️ التحقق: روايات متعارضة"
    return "⏳ التحقق: غير مؤكد بعد — مصدر واحد"


def fmt(n, update=False, kind="news"):
    """الخبر المحرَّر + المصدر + وسم المحافظة + دعوة القناة. التفاصيل صارت زراً تحت الخبر."""
    mark = "🔴 عاجل | " if is_breaking(n) else ""
    if kind == "update":
        mark = "🔄 تحديث | "
    lines = [f"<b>{mark}{H.escape(headline(n))}</b>"]
    if n.get("_lead"):
        lines[0] += "\n" + H.escape(n["_lead"])
    sl = src_label(n)
    if sl:
        lines.append(f"📌 المصدر: {H.escape(sl)}")
    lines.append(verify_line(n))
    tags = province_tags(n.get("title"))
    if tags:
        lines.append(" ".join(tags))
    return "\n\n".join([lines[0], "\n".join(lines[1:])] if len(lines) > 1 else lines) + f"\n\nزورونا على الرابط للأخبار العاجلة 👇\n{CHANNEL}"


def buttons(n):
    import urllib.parse as _u
    row = []
    url = detail_url(n)
    if url and (is_important(n) or is_vague(n["title"])):
        row.append({"text": "📖 التفاصيل", "url": url})
    share = "https://t.me/share/url?" + _u.urlencode({"url": CHANNEL, "text": "هسة وصل — أخبار العراق لحظة بلحظة"})
    row.append({"text": "↗️ شارك القناة", "url": share})
    rows = [row]
    if BOT_USER[0]:
        rows.append([{"text": "🔔 أخبار محافظتك بالخاص", "url": f"https://t.me/{BOT_USER[0]}?start=sub"}])
    return json.dumps({"inline_keyboard": rows}, ensure_ascii=False)


BOT_USER = [""]


MSGS = DATA / "tg_msgs.json"


def fastlane_sigs(name="fast_sigs.json"):
    import subprocess
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run(["gh", "release", "download", "fastlane", "-p", name, "-D", td, "--clobber"], capture_output=True, timeout=25)
            return json.loads((Path(td) / name).read_text(encoding="utf-8")) if r.returncode == 0 else []
    except Exception:  # noqa: BLE001
        return []


DEDUP_H = 36  # نافذة منع التكرار: خبر الأمس نفسه لا يُعاد اليوم (احتجاج الشاحنات تكرر في يومين)


def publish_main_sigs(titles, name="main_sigs.json"):
    """بصمات ما نُشر (آخر 36 ساعة) على إصدار fastlane ليقرأها كل مسار (رئيسي/سريع/تلفزيون) فلا يكرر غيره."""
    import subprocess
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / name
            p.write_text(json.dumps([x for x in titles if x.get("ts", 0) >= datetime.now(timezone.utc).timestamp() - DEDUP_H * 3600][-600:], ensure_ascii=False), encoding="utf-8")
            if subprocess.run(["gh", "release", "view", "fastlane"], capture_output=True, timeout=25).returncode:
                subprocess.run(["gh", "release", "create", "fastlane", "--title", "المسار السريع", "--notes", "بصمات المنشور بين المسارين", "--prerelease"],
                               capture_output=True, timeout=25)
            subprocess.run(["gh", "release", "upload", "fastlane", str(p), "--clobber"], capture_output=True, timeout=25)
    except Exception:  # noqa: BLE001
        pass


CARDS = PWA / "cards"
ANIM = DATA / "anim"
CARD_STYLE = "news4A"  # «شاشة الحدث» 2026-11-03: صورة كاملة، أحمر للعاجل فقط مع وميض متحرك. قبلها news3 # «نشرة ٣» عمودي 4:5 بشعار ملوّن مميز، يُرسل صورة قابلة للحفظ — طلب إيهاب 2026-11-03. قبلها: # «نشرة ٢» شريط تلفزيوني كامل وشعار مفرّغ — طلب إيهاب 2026-11-02 (قبلها «news»)  # «نشرة» بأسلوب القنوات الإخبارية وخط Cairo — طلب إيهاب 2026-11-01 (قبلها «lux»)  # «أ» الفاخر (زجاج مغبّش + معالجة سينمائية) — طلب إيهاب قالباً أفخم 2026-11-01 (قبلها «a»)
PENDING = DATA / "tg_pending.json"


def news_photo(n):
    from tools import tg_card
    _, url = src(n)
    img = tg_card.find_image(url)
    if img:
        try:
            return tg_card.fetch_jpeg(img)
        except Exception:  # noqa: BLE001
            return None
    return None


def save_card(jpg, key):
    CARDS.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9_]", "", key)[:40] + f"_{int(datetime.now(timezone.utc).timestamp())}.jpg"
    (CARDS / name).write_bytes(jpg)
    return name


def prepare_card(n, tag=None):
    """يصنع بطاقة الخبر (صورة المصدر أو خلفية الهوية) ويحفظها في pwa/cards ليُنشر رابطها مع موقع التطبيق."""
    from tools import tg_card
    _, url = src(n)
    img = tg_card.find_image(url)
    DEBUG.append(f"{urllib.parse.urlparse(url).netloc}:{'img' if img else 'noimg'}")
    photo = None
    if img:
        try:
            photo = tg_card.fetch_jpeg(img)
        except Exception as e:  # noqa: BLE001
            DEBUG.append(f"imgfail:{type(e).__name__}")
    maker = {"news2": tg_card.card_news2, "news": tg_card.card_news, "lux": tg_card.card_lux, "a": tg_card.card_a, "b": tg_card.card_b, "c": tg_card.card_c, "v3": tg_card.news_card3}.get(CARD_STYLE, tg_card.news_card2)
    if CARD_STYLE == "news4A":
        jpg = tg_card.card_news4(photo, headline(n), is_breaking(n), n.get("first_utc") or n.get("latest_utc"), tag=tag, source=src(n)[0], style="A")
    elif CARD_STYLE == "news3":
        jpg = tg_card.card_news3(photo, headline(n), is_breaking(n), n.get("first_utc") or n.get("latest_utc"), tag=tag, source=src(n)[0])
    elif CARD_STYLE == "news2":
        jpg = tg_card.card_news2(photo, headline(n), is_breaking(n), n.get("first_utc") or n.get("latest_utc"), tag=tag)
    else:
        jpg = maker(photo, headline(n), is_breaking(n), n.get("first_utc") or n.get("latest_utc"))
    CARDS.mkdir(parents=True, exist_ok=True)
    cut = datetime.now(timezone.utc).timestamp() - 5 * 86400  # البطاقات تبقى متاحة 5 أيام (تُحفظ بين الجولات)
    for f in CARDS.glob("*.jpg"):
        if f.stat().st_mtime < cut:
            f.unlink()
    name = re.sub(r"[^A-Za-z0-9_]", "", n["id"])[:40] + f"_{int(datetime.now(timezone.utc).timestamp())}.jpg"
    (CARDS / name).write_bytes(jpg)
    if is_breaking(n) and CARD_STYLE in ("v3", "a", "b", "c", "lux", "news", "news2", "news4A"):  # العاجل: بطاقة متحركة بوميض شارة «عاجل»
        try:
            ANIM.mkdir(parents=True, exist_ok=True)
            for f in ANIM.glob("*.mp4"):
                if f.stat().st_mtime < cut:
                    f.unlink()
            (ANIM / name.replace(".jpg", ".mp4")).write_bytes(tg_card.breaking_anim(photo, headline(n), n.get("first_utc") or n.get("latest_utc"), style=CARD_STYLE, source=src(n)[0]))
        except Exception as e:  # noqa: BLE001
            DEBUG.append(f"animfail:{type(e).__name__}:{str(e)[:40]}")
    return name, "source" if photo else "card"


def url_ok(u, timeout=6):
    try:
        req = urllib.request.Request(u, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def send_pending(token, chat_id, only_breaking=False):
    """بعد نشر الموقع: رسالة نصية قابلة للنسخ، والبطاقة كبيرة فوقها (معاينة الرابط)، وزر التفاصيل والمشاركة تحتها.
    غير العاجل يصل بإشعار صامت. التحديث والتصحيح يُرسلان كرد على المنشور الأصلي. معرّفات الرسائل تُحفظ في tg_msgs.json."""
    import time as _t
    pend = load(PENDING, [])
    later = []
    if only_breaking:  # العاجل يُرسل فوراً بمرحلة التحضير (رفع البطاقة مباشرة) بلا انتظار نشر الموقع
        later = [p for p in pend if not ((p.get("b") or p.get("now")) and not p.get("textonly"))]
        pend = [p for p in pend if (p.get("b") or p.get("now")) and not p.get("textonly")]
    msgs = load(MSGS, {})
    done = {"preview": 0, "photo": 0, "text": 0, "anim": 0, "replies": 0}
    deadline = _t.time() + 60

    def common(p):
        kw = {"parse_mode": "HTML", "disable_notification": "false" if p.get("b") else "true"}
        if p.get("kb"):
            kw["reply_markup"] = p["kb"]
        if p.get("reply_to") and msgs.get(p["reply_to"]):
            kw["reply_parameters"] = json.dumps({"message_id": msgs[p["reply_to"]], "allow_sending_without_reply": True})
        return kw

    def keep(p, r):
        try:
            if r.get("ok"):
                msgs[p["id"]] = r["result"]["message_id"]
        except Exception:  # noqa: BLE001
            pass

    late_sigs = None
    for p in pend:
        if p.get("sig") and not p.get("textonly"):
            # فحص أخير قبل الإرسال: هل نشر المسار السريع أو التلفزيون الخبر نفسه خلال دقائق هذه الجولة؟
            if late_sigs is None:
                late_sigs = [x for x in fastlane_sigs() + fastlane_sigs("tv_sigs.json") if x.get("ts", 0) >= _t.time() - 3 * 3600]
            if any(same_story((set(p["sig"]["w"]), set(p["sig"]["d"])), x) for x in late_sigs):
                done["late_dup"] = done.get("late_dup", 0) + 1
                continue
        if p.get("first") and not p.get("textonly"):
            try:  # فحص العمر لحظة الإرسال: الجولة قد تطول، وخبر تجاوز 15 دقيقة منذ أول نشر لا يُرسل (تدقيق 2822، 2841)
                if _t.time() - datetime.fromisoformat(p["first"].replace("Z", "+00:00")).timestamp() > (FRESH_MIN + 3) * 60:
                    done["stale"] = done.get("stale", 0) + 1
                    continue
            except ValueError:
                pass
        if p.get("textonly"):
            try:
                r = api(token, "sendMessage", chat_id=chat_id, text=p["text"], disable_web_page_preview="true", **common(p))
                keep(p, r)
                done["replies"] += 1
            except Exception as e:  # noqa: BLE001
                DEBUG.append(f"replyfail:{type(e).__name__}:{str(e)[:50]}")
            continue
        av = ANIM / p["card"].replace(".jpg", ".mp4")
        if av.exists():  # عاجل: بطاقة متحركة تومض + النص كاملاً كتعليق
            try:
                r = api(token, "sendAnimation", files={"animation": (av.name, av.read_bytes(), "video/mp4")}, chat_id=chat_id,
                        caption=p["text"][:1024], width="1080" if CARD_STYLE == "news4A" else "1280", height="1350" if CARD_STYLE == "news4A" else "720", **common(p))
                av.unlink()
                if r.get("ok"):
                    keep(p, r)
                    done["anim"] += 1
                    continue
            except Exception as e:  # noqa: BLE001
                DEBUG.append(f"animsend:{type(e).__name__}:{str(e)[:50]}")
        cu = APP_URL + "cards/" + p["card"]
        ok = False  # كل المنشورات صورة (sendPhoto): تُحفظ بالضغط عليها، ولا ننتظر نشر الموقع — أسرع بدقائق (طلب إيهاب 2026-11-03)
        while CARD_STYLE not in ("news3", "news4A") and not only_breaking and _t.time() < deadline:
            if url_ok(cu):
                ok = True
                break
            _t.sleep(4)
        try:
            if ok:
                r = api(token, "sendMessage", chat_id=chat_id, text=p["text"],
                        link_preview_options=json.dumps({"url": cu, "prefer_large_media": True, "show_above_text": True}), **common(p))
                done["preview"] += 1
            else:
                r = api(token, "sendPhoto", files={"photo": (p["card"], (CARDS / p["card"]).read_bytes())}, chat_id=chat_id,
                        caption=p["text"][:1024], **common(p))
                done["photo"] += 1
            keep(p, r)
        except Exception as e:  # noqa: BLE001
            DEBUG.append(f"sendfail:{type(e).__name__}:{str(e)[:60]}")
            try:
                r = api(token, "sendMessage", chat_id=chat_id, text=p["text"], parse_mode="HTML", disable_web_page_preview="true")
                keep(p, r)
                done["text"] += 1
            except Exception:  # noqa: BLE001
                try:  # آخر محاولة: نص خام بلا تنسيق (خطأ HTML لا يُسقط المنشور)
                    r = api(token, "sendMessage", chat_id=chat_id, text=H.unescape(re.sub(r"<[^>]+>", "", p["text"]))[:4000], disable_web_page_preview="true")
                    keep(p, r)
                    done["text"] += 1
                except Exception as e2:  # noqa: BLE001
                    DEBUG.append(f"sendfail2:{p['id'][:20]}:{str(e2)[:60]}")
    try:  # نسخة لمشتركي المحافظات والمواضيع بالخاص
        from tools import subs as SB
        items = [{"id": p["id"], "card": p.get("card"), "text": p["text"],
                  "title": re.sub(r"<[^>]+>", "", p["text"]).split("\n")[0]} for p in pend if not p.get("textonly") and p["id"] in msgs]
        done["subs"] = SB.dispatch(token, api, items, load(SENT, {}), msgs, APP_URL)
    except Exception as e:  # noqa: BLE001
        DEBUG.append(f"subs:{type(e).__name__}:{str(e)[:40]}")
    PENDING.write_text(json.dumps(later, ensure_ascii=False), encoding="utf-8")
    if only_breaking:
        MSGS.write_text(json.dumps(msgs, ensure_ascii=False), encoding="utf-8")
        return done
    try:
        done.update(evening_digest(token, chat_id, msgs) or {})
    except Exception as e:  # noqa: BLE001
        DEBUG.append(f"digest:{type(e).__name__}:{str(e)[:50]}")
    try:
        done.update(daily_stats(token, msgs) or {})
    except Exception as e:  # noqa: BLE001
        DEBUG.append(f"stats:{type(e).__name__}:{str(e)[:50]}")
    keep_ids = sorted(((k, v) for k, v in msgs.items() if not k.startswith("_")), key=lambda kv: kv[1])[-1500:]
    MSGS.write_text(json.dumps({**{k: v for k, v in msgs.items() if k.startswith("_")}, **dict(keep_ids)}, ensure_ascii=False), encoding="utf-8")
    return done


def evening_digest(token, chat_id, msgs):
    """موجزان يومياً بالقناة ببوستر مصمم + روابط المنشورات: الصباح 8 (ما حدث خلال الليل) والمساء 9 (أبرز اليوم)."""
    now = datetime.now(timezone.utc)
    bgd = now + timedelta(hours=3)
    today = bgd.strftime("%Y-%m-%d")
    slot = "_morning" if bgd.hour == 8 else "_evening" if bgd.hour == 21 else None
    if not slot or msgs.get(slot) == today:
        return None
    news = load(PWA / "news.json", [])
    hrs = 12 if slot == "_morning" else 15
    start = (now - timedelta(hours=hrs)).strftime("%Y-%m-%dT%H:%M:%S")
    pool = [n for n in news if n["id"] in msgs and (n.get("first_utc") or "") >= start and (n.get("about_iraq") or n.get("pmf"))]
    top = sorted(pool, key=lambda n: -importance(n))[:5]
    if len(top) < 3:
        return None
    from tools.editorial import clean_headline
    from tools import tg_card
    months = ['كانون الثاني', 'شباط', 'آذار', 'نيسان', 'أيار', 'حزيران', 'تموز', 'آب', 'أيلول', 'تشرين الأول', 'تشرين الثاني', 'كانون الأول']
    date = f"{bgd.day} {months[bgd.month - 1]} {bgd.year}"
    title = "صباح العراق" if slot == "_morning" else "حصاد اليوم"
    sub = "أبرز ما حدث خلال الليل" if slot == "_morning" else "أبرز أخبار العراق اليوم"
    heads = [clean_headline(n["title"], 110) for n in top]
    ch = CHANNEL.rstrip("/").split("/")[-1]
    lines = [f"🗞 <b>{title}</b> — {sub}", date, ""]
    for i, (n, h) in enumerate(zip(top, heads), 1):
        lines.append(f"{i}. <a href=\"https://t.me/{ch}/{msgs[n['id']]}\">{H.escape(h)}</a>")
    lines += ["", f"تابعونا لحظة بلحظة 👇\n{CHANNEL}"]
    cap = "\n".join(lines)
    r = {"ok": False}
    try:
        card = tg_card.card_digest(title, sub, date, heads)
        r = api(token, "sendPhoto", files={"photo": ("digest.jpg", card)}, chat_id=chat_id, caption=cap[:1024], parse_mode="HTML",
                disable_notification="true")
    except Exception as e:  # noqa: BLE001
        DEBUG.append(f"digestcard:{type(e).__name__}:{str(e)[:40]}")
    if not r.get("ok"):
        r = api(token, "sendMessage", chat_id=chat_id, text=cap, parse_mode="HTML", disable_web_page_preview="true", disable_notification="true")
    if r.get("ok"):
        msgs[slot] = today
        return {"digest": slot}
    return None


def daily_stats(token, msgs):
    """تقرير أداء يومي للمحررين (11 مساءً بغداد): مشاهدات منشورات اليوم من صفحة القناة العامة، الأعلى مشاهدة، وأفضل ساعات النشر (آخر 7 أيام)."""
    now = datetime.now(timezone.utc)
    bgd = now + timedelta(hours=3)
    today = bgd.strftime("%Y-%m-%d")
    if bgd.hour != 23 or msgs.get("_stats") == today:
        return None
    ch = CHANNEL.rstrip("/").split("/")[-1]
    posts, before = [], ""
    for _ in range(6):
        page = urllib.request.urlopen(urllib.request.Request(f"https://t.me/s/{ch}{before}", headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read().decode("utf-8", "replace")
        blocks = page.split('class="tgme_widget_message_wrap')[1:]
        if not blocks:
            break
        for b in blocks:
            pid = re.search(rf'data-post="{ch}/(\d+)"', b)
            v = re.search(r'tgme_widget_message_views">([^<]+)<', b)
            t = re.search(r'<time[^>]+datetime="([^"]+)"', b)
            tx = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', b, re.S)
            if not (pid and v and t):
                continue
            vs = v.group(1).strip().upper()
            num = float(vs.rstrip("KM")) * (1000 if vs.endswith("K") else 1_000_000 if vs.endswith("M") else 1)
            posts.append({"id": int(pid.group(1)), "views": int(num), "t": datetime.fromisoformat(t.group(1)),
                          "text": H.unescape(re.sub(r"<[^>]+>", " ", tx.group(1))).strip()[:90] if tx else ""})
        before = f"?before={min(p['id'] for p in posts)}" if posts else ""
        if posts and min(p["t"] for p in posts) < now - timedelta(days=7):
            break
    if not posts:
        return None
    day0 = (bgd.replace(hour=0, minute=0, second=0) - timedelta(hours=3))
    todayp = [p for p in posts if p["t"] >= day0]
    week = [p for p in posts if p["t"] >= now - timedelta(days=7)]
    byh = {}
    for p in week:
        h = (p["t"] + timedelta(hours=3)).hour
        byh.setdefault(h, []).append(p["views"])
    best = sorted(((sum(v) / len(v), h) for h, v in byh.items() if len(v) >= 3), reverse=True)[:3]
    top = sorted(todayp, key=lambda p: -p["views"])[:5]
    lines = [f"📊 أداء «هسة وصل» اليوم {today}", f"منشورات اليوم: {len(todayp)} · مجموع المشاهدات: {sum(p['views'] for p in todayp):,}",
             f"متوسط المشاهدة للمنشور: {int(sum(p['views'] for p in todayp) / max(1, len(todayp))):,}", "", "الأعلى مشاهدة:"]
    lines += [f"• {p['views']:,} — {p['text']}" for p in top]
    if best:
        lines += ["", "أفضل ساعات النشر (آخر 7 أيام، متوسط المشاهدة): " + "، ".join(f"{h}:00 ({int(a):,})" for a, h in best)]
    lines.append("ملاحظة: المشاهدات من صفحة القناة العامة وقت القياس، وليست أشخاصاً فريدين.")
    sent = load(SENT, {})
    for c in (sent.get("_editor_chats") or {}).values():
        try:
            api(token, "sendMessage", chat_id=c, text="\n".join(lines)[:4000], disable_web_page_preview="true")
        except Exception:  # noqa: BLE001
            pass
    msgs["_stats"] = today
    return {"daily_stats": len(todayp)}


def digest(news, now):
    day = [n for n in news if n.get("latest_utc") and datetime.fromisoformat(n["latest_utc"].replace("Z", "+00:00")) >= now - timedelta(hours=24)]
    top = sorted([n for n in day if n.get("about_iraq") and n.get("origin") != "أجنبي"],
                 key=lambda n: (-(n.get("n_sources") or 1), -rank(n)))[:10]
    pmf = sorted([n for n in day if n.get("pmf")], key=lambda n: -(n.get("n_sources") or 1))[:4]
    frn = sorted([n for n in day if n.get("origin") == "أجنبي"], key=lambda n: n.get("latest_utc") or "", reverse=True)[:4]
    d = (now + timedelta(hours=3)).strftime("%Y/%m/%d")
    out = [f"🗞 موجز هوبي عاجل — {d}", "", "أبرز أحداث العراق خلال 24 ساعة (حسب عدد الجهات الناشرة):"]
    for i, n in enumerate(top, 1):
        out.append(f"{i}. {n['title']} — {n.get('n_sources') or 1} جهات")
    if pmf:
        out += ["", "الحشد الشعبي:"] + [f"• {n['title']}" for n in pmf]
    if frn:
        out += ["", "الصحافة الأجنبية عن العراق (ترجمة آلية):"] + [f"• {n['title']} — {src(n)[0]}" for n in frn]
    out += ["", "كثرة الجهات تعني انتشاراً لا تأكيداً.", f"التفاصيل والمصادر: {APP_URL}", f"📡 تابعونا: {CHANNEL}"]
    return "\n".join(out)[:4000]


def surge_alerts(token, sent, news, now, msgs):
    """تنبيه مبكر للمحررين بالخاص: خبر عراقي يتصاعد الآن (5 جهات فأكثر خلال 20 دقيقة). مرة واحدة لكل خبر."""
    chats = list((sent.get("_editor_chats") or {}).values())
    done = sent.setdefault("_surge", {})
    for k in [k for k, v in done.items() if v < now.timestamp() - 48 * 3600]:
        done.pop(k, None)
    n_sent = 0
    for n in sorted(news, key=lambda n: -(n.get("surge_n") or 0)):
        if not surging(n) or n["id"] in done or not (n.get("about_iraq") or n.get("pmf")) or not iraq_strict(n.get("title") or ""):
            continue
        if low_value(n.get("title") or "") or n_sent >= 3:
            continue
        done[n["id"]] = now.timestamp()
        fs = n.get("first_src") or {}
        posted = "✅ منشور بالقناة" if n["id"] in msgs else "⏳ لم يُنشر بعد بالقناة"
        txt = (f"🚀 يتصاعد الآن\n<b>{H.escape(n['title'][:300])}</b>\n\n{n.get('surge_n')} جهات خلال 20 دقيقة · {n.get('n_sources') or 1} جهات إجمالاً\n"
               f"أول ظهور: {H.escape(fs.get('name') or '?')} {bg(fs.get('time')) if fs.get('time') else ''}\n"
               f"الحالة: {H.escape(n.get('status') or 'غير مؤكد')} · {posted}\nالانتشار ليس تأكيداً.")
        for c in chats:
            try:
                api(token, "sendMessage", chat_id=c, text=txt[:4000], parse_mode="HTML", disable_web_page_preview="true")
            except Exception:  # noqa: BLE001
                pass
        n_sent += 1
    return n_sent


def watch_alerts(token, sent, news, now):
    """تنبيهات قوائم المتابعة بالخاص للمحررين (لا للقناة العامة): حدث واحد = تنبيه واحد، وتحديث واحد إذا صار عاجلاً."""
    chats = list((sent.get("_editor_chats") or {}).values())
    if not chats:
        return {"chats": 0}
    try:
        names = {f["id"]: f["name"] for f in json.loads((ROOT / "config" / "follow.json").read_text(encoding="utf-8"))["follow"]}
    except Exception:  # noqa: BLE001
        names = {}
    wa = sent.setdefault("_walert", {})
    n_sent = 0
    for n in sorted(news, key=lambda n: n.get("collected_utc") or ""):
        hits = n.get("watch") or []
        if not hits:
            continue
        seen = n.get("collected_utc")
        if not seen or datetime.fromisoformat(seen.replace("Z", "+00:00")) < now - timedelta(minutes=15):
            continue
        direct = any(h.get("prov") in ("رصد مباشر", "إدخال يدوي") for h in hits)
        worthy_w = direct or is_breaking(n) or n.get("level") in ("عاجل", "مهم") or n.get("vstatus") == "متنازع عليه"
        if not worthy_w:
            continue
        prev = wa.get(n["id"])
        upd = prev is not None
        if prev and (prev.get("b") or not is_breaking(n)):
            continue
        tags = " · ".join(dict.fromkeys(names.get(h["id"], h["id"]) for h in hits))
        prov = next((h["prov"] for h in hits if h.get("prov")), "رصد موضوعي")
        _, url = src(n)
        txt = (f"{'🔁 تحديث | ' if upd else ''}👁 <b>{H.escape(tags)}</b>\n{'🔴 ' if is_breaking(n) else ''}{H.escape(n['title'][:500])}\n\n"
               f"{H.escape(prov)} · {H.escape(n.get('vstatus') or '')} · {H.escape(src(n)[0])} · {bg(n.get('latest_utc'))} بغداد"
               + (f"\n🔗 <a href=\"{H.escape(url, quote=True)}\">المصدر</a>" if url else "") + f"\n🆔 {n['id']}")
        for c in chats:
            try:
                api(token, "sendMessage", chat_id=c, text=txt, parse_mode="HTML", disable_web_page_preview="true")
            except Exception:  # noqa: BLE001
                pass
        wa[n["id"]] = {"t": now.timestamp(), "b": is_breaking(n)}
        n_sent += 1
        if n_sent >= 12:
            break
    # ملخص المتابعة اليومي 8 صباحاً بغداد
    bgd = now + timedelta(hours=3)
    today = bgd.strftime("%Y-%m-%d")
    if bgd.hour == 8 and sent.get("_wdigest") != today:
        day = [n for n in news if n.get("watch") and n.get("latest_utc") and datetime.fromisoformat(n["latest_utc"].replace("Z", "+00:00")) >= now - timedelta(hours=24)]
        by = {}
        for n in day:
            for h in n["watch"]:
                by.setdefault(h["id"], []).append(n)
        lines = [f"👁 ملخص قوائم المتابعة — {bgd.strftime('%Y/%m/%d')}", ""]
        for wid, lst in sorted(by.items(), key=lambda kv: -len(kv[1]))[:15]:
            lst = sorted(lst, key=lambda n: (-(n.get("n_sources") or 1)))[:3]
            lines.append(f"<b>{H.escape(names.get(wid, wid))}</b> — {len(by[wid])} حدث")
            for n in lst:
                _, u = src(n)
                lines.append(f"• <a href=\"{H.escape(u, quote=True)}\">{H.escape(n['title'][:120])}</a> ({H.escape(n.get('vstatus') or '')})" if u else f"• {H.escape(n['title'][:120])}")
            lines.append("")
        lines.append(f"التفاصيل: {APP_URL}#watch")
        for c in chats:
            try:
                api(token, "sendMessage", chat_id=c, text="\n".join(lines)[:4000], parse_mode="HTML", disable_web_page_preview="true")
            except Exception:  # noqa: BLE001
                pass
        sent["_wdigest"] = today
    return {"chats": len(chats), "sent": n_sent}


def main():
    now = datetime.now(timezone.utc)
    status = {"enabled": False, "updated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "sent_now": 0, "candidates": 0, "chat_title": None, "error": None}
    token = os.environ.get("MARSAD_TG_BOT_TOKEN", "").strip()
    if not token:
        status["error"] = "غير مفعّل: أضف السر MARSAD_TG_BOT_TOKEN في إعدادات GitHub"
        STATUS.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
        print(status)
        return
    try:
        chat = load(CHAT, {})
        chat_id = os.environ.get("MARSAD_TG_CHAT_ID", "").strip() or chat.get("id") or "@hassawassal"  # القناة عامة: اسمها يكفي
        if not chat_id:
            ups = api(token, "getUpdates", timeout=0).get("result", [])
            for u in reversed(ups):
                c = (u.get("channel_post") or u.get("message") or (u.get("my_chat_member") or {}) or {}).get("chat") or {}
                if c.get("type") in ("channel", "supergroup", "group"):
                    chat = {"id": c["id"], "title": c.get("title")}
                    CHAT.write_text(json.dumps(chat, ensure_ascii=False), encoding="utf-8")
                    chat_id = c["id"]
                    break
        if not chat_id:
            status["error"] = "البوت شغّال بس ما لكى قناة: أضفه مشرفاً للقناة واكتب فيها أي رسالة"
            STATUS.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
            print(status)
            return
        status["enabled"] = True
        status["chat_title"] = chat.get("title") or "عاجل هسه وصل"
        news = load(PWA / "news.json", [])
        sent = load(SENT, {})
        if not sent.get("_bot_user"):
            try:
                sent["_bot_user"] = api(token, "getMe").get("result", {}).get("username") or ""
            except Exception:  # noqa: BLE001
                pass
        BOT_USER[0] = sent.get("_bot_user") or ""
        status["bot_user"] = BOT_USER[0]
        first_run = not sent.get("_init")
        out = []
        build_idf([x.get("title") or "" for x in news])
        posted = [x for x in sent.get("_titles", []) if x.get("ts", 0) >= now.timestamp() - DEDUP_H * 3600]
        fast = fastlane_sigs() + fastlane_sigs("tv_sigs.json")  # ما نشره المسار السريع ومقاطع التلفزيون: لا نكرره، ويُحسب بالسقف الساعي
        posted_all = posted + [x for x in fast if x.get("ts", 0) >= now.timestamp() - DEDUP_H * 3600]
        # نسخة البصمات المنشورة على الإصدار: حماية من ذاكرة مخبأة قديمة (جولتان متوازيتان أو كاش لم يُحفظ)
        mine_ts = {round(x.get("ts", 0)) for x in posted}
        posted_all += [x for x in fastlane_sigs("main_sigs.json") if x.get("ts", 0) >= now.timestamp() - DEDUP_H * 3600 and round(x.get("ts", 0)) not in mine_ts]
        hour_n = sum(1 for x in posted_all if x.get("id") and x.get("ts", 0) >= now.timestamp() - 3600)  # منشورات النظام الجديد + السريع
        reg_n = sum(1 for x in posted if x.get("reg") and x.get("ts", 0) >= now.timestamp() - 3600)
        dup_skipped = 0
        msgs = load(MSGS, {})
        updates = []
        # الأهم أولاً: السقف الساعي يذهب لأقوى الأخبار لا لأقدمها جمعاً
        for n in sorted(news, key=lambda n: (-importance(n), n.get("collected_utc") or "")):
            if n["id"] in sent or not worthy(n, now):
                continue  # كل خبر يُنشر مرة واحدة فقط (لا إعادة نشر حتى لو تكرر لدى جهات أكثر — طلب إيهاب 2026-11-01)
            sig = title_sig(n["title"])
            # عنقود آخر للخبر نفسه (صياغة مختلفة) نُشر قبل 15 دقيقة؟ = الخبر قديم حتى لو عنقوده جديد (تدقيق 2822، 2841)
            if not _SIGS:
                _SIGS.update({m["id"]: title_sig(m.get("title") or "") for m in news if m.get("first_utc")})
            old_first = min((m["first_utc"] for m in news if m["id"] != n["id"] and m["id"] in _SIGS and m.get("first_utc")
                             and same_story(sig, {"w": _SIGS[m["id"]][0], "d": _SIGS[m["id"]][1]})), default=None)
            if old_first and datetime.fromisoformat(old_first.replace("Z", "+00:00")) < now - timedelta(minutes=FRESH_MIN):
                status["stale_cluster"] = status.get("stale_cluster", 0) + 1
                continue
            prev = next((x for x in posted_all if same_story(sig, x)), None)
            if not prev and sec_dup(n.get("title"), posted_all, now.timestamp()):
                dup_skipped += 1
                sent[n["id"]] = {"r": rank(n), "n": n.get("n_sources") or 1, "t": now.timestamp(), "dup": True}
                continue
            if prev:
                dup_skipped += 1
                sent[n["id"]] = {"r": rank(n), "n": n.get("n_sources") or 1, "t": now.timestamp(), "dup": True}
                # تطور جوهري بنفس القصة (رقم جديد: حصيلة، مبلغ، موعد) ← «تحديث» كرد على المنشور الأصلي، مرة كل ساعتين
                newnums = sig[1] - set(prev.get("d") or [])
                if (newnums and prev.get("id") and prev.get("id") in msgs and now.timestamp() - prev.get("upd", 0) > 7200
                        and rank(n) >= 2 and len(updates) < 2):
                    prev["upd"] = now.timestamp()
                    prev["d"] = sorted(set(prev.get("d") or []) | sig[1])
                    updates.append((n, prev["id"]))
                continue
            lk = lead_key(n.get("title"))
            burst = sum(1 for x in posted_all if x.get("ts", 0) >= now.timestamp() - 3600 and lead_key(x.get("title") or "") == lk)
            if burst >= 2 and not (is_breaking(n) and n.get("source_flag")):
                status["burst_cap"] = status.get("burst_cap", 0) + 1
                sent[n["id"]] = {"r": rank(n), "n": n.get("n_sources") or 1, "t": now.timestamp(), "dup": True}
                continue  # منشوران عن الجهة نفسها خلال ساعة يكفيان (اجتماع واحد نزل 6 مرات)
            reg = is_regional(n)
            if reg and IDF and any(x.get("reg") and x.get("ts", 0) >= now.timestamp() - 6 * 3600 and
                                   any(IDF.get(w, 6.0) >= RARE + 1 for w in set(x.get("w") or []) & sig[0]) for x in posted_all):
                status["region_topic_dup"] = status.get("region_topic_dup", 0) + 1
                continue  # الحدث الإقليمي نفسه (قشم، سيستان) يُنشر مرة واحدة خلال 6 ساعات مهما تعددت صياغاته
            if reg and reg_n >= REGION_PER_HOUR and not is_breaking(n):
                status["region_cap"] = status.get("region_cap", 0) + 1
                continue
            if hour_n >= MAX_PER_HOUR and not is_breaking(n):
                status["hour_cap"] = status.get("hour_cap", 0) + 1
                continue  # سقف ساعي: بعده العاجل فقط (القناة لا تُغرق)
            if not is_breaking(n) and hour_n >= MAX_PER_HOUR * 0.7:
                from tools.learn import lift_of
                if lift_of(sent, n.get("title")) < 0.8 and (n.get("n_sources") or 1) < 4:
                    status["low_interest"] = status.get("low_interest", 0) + 1
                    continue  # عند الزحام: موضوع أثبتت المشاهدات ضعف اهتمام المتابعين به، ونشرته جهات قليلة
            entry = {"w": sorted(sig[0]), "d": sorted(sig[1]), "ts": now.timestamp(), "reg": reg, "id": n["id"], "title": (n.get("title") or "")[:200]}
            posted.append(entry)
            posted_all.append(entry)
            hour_n += 1
            reg_n += reg
            out.append((n, False))
        sent["_titles"] = posted[-600:]
        publish_main_sigs(sent["_titles"])
        status["dup_skipped"] = dup_skipped
        status["candidates"] = len(out)
        if first_run:  # أول تشغيل: لا نغرق القناة بالقديم؛ نرسل رسالة ترحيب ونعلّم الموجود كمُرسل
            for n, _ in out:
                sent[n["id"]] = {"r": rank(n), "n": n.get("n_sources") or 1, "t": now.timestamp()}
            sent["_init"] = True
            out = []
        status["images"] = {}
        pend = []
        # العاجل أولاً ثم الأحدث
        for n, upd in sorted(out[-MAX_PER_RUN:], key=lambda x: (not is_breaking(x[0]), x[0].get("collected_utc") or "")):
            try:
                card, kind = prepare_card(n)
            except Exception as e:  # noqa: BLE001
                DEBUG.append(f"cardfail:{type(e).__name__}")
                continue
            status["images"][kind] = status["images"].get(kind, 0) + 1
            pend.append({"id": n["id"], "card": card, "text": fmt(n, upd), "b": is_breaking(n), "kb": buttons(n),
                         "now": True, "sig": {"w": sorted(sig[0]), "d": sorted(sig[1])}, "first": n.get("first_utc")})  # صورة مباشرة: لا داعي لانتظار نشر الموقع  # المهم العراقي يُرسل فوراً بلا انتظار نشر الموقع
            sent[n["id"]] = {"r": rank(n), "n": n.get("n_sources") or 1, "t": now.timestamp(), "b": is_breaking(n)}
            status["sent_now"] += 1
        for n, orig in updates:  # تحديثات كرد على المنشور الأصلي (نص فقط، بلا بطاقة)
            pend.append({"id": n["id"], "text": fmt(n, kind="update"), "reply_to": orig, "b": False, "kb": buttons(n), "textonly": True})
            status["updates"] = status.get("updates", 0) + 1
        # تصحيح: خبر نشرناه ثم حكم المحرر أو التحقق بأنه غير صحيح ← تصحيح كرد عليه، مرة واحدة
        corrected = set(sent.get("_corrected", []))
        for n in news:
            if n.get("vstatus") == "ثبت عدم صحته" and n["id"] in msgs and n["id"] not in corrected:
                pend.append({"id": n["id"] + "_fix", "reply_to": n["id"], "b": True, "textonly": True,
                             "text": f"⚠️ <b>تصحيح</b>\n\nتبيّن أن هذا الخبر غير صحيح وفق التحقق اللاحق" + (f": {H.escape(n.get('vwhy') or '')}" if n.get("vwhy") else ".") +
                                     f"\n\nنعتذر لمتابعينا. «هسة وصل» تصحّح علناً.\n{CHANNEL}"})
                corrected.add(n["id"])
                status["corrections"] = status.get("corrections", 0) + 1
        sent["_corrected"] = sorted(corrected)[-300:]
        # «قراءة هسة وصل»: رأي تحريري بأسلوب محلل الاستوديو، بزاوية إيجابية بنّاءة للعراق — مرتان يومياً (2–6 عصراً و8–12 ليلاً بغداد)
        # عن أكثر خبر عراقي تداولاً اليوم مناسب لقراءة بنّاءة (لا مآسي ولا حوادث). إن فشل النموذج لا يُنشر بديل، ويُعاد في الجولة التالية ضمن الفترة.
        ana = load(PWA / "analysis.json", {}).get("items", [])
        ap = sent.get("_ana_posted") or {}
        day = (now + timedelta(hours=3)).strftime("%Y-%m-%d")
        bh0 = (now + timedelta(hours=3)).hour
        aslot = "a1" if 14 <= bh0 < 18 else "a2" if 20 <= bh0 < 24 else None
        tries = sent.setdefault("_op_tries", {})
        slot_done = any(v.get("slot") == day + aslot and (("op_" + k) in msgs or now.timestamp() - v.get("t", 0) < 900) for k, v in ap.items()) if aslot else True
        if aslot and not slot_done and tries.get(day + aslot, 0) < 6:  # الفترة تُحسب منجزة فقط إذا وصل المنشور فعلاً للقناة
            from tools import analysis as A, tg_card
            from tools.editorial import pick_best, clean_headline
            done_t = [title_sig(v.get("title") or "") for v in ap.values() if v.get("d") == day]
            pool = [a for a in ana if a["id"] not in ap and iraq_title(a["title"]) and not far_title(a["title"]) and A.op_eligible(a)
                    and (a.get("last_time") or "") >= (now - timedelta(hours=16)).strftime("%Y-%m-%dT%H:%M")
                    and not any(same_story(title_sig(a["title"]), {"w": sorted(t[0]), "d": sorted(t[1])}) for t in done_t)]
            if not pool:  # احتياط: أبرز خبر إيجابي عراقي (3 جهات فأكثر) إن لم يوجد حدث كبير مناسب
                pn = A.pick_positive(news, set(ap), (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S"))
                if pn:
                    pool = [{"id": pn["id"], "title": pn["title"], "n_sources": pn.get("n_sources") or 1, "vstatus": pn.get("vstatus"),
                             "excerpts": [{"source": "", "text": (pn.get("lead") or "")[:400]}] if pn.get("lead") else [], "narratives": []}]
            if pool:
                a = dict(max(pool, key=A.op_score))
                a["title"] = clean_headline(pick_best([a["title"]] + [x["title"] for x in (a.get("narratives") or [])] +
                                                       [x["text"][:200].split("\n")[0] for x in (a.get("excerpts") or []) if x.get("text")])) or a["title"]
                tries[day + aslot] = tries.get(day + aslot, 0) + 1
                art = None
                try:
                    art = A.write_opinion(a)
                except Exception as e:  # noqa: BLE001
                    DEBUG.append(f"opinion:{type(e).__name__}")
                if art:
                    otitle, obody = art
                    body = H.escape(obody[:3200])
                    for h in A.OP_HEADS:
                        body = body.replace(h, f"<b>{h}</b>")
                    n0 = next((x for x in news if x["id"] == a["id"]), None)
                    photo = news_photo(n0) if n0 else None
                    try:
                        card = save_card(tg_card.card_news4(photo, otitle, False, now.strftime("%Y-%m-%dT%H:%M:%SZ"), tag="رأي", style="A"), "op_" + a["id"])
                        text = (f"🎙 <b>قراءة هسة وصل</b>\n<b>{H.escape(otitle)}</b>\n\n{body}\n\n"
                                f"<i>رأي تحريري لقناة «هسة وصل» مبني على ما نُشر عن الخبر، بصياغة آلية بحارس حقائق.</i>\n\n#قراءة_هسة_وصل\n{CHANNEL}")
                        pend.append({"id": "op_" + a["id"], "card": card, "text": text[:4000], "b": False, "kb": buttons(n0) if n0 else None})
                        ap[a["id"]] = {"d": day, "t": now.timestamp(), "slot": day + aslot, "title": a["title"]}
                        status["opinion_post"] = {"id": a["id"], "title": otitle}
                    except Exception as e:  # noqa: BLE001
                        DEBUG.append(f"opcard:{type(e).__name__}:{str(e)[:40]}")
                else:
                    status["opinion_post"] = f"فشل النموذج/الحارس (محاولة {tries[day + aslot]})"
        sent["_op_tries"] = dict(list(tries.items())[-20:])
        sent["_ana_posted"] = dict(list(ap.items())[-200:])
        # منوعات: خبر عراقي خفيف (رياضة، طقس، ثقافة، تقنية، صحة، أسعار) — واحد كل 75 دقيقة كحد أعلى، 8 يومياً، 8 صباحاً–11 ليلاً، بإشعار صامت
        vs = sent.get("_variety") or {}
        v_today = [v for v in vs.values() if v.get("d") == day]
        v_last = max([v.get("t", 0) for v in vs.values()] or [0])
        if 8 <= bh0 < 23 and len(v_today) < VARIETY_MAX_DAY and now.timestamp() - v_last > VARIETY_GAP:
            vc = []
            for n in news:
                if n["id"] in sent or n["id"] in vs or not n.get("about_iraq") or not iraq_strict(n.get("title") or ""):
                    continue  # علامة عراقية صريحة: «قاليباف: الكرة في ملعب الولايات المتحدة» مرّ منوعات رياضة (تدقيق 2821)
                if (n.get("first_utc") or "9") < (now - timedelta(minutes=FRESH_MIN)).strftime("%Y-%m-%dT%H:%M:%S"):
                    continue  # خبر قديم لدى الجهات الأخرى (2821 نُشر بعد 62 دقيقة)
                seen = n.get("collected_utc") or ""
                if seen < (now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M") or n.get("ctype") == "تحليل/رأي" or is_breaking(n):
                    continue
                from tools.editorial import clean_headline
                ct = clean_headline(n.get("title") or "")
                if len(ct.split()) < 6 or PROMO_RX.search(ct) or JUNK.match(ct):
                    continue
                k = variety_kind(n)
                if not k or (n.get("n_sources") or 1) < 2:
                    continue
                sig = title_sig(n["title"])
                if any(same_story(sig, x) for x in posted_all):
                    continue
                from tools.learn import lift_of
                vc.append(((n.get("n_sources") or 1) * lift_of(sent, n.get("title")), n, k, sig))
            if vc:
                _, n, k, sig = max(vc, key=lambda x: x[0])
                try:
                    card, _kind = prepare_card(n, tag="منوعات")
                    text = fmt(n).replace("\n\nزورونا", f"\n#منوعات #{k}\n\nزورونا", 1)
                    pend.append({"id": n["id"], "card": card, "text": text, "b": False, "kb": buttons(n)})
                    sent[n["id"]] = {"r": rank(n), "n": n.get("n_sources") or 1, "t": now.timestamp(), "v": k}
                    vs[n["id"]] = {"d": day, "t": now.timestamp(), "k": k}
                    entry = {"w": sorted(sig[0]), "d": sorted(sig[1]), "ts": now.timestamp(), "id": n["id"], "title": (n.get("title") or "")[:200]}
                    posted.append(entry)
                    sent["_titles"] = posted[-600:]
                    status["variety_post"] = {"id": n["id"], "k": k}
                except Exception as e:  # noqa: BLE001
                    DEBUG.append(f"variety:{type(e).__name__}:{str(e)[:40]}")
        sent["_variety"] = dict(list(vs.items())[-300:])
        pp = sent.get("_pos") or {}  # التحليل الإيجابي القديم دُمج في «قراءة هسة وصل» (طلب إيهاب 2026-11-02)
        sent["_pos"] = pp
        from tools.editorial import LLM_STATS
        status["editor_llm"] = LLM_STATS
        PENDING.write_text(json.dumps(pend, ensure_ascii=False), encoding="utf-8")
        SENT.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")
        if any((p.get("b") or p.get("now")) and not p.get("textonly") for p in pend):
            try:
                status["breaking_now"] = send_pending(token, chat_id, only_breaking=True)
            except Exception as e:  # noqa: BLE001
                DEBUG.append(f"breaking_now:{type(e).__name__}")
        # موجز 8 صباحاً بغداد، مرة واحدة يومياً
        bgd = now + timedelta(hours=3)
        today = bgd.strftime("%Y-%m-%d")
        if bgd.hour == 8 and sent.get("_digest") != today:
            for c in (sent.get("_editor_chats") or {}).values():  # للمحررين بالخاص فقط — لا يُنشر بالقناة العامة (طلب إيهاب 2026-11-01)
                try:
                    api(token, "sendMessage", chat_id=c, text=digest(news, now), disable_web_page_preview="true")
                except Exception:  # noqa: BLE001
                    pass
            sent["_digest"] = today
            status["digest"] = today
        status["watch_alerts"] = watch_alerts(token, sent, news, now)
        try:
            status["surge_alerts"] = surge_alerts(token, sent, news, now, msgs)
        except Exception as e:  # noqa: BLE001
            status["surge_alerts"] = f"خطأ {type(e).__name__}"
        cut = now.timestamp() - 3 * 86400
        sent = {k: v for k, v in sent.items() if k.startswith("_") or v.get("t", 0) >= cut}
        wa = sent.get("_walert", {})
        sent["_walert"] = {k: v for k, v in wa.items() if v.get("t", 0) >= cut}
        SENT.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if token:
            msg = msg.replace(token, "***")
        status["error"] = f"{type(e).__name__}: {msg}"[:200]
    status["img_debug"] = DEBUG[-12:]
    STATUS.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    print({k: v for k, v in status.items()})


def send_main():
    token = os.environ.get("MARSAD_TG_BOT_TOKEN", "").strip()
    if not token:
        return
    chat = load(CHAT, {})
    chat_id = os.environ.get("MARSAD_TG_CHAT_ID", "").strip() or chat.get("id") or "@hassawassal"
    try:
        r = send_pending(token, chat_id)
    except Exception as e:  # noqa: BLE001
        r = {"error": f"{type(e).__name__}: {str(e).replace(token, '***')[:150]}"}
    print(f"::notice title=tg_send::{json.dumps({**r, 'debug': DEBUG[-6:]}, ensure_ascii=False)}")


if __name__ == "__main__":
    if "--send" in sys.argv:
        send_main()
    else:
        main()
