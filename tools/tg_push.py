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
MAX_PER_HOUR = 20
REGION_MIN_SOURCES = 8
REGION_PER_HOUR = 4


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


IRAQ_T = None


def _markers():
    global IRAQ_T
    if IRAQ_T is None:
        from tools.export_pwa import IRAQ_AR, FOREIGN_AR
        from marsad.textnorm import norm_ar
        extra_f = [norm_ar(w) for w in ["حمص", "حلب", "إدلب", "ادلب", "دير الزور", "خانيونس", "خان يونس", "رفح", "بيروت", "الجنوب اللبناني", "صنعاء", "عدن",
                                         "اليمنية", "اليمني", "السورية", "اللبنانية", "الإسرائيلية", "الاسرائيلي", "الاحتلال", "نتنياهو", "تل أبيب",
                                         "بولندا", "البولندي", "المجر", "أوربان", "كييف", "موسكو", "بوتين", "زيلينسكي", "الأوكرانية", "الروسية", "الكرملين",
                                         "السودان", "الخرطوم", "ليبيا", "تونس", "المغرب", "الجزائر", "باكستان", "الهند", "أفغانستان", "طالبان", "كوريا", "اليابان", "ألمانيا"]]
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
                                     "السودان", "الخرطوم", "ليبيا", "تونس", "الجزائر", "المغرب", "الدوري الإسباني", "برشلونة", "ريال مدريد"]]
    t = " " + norm_ar(title or "") + " "
    return any(w in t for w in FAR)


def iraq_title(title):
    """فحص على مستوى العنوان نفسه: عنوان فيه بلد/جهة أجنبية بلا أي إشارة عراقية = خبر غير عراقي (لا يُنشر بقناة أخبار العراق)."""
    from marsad.textnorm import norm_ar
    iq, fr = _markers()
    t = " " + norm_ar(title or "") + " "
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
              "الحوثي", "صنعاء", "الخليج", "هرمز", "البحر الأحمر", "ترامب", "واشنطن", "البيت الأبيض", "البنتاغون", "أوبك", "النفط", "برنت"]
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
    if first and datetime.fromisoformat(first.replace("Z", "+00:00")) < now - timedelta(minutes=25):
        return False
    t = n.get("title") or ""
    from tools.editorial import clean_headline
    ct = clean_headline(t)
    if JUNK.match(ct or "") or len((ct or "").split()) < 6 or PROMO_RX.search(ct) or ct.lstrip().startswith(("•", "-", "▪")):
        return False
    if n.get("ctype") == "تحليل/رأي":
        return False
    if (n.get("about_iraq") or n.get("pmf")) and iraq_title(t) and n.get("origin") != "أجنبي":
        return bool(n.get("source_flag")) or n.get("level") in ("عاجل", "مهم")
    return is_regional(n)


def is_regional(n):
    """الشرق الأوسط والمنطقة: فقط المهم والمتداول على نطاق واسع (عاجل/مهم ونشرته 5 جهات فأكثر)، لا الأخبار البعيدة عن المنطقة."""
    t = n.get("title") or ""
    if iraq_title(t) and (n.get("about_iraq") or n.get("pmf")):
        return False
    if far_title(t) or not me_title(t) or MINOR_RX.search(t):
        return False
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
    if iraq_title(n.get("title") or "") and (n.get("about_iraq") or n.get("pmf")):
        return True
    t = n.get("title") or ""
    return not far_title(t) and me_title(t) and (n.get("n_sources") or 1) >= 12


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


def title_sig(t):
    """بصمة العنوان: جذور الكلمات المضمونية + الأرقام — لكشف الخبر نفسه بصياغة أخرى من جهة ثانية."""
    from tools.editorial import _stem, DIGITS, clean_headline, STYLE_OK
    t = clean_headline(t or "")
    words = {_stem(w) for w in t.split()}
    stop = {_stem(w) for w in STYLE_OK}
    return ({w for w in words if len(w) >= 3 and w not in stop}, set(DIGITS.findall(t)))


