"""بطاقة «أكا ميديا» v6 — نظام قوالب حسب نوع الخبر (طلب إيهاب 05/11: «القالب يناسب الخبر أو يشير للحدث»).

الفكرة البصرية: غرفة أخبار حديثة — صورة الحدث بطلة البطاقة، ولون واحد لكل نوع خبر يقود العين:
  عاجل/أمن أحمر الهوية · سياسة أزرق · اقتصاد أخضر · طقس سماوي · رياضة ليموني · تعليم برتقالي · صحة فيروزي.
عناصر التوقيع: «عمود» ملوّن بطول العنوان على يمينه (بداية القراءة)، وسم النوع بلون القسم، شريط سفلي بلون القسم.
تخطيطات خاصة:
  - رقم: خبر فيه رقم بارز (سعر، نسبة، عدد) ← الرقم عملاق بلون القسم فوق العنوان.
  - تصريح: «جهة: كلام» ← اسم المتحدث بلون القسم وعلامة اقتباس كبيرة خافتة.
  - بلا صورة: خلفية داكنة مشبّعة بلون القسم واسم القسم بحروف عملاقة شبه شفافة (ملمس طباعي لا رسم).
الخطوط: Alexandria (العناوين والأرقام) + IBM Plex Sans Arabic (البيانات). 1080×1350 (4:5 كما يعرضها تلغرام).
"""
import io
import re

from PIL import Image, ImageDraw, ImageFilter

from tools import tg_card as C

W, H = 1080, 1350
INK = (8, 11, 18)
WHITE = (255, 255, 255)
RED = (226, 24, 38)

KINDS = {  # الاسم المعروض، اللون، كلمات الكشف (على العنوان)
    "security": ("أمن", (232, 46, 58), r"(انفجار|اشتباك|قصف|استهداف|اغتيال|مقتل|قتلى|جرحى|إصابة|اصابة|عبوة|هجوم|مسيرة|طائرة مسيرة|"
                                        r"اعتقال|القبض|ضبط|إرهاب|ارهاب|داعش|عملية أمنية|حظر تجوال|حريق|غرق|حادث سير|جثة)"),
    "weather": ("طقس", (56, 189, 248), r"(الأنواء|الانواء|أمطار|امطار|الطقس|درجات الحرارة|الحرارة|غبار|عاصفة|سيول|فيضان|ثلوج|رياح|منخفض جوي)"),
    "education": ("تعليم", (251, 146, 60), r"(التربية|التعليم العالي|الدوام|عطلة|تعطيل|الامتحانات|امتحانات|الطلبة|المدارس|الجامعات|السادس الإعدادي|نتائج)"),
    "economy": ("اقتصاد", (34, 197, 94), r"(دينار|دولار|أسعار|اسعار|سعر|النفط|برميل|الموازنة|رواتب|الرواتب|المصرف|البنك المركزي|صادرات|"
                                        r"استيراد|الجمارك|الضريبة|السلف|القروض|الأمبير|الامبير|الكهرباء|البورصة|التضخم)"),
    "sport": ("رياضة", (190, 242, 100), r"(المنتخب|منتخب|الدوري|مباراة|اعتزال|اعتزاله|ريال مدريد|برشلونة|رونالدو|ميسي|كأس|كاس|نادي|اللاعب|لاعب|المدرب|بطولة|هدف|الفيفا|أسود الرافدين)"),
    "health": ("صحة", (45, 212, 191), r"(الصحة|مستشفى|المستشفى|وباء|إصابات بـ|لقاح|الكوليرا|الحمى|مرض|علاج|دواء|الأدوية)"),
    "politics": ("سياسة", (96, 165, 250), r"(البرلمان|مجلس النواب|رئيس الوزراء|السوداني|الحكومة|مجلس الوزراء|الوزير|وزير|الانتخابات|"
                                         r"المحافظ|رئيس الجمهورية|الكتلة|تحالف|الإطار|السفير|وفد|يستقبل|يلتقي|اجتماع|قانون)"),
}
KINDS_RX = {k: re.compile(v[2]) for k, v in KINDS.items()}
ORDER = ["security", "education", "weather", "economy", "sport", "health", "politics"]  # التعليم قبل الطقس: «تعطيل الدوام بسبب الأمطار» خبر تعليم

