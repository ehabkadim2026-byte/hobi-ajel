"""خلفية «خريطة الحدث» للبطاقة حين لا توجد صورة صالحة (إيهاب 07/11: بعض القوالب تبقى فارغة بلا خلفية مميزة).

بدل التدرج الفارغ: خريطة العراق بحدود المحافظات، والمحافظة المذكورة بالخبر مضاءة بالأحمر مع اسمها.
خبر بلا محافظة محددة ⇒ الخريطة كاملة بإضاءة هادئة (بلا تحديد مكان مضلل).
البيانات: Natural Earth admin-1 (ملكية عامة) مبسّطة ← assets/geo/iraq_provinces.json.
"""
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
RED = (226, 24, 38)

# اسم المحافظة بالخريطة ← كلمات تدل عليها (المحافظة ومركزها وأبرز أقضيتها)
PROV = [
    ("محافظة البصرة", "البصرة", r"البصرة|الزبير|أبو الخصيب|ابو الخصيب|الفاو|أم قصر|ام قصر|القرنة|شط العرب"),
    ("محافظة نينوى", "نينوى", r"نينوى|الموصل|تلعفر|سنجار|الحمدانية|سهل نينوى|ربيعة|القيارة"),
    ("محافظة الأنبار", "الأنبار", r"الأنبار|الانبار|الرمادي|الفلوجة|هيت|حديثة|القائم|الرطبة|عانة|راوة|الكرمة|عامرية الفلوجة"),
    ("محافظة أربيل", "أربيل", r"أربيل|اربيل|سوران|كويه|شقلاوة"),
    ("محافظة السليمانية", "السليمانية", r"السليمانية|حلبجة|رانية|جمجمال|دوكان|كلار"),
    ("محافظة دهوك", "دهوك", r"دهوك|زاخو|العمادية|سيميل|ابراهيم الخليل|إبراهيم الخليل"),
    ("كركوك", "كركوك", r"كركوك|الحويجة|داقوق|دبس"),
    ("صلاح الدين", "صلاح الدين", r"صلاح الدين|تكريت|سامراء|بيجي|الشرقاط|طوزخورماتو|طوز|بلد|الدجيل|الضلوعية"),
    ("محافظة ديالى", "ديالى", r"ديالى|ديالي|بعقوبة|المقدادية|خانقين|بلدروز|الخالص|مندلي"),
    ("محافظة واسط", "واسط", r"واسط|الكوت|الصويرة|العزيزية|النعمانية|الحي |بدرة|زرباطية"),
    ("محافظة ميسان", "ميسان", r"ميسان|العمارة|المجر|الكحلاء|علي الغربي|قلعة صالح"),
    ("ذي قار", "ذي قار", r"ذي قار|ذيقار|الناصرية|الشطرة|سوق الشيوخ|الرفاعي|الجبايش|قلعة سكر|الغراف"),
    ("محافظة المثنى", "المثنى", r"المثنى|السماوة|الرميثة|الخضر"),
    ("محافظة القادسية", "الديوانية", r"القادسية|الديوانية|عفك|الشامية"),
    ("محافظة النجف", "النجف", r"النجف|الكوفة|المناذرة"),
    ("محافظة كربلاء", "كربلاء", r"كربلاء|عين التمر"),
    ("محافظة بابل", "بابل", r"بابل|الحلة|المسيب|الإسكندرية|الاسكندرية|جرف الصخر|جرف النصر|المحاويل|الهاشمية"),
    ("محافظة بغداد", "بغداد", r"بغداد|الكرخ|الرصافة|الكاظمية|الأعظمية|الاعظمية|مدينة الصدر|الدورة|المنصور|أبو غريب|ابو غريب|التاجي|الطارمية|المدائن|الحسينية|الشعلة|الزعفرانية|البياع|الكرادة|المطار"),
]
# أسماء تحتمل معنى آخر حين تأتي وحدها
_FALSE = re.compile(r"البنك المركزي|ساحة التحرير")


@lru_cache(maxsize=1)
def _shapes():
    return json.loads((ROOT / "assets" / "geo" / "iraq_provinces.json").read_text(encoding="utf-8"))


def province(title):
    """(اسم الخريطة، الاسم المعروض) لأول محافظة مذكورة بالعنوان — أو None. بغداد آخراً لأنها تُذكر عرضاً كثيراً."""
    t = title or ""
    hits = []
    for key, label, rx in PROV:
        m = re.search(rx, t)
        if m:
            hits.append((m.start(), key, label))
    if not hits:
        return None
    hits.sort()
    non_bgd = [h for h in hits if h[1] != "محافظة بغداد"]
    _, key, label = (non_bgd or hits)[0]
    return key, label