IDF = {}
RARE = 5.0
GENERIC = set()


def _generic():
    from tools.editorial import _stem
    return {_stem(w) for w in """جاري رفع اطلاق إطلاق تمويل يبحث بحث يبحثان يستقبل استقبل يلتقي التقى لقاء وزير وزيرة سفير السفير رئيس يعلن أعلن تعلن أعلنت
يؤكد أكد أكدت مدير عام العامة دائرة شركة الشركة وزارة محافظ مجلس لجنة يزور زار زيارة اجتماع يترأس ترأس بشأن ملف عن جديد جديدة""".split()}


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
    if j >= 0.45 or (bool(d & pd) and j >= 0.3):
        return True
    if IDF:  # تشابه موزون بالندرة: نفس الأسماء والمفردات النادرة بصياغة مختلفة
        idf = lambda x: IDF.get(x, 6.0)
        sw = sum(idf(x) for x in shared)
        rare = sum(1 for x in shared if idf(x) >= RARE)  # كلمتان نادرتان مشتركتان على الأقل (اسم/مكان/موضوع محدد)
        return rare >= 2 and len(shared) >= 3 and sw / max(1e-6, min(sum(idf(x) for x in w), sum(idf(x) for x in pw))) >= 0.38
    return len(shared) / min(len(w), len(pw)) >= 0.7 and len(shared) >= 4


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
    return json.dumps({"inline_keyboard": [row]}, ensure_ascii=False)


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


def publish_main_sigs(titles):
    """بصمات ما نشرته الجولة الرئيسية (آخر 12 ساعة) ليقرأها المسار السريع فلا يكرره."""
    import subprocess
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "main_sigs.json"
            p.write_text(json.dumps([x for x in titles if x.get("ts", 0) >= datetime.now(timezone.utc).timestamp() - 12 * 3600], ensure_ascii=False), encoding="utf-8")
            if subprocess.run(["gh", "release", "view", "fastlane"], capture_output=True, timeout=25).returncode:
                subprocess.run(["gh", "release", "create", "fastlane", "--title", "المسار السريع", "--notes", "بصمات المنشور بين المسارين", "--prerelease"],
                               capture_output=True, timeout=25)
            subprocess.run(["gh", "release", "upload", "fastlane", str(p), "--clobber"], capture_output=True, timeout=25)
    except Exception:  # noqa: BLE001
        pass