NUM_RX = re.compile(r"(?<![\w؀-ۿ])([0-9٠-٩][0-9٠-٩,\.٬٫]*)\s*(%|٪|بالمئة|بالمائة|دينار|دولار|برميل|مليار|مليون|ألف|الف|"
                    r"درجة|درجات|ميغاواط|ميكاواط|طن|أطنان|ساعة|ساعات|يوماً|يوما|أيام)?")


def kind_of(text, breaking=False):
    for k in ORDER:
        if KINDS_RX[k].search(text or ""):
            return k
    return "news"


def key_number(text):
    """أبرز رقم بالخبر مع وحدته (يُفضّل ذو الوحدة). يتجاهل السنوات والأرقام بين أقواس (أرقام دورات/قرارات)."""
    best = None
    for m in NUM_RX.finditer(text or ""):
        n, unit = m.group(1).strip(",.٬٫"), (m.group(2) or "")
        digits = re.sub(r"\D", "", n.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
        if not digits:
            continue
        if len(digits) == 4 and digits.startswith(("19", "20")) and not unit:
            continue  # سنة
        if text[max(0, m.start() - 1):m.start()] == "(":
            continue
        if not unit and len(digits) < 2:
            continue
        score = (2 if unit else 0) + min(len(digits), 7) / 10
        if not best or score > best[0]:
            best = (score, n, unit)
    if best and (best[2] or len(re.sub(r"\D", "", best[1])) >= 3):
        return best[1], best[2]
    return None


def _f(name, size):
    return C._ff(name, size)


def _H(s):
    return _f("Alexandria-Black.ttf", s)


def _M(s):
    return _f("IBMPlexSansArabic-SemiBold.ttf", s)


def _tw(d, t, f):
    kw = {"direction": "rtl", "language": "ar"} if C.RAQM else {}
    return d.textlength(C._shape(t), font=f, **kw)


def _photo(photo_jpg, w, h):
    src = Image.open(io.BytesIO(photo_jpg)).convert("RGB")
    im = C._cover(src, w, h).filter(ImageFilter.UnsharpMask(radius=1.4, percent=50, threshold=3))
    return C._grade(im)


def _mix(a, b, k):
    return tuple(int(x + (y - x) * k) for x, y in zip(a, b))


def _backdrop(kind_name, accent):
    """خلفية بلا صورة: تدرّج داكن مشبّع بلون القسم + اسم القسم عملاقاً شبه شفاف خارجاً عن الحافة."""
    top, bot = _mix(INK, accent, 0.30), _mix(INK, accent, 0.06)
    g = Image.new("RGB", (W, H), bot)
    d = ImageDraw.Draw(g)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=_mix(top, bot, min(1, y / (H * 0.8))))
    try:  # شعار أكا كبير وخافت كملمس (أنيق ومن الهوية) بدل كلمة القسم العملاقة التي بدت فراغاً (ملاحظة إيهاب 05/11)
        lg = Image.open(C.LOGO_RGBA).convert("RGBA")
        k = 980 / lg.width
        lg = lg.resize((int(lg.width * k), int(lg.height * k)))
        a = lg.getchannel("A").point(lambda v: int(v * 0.07))
        g.paste(Image.new("RGB", lg.size, WHITE), (int((W - lg.width) / 2) + 120, 140), a)
    except Exception:  # noqa: BLE001
        pass
    return g