def _project(box):
    """دالة إسقاط (lon,lat) ← (x,y) تملأ الصندوق مع الحفاظ على النسبة (تصحيح خط العرض)."""
    pts = [p for polys in _shapes().values() for ring in polys for p in ring]
    lons, lats = [p[0] for p in pts], [p[1] for p in pts]
    k = math.cos(math.radians((min(lats) + max(lats)) / 2))
    w_geo, h_geo = (max(lons) - min(lons)) * k, max(lats) - min(lats)
    x0, y0, x1, y1 = box
    s = min((x1 - x0) / w_geo, (y1 - y0) / h_geo)
    ox = x0 + ((x1 - x0) - w_geo * s) / 2
    oy = y0 + ((y1 - y0) - h_geo * s) / 2
    lo, la = min(lons), max(lats)
    return lambda lon, lat: (ox + (lon - lo) * k * s, oy + (la - lat) * s)


def backdrop(title, w, h, box=None, font=None, draw_rtl=None):
    """صورة RGB بحجم w×h: خلفية داكنة + خريطة العراق، والمحافظة المذكورة مضاءة."""
    box = box or (int(w * 0.14), int(h * 0.10), int(w * 0.86), int(h * 0.60))
    im = Image.new("RGB", (w, h), (9, 12, 20))
    d = ImageDraw.Draw(im)
    for y in range(h):  # تدرج عمودي خفيف (أعلى أفتح قليلاً)
        k = y / h
        d.line([(0, y), (w, y)], fill=(int(16 - 7 * k), int(22 - 10 * k), int(36 - 16 * k)))
    for gy in range(18, h, 36):  # شبكة نقاط دقيقة كملمس خرائط
        for gx in range(18, w, 36):
            d.point((gx, gy), fill=(40, 48, 64))
    P = _project(box)
    hit = province(title)
    shapes = _shapes()
    poly = {name: [[P(x, y) for x, y in ring] for ring in rings] for name, rings in shapes.items()}
    if hit and hit[0] in poly:  # تقريب نحو المحافظة: الخريطة أكبر ×1.75 والمحافظة بمنتصف منطقة الخريطة (أقوى بصرياً)
        pts = [p for ring in poly[hit[0]] for p in ring]
        pcx, pcy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
        z, tx, ty = 1.75, w / 2, (box[1] + box[3]) / 2
        poly = {n: [[((x - pcx) * z + tx, (y - pcy) * z + ty) for x, y in ring] for ring in rings] for n, rings in poly.items()}

    if hit and hit[0] in poly:  # توهج أحمر خلف المحافظة
        glow = Image.new("L", (w, h), 0)
        gd = ImageDraw.Draw(glow)
        for ring in poly[hit[0]]:
            gd.polygon(ring, fill=255)
        glow = glow.filter(ImageFilter.GaussianBlur(46)).point(lambda v: int(v * 0.75))
        im.paste(Image.new("RGB", (w, h), RED), (0, 0), glow)

    ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    base_fill = (255, 255, 255, 20)
    if not hit:  # خبر عام: الخريطة كلها بتدرج أحمر هادئ (هوية القناة) بدل رمادي باهت
        mask = Image.new("L", (w, h), 0)
        md = ImageDraw.Draw(mask)
        for rings in poly.values():
            for ring in rings:
                md.polygon(ring, fill=255)
        grad = Image.new("RGB", (w, h))
        gd = ImageDraw.Draw(grad)
        for y in range(h):
            k = min(1, max(0, (y - box[1]) / max(1, box[3] - box[1])))
            gd.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * k) for a, b in zip((150, 20, 32), (40, 14, 22))))
        im.paste(grad, (0, 0), mask.point(lambda v: int(v * 0.85)))
    for name, rings in poly.items():
        for ring in rings:
            if hit and name == hit[0]:
                od.polygon(ring, fill=RED + (235,))
            elif hit:
                od.polygon(ring, fill=base_fill)
    for name, rings in poly.items():
        for ring in rings:
            od.line(ring + [ring[0]], fill=(255, 255, 255, 235 if hit and name == hit[0] else (60 if hit else 95)), width=4 if hit and name == hit[0] else 2, joint="curve")
    im.paste(ov, (0, 0), ov)

    if hit and hit[0] in poly and font and draw_rtl:  # اسم المحافظة بجانبها
        pts = [p for ring in poly[hit[0]] for p in ring]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        d = ImageDraw.Draw(im)
        r = 11
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255))
        d.ellipse([cx - r * 2.1, cy - r * 2.1, cx + r * 2.1, cy + r * 2.1], outline=(255, 255, 255), width=3)
        try:
            tw = d.textlength(hit[1], font=font, direction="rtl", language="ar")
        except Exception:  # noqa: BLE001
            tw = d.textlength(hit[1], font=font)
        right = cx - 44 if cx > w * 0.55 else cx + 44 + tw  # الاسم بالجهة الأوسع
        right = max(min(right, w - 40), tw + 40)
        ty = cy - font.size * 0.75
        pad = 16
        d.rectangle([right - tw - pad, ty - 4, right + pad, ty + font.size * 1.45], fill=(9, 12, 20))
        draw_rtl(d, right, ty, hit[1], font, (255, 255, 255))
    return im