CARDS = PWA / "cards"
ANIM = DATA / "anim"
CARD_STYLE = "news2"  # «نشرة ٢» شريط تلفزيوني كامل وشعار مفرّغ — طلب إيهاب 2026-11-02 (قبلها «news»)  # «نشرة» بأسلوب القنوات الإخبارية وخط Cairo — طلب إيهاب 2026-11-01 (قبلها «lux»)  # «أ» الفاخر (زجاج مغبّش + معالجة سينمائية) — طلب إيهاب قالباً أفخم 2026-11-01 (قبلها «a»)
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
    if CARD_STYLE == "news2":
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
    if is_breaking(n) and CARD_STYLE in ("v3", "a", "b", "c", "lux", "news", "news2"):  # العاجل: بطاقة متحركة بوميض شارة «عاجل»
        try:
            ANIM.mkdir(parents=True, exist_ok=True)
            for f in ANIM.glob("*.mp4"):
                if f.stat().st_mtime < cut:
                    f.unlink()
            (ANIM / name.replace(".jpg", ".mp4")).write_bytes(tg_card.breaking_anim(photo, headline(n), n.get("first_utc") or n.get("latest_utc"), style=CARD_STYLE))
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
        later = [p for p in pend if not (p.get("b") and not p.get("textonly"))]
        pend = [p for p in pend if p.get("b") and not p.get("textonly")]
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

    for p in pend:
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
                        caption=p["text"][:1024], width="1280", height="720", **common(p))
                av.unlink()
                if r.get("ok"):
                    keep(p, r)
                    done["anim"] += 1
                    continue
            except Exception as e:  # noqa: BLE001
                DEBUG.append(f"animsend:{type(e).__name__}:{str(e)[:50]}")
        cu = APP_URL + "cards/" + p["card"]
        ok = False
        while not only_breaking and _t.time() < deadline:
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
                pass
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
    """موجز المساء 9 مساءً بغداد بالقناة: أبرز 5 أخبار عراقية نُشرت اليوم (حسب عدد الجهات)، كل سطر رابط للمنشور نفسه."""
    now = datetime.now(timezone.utc)
    bgd = now + timedelta(hours=3)
    today = bgd.strftime("%Y-%m-%d")
    if bgd.hour != 21 or msgs.get("_evening") == today:
        return None
    news = load(PWA / "news.json", [])
    start = (bgd.replace(hour=0, minute=0, second=0) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
    pool = [n for n in news if n["id"] in msgs and (n.get("first_utc") or "") >= start and (n.get("about_iraq") or n.get("pmf"))]
    top = sorted(pool, key=lambda n: (-(n.get("n_sources") or 1), -rank(n)))[:5]
    if len(top) < 3:
        return None
    ch = CHANNEL.rstrip("/").split("/")[-1]
    lines = [f"🗞 <b>أبرز أخبار العراق اليوم</b> — {bgd.day} {['كانون الثاني', 'شباط', 'آذار', 'نيسان', 'أيار', 'حزيران', 'تموز', 'آب', 'أيلول', 'تشرين الأول', 'تشرين الثاني', 'كانون الأول'][bgd.month - 1]}", ""]
    for i, n in enumerate(top, 1):
        from tools.editorial import clean_headline
        lines.append(f"{i}. <a href=\"https://t.me/{ch}/{msgs[n['id']]}\">{H.escape(clean_headline(n['title'], 120))}</a>")
    lines += ["", f"تابعونا لحظة بلحظة 👇\n{CHANNEL}"]
    r = api(token, "sendMessage", chat_id=chat_id, text="\n".join(lines), parse_mode="HTML", disable_web_page_preview="true", disable_notification="true")
    if r.get("ok"):
        msgs["_evening"] = today
        return {"evening_digest": True}
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
        first_run = not sent.get("_init")
        out = []
        build_idf([x.get("title") or "" for x in news])
        posted = [x for x in sent.get("_titles", []) if x.get("ts", 0) >= now.timestamp() - 12 * 3600]
        fast = fastlane_sigs()  # ما نشره المسار السريع: لا نكرره، ويُحسب بالسقف الساعي
        posted_all = posted + [x for x in fast if x.get("ts", 0) >= now.timestamp() - 12 * 3600]
        # نسخة البصمات المنشورة على الإصدار: حماية من ذاكرة مخبأة قديمة (جولتان متوازيتان أو كاش لم يُحفظ)
        mine_ts = {round(x.get("ts", 0)) for x in posted}
        posted_all += [x for x in fastlane_sigs("main_sigs.json") if x.get("ts", 0) >= now.timestamp() - 12 * 3600 and round(x.get("ts", 0)) not in mine_ts]
        hour_n = sum(1 for x in posted_all if x.get("id") and x.get("ts", 0) >= now.timestamp() - 3600)  # منشورات النظام الجديد + السريع
        reg_n = sum(1 for x in posted if x.get("reg") and x.get("ts", 0) >= now.timestamp() - 3600)
        dup_skipped = 0
        msgs = load(MSGS, {})
        updates = []
        for n in sorted(news, key=lambda n: n.get("collected_utc") or ""):
            if n["id"] in sent or not worthy(n, now):
                continue  # كل خبر يُنشر مرة واحدة فقط (لا إعادة نشر حتى لو تكرر لدى جهات أكثر — طلب إيهاب 2026-11-01)
            sig = title_sig(n["title"])
            prev = next((x for x in posted_all if same_story(sig, x)), None)
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
            reg = is_regional(n)
            if reg and reg_n >= REGION_PER_HOUR and not is_breaking(n):
                status["region_cap"] = status.get("region_cap", 0) + 1
                continue
            if hour_n >= MAX_PER_HOUR and not is_breaking(n):
                status["hour_cap"] = status.get("hour_cap", 0) + 1
                continue  # سقف ساعي: بعده العاجل فقط (القناة لا تُغرق)
            entry = {"w": sorted(sig[0]), "d": sorted(sig[1]), "ts": now.timestamp(), "reg": reg, "id": n["id"], "title": (n.get("title") or "")[:200]}
            posted.append(entry)
            posted_all.append(entry)
            hour_n += 1
            reg_n += reg
            out.append((n, False))
        sent["_titles"] = posted[-400:]
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
            pend.append({"id": n["id"], "card": card, "text": fmt(n, upd), "b": is_breaking(n), "kb": buttons(n)})
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
        # وكيل التحليل الخبري: مقالتان يومياً (2–6 عصراً و8–11 مساءً بغداد) عن أكثر خبر عراقي تداولاً لم يُحلَّل بعد، مع بطاقة «تحليل»
        ana = load(PWA / "analysis.json", {}).get("items", [])
        ap = sent.get("_ana_posted") or {}
        day = (now + timedelta(hours=3)).strftime("%Y-%m-%d")
        bh0 = (now + timedelta(hours=3)).hour
        aslot = "a1" if 14 <= bh0 < 18 else "a2" if 20 <= bh0 < 24 else None
        if aslot and not any(v.get("slot") == day + aslot for v in ap.values()):
            done_t = [title_sig(v.get("title") or "") for v in ap.values() if v.get("d") == day]
            cand = [a for a in ana if a["id"] not in ap and iraq_title(a["title"]) and not far_title(a["title"])
                    and (a.get("last_time") or "") >= (now - timedelta(hours=16)).strftime("%Y-%m-%dT%H:%M")
                    and not any(same_story(title_sig(a["title"]), {"w": sorted(t[0]), "d": sorted(t[1])}) for t in done_t)]
            if cand:
                a = dict(max(cand, key=lambda x: x["n_sources"]))
                from tools import analysis as A, tg_card
                from tools.editorial import pick_best, clean_headline
                a["title"] = clean_headline(pick_best([a["title"]] + [x["title"] for x in (a.get("narratives") or [])] +
                                                       [x["text"][:200].split("\n")[0] for x in (a.get("excerpts") or [])])) or a["title"]
                if a.get("reach10_min") is not None:
                    m = a["reach10_min"]
                    a["reach_txt"] = f"{m} د" if m < 90 else f"{round(m / 60)} س"
                art, by = None, "Gemini"
                try:
                    art = A.write_article(a)
                except Exception as e:  # noqa: BLE001
                    DEBUG.append(f"article:{type(e).__name__}")
                if not art:
                    art, by = A.data_reading(a), "بيانات التغطية"
                atitle, abody = art
                body = H.escape(abody)
                for h in A.ART_HEADS + ("الصياغات المتداولة:",):
                    body = body.replace(h, f"<b>{h}</b>")
                n0 = next((x for x in news if x["id"] == a["id"]), None)
                photo = news_photo(n0) if n0 else None
                f = a.get("first") or {}
                stats = [(a["n_sources"], "جهة نشرت الخبر"), ((f.get("source") or "—").split(" — ")[0][:18], "أقدم ناشر مرصود")]
                if a.get("reach10_min") is not None:
                    stats.append((a["reach_txt"], "حتى بلغ 10 جهات"))
                try:
                    card = save_card(tg_card.card_news2(photo, atitle, False, now.strftime("%Y-%m-%dT%H:%M:%SZ"), tag="تحليل", stats=stats), "ana_" + a["id"])
                    note = ("صياغة آلية محايدة بحارس حقائق" if by == "Gemini" else "قراءة محسوبة من بيانات التغطية")
                    text = (f"🧭 <b>تحليل خبري</b>\n<b>{H.escape(atitle)}</b>\n\n{body}\n\n"
                            f"<i>{note}، استناداً إلى {a['n_sources']} جهة رصدتها «هسة وصل». الانتشار لا يعني التأكيد.</i>\n\n#تحليل_خبري\n{CHANNEL}")
                    pend.append({"id": "ana_" + a["id"], "card": card, "text": text[:4000], "b": False, "kb": buttons(n0) if n0 else None})
                    ap[a["id"]] = {"d": day, "t": now.timestamp(), "slot": day + aslot, "title": a["title"], "by": by}
                    status["analysis_post"] = {"id": a["id"], "by": by, "n": a["n_sources"]}
                except Exception as e:  # noqa: BLE001
                    DEBUG.append(f"anacard:{type(e).__name__}:{str(e)[:40]}")
        sent["_ana_posted"] = dict(list(ap.items())[-200:])
        # منوعات: خبر عراقي خفيف (رياضة، طقس، ثقافة، تقنية، صحة، أسعار) — واحد كل 75 دقيقة كحد أعلى، 8 يومياً، 8 صباحاً–11 ليلاً، بإشعار صامت
        vs = sent.get("_variety") or {}
        v_today = [v for v in vs.values() if v.get("d") == day]
        v_last = max([v.get("t", 0) for v in vs.values()] or [0])
        if 8 <= bh0 < 23 and len(v_today) < VARIETY_MAX_DAY and now.timestamp() - v_last > VARIETY_GAP:
            vc = []
            for n in news:
                if n["id"] in sent or n["id"] in vs or not n.get("about_iraq") or not iraq_title(n.get("title") or ""):
                    continue
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
                vc.append((n.get("n_sources") or 1, n, k, sig))
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
                    sent["_titles"] = posted[-400:]
                    status["variety_post"] = {"id": n["id"], "k": k}
                except Exception as e:  # noqa: BLE001
                    DEBUG.append(f"variety:{type(e).__name__}:{str(e)[:40]}")
        sent["_variety"] = dict(list(vs.items())[-300:])
        # تحليل خبر إيجابي عن العراق: مرتان يومياً (12 ظهراً و6 مساءً بغداد)
        bh = (now + timedelta(hours=3)).hour
        slot = "noon" if 12 <= bh < 15 else "eve" if 18 <= bh < 21 else None
        pp = sent.get("_pos") or {}
        if slot and pp.get(day + slot) is None:
            from tools import analysis as A
            n = A.pick_positive(news, set(pp.get("ids", [])), (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S"))
            r = A.write_positive(n) if n else None
            if r:
                body = H.escape(r)
                for h in ("ما الذي حدث:", "لماذا هو تطور إيجابي:", "ما الذي يحتاجه ليكتمل أثره:"):
                    body = body.replace(h, f"<b>{h}</b>")
                pend.append({"id": "pos_" + n["id"], "textonly": True, "b": False, "reply_to": n["id"],
                             "text": f"🌱 <b>تحليل خبري | {H.escape(n['title'][:150])}</b>\n\n{body}\n\n"
                                     f"<i>قراءة آلية استناداً إلى ما نشرته {n.get('n_sources') or 1} جهة رصدتها «هسة وصل».</i>\n\n{CHANNEL}"})
                pp[day + slot] = n["id"]
                pp["ids"] = (pp.get("ids", []) + [n["id"]])[-100:]
                status["positive_post"] = n["id"]
            elif n is None:
                status["positive_post"] = "لا يوجد خبر إيجابي مناسب الآن"
        sent["_pos"] = pp
        from tools.editorial import LLM_STATS
        status["editor_llm"] = LLM_STATS
        PENDING.write_text(json.dumps(pend, ensure_ascii=False), encoding="utf-8")
        SENT.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")
        if any(p.get("b") and not p.get("textonly") for p in pend):
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