def card(photo_jpg, title, breaking=False, when_utc=None, source=None, kind=None, dim=False):
    kick, head = C.split_kicker(title)
    kind = kind or ("security" if breaking and KINDS_RX["security"].search(title or "") else kind_of(title))
    kname, accent = (KINDS[kind][0], KINDS[kind][1]) if kind in KINDS else ("خبر", (240, 240, 240))
    # 05/11: إيهاب اختار بطاقة «سلف الرافدين» (لسان أحمر + صورة الخبر + عنوان كبير) قالباً أساسياً ⇒ أحمر الهوية لكل الأخبار،
    # ونوع الخبر يُكتب نصاً بالوسم بدل تعدد الألوان (KINDS تبقى للكشف والاسم فقط)
    accent = RED
    backdrop_tint = KINDS[kind][1] if kind in KINDS else RED
    has_photo = bool(photo_jpg) and not C.looks_like_logo(photo_jpg)
    num = key_number(head) if kind in ("economy", "weather", "education", "health", "news", "politics") else None
    quote = bool(kick) and not num and len(kick.split()) <= 6 and kind in ("politics", "news")

    # الطبقة الأساسية
    if has_photo:
        src = Image.open(io.BytesIO(photo_jpg))
        wide = src.width / max(1, src.height) > 1.15
        im = Image.new("RGB", (W, H), INK)
        if wide:
            ph_h = int(H * 0.68)
            fade = Image.linear_gradient("L").resize((W, ph_h)).point(lambda v: 255 if v < 140 else int(255 * (255 - v) / 115))
            im.paste(_photo(photo_jpg, W, ph_h), (0, 0), fade)
        else:
            im.paste(_photo(photo_jpg, W, H), (0, 0))
    else:
        im = _backdrop("عاجل" if breaking and kind == "news" else kname, _mix(RED, backdrop_tint, 0.35))
    d = ImageDraw.Draw(im)

    P = 72
    text_w = W - 2 * P - 24  # 24 = العمود الملوّن + فراغه
    # قياس كتلة النص من الأسفل للأعلى
    max_lines = 3 if num else (4 if has_photo else 5)
    sizes = [92, 86, 80, 74, 68, 62, 58, 54, 50]
    _pp = re.split(r"\s*(?:\.{2,}|…)\s*", head, maxsplit=1)
    if len(head.split()) > 15 and len(_pp) == 2 and len(_pp[1].split()) >= 6 and len(_pp[0].split()) <= 6:
        head = _pp[1]  # «خطوة حاسمة في ملف السلاح... الخبر» ← التمهيد التشويقي يُحذف من البطاقة (يبقى بالنص تحتها)
    f, sz, lines = C._fit_font(d, head, text_w, max_lines, sizes, _H)
    if lines and lines[-1].endswith("…"):  # عنوان مبتور (ملاحظة إيهاب 05/11): نحذف التمهيد التشويقي قبل «...» ونبقي الخبر نفسه
        parts = re.split(r"\s*(?:\.{2,}|…)\s*", head, maxsplit=1)
        if len(parts) == 2 and len(parts[1].split()) >= 5:
            head = parts[1]
            f, sz, lines = C._fit_font(d, head, text_w, max_lines + 1, sizes, _H)
    lh = int(sz * 1.46)  # Alexandria عالية الصواعد: أقل من 1.4 تتلامس السطور
    y_meta = H - 108
    y_text = y_meta - 46 - lh * len(lines)
    if not has_photo:  # بلا صورة: الكتلة بمنتصف البطاقة بدل أسفلها وفوقها فراغ
        block = lh * len(lines) + (196 if num else 0) + (76 if kick else 0) + 70
        y_text = min(y_text, int(250 + (y_meta - 60 - 250 - block) / 2 + block - lh * len(lines)))
    y = y_text
    num_h = 0
    if num:
        fn = _H(178)
        num_h = 190
        y -= num_h + 6
    kick_h = 0
    if kick:
        fk = _H(42)
        kick_h = 76
        y -= kick_h
    y_label = y - 70

    # تظليل لقراءة النص (يتكيّف مع ارتفاع الكتلة)
    if has_photo:
        k0 = max(0.05, (y_label - 300) / H)
        shade = C._vgrad(W, H, [(0, 110), (0.16, 0), (k0, 0), (min(0.98, (y_label + 60) / H), 222), (1, 248)])
        im.paste(Image.new("RGB", (W, H), INK), (0, 0), shade)
        d = ImageDraw.Draw(im)

    # الشعار
    C._paste_badge(im, W - P - 150 + 8, 50, 150)
    d = ImageDraw.Draw(im)

    # وسم النوع: عاجل = لسان أحمر مصمت بنقطة، غيره = نقطة ملوّنة + اسم القسم
    x1 = W - P
    if breaking:
        lab = "عاجل"
        fl = _H(38)
        tw = _tw(d, lab, fl)
        bw = int(tw + 50)
        d.rounded_rectangle([x1 - bw, y_label, x1, y_label + 58], radius=6, fill=(110, 10, 18) if dim else RED)
        C._draw_rtl(d, x1 - 25, y_label + 3, lab, fl, WHITE)
        cx = x1 - bw - 26
        d.ellipse([cx - 9, y_label + 20, cx + 9, y_label + 38], fill=(120, 20, 28) if dim else (255, 70, 80))
        lab2 = kname if kind != "news" else ""
        if lab2:
            fl2 = _M(30)
            C._draw_rtl(d, cx - 26, y_label + 10, lab2, fl2, _mix(WHITE, INK, 0.25))
    else:  # وسم أبيض بنص أحمر (نوع الخبر) — نفس شكل لسان «عاجل» حتى تبقى الهوية واحدة
        lab = kname
        fl = _H(34)
        tw = _tw(d, lab, fl)
        bw = int(tw + 46)
        d.rounded_rectangle([x1 - bw, y_label, x1, y_label + 58], radius=6, fill=WHITE)
        C._draw_rtl(d, x1 - 23, y_label + 1, lab, fl, RED)

    # المتحدث/الجهة (تصريح) + علامة اقتباس
    yy = y_label + 74
    if kick:
        C._draw_rtl(d, x1, yy - 6, kick, fk, accent)
        yy += kick_h
    if quote:
        fq = _H(300)
        q = Image.new("L", (W, H), 0)
        ImageDraw.Draw(q).text((P - 10, yy - 150), "”", font=fq, fill=40)
        im.paste(Image.new("RGB", (W, H), accent), (0, 0), q)
        d = ImageDraw.Draw(im)

    # الرقم البارز
    if num:
        n, unit = num
        tn = _tw(d, n, fn)
        C._draw_rtl(d, x1, yy - 40, n, fn, accent)
        if unit:
            fu = _M(46)
            C._draw_rtl(d, int(x1 - tn - 24), yy + 70, unit, fu, WHITE)
        yy += num_h + 6

    # العمود الملوّن + العنوان
    d.rectangle([x1 - 8 + 18, y_text + 10, x1 + 18, y_text + lh * len(lines) - int(sz * 0.18)], fill=accent)
    for i, ln in enumerate(lines):
        C._draw_rtl(d, x1 - 12, y_text + i * lh - int(sz * 0.12), ln, f, WHITE)

    # البيانات
    d.line([(P, y_meta - 22), (W - P, y_meta - 22)], fill=_mix(INK, WHITE, 0.2), width=2)
    fm = _f("IBMPlexSansArabic-Medium.ttf", 28)
    w = C._when(when_utc)
    meta = " · ".join([x for x in [source, w] if x])
    if meta:
        C._draw_rtl(d, x1, y_meta, meta, fm, _mix(WHITE, INK, 0.28))
    d.text((P, y_meta + 2), "@akamedia_iq", font=_f("IBMPlexSansArabic-Medium.ttf", 28), fill=_mix(WHITE, INK, 0.4))
    d.rectangle([0, H - 12, W, H], fill=accent if not breaking else RED)
    return C._jpg(im)
