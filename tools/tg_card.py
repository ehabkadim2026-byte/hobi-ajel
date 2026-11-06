"""صورة الخبر لمنشورات تلغرام.

1) صورة المنشور الأصلي: لمصادر تلغرام نقرأ صفحة التضمين العامة t.me/<قناة>/<رقم>?embed=1،
   ولمصادر الويب نقرأ og:image من صفحة الخبر (لا نقرأ روابط Google News).
2) إن لم توجد صورة: بطاقة «أكا ميديا» مولّدة بالعنوان (PIL)، بلا أي صورة مختلقة.
"""
import html
import io
import re
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (HobiAjel news monitor)"}
FONT_CANDIDATES = [ROOT / "assets" / "NotoKufiArabic.ttf", Path.home() / "fonts" / "NotoKufiArabic.ttf",
                   Path("/usr/share/fonts/truetype/noto/NotoKufiArabic-Bold.ttf"),
                   Path("/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf"),
                   Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
                   Path("/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf")]
BG_URL = re.compile(r"background-image:url\('([^']+)'\)")


def _get(url, timeout=8, limit=600_000):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit).decode("utf-8", "replace")


def tg_photo(url):
    """رابط صورة/غلاف فيديو منشور تلغرام عام، أو None."""
    m = re.match(r"https://t\.me/(?:s/)?([\w\d_]+)/(\d+)", url or "")
    if not m:
        return None
    page = _get(f"https://t.me/{m.group(1)}/{m.group(2)}?embed=1")
    for cls in ("tgme_widget_message_photo_wrap", "tgme_widget_message_video_thumb", "link_preview_right_image", "link_preview_image"):
        i = page.find(cls)
        if i >= 0:
            mm = BG_URL.search(page, i, i + 1500)
            if mm and mm.group(1).startswith("https://"):
                return html.unescape(mm.group(1))
    return None


def og_image(url):
    if not url or "news.google." in url or not url.startswith("http"):
        return None
    page = _get(url)
    for rx in (r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
               r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image',
               r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)'):
        m = re.search(rx, page, re.I)
        if m and m.group(1).startswith("https://"):
            return html.unescape(m.group(1))
    return None


def find_image(url):
    try:
        return tg_photo(url) if "t.me/" in (url or "") else og_image(url)
    except Exception as e:  # noqa: BLE001
        print("find_image", url, type(e).__name__, str(e)[:80])
        return None


def fetch_jpeg(img_url):
    """ننزّل الصورة بأنفسنا ونرفعها (تلغرام لا يقبل روابط CDN مباشرة)."""
    req = urllib.request.Request(img_url, headers=UA)
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read(8_000_000)
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    im.thumbnail((1600, 1600))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return buf.getvalue()


LOGO = ROOT / "assets" / "brand" / "aka_logo_white.png"


def brand(jpg_bytes):
    """يضيف شعار «أكا ميديا» على الصورة (شارة بيضاء أسفل اليسار)."""
    from PIL import ImageDraw as _D
    im = Image.open(io.BytesIO(jpg_bytes)).convert("RGB")
    if LOGO.exists():
        W, H = im.size
        lg = Image.open(LOGO).convert("RGB")
        lw = max(110, int(min(W, H) * 0.20))
        lh = int(lg.height * lw / lg.width)
        lg = lg.resize((lw, lh), Image.LANCZOS)
        pad, m = int(lw * 0.10), int(min(W, H) * 0.03)
        bw, bh = lw + 2 * pad, lh + 2 * pad
        x0, y0 = m, H - bh - m
        mask = Image.new("L", (bw, bh), 0)
        _D.Draw(mask).rounded_rectangle([0, 0, bw - 1, bh - 1], radius=int(pad * 1.4), fill=255)
        badge = Image.new("RGB", (bw, bh), (255, 255, 255))
        badge.paste(lg, (pad, pad))
        im.paste(badge, (x0, y0), mask)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def _font(size):
    for p in FONT_CANDIDATES:
        if p.exists():
            try:
                f = ImageFont.truetype(str(p), size)
                try:
                    f.set_variation_by_name("Bold")
                except Exception:  # noqa: BLE001
                    pass
                return f
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


RAQM = features.check("raqm")


def _shape(text):
    """بدون raqm نشكّل الحروف يدوياً (arabic_reshaper + bidi)."""
    if RAQM:
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except Exception:  # noqa: BLE001
        return text


def _draw_rtl(d, xy_right, y, text, font, fill):
    kw = {"direction": "rtl", "language": "ar"} if RAQM else {}
    t = _shape(text)
    w = d.textlength(t, font=font, **kw)
    d.text((xy_right - w, y), t, font=font, fill=fill, **kw)


def _wrap(d, text, font, width):
    kw = {"direction": "rtl", "language": "ar"} if RAQM else {}
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if d.textlength(_shape(t), font=font, **kw) <= width:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def card(title, head, meta, footer):
    """بطاقة 1280×720 بالعنوان. ترجع bytes بصيغة JPEG."""
    W, H, P = 1280, 720, 70
    red = (200, 16, 46) if "عاجل" in head else (226, 120, 20)
    im = Image.new("RGB", (W, H), (12, 18, 32))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 14], fill=red)
    for i in range(H):  # تدرّج خفيف
        a = int(18 * i / H)
        d.line([(0, i), (W, i)], fill=(12 + a, 18 + a, 32 + a))
    d.rectangle([0, 0, W, 14], fill=red)
    fh, fb, fs = _font(40), _font(60), _font(30)
    # شارة المستوى
    kw = {"direction": "rtl", "language": "ar"} if RAQM else {}
    hw = d.textlength(_shape(head), font=fh, **kw)
    d.rounded_rectangle([W - P - hw - 40, 60, W - P, 128], radius=14, fill=red)
    _draw_rtl(d, W - P - 20, 66, head, fh, (255, 255, 255))
    # العنوان
    size = 60
    lines = _wrap(d, title, fb, W - 2 * P)
    while len(lines) > 5 and size > 38:
        size -= 6
        fb = _font(size)
        lines = _wrap(d, title, fb, W - 2 * P)
    if len(lines) > 6:
        lines = lines[:6]
        lines[-1] += " …"
    y = 165
    for ln in lines:
        _draw_rtl(d, W - P, y, ln, fb, (245, 247, 250))
        y += int(size * 1.6)
    # التذييل
    fw = d.textlength(footer, font=fs)
    d.text((W - P - fw, H - 80), footer, font=fs, fill=(120, 190, 255))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return brand(buf.getvalue())


if __name__ == "__main__":
    Path("card_test.jpg").write_bytes(card("عاجل: رئيس الوزراء يوجه بفتح تحقيق عاجل في حادثة انقطاع الكهرباء عن عدة محافظات جنوبية", "🔴 عاجل".replace("🔴 ", ""),
                                           "السومرية نيوز · 14:32 بغداد · غير مؤكد", "t.me/akamedia_iq"))


def _cover(im, W, H):
    r = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * r) + 1, int(im.height * r) + 1), Image.LANCZOS)
    x, y = (im.width - W) // 2, max(0, int((im.height - H) * 0.35))
    return im.crop((x, y, x + W, y + H))


def news_card(photo_jpg, title, breaking=True, time_str="", handle="t.me/akamedia_iq"):
    """قالب الخبر الموحّد 1280×720 (أسلوب غرف الأخبار العربية الكبرى، بهوية «أكا ميديا»):
    صورة الخبر كاملة + تدرّج داكن سفلي + شريط أحمر جانبي + شارة «عاجل»/«خبر» + العنوان بخط عريض + تذييل الوقت والشعار."""
    from PIL import ImageDraw as _D, ImageFilter
    W, H, P = 1280, 720, 64
    red, navy, gold = (204, 18, 38), (10, 24, 52), (230, 178, 60)
    if photo_jpg:
        bgimg = _cover(Image.open(io.BytesIO(photo_jpg)).convert("RGB"), W, H)
    else:  # بلا صورة: خلفية كحلية متدرجة بخطوط مائلة خفيفة وشعار باهت
        bgimg = Image.new("RGB", (W, H), navy)
        d0 = _D.Draw(bgimg)
        for i in range(H):
            k = i / H
            d0.line([(0, i), (W, i)], fill=(int(10 + 14 * k), int(24 + 18 * k), int(52 + 30 * k)))
        for x in range(-H, W, 46):
            d0.line([(x, H), (x + H, 0)], fill=(22, 40, 78), width=2)
        if LOGO.exists():
            lg = Image.open(LOGO).convert("L").resize((520, int(520 * Image.open(LOGO).height / Image.open(LOGO).width)))
            ghost = Image.new("RGB", lg.size, (255, 255, 255))
            mask = lg.point(lambda v: 26 if v < 200 else 0)
            bgimg.paste(ghost, (W - lg.width - 40, 40), mask)
    im = bgimg.copy()
    # تدرّج داكن من المنتصف للأسفل لقراءة العنوان
    grad = Image.new("L", (1, H))
    for y in range(H):
        grad.putpixel((0, y), int(max(0, (y - H * 0.30) / (H * 0.70)) ** 1.3 * 235))
    shade = Image.new("RGB", (W, H), (6, 10, 20))
    im.paste(shade, (0, 0), grad.resize((W, H)))
    d = _D.Draw(im)
    kw = {"direction": "rtl", "language": "ar"} if RAQM else {}
    # العنوان: حتى 3 أسطر، حجم متكيّف
    size = 58
    fb = _font(size)
    lines = _wrap(d, title, fb, W - 2 * P - 30)
    while len(lines) > 3 and size > 38:
        size -= 4
        fb = _font(size)
        lines = _wrap(d, title, fb, W - 2 * P - 30)
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] = lines[-1] + " …"
    lh = int(size * 1.55)
    foot_y = H - 70
    y0 = foot_y - 26 - lh * len(lines)
    # شارة عاجل/خبر فوق العنوان
    tag = "عاجل" if breaking else "خبر"
    ft = _font(34)
    tw = d.textlength(_shape(tag), font=ft, **kw)
    ty = y0 - 64
    d.rectangle([W - P - tw - 36, ty, W - P, ty + 50], fill=red if breaking else navy)
    if not breaking:
        d.rectangle([W - P - tw - 36, ty + 46, W - P, ty + 50], fill=gold)
    _draw_rtl(d, W - P - 18, ty + 2, tag, ft, (255, 255, 255))
    # شريط أحمر جانبي بطول العنوان
    d.rectangle([W - P + 14, y0 + 6, W - P + 22, y0 + lh * len(lines) - 10], fill=red)
    for i, ln in enumerate(lines):
        _draw_rtl(d, W - P - 6, y0 + i * lh, ln, fb, (255, 255, 255))
    # التذييل: خط رفيع + الوقت والقناة يميناً + الشعار يساراً
    d.rectangle([P, foot_y, W - P, foot_y + 2], fill=(255, 255, 255))
    fs = _font(26)
    meta = (time_str + " بتوقيت بغداد" if time_str else "")
    if meta:
        _draw_rtl(d, W - P, foot_y + 16, meta, fs, (225, 230, 240))
    d.text((P, foot_y + 18), handle, font=_font(24), fill=(200, 210, 225))
    if LOGO.exists():
        lg = Image.open(LOGO).convert("RGB")
        lw = 118
        lg = lg.resize((lw, int(lg.height * lw / lg.width)), Image.LANCZOS)
        pad = 8
        badge = Image.new("RGB", (lw + 2 * pad, lg.height + 2 * pad), (255, 255, 255))
        badge.paste(lg, (pad, pad))
        bm = Image.new("L", badge.size, 0)
        _D.Draw(bm).rounded_rectangle([0, 0, badge.width - 1, badge.height - 1], radius=12, fill=255)
        im.paste(badge, (P - 24, 28), bm)  # الشعار أعلى اليسار، بعيداً عن العنوان
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return buf.getvalue()


AR_DAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
AR_MONTHS = ["كانون الثاني", "شباط", "آذار", "نيسان", "أيار", "حزيران", "تموز", "آب", "أيلول", "تشرين الأول", "تشرين الثاني", "كانون الأول"]


def news_card2(photo_jpg, title, breaking=True, when_utc=None, handle="t.me/akamedia_iq"):
    """القالب الفاخر 1280×720: صورة كاملة + لوح زجاجي ضبابي أسفل + خط أحمر-ذهبي + شارة عاجل/خبر + شريحة التاريخ والوقت + الشعار."""
    from datetime import datetime, timedelta
    from PIL import ImageDraw as _D, ImageFilter, ImageEnhance
    W, H, P = 1280, 720, 60
    red, red2, gold, navy = (210, 20, 40), (150, 8, 24), (232, 182, 64), (9, 20, 44)
    kw = {"direction": "rtl", "language": "ar"} if RAQM else {}
    if photo_jpg:
        base = _cover(Image.open(io.BytesIO(photo_jpg)).convert("RGB"), W, H)
        base = ImageEnhance.Contrast(base).enhance(1.06)
    else:
        base = Image.new("RGB", (W, H), navy)
        px = base.load()
        for y in range(H):
            for x in range(0, W, 2):
                dx, dy = (x - W * 0.82) / W, (y - H * 0.15) / H
                g = max(0.0, 1 - (dx * dx + dy * dy) ** 0.5 * 1.6)
                c = (int(9 + 120 * g * 0.55), int(20 + 10 * g), int(44 + 20 * g))
                px[x, y] = c
                if x + 1 < W:
                    px[x + 1, y] = c
        d0 = _D.Draw(base)
        for i, x in enumerate(range(-H, W, 90)):
            d0.line([(x, H), (x + H, 0)], fill=(70, 90, 140) if i % 4 == 0 else (24, 38, 72), width=1)
        if LOGO.exists():
            lgi = Image.open(LOGO)
            lg = lgi.convert("L").resize((560, int(560 * lgi.height / lgi.width)))
            base.paste(Image.new("RGB", lg.size, (255, 255, 255)), (W - lg.width - 30, 10), lg.point(lambda v: 22 if v < 200 else 0))
    im = base.copy()
    # لوح زجاجي: ضبابية + تعتيم للجزء السفلي
    top = int(H * 0.52)
    glass = im.crop((0, top, W, H)).filter(ImageFilter.GaussianBlur(22))
    glass = Image.blend(glass, Image.new("RGB", glass.size, (6, 12, 28)), 0.62)
    im.paste(glass, (0, top))
    # تدرّج انتقالي فوق اللوح
    fade = Image.new("L", (1, 90))
    for y in range(90):
        fade.putpixel((0, y), int(150 * (y / 90) ** 1.6))
    im.paste(Image.new("RGB", (W, 90), (6, 12, 28)), (0, top - 90), fade.resize((W, 90)))
    d = _D.Draw(im)
    # خط أحمر→ذهبي أعلى اللوح
    for x in range(W):
        k = x / W
        d.line([(x, top), (x, top + 5)], fill=(int(gold[0] * (1 - k) + red[0] * k), int(gold[1] * (1 - k) + red[1] * k), int(gold[2] * (1 - k) + red[2] * k)))
    # شارة عاجل / خبر (يمين، تتقاطع مع الخط)
    tag = "عاجل" if breaking else "خبر"
    ft = _font(36)
    tw = d.textlength(_shape(tag), font=ft, **kw)
    bx1, by0 = W - P, top - 30
    bx0 = bx1 - tw - 74
    d.rounded_rectangle([bx0, by0, bx1, by0 + 60], radius=10, fill=red if breaking else navy, outline=None if breaking else gold, width=0 if breaking else 3)
    d.ellipse([bx1 - 30, by0 + 23, bx1 - 16, by0 + 37], fill=(255, 255, 255) if breaking else gold)
    _draw_rtl(d, bx1 - 42, by0 + 6, tag, ft, (255, 255, 255))
    # العنوان
    size = 56
    fb = _font(size)
    lines = _wrap(d, title, fb, W - 2 * P)
    while len(lines) > 3 and size > 38:
        size -= 3
        fb = _font(size)
        lines = _wrap(d, title, fb, W - 2 * P)
    if len(lines) > 3:
        lines = lines[:3]
        lines[-1] += " …"
    lh = int(size * 1.5)
    bottom_bar = 58
    avail = H - bottom_bar - (top + 46)
    y = top + 46 + max(0, (avail - lh * len(lines)) // 2) - 6
    for ln in lines:
        _draw_rtl(d, W - P, y + 2, ln, fb, (0, 0, 0))  # ظل خفيف
        _draw_rtl(d, W - P - 1, y, ln, fb, (255, 255, 255))
        y += lh
    # الشريط السفلي
    d.rectangle([0, H - bottom_bar, W, H], fill=(4, 8, 20))
    d.rectangle([0, H - bottom_bar, W, H - bottom_bar + 2], fill=red2)
    fs = _font(24)
    _draw_rtl(d, W - P, H - bottom_bar + 13, "أكا ميديا — نرى أبعد... ونروي أعمق", fs, (230, 232, 240))
    d.text((P, H - bottom_bar + 15), handle, font=_font(22), fill=gold)
    # شريحة التاريخ والوقت (أعلى اليمين) + الشعار (أعلى اليسار)
    if when_utc:
        try:
            t = datetime.fromisoformat(when_utc.replace("Z", "+00:00")) + timedelta(hours=3)
            chip = f"{AR_DAYS[t.weekday()]} {t.day} {AR_MONTHS[t.month - 1]} · {t.strftime('%H:%M')}"
            fc = _font(24)
            cw = d.textlength(_shape(chip), font=fc, **kw)
            cbox = Image.new("RGBA", (int(cw) + 40, 48), (6, 12, 28, 170))
            im.paste(cbox.convert("RGB"), (W - P - int(cw) - 40, 30), cbox.split()[3])
            d = _D.Draw(im)
            d.rectangle([W - P - 4, 30, W - P, 78], fill=red)
            _draw_rtl(d, W - P - 18, 38, chip, fc, (255, 255, 255))
        except Exception:  # noqa: BLE001
            pass
    if LOGO.exists():
        lg = Image.open(LOGO).convert("RGB")
        lw = 120
        lg = lg.resize((lw, int(lg.height * lw / lg.width)), Image.LANCZOS)
        pad = 8
        badge = Image.new("RGB", (lw + 2 * pad, lg.height + 2 * pad), (255, 255, 255))
        badge.paste(lg, (pad, pad))
        bm = Image.new("L", badge.size, 0)
        _D.Draw(bm).rounded_rectangle([0, 0, badge.width - 1, badge.height - 1], radius=14, fill=255)
        im.paste(badge, (P - 20, 26), bm)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


# ───────────────────────── هوية «أكا ميديا» v3 ─────────────────────────
# مستخرجة من الشعار: أحمر الإشارة + كحلي، أشعة «وصل» الثلاث، خط Alexandria الهندسي المطابق لحروف الشعار.
FONTS_DIR = ROOT / "assets" / "fonts"
BRAND_RED, BRAND_NAVY, INK, PAPER, MUTED = (227, 6, 19), (13, 35, 71), (13, 27, 52), (255, 255, 255), (112, 122, 140)


def _ff(name, size):
    p = FONTS_DIR / name
    try:
        return ImageFont.truetype(str(p), size)
    except Exception:  # noqa: BLE001
        return _font(size)


def _rays(d, x, y, s, fill, width=None, dot=False):
    """نقطة «وصل» وأشعتها الثلاث (لأعلى-يمين كما في الشعار). (x, y) مركز النقطة، s الحجم."""
    import math
    w = width or max(3, int(s * 0.14))
    if dot:
        r = s * 0.22
        d.ellipse([x - r, y - r, x + r, y + r], fill=fill)
    for ang, ln in ((-78, 0.62), (-42, 0.72), (-8, 0.56)):
        a = math.radians(ang)
        r0 = s * 0.42
        x0, y0 = x + math.cos(a) * r0, y + math.sin(a) * r0
        x1, y1 = x + math.cos(a) * (r0 + s * ln), y + math.sin(a) * (r0 + s * ln)
        d.line([(x0, y0), (x1, y1)], fill=fill, width=w)
        for (cx, cy) in ((x0, y0), (x1, y1)):
            d.ellipse([cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2], fill=fill)


def news_card3(photo_jpg, title, breaking=True, when_utc=None, handle="t.me/akamedia_iq", source=None, dim=False):
    """بطاقة الهوية v3 (1280×720): صورة الخبر أعلى، لوح أبيض تحريري أسفل بعنوان كحلي، شارة عاجل حمراء بأشعة الإشارة،
    وتذييل: الشعار الأصلي (خلفيته بيضاء فيندمج) + التاريخ والوقت بتوقيت بغداد + رابط القناة."""
    from datetime import datetime, timedelta
    from PIL import ImageDraw as _D, ImageEnhance
    W, H, P = 1280, 720, 64
    split = 372
    kw = {"direction": "rtl", "language": "ar"} if RAQM else {}
    im = Image.new("RGB", (W, H), PAPER)
    # ── الصورة
    if photo_jpg:
        ph = _cover(Image.open(io.BytesIO(photo_jpg)).convert("RGB"), W, split)
        ph = ImageEnhance.Contrast(ImageEnhance.Color(ph).enhance(0.92)).enhance(1.05)
        # تظليل كحلي خفيف أسفل الصورة للعمق
        sh = Image.new("L", (1, split))
        for y in range(split):
            k = max(0.0, (y - split * 0.45) / (split * 0.55))
            sh.putpixel((0, y), int(150 * k ** 1.8))
        ph.paste(Image.new("RGB", (W, split), BRAND_NAVY), (0, 0), sh.resize((W, split)))
    else:
        ph = Image.new("RGB", (W, split), BRAND_NAVY)
        d0 = _D.Draw(ph)
        for i in range(9):  # حلقات إشارة باهتة
            r = 90 + i * 70
            d0.ellipse([W * 0.2 - r, split * 0.62 - r, W * 0.2 + r, split * 0.62 + r], outline=(22, 48, 92), width=2)
        _rays(d0, W * 0.2, split * 0.62, 110, BRAND_RED, dot=True)
    im.paste(ph, (0, 0))
    d = _D.Draw(im)
    # ── خط الإشارة: أحمر عريض يمين، يتحول لخط رفيع
    d.rectangle([0, split, W, split + (5 if breaking else 3)], fill=BRAND_RED if breaking else BRAND_NAVY)
    # ── الشارة (عاجل / خبر)
    tag = "عاجل" if breaking else "خبر"
    ft = _ff("Alexandria-Black.ttf", 34)
    tw = d.textlength(_shape(tag), font=ft, **kw)
    bh = 62
    bx1 = W - P
    bx0 = int(bx1 - tw - 38 - (52 if breaking else 0))
    by0 = split - bh // 2 - 14
    d.rectangle([bx0, by0, bx1, by0 + bh], fill=((92, 8, 16) if dim else BRAND_RED) if breaking else BRAND_NAVY)
    if not breaking:
        d.rectangle([bx0, by0 + bh - 5, bx1, by0 + bh], fill=BRAND_RED)
    _draw_rtl(d, bx1 - 19, by0 + 7, tag, ft, (255, 150, 155) if dim else PAPER)
    if breaking and not dim:
        _rays(d, bx0 + 20, by0 + bh * 0.66, 30, PAPER, width=4, dot=True)
    elif breaking:  # في الوميض المطفأ تبقى النقطة فقط (الإشارة «تنبض»)
        d.ellipse([bx0 + 14, by0 + bh * 0.66 - 6, bx0 + 26, by0 + bh * 0.66 + 6], fill=(255, 150, 155))
    # ── العنوان
    foot = 78
    top_t = split + 62
    avail_h = H - foot - top_t - 6
    size = 64
    while True:
        fb = _ff("Alexandria-Bold.ttf", size)
        lines = _wrap(d, title, fb, W - 2 * P)
        lh = int(size * 1.42)
        if (len(lines) * lh <= avail_h and len(lines) <= (2 if size > 54 else 3)) or size <= 34:
            break
        size -= 2
    # لا نترك كلمة يتيمة في السطر الأخير إذا كان تصغير بسيط يجمع العنوان بسطور أقل
    if len(lines) > 1 and len(lines[-1].split()) <= 1:
        for s2 in range(size - 2, 45, -2):
            f2 = _ff("Alexandria-Bold.ttf", s2)
            l2 = _wrap(d, title, f2, W - 2 * P)
            if len(l2) < len(lines):
                size, fb, lines, lh = s2, f2, l2, int(s2 * 1.42)
                break
    if len(lines) * lh > avail_h:
        keep = max(1, avail_h // lh)
        lines = lines[:keep]
        lines[-1] = lines[-1].rstrip("،.") + " …"
    y = top_t + max(0, (avail_h - len(lines) * lh) // 2) - int(size * 0.18)
    for ln in lines:
        _draw_rtl(d, W - P, y, ln, fb, INK)
        y += lh
    # ── التذييل
    fy = H - foot
    d.line([(P, fy), (W - P, fy)], fill=(228, 231, 237), width=2)
    meta = []
    if when_utc:
        try:
            t = datetime.fromisoformat(when_utc.replace("Z", "+00:00")) + timedelta(hours=3)
            meta.append(f"{AR_DAYS[t.weekday()]} {t.day} {AR_MONTHS[t.month - 1]} · {t.strftime('%H:%M')} بغداد")
        except Exception:  # noqa: BLE001
            pass
    fm = _ff("ReadexPro-Medium.ttf", 23)
    xr = W - P
    d.rectangle([xr - 6, fy + 26, xr, fy + 52], fill=BRAND_RED)
    if meta:
        _draw_rtl(d, xr - 18, fy + 22, meta[0], fm, MUTED)
    if LOGO.exists():
        lg = Image.open(LOGO).convert("RGB")
        lh_ = 62
        lg = lg.resize((int(lg.width * lh_ / lg.height), lh_), Image.LANCZOS)
        im.paste(lg, (P - 6, fy + 8))
        d.text((P - 6 + lg.width + 18, fy + 25), handle, font=_ff("ReadexPro-Medium.ttf", 21), fill=BRAND_NAVY)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92, subsampling=0)
    return buf.getvalue()


SHOW_SOURCE = False  # إيهاب 06/11: لا نذكر اسم المصدر في الخبر ولا على البطاقة


def breaking_anim(photo_jpg, title, when_utc=None, style="v3", source=None):
    source = source if SHOW_SOURCE else None
    """بطاقة عاجل متحركة (MP4 صامت يتكرر تلقائياً في تلغرام): شارة «عاجل» تومض وأشعة الإشارة تنبض. ~2 ثانية."""
    import os
    import subprocess
    import tempfile
    import imageio_ffmpeg
    fn = {"a": card_a, "b": card_b, "c": card_c, "lux": globals().get("card_lux"), "news": globals().get("card_news"), "news2": globals().get("card_news2"),
          "news4A": lambda p, t, b, w: globals()["card_news4"](p, t, b, w, source=source, style="A")}.get(style)
    if fn:
        a = Image.open(io.BytesIO(fn(photo_jpg, title, True, when_utc)))
        _DIM[0] = True
        try:
            b = Image.open(io.BytesIO(fn(photo_jpg, title, True, when_utc)))
        finally:
            _DIM[0] = False
    else:
        a = Image.open(io.BytesIO(news_card3(photo_jpg, title, True, when_utc)))
        b = Image.open(io.BytesIO(news_card3(photo_jpg, title, True, when_utc, dim=True)))
    fps, n = 12, 24
    # منحنى الوميض: مضيء 0.6ث، انطفاء سريع، مطفأ 0.35ث، رجوع سريع
    curve = [0, 0, 0, 0, 0, 0, 0, 0.5, 1, 1, 1, 1, 0.5, 0, 0, 0, 0, 0, 0, 0, 0.5, 1, 1, 0.5]
    with tempfile.TemporaryDirectory() as td:
        for i, k in enumerate(curve[:n]):
            Image.blend(a, b, k).save(os.path.join(td, f"f{i:03d}.png"))
        out = os.path.join(td, "a.mp4")
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-framerate", str(fps), "-i", os.path.join(td, "f%03d.png"),
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", out],
                       check=True, timeout=60)
        return open(out, "rb").read()


# ───────────────────── v4: ثلاثة اتجاهات بعنوان مسيطر ─────────────────────
_DIM = [False]


def split_kicker(title):
    """«الجهة: الخبر» ← (الجهة، الخبر). الجهة تظهر سطراً أحمر صغيراً فوق العنوان الكبير."""
    m = re.match(r"^\s*([^:«»]{3,34}?)\s*:\s*(.{12,})$", title or "")
    if m and len(m.group(1).split()) <= 5:
        return m.group(1).strip(), m.group(2).strip()
    return None, (title or "").strip()


def _fit(d, text, font_name, width, max_lines, sizes, max_h=None, lh_k=1.38):
    for sz in sizes:
        f = _ff(font_name, sz)
        lines = _wrap(d, text, f, width)
        if len(lines) <= max_lines and (max_h is None or len(lines) * int(sz * lh_k) <= max_h):
            return f, sz, lines
    f = _ff(font_name, sizes[-1])
    lines = _wrap(d, text, f, width)[:max_lines]
    lines[-1] = lines[-1].rstrip("،.") + " …"
    return f, sizes[-1], lines


def _when(when_utc):
    from datetime import datetime, timedelta
    try:
        t = datetime.fromisoformat(when_utc.replace("Z", "+00:00")) + timedelta(hours=3)
        return f"{t.strftime('%H:%M')} بغداد · {t.day} {AR_MONTHS[t.month - 1]}"
    except Exception:  # noqa: BLE001
        return ""


def _tag(d, x_right, y, breaking, size=34):
    """شارة عاجل/خبر بنقطة وأشعة الشعار. ترجع (x0, x1)."""
    tag = "عاجل" if breaking else "خبر"
    ft = _ff("Alexandria-Black.ttf", size)
    kw = {"direction": "rtl", "language": "ar"} if RAQM else {}
    tw = d.textlength(_shape(tag), font=ft, **kw)
    h = int(size * 1.75)
    x0 = int(x_right - tw - 34 - (46 if breaking else 0))
    dim = breaking and _DIM[0]
    d.rectangle([x0, y, x_right, y + h], fill=((92, 8, 16) if dim else BRAND_RED) if breaking else PAPER)
    _draw_rtl(d, x_right - 17, y + int(h * 0.1), tag, ft, ((255, 150, 155) if dim else PAPER) if breaking else BRAND_NAVY)
    if breaking and not dim:
        _rays(d, x0 + 20, y + h * 0.64, 26, PAPER, width=4, dot=True)
    elif breaking:
        d.ellipse([x0 + 14, y + h * 0.64 - 6, x0 + 26, y + h * 0.64 + 6], fill=(255, 150, 155))
    return x0, x_right


def _logo(im, x, y, h):
    if LOGO.exists():
        lg = Image.open(LOGO).convert("RGB")
        lg = lg.resize((int(lg.width * h / lg.height), h), Image.LANCZOS)
        pad = 10
        badge = Image.new("RGB", (lg.width + 2 * pad, h + 2 * pad), PAPER)
        badge.paste(lg, (pad, pad))
        im.paste(badge, (x, y))
        return badge.width
    return 0


def _photo_or_brand(photo_jpg, W, H):
    from PIL import ImageDraw as _D, ImageEnhance
    if photo_jpg:
        ph = _cover(Image.open(io.BytesIO(photo_jpg)).convert("RGB"), W, H)
        return ImageEnhance.Contrast(ph).enhance(1.05), True
    ph = Image.new("RGB", (W, H), BRAND_NAVY)
    d0 = _D.Draw(ph)
    for i, x in enumerate(range(-H, W + H, 46)):  # خطوط مائلة رفيعة جداً
        d0.line([(x, H), (x + H, 0)], fill=(18, 42, 82), width=2)
    _rays(d0, W * 0.16, H * 0.62, min(W, H) * 0.42, (30, 58, 104), width=int(min(W, H) * 0.05), dot=True)
    return ph, False


def card_a(photo_jpg, title, breaking=True, when_utc=None):
    """A — بث تلفزيوني: صورة كاملة، تدرّج كحلي عميق، عنوان أبيض ضخم، شارة عاجل، الشعار أعلى اليسار."""
    from PIL import ImageDraw as _D
    W, H, P = 1280, 720, 64
    im, has = _photo_or_brand(photo_jpg, W, H)
    g = Image.new("L", (1, H))
    for y in range(H):
        k = max(0.0, (y - H * 0.22) / (H * 0.78))
        g.putpixel((0, y), int(250 * min(1, k ** 1.15)))
    im.paste(Image.new("RGB", (W, H), (6, 16, 36)), (0, 0), g.resize((W, H)))
    top = Image.new("L", (1, 130))
    for y in range(130):
        top.putpixel((0, y), int(150 * (1 - y / 130) ** 1.5))
    im.paste(Image.new("RGB", (W, 130), (6, 16, 36)), (0, 0), top.resize((W, 130)))
    d = _D.Draw(im)
    kick, head = split_kicker(title)
    f, sz, lines = _fit(d, head, "Alexandria-Black.ttf", W - 2 * P, 3, [92, 86, 80, 74, 68, 62, 56], max_h=420)
    lh = int(sz * 1.38)
    y = H - 54 - lh * len(lines)
    if kick:
        y -= 60
        _draw_rtl(d, W - P, y, kick, _ff("Alexandria-Bold.ttf", 40), (255, 96, 104))
        tag_y = y - 82
        y += 60
    else:
        tag_y = y - 84
    _tag(d, W - P, tag_y, breaking)
    for ln in lines:
        _draw_rtl(d, W - P, y, ln, f, PAPER)
        y += lh
    d.rectangle([0, H - 10, W, H], fill=BRAND_RED)
    _logo(im, P - 24, 30, 64)
    w = _when(when_utc)
    if w:
        _draw_rtl(d, W - P, 40, w, _ff("ReadexPro-Medium.ttf", 26), (235, 238, 245))
    return _jpg(im)


def card_b(photo_jpg, title, breaking=True, when_utc=None):
    """B — تقسيم جريء: لوح كحلي يمين بعنوان أبيض ضخم، الصورة يسار بكامل الارتفاع، فاصل أحمر عمودي."""
    from PIL import ImageDraw as _D
    W, H, P = 1280, 720, 58
    split = 560
    im = Image.new("RGB", (W, H), BRAND_NAVY)
    ph, has = _photo_or_brand(photo_jpg, split, H)
    im.paste(ph, (0, 0))
    d = _D.Draw(im)
    d.rectangle([split, 0, split + 10, H], fill=BRAND_RED)
    x_r, x_l = W - P, split + 10 + P
    kick, head = split_kicker(title)
    f, sz, lines = _fit(d, head, "Alexandria-Black.ttf", x_r - x_l, 4, [72, 66, 60, 56, 52, 48, 44],
                        max_h=H - 150 - 110 - (70 if kick else 0), lh_k=1.4)
    lh = int(sz * 1.4)
    block = lh * len(lines) + (70 if kick else 0)
    y = 140 + max(0, (H - 140 - 110 - block) // 2)
    _tag(d, x_r, 52, breaking, size=30)
    if kick:
        _draw_rtl(d, x_r, y, kick, _ff("Alexandria-Bold.ttf", 38), (255, 92, 100))
        y += 70
    for ln in lines:
        _draw_rtl(d, x_r, y, ln, f, PAPER)
        y += lh
    fy = H - 92
    lw = _logo(im, x_l - 10, fy, 56)
    w = _when(when_utc)
    if w:
        _draw_rtl(d, x_r, fy + 22, w, _ff("ReadexPro-Medium.ttf", 24), (160, 176, 205))
    return _jpg(im)


def card_c(photo_jpg, title, breaking=True, when_utc=None):
    """C — تحريري أبيض: صورة أعلى، الجهة بالأحمر، عنوان كحلي ضخم، تذييل نظيف بالشعار."""
    from PIL import ImageDraw as _D
    W, H, P = 1280, 720, 64
    top = 300
    im = Image.new("RGB", (W, H), PAPER)
    ph, has = _photo_or_brand(photo_jpg, W, top)
    im.paste(ph, (0, 0))
    d = _D.Draw(im)
    d.rectangle([0, top, W, top + 8], fill=BRAND_RED if breaking else BRAND_NAVY)
    _tag(d, W - P, top - 40, breaking, size=32)
    kick, head = split_kicker(title)
    avail = H - top - 8 - 96
    f, sz, lines = _fit(d, head, "Alexandria-Black.ttf", W - 2 * P, 3 if not kick else 2, [76, 70, 64, 58, 54, 50, 46],
                        max_h=avail - 40 - (56 if kick else 0), lh_k=1.36)
    lh = int(sz * 1.36)
    block = lh * len(lines) + (56 if kick else 0)
    y = top + 8 + max(28, (avail - block) // 2)
    if kick:
        _draw_rtl(d, W - P, y, kick, _ff("Alexandria-Bold.ttf", 36), BRAND_RED)
        y += 56
    for ln in lines:
        _draw_rtl(d, W - P, y, ln, f, INK)
        y += lh
    fy = H - 84
    d.line([(P, fy), (W - P, fy)], fill=(230, 233, 238), width=2)
    if LOGO.exists():
        lg = Image.open(LOGO).convert("RGB")
        lg = lg.resize((int(lg.width * 60 / lg.height), 60), Image.LANCZOS)
        im.paste(lg, (P - 6, fy + 12))
    w = _when(when_utc)
    if w:
        _draw_rtl(d, W - P, fy + 26, w, _ff("ReadexPro-Medium.ttf", 24), MUTED)
    return _jpg(im)


def _jpg(im):
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92, subsampling=0)
    return buf.getvalue()


def card_lux(photo_jpg, title, breaking=True, when_utc=None):
    """«أ» الفاخر: معالجة لونية سينمائية للصورة + زجاج مُغبّش خلف العنوان + خط أحمر عمودي + شارة دقيقة + حبيبات خفيفة.
    العنوان أبيض ضخم بخط Alexandria، والجهة فوقه بالأحمر الفاتح، والشعار في كبسولة بيضاء أسفل اليسار."""
    from PIL import ImageDraw as _D, ImageFilter, ImageEnhance, ImageOps
    W, H, P = 1280, 720, 70
    if photo_jpg:
        src = Image.open(io.BytesIO(photo_jpg)).convert("RGB")
        mx, my = int(src.width * 0.03), int(src.height * 0.03)  # كثير من صور المواقع بإطار/شريط ملون على الحافة
        src = src.crop((mx, my, src.width - mx, src.height - my))
        ph = _cover(src, W, H)
        ph = ImageEnhance.Contrast(ImageEnhance.Color(ph).enhance(0.82)).enhance(1.08)
        g = ImageOps.grayscale(ph)
        duo = ImageOps.colorize(g, black=(4, 14, 34), white=(246, 240, 232), mid=(96, 104, 120))
        im = Image.blend(ph, duo, 0.38)
    else:
        im, _ = _photo_or_brand(None, W, H)
    vig = Image.new("L", (W, H), 0)
    dv = _D.Draw(vig)
    for i in range(18):
        dv.rectangle([i * 9, i * 6, W - i * 9, H - i * 6], outline=int(120 - i * 6.5), width=9)
    im.paste(Image.new("RGB", (W, H), (2, 8, 20)), (0, 0), vig.filter(ImageFilter.GaussianBlur(40)))
    d = _D.Draw(im)
    kick, head = split_kicker(title)
    f, sz, lines = _fit(d, head, "Alexandria-Black.ttf", W - 2 * P - 26, 3, [80, 74, 68, 62, 58, 54, 50], max_h=330, lh_k=1.32)
    if len(lines) > 1 and len(lines[-1].split()) <= 1:  # لا كلمة يتيمة بالسطر الأخير
        for s2 in range(sz - 2, 46, -2):
            f2 = _ff("Alexandria-Black.ttf", s2)
            l2 = _wrap(d, head, f2, W - 2 * P - 26)
            if len(l2) < len(lines) or (len(l2) == len(lines) and len(l2[-1].split()) > 1):
                f, sz, lines = f2, s2, l2
                break
    lh = int(sz * 1.32)
    block_h = lh * len(lines) + (58 if kick else 0)
    bottom = H - 112  # مساحة محجوزة لسطر الشعار تحت العنوان
    top = bottom - block_h - 40
    glass = im.crop((0, top, W, H)).filter(ImageFilter.GaussianBlur(28))
    glass = Image.blend(glass, Image.new("RGB", glass.size, (5, 14, 34)), 0.64)
    ext = 170  # تدرّج طويل ناعم فوق الزجاج بلا حافة ظاهرة
    top2 = max(0, top - ext)
    glass = im.crop((0, top2, W, H)).filter(ImageFilter.GaussianBlur(28))
    glass = Image.blend(glass, Image.new("RGB", glass.size, (5, 14, 34)), 0.64)
    fade = Image.new("L", (1, H - top2))
    for y in range(H - top2):
        k = min(1.0, y / max(1, (top - top2) + 30))
        fade.putpixel((0, y), int(255 * (k * k * (3 - 2 * k))))
    im.paste(glass, (0, top2), fade.resize((W, H - top2)))
    d = _D.Draw(im)
    y = top + 34
    d.rectangle([W - P + 14, y + 6, W - P + 22, y + block_h - 10], fill=BRAND_RED)
    if kick:
        _draw_rtl(d, W - P - 12, y, kick, _ff("Alexandria-Bold.ttf", 38), (255, 120, 126))
        y += 58
    for ln in lines:
        _draw_rtl(d, W - P - 12, y, ln, f, PAPER)
        y += lh
    tag = "عاجل" if breaking else "خبر"
    ft = _ff("Alexandria-Black.ttf", 30)
    kw = {"direction": "rtl", "language": "ar"} if RAQM else {}
    tw = d.textlength(_shape(tag), font=ft, **kw)
    x1, y0 = W - P + 22, 44
    x0 = int(x1 - tw - 70)
    dim = breaking and _DIM[0]
    pill_col = ((140, 10, 22) if dim else BRAND_RED) if breaking else PAPER
    pm = Image.new("L", (x1 - x0, 54), 0)
    _D.Draw(pm).rounded_rectangle([0, 0, x1 - x0 - 1, 53], radius=27, fill=255)
    im.paste(Image.new("RGB", (x1 - x0, 54), pill_col), (x0, y0), pm)
    d = _D.Draw(im)
    dc = (255, 160, 165) if dim else (PAPER if breaking else BRAND_RED)
    d.ellipse([x0 + 20, y0 + 20, x0 + 34, y0 + 34], fill=dc)
    _draw_rtl(d, x1 - 22, y0 + 5, tag, ft, (255, 200, 204) if dim else (PAPER if breaking else BRAND_NAVY))
    w = _when(when_utc)
    if w:
        _draw_rtl(d, x0 - 18, y0 + 12, w, _ff("ReadexPro-Medium.ttf", 24), (232, 236, 244))
    if LOGO.exists():
        lg = Image.open(LOGO).convert("RGB")
        hh = 50
        lg = lg.resize((int(lg.width * hh / lg.height), hh), Image.LANCZOS)
        cap = Image.new("RGB", (lg.width + 28, hh + 16), PAPER)
        cap.paste(lg, (14, 8))
        cm = Image.new("L", cap.size, 0)
        _D.Draw(cm).rounded_rectangle([0, 0, cap.width - 1, cap.height - 1], radius=14, fill=255)
        cy = H - 34 - cap.height
        im.paste(cap, (W - P + 22 - cap.width, cy), cm)
        d = _D.Draw(im)
        d.line([(P, cy + cap.height // 2), (W - P + 22 - cap.width - 24, cy + cap.height // 2)], fill=(70, 84, 112), width=1)
        d.text((P, cy + 20), "t.me/akamedia_iq", font=_ff("ReadexPro-Medium.ttf", 22), fill=(200, 208, 224))
    noise = Image.effect_noise((W, H), 40).convert("L").point(lambda v: 7 if v > 175 else 0)  # ملمس خفيف جداً لا يُرى كنقاط
    im.paste(Image.new("RGB", (W, H), (255, 255, 255)), (0, 0), noise)
    return _jpg(im)


# ───────────────────── «نشرة»: أسلوب قنوات الأخبار الكبرى (شريط سفلي) ─────────────────────
NEWS_BLUE_A, NEWS_BLUE_B, NEWS_RED = (5, 22, 58), (10, 52, 118), (212, 17, 30)


def _cairo(size, weight=800):
    from PIL import ImageFont
    p = FONTS_DIR / "Cairo-VF.ttf"
    if not p.exists():
        return _ff("Alexandria-Black.ttf", size)
    f = ImageFont.truetype(str(p), size, layout_engine=ImageFont.Layout.RAQM if RAQM else ImageFont.Layout.BASIC)
    try:
        f.set_variation_by_axes([weight, 0])
    except Exception:  # noqa: BLE001
        pass
    return f


def _fit_cairo(d, text, width, max_lines, sizes, weight=800, lh_k=1.5):
    for sz in sizes:
        f = _cairo(sz, weight)
        lines = _wrap(d, text, f, width)
        if len(lines) <= max_lines and not (len(lines) > 1 and len(lines[-1].split()) <= 1 and sz > sizes[-1]):
            return f, sz, lines
    f = _cairo(sizes[-1], weight)
    lines = _wrap(d, text, f, width)[:max_lines]
    if len(_wrap(d, text, f, width)) > max_lines:
        lines[-1] = lines[-1].rstrip("،.") + " …"
    return f, sizes[-1], lines


def card_news(photo_jpg, title, breaking=True, when_utc=None):
    """«نشرة»: صورة كاملة واضحة + شريط سفلي أزرق عميق بعنوان أبيض كبير بخط Cairo (وضوح عالٍ على الهاتف)،
    لسان «عاجل» أحمر على حافة الشريط، وسطر الجهة فوق العنوان، والوقت والشعار في شريط سفلي رفيع."""
    from PIL import ImageDraw as _D, ImageFilter, ImageEnhance
    W, H, P = 1280, 720, 56
    if photo_jpg:
        src = Image.open(io.BytesIO(photo_jpg)).convert("RGB")
        mx, my = int(src.width * 0.03), int(src.height * 0.03)
        src = src.crop((mx, my, src.width - mx, src.height - my))
        im = ImageEnhance.Contrast(ImageEnhance.Color(_cover(src, W, H)).enhance(0.95)).enhance(1.06)
    else:
        im = Image.new("RGB", (W, H), NEWS_BLUE_A)
        d0 = _D.Draw(im)
        for y in range(H):  # تدرّج عمودي هادئ
            k = y / H
            d0.line([(0, y), (W, y)], fill=tuple(int(NEWS_BLUE_B[i] * (1 - k) + NEWS_BLUE_A[i] * k) for i in range(3)))
        for x in range(-H, W + H, 54):
            d0.line([(x, H), (x + H, 0)], fill=(14, 44, 96), width=2)
        if LOGO.exists():  # الشعار باهتاً كبيراً في الخلفية
            lg = Image.open(LOGO).convert("L")
            hh = 300
            lg = lg.resize((int(lg.width * hh / lg.height), hh), Image.LANCZOS)
            im.paste(Image.new("RGB", lg.size, (40, 80, 150)), (W // 2 - lg.width // 2, 70), lg.point(lambda v: 60 if v < 128 else 0))
    d = _D.Draw(im)
    kick, head = split_kicker(title)
    tw_max = W - 2 * P
    f, sz, lines = _fit_cairo(d, head, tw_max, 3, [62, 58, 54, 50, 46, 42])
    lh = int(sz * 1.5)
    foot = 54
    kick_h = 50 if kick else 0
    panel_h = 34 + kick_h + lh * len(lines) + 18 + foot
    top = H - panel_h
    # ظل ناعم فوق الشريط ليفصل الصورة
    sh = Image.new("L", (W, 120), 0)
    for y in range(120):
        _D.Draw(sh).line([(0, y), (W, y)], fill=int(150 * (y / 120) ** 2))
    im.paste(Image.new("RGB", (W, 120), (0, 6, 20)), (0, top - 120), sh)
    band = Image.new("RGB", (W, panel_h))
    db = _D.Draw(band)
    for x in range(W):  # تدرّج أفقي: أغمق يساراً
        k = x / W
        db.line([(x, 0), (x, panel_h)], fill=tuple(int(NEWS_BLUE_A[i] * (1 - k) + NEWS_BLUE_B[i] * k) for i in range(3)))
    db.rectangle([0, panel_h - foot, W, panel_h], fill=(3, 12, 34))
    im.paste(band, (0, top))
    d = _D.Draw(im)
    dim = breaking and _DIM[0]
    accent = ((120, 10, 20) if dim else NEWS_RED) if breaking else (64, 150, 255)
    d.rectangle([0, top, W, top + 5], fill=accent)
    # لسان «عاجل/خبر» على الحافة اليمنى للشريط
    tag = "عاجل" if breaking else "خبر"
    ft = _cairo(34, 900)
    kw = {"direction": "rtl", "language": "ar"} if RAQM else {}
    tw = d.textlength(_shape(tag), font=ft, **kw)
    tab_w, tab_h = int(tw + 64 + (30 if breaking else 0)), 60
    x0 = W - P - tab_w + 20
    d.rectangle([x0, top - tab_h, W - P + 20, top], fill=accent if breaking else PAPER)
    _draw_rtl(d, W - P - 6, top - tab_h + 2, tag, ft, ((255, 170, 175) if dim else PAPER) if breaking else NEWS_BLUE_A)
    if breaking:
        c = (255, 170, 175) if dim else PAPER
        d.ellipse([x0 + 18, top - tab_h / 2 - 8, x0 + 34, top - tab_h / 2 + 8], fill=c)
    y = top + 26
    if kick:
        _draw_rtl(d, W - P, y, kick, _cairo(34, 700), (255, 196, 92) if breaking else (150, 200, 255))
        y += kick_h
    for ln in lines:
        _draw_rtl(d, W - P, y, ln, f, PAPER)
        y += lh
    fy = H - foot
    w = _when(when_utc)
    if w:
        _draw_rtl(d, P + d.textlength(_shape(w), font=_cairo(24, 600), **kw), fy + 5, w, _cairo(24, 600), (190, 204, 228))
    if LOGO.exists():
        lg = Image.open(LOGO).convert("RGB")
        hh = 36
        lg = lg.resize((int(lg.width * hh / lg.height), hh), Image.LANCZOS)
        cap = Image.new("RGB", (lg.width + 20, hh + 10), PAPER)
        cap.paste(lg, (10, 5))
        im.paste(cap, (W - P - cap.width + 20, fy + (foot - cap.height) // 2))
        d = _D.Draw(im)
        hx = W - P - cap.width - 4
        _draw_rtl(d, hx, fy + 6, "t.me/akamedia_iq", _cairo(22, 600), (150, 166, 196))
    return _jpg(im)


# ───────────────────── «نشرة ٢»: شريط عنوان تلفزيوني كامل + شعار مفرّغ + معالجة الصور الصغيرة ─────────────────────
TAGS = {  # لون الشريط واسم الوسم لكل نوع منشور
    "عاجل": ((200, 16, 30), (255, 255, 255)),
    "خبر": ((14, 38, 84), (255, 255, 255)),
    "تحليل": ((176, 132, 46), (255, 255, 255)),
    "منوعات": ((0, 122, 120), (255, 255, 255)),
    "رأي": ((176, 132, 46), (255, 255, 255)),
    "تحديث": ((14, 38, 84), (255, 255, 255)),
}
_LOGO_W = {}


def _logo_white(h):
    """الشعار أبيض مفرّغ (بلا مربع أبيض) لوضعه على خلفية داكنة."""
    if h in _LOGO_W:
        return _LOGO_W[h]
    if not LOGO.exists():
        return None
    lg = Image.open(LOGO).convert("L")
    lg = lg.resize((int(lg.width * h / lg.height), h), Image.LANCZOS)
    alpha = lg.point(lambda v: 0 if v > 225 else min(255, int((235 - v) * 1.6)))
    w = Image.new("RGBA", lg.size, (255, 255, 255, 0))
    w.putalpha(alpha)
    _LOGO_W[h] = w
    return w


def _photo_frame(photo_jpg, W, H):
    """صورة واضحة: الصغيرة تُعرض بحجمها الطبيعي فوق نسخة مغبّشة منها (بدل تكبيرها حتى تتشوه)، مع حدّة خفيفة."""
    from PIL import ImageFilter, ImageEnhance, ImageDraw as _D
    src = Image.open(io.BytesIO(photo_jpg)).convert("RGB")
    mx, my = int(src.width * 0.025), int(src.height * 0.025)
    src = src.crop((mx, my, src.width - mx, src.height - my))
    if src.width >= W * 0.72:
        im = _cover(src, W, H)
        im = im.filter(ImageFilter.UnsharpMask(radius=1.4, percent=60, threshold=3))
        return ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(0.96)).enhance(1.05)
    bg = _cover(src, W, H).filter(ImageFilter.GaussianBlur(34))
    bg = ImageEnhance.Brightness(bg).enhance(0.55)
    k = min(H * 0.86 / src.height, W * 0.8 / src.width, 1.9)
    fg = src.resize((int(src.width * k), int(src.height * k)), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=1.2, percent=70, threshold=2))
    x, y = (W - fg.width) // 2, int(H * 0.05)
    sh = Image.new("L", (W, H), 0)
    _D.Draw(sh).rectangle([x + 10, y + 14, x + fg.width + 10, y + fg.height + 14], fill=150)
    bg.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), sh.filter(ImageFilter.GaussianBlur(18)))
    bg.paste(fg, (x, y))
    return bg


def card_news2(photo_jpg, title, breaking=True, when_utc=None, tag=None, stats=None):
    """«نشرة ٢»: صورة نظيفة + شعار أبيض مفرّغ أعلى الصورة، وتحتها شريط وسم ملوّن كامل العرض (عاجل/خبر/تحليل/منوعات)
    فيه الوقت، ثم لوح عنوان كحلي صلب بخط Cairo عريض. stats = [(قيمة، وصف)] تظهر صفاً تحت العنوان (لبطاقات التحليل)."""
    from PIL import ImageDraw as _D, ImageFilter
    W, H, P = 1280, 720, 58
    tag = tag or ("عاجل" if breaking else "خبر")
    col, fg_col = TAGS.get(tag, TAGS["خبر"])
    dim = tag == "عاجل" and _DIM[0]
    if dim:
        col = (110, 10, 18)
    if photo_jpg:
        im = _photo_frame(photo_jpg, W, H)
    else:
        im = Image.new("RGB", (W, H), (8, 22, 52))
        d0 = _D.Draw(im)
        for y in range(H):
            k = y / H
            d0.line([(0, y), (W, y)], fill=(int(16 - 8 * k), int(44 - 22 * k), int(98 - 46 * k)))
        lw = _logo_white(260)
        if lw:
            a = lw.split()[3].point(lambda v: int(v * 0.10))
            im.paste(Image.new("RGB", lw.size, (255, 255, 255)), (W // 2 - lw.width // 2, 60), a)
    d = _D.Draw(im)
    kick, head = split_kicker(title)
    f, sz, lines = _fit_cairo(d, head, W - 2 * P, 3, [60, 56, 52, 48, 44, 40])
    lh = int(sz * 1.48)
    bar_h = 58
    kick_h = 46 if kick else 0
    stats_h = 92 if stats else 0
    panel_h = 30 + kick_h + lh * len(lines) + 22 + stats_h
    top = H - panel_h
    btop = top - bar_h
    # ظل ناعم يفصل الصورة عن الشريط
    sh = Image.new("L", (W, 150), 0)
    ds = _D.Draw(sh)
    for y in range(150):
        ds.line([(0, y), (W, y)], fill=int(170 * (y / 150) ** 2.2))
    im.paste(Image.new("RGB", (W, 150), (0, 5, 16)), (0, btop - 150), sh)
    d = _D.Draw(im)
    # شعار القناة أعلى يمين الصورة: قرص أبيض بالشعار الحقيقي (الشعار لا يوضع مباشرة على صورة أو خلفية داكنة)
    _paste_badge(im, W - P - 110 + 18, 24, 110)
    d = _D.Draw(im)
    # شريط الوسم الكامل
    d.rectangle([0, btop, W, top], fill=col)
    ft = _cairo(32, 900)
    kw = {"direction": "rtl", "language": "ar"} if RAQM else {}
    _draw_rtl(d, W - P, btop + 4, tag, ft, (255, 175, 180) if dim else fg_col)
    tw = d.textlength(_shape(tag), font=ft, **kw)
    sx = W - P - tw - 24
    d.line([(sx, btop + 16), (sx, top - 16)], fill=(255, 255, 255) if not dim else (200, 120, 125), width=2)
    sub = {"عاجل": "أكا ميديا · أخبار العراق", "تحليل": "قراءة في أبرز حدث اليوم", "منوعات": "من العراق", "رأي": "قراءة أكا ميديا"}.get(tag, "أكا ميديا · أخبار العراق")
    _draw_rtl(d, sx - 20, btop + 12, sub, _cairo(24, 600), (255, 236, 238) if tag == "عاجل" else (230, 236, 248))
    w = _when(when_utc)
    if w:
        fw = _cairo(24, 700)
        _draw_rtl(d, P + d.textlength(_shape(w), font=fw, **kw), btop + 12, w, fw, fg_col)
    # لوح العنوان
    d.rectangle([0, top, W, H], fill=(9, 20, 46))
    d.rectangle([0, top, W, top + 3], fill=(255, 255, 255) if tag != "عاجل" else (255, 210, 214))
    y = top + 22
    if kick:
        _draw_rtl(d, W - P, y, kick, _cairo(32, 700), (130, 186, 255) if tag not in ("تحليل", "رأي") else (232, 196, 120))
        y += kick_h
    for ln in lines:
        _draw_rtl(d, W - P, y, ln, f, (255, 255, 255))
        y += lh
    if stats:
        y += 8
        n = len(stats)
        cw = (W - 2 * P) / n
        for i, (val, lab) in enumerate(stats):
            xr = W - P - i * cw
            if i:
                d.line([(xr + 14, y + 6), (xr + 14, y + 70)], fill=(60, 78, 112), width=2)
            _draw_rtl(d, xr, y - 4, str(val), _cairo(38, 800), (232, 196, 120))
            _draw_rtl(d, xr, y + 44, lab, _cairo(21, 600), (170, 184, 210))
    return _jpg(im)


_BADGE = {}


LOGO_RGBA = ROOT / "assets" / "brand" / "aka_logo.png"  # الشعار مفرّغ؛ «ميديا» رمادي داكن وداخله أبيض فيحتاج خلفية فاتحة دائماً


def _logo_badge(h):
    """شعار «أكا ميديا» الحقيقي داخل قرص أبيض نظيف بقطر h (حافة رمادية رفيعة جداً)، ليُقرأ على أي صورة أو خلفية داكنة.
    الظل يضيفه المستدعي عبر _paste_badge."""
    if h in _BADGE:
        return _BADGE[h]
    if not LOGO_RGBA.exists():
        return None
    from PIL import ImageDraw as _D
    S = 4  # رسم بدقة أعلى ثم تصغير لحواف ناعمة
    D = h * S
    b = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    d = _D.Draw(b)
    d.ellipse([0, 0, D - 1, D - 1], fill=(255, 255, 255, 255))
    d.ellipse([0, 0, D - 1, D - 1], outline=(214, 218, 224, 255), width=max(2, S))
    lg = Image.open(LOGO_RGBA).convert("RGBA")
    lh = int(D * 0.88)
    lg = lg.resize((int(lg.width * lh / lg.height), lh), Image.LANCZOS)
    b.alpha_composite(lg, ((D - lg.width) // 2 + int(D * 0.012), int(D * 0.052)))
    b = b.resize((h, h), Image.LANCZOS)
    _BADGE[h] = b
    return b


def _paste_badge(im, x, y, h, shadow=0.34):
    """يلصق قرص الشعار على im عند (x, y) أعلى اليسار، بظل ناعم خفيف تحته."""
    from PIL import ImageFilter
    b = _logo_badge(h)
    if not b:
        return 0
    m = max(12, h // 7)
    sm = Image.new("L", (b.width + 2 * m, b.height + 2 * m), 0)
    sm.paste(b.split()[3], (m, m))
    sm = sm.filter(ImageFilter.GaussianBlur(m * 0.55)).point(lambda v: int(v * shadow))
    im.paste(Image.new("RGB", sm.size, (0, 0, 0)), (x - m, y - m + max(3, h // 28)), sm)
    im.paste(b, (x, y), b)
    return b.width


def card_news3(photo_jpg, title, breaking=True, when_utc=None, tag=None, source=None):
    """«نشرة ٣» عمودي 4:5 (1080×1350) — يأخذ مساحة أكبر في شاشة الهاتف داخل تلغرام.
    صورة كاملة أعلى البطاقة تذوب في لوح حبر كحلي، لسان وسم مستدير على الحد، شريط لوني رفيع بجانب العنوان،
    عنوان Cairo عريض كبير حتى 4 أسطر، وتذييل هادئ فيه الجهة والوقت والمعرّف. بلا زخارف لا وظيفة لها."""
    from PIL import ImageDraw as _D, ImageFilter
    W, H, P = 1080, 1350, 64
    tag = tag or ("عاجل" if breaking else "خبر")
    col, fg_col = TAGS.get(tag, TAGS["خبر"])
    if tag in ("خبر", "تحديث"):
        col = (34, 92, 220)  # أزرق أوضح من الكحلي حتى لا يذوب اللسان في اللوح
    ink = (8, 17, 40)
    kw = {"direction": "rtl", "language": "ar"} if RAQM else {}
    tmp = _D.Draw(Image.new("RGB", (10, 10)))
    kick, head = split_kicker(title)
    f, sz, lines = _fit_cairo(tmp, head, W - 2 * P - 26, 4, [74, 68, 62, 58, 54, 50], weight=850, lh_k=1.42)
    lh = int(sz * 1.42)
    kick_h = 54 if kick else 0
    foot_h = 96
    panel_h = 98 + kick_h + lh * len(lines) + 40 + foot_h
    ph_h = H - panel_h + 70  # الصورة تمتد تحت أول اللوح ليذوب فيها
    im = Image.new("RGB", (W, H), ink)
    if photo_jpg:
        im.paste(_photo_frame(photo_jpg, W, ph_h), (0, 0))
    else:
        d0 = _D.Draw(im)
        for y in range(ph_h):
            k = y / ph_h
            d0.line([(0, y), (W, y)], fill=(int(18 - 8 * k), int(42 - 22 * k), int(92 - 46 * k)))
        lw = _logo_white(300)
        if lw:
            a = lw.split()[3].point(lambda v: int(v * 0.10))
            im.paste(Image.new("RGB", lw.size, (255, 255, 255)), (W // 2 - lw.width // 2, ph_h // 2 - 150), a)
    top = H - panel_h
    # ذوبان الصورة في اللوح + تعتيم خفيف أعلى الصورة لوضوح الشعار
    g = Image.new("L", (W, 260), 0)
    dg = _D.Draw(g)
    for y in range(260):
        dg.line([(0, y), (W, y)], fill=int(255 * (y / 260) ** 1.6))
    im.paste(Image.new("RGB", (W, 260), ink), (0, top - 190), g)
    im.paste(Image.new("RGB", (W, H - top - 70), ink), (0, top + 70))
    gt = Image.new("L", (W, 170), 0)
    dt = _D.Draw(gt)
    for y in range(170):
        dt.line([(0, y), (W, y)], fill=int(120 * (1 - y / 170) ** 1.8))
    im.paste(Image.new("RGB", (W, 170), (0, 0, 0)), (0, 0), gt)
    d = _D.Draw(im)
    _paste_badge(im, W - P - 140 + 18, 30, 140)
    d = _D.Draw(im)
    # لسان الوسم المستدير على حد اللوح
    ft = _cairo(36, 900)
    label = tag
    tw = d.textlength(_shape(label), font=ft, **kw)
    dot = 26 if tag == "عاجل" else 0
    pw, phh = int(tw + 56 + dot), 66
    px1, py0 = W - P, top + 6
    d.rounded_rectangle([px1 - pw, py0, px1, py0 + phh], radius=33, fill=col)
    if dot:
        cx, cy = px1 - 30, py0 + phh // 2
        d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(255, 255, 255))
    _draw_rtl(d, px1 - 28 - dot, py0 + 5, label, ft, fg_col)
    sub = {"عاجل": "الآن", "رأي": "قراءة أكا ميديا", "تحليل": "قراءة في حدث اليوم", "منوعات": "من العراق"}.get(tag)
    if sub:
        _draw_rtl(d, px1 - pw - 22, py0 + 14, sub, _cairo(28, 700), (205, 214, 232))
    y = py0 + phh + 26
    if kick:
        _draw_rtl(d, W - P, y, kick, _cairo(36, 750), (255, 196, 92) if tag in ("تحليل", "رأي") else (122, 178, 255))
        y += kick_h
    # الشريط اللوني الرفيع بجانب العنوان (بداية السطر العربي)
    d.rounded_rectangle([W - P + 18, y + 10, W - P + 26, y + lh * len(lines) - int(sz * 0.25)], radius=4, fill=col)
    for ln in lines:
        _draw_rtl(d, W - P - 10, y, ln, f, (255, 255, 255))
        y += lh
    # التذييل
    fy = H - foot_h + 18
    d.line([(P, fy - 14), (W - P, fy - 14)], fill=(38, 54, 88), width=2)
    fs = _cairo(27, 700)
    right = source if source and source != kick else "أكا ميديا"
    _draw_rtl(d, W - P, fy, right, fs, (196, 206, 226))
    ffl = _cairo(26, 600)
    hd = "@akamedia_iq"
    d.text((P, fy + 1), hd, font=ffl, fill=(140, 156, 188), **({"direction": "ltr"} if RAQM else {}))
    w = _when(when_utc)
    if w:
        xw = P + d.textlength(hd, font=ffl) + 22
        d.text((xw, fy + 1), "·", font=ffl, fill=(90, 106, 140))
        _draw_rtl(d, xw + 22 + d.textlength(_shape(w), font=ffl, **kw), fy + 1, w, ffl, (140, 156, 188))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90, optimize=True, progressive=True)
    return buf.getvalue()


def _fit_font(d, text, width, max_lines, sizes, loader):
    for sz in sizes:
        f = loader(sz)
        lines = _wrap(d, text, f, width)
        if len(lines) <= max_lines and not (len(lines) > 1 and len(lines[-1].split()) <= 1 and sz > sizes[-1]):
            return f, sz, lines
    f = loader(sizes[-1])
    lines = _wrap(d, text, f, width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip("،.") + " …"
    return f, sizes[-1], lines


def _grade(im, warm=True):
    """تدريج لوني خفيف موحّد لكل الصور: تباين أعلى قليلاً وتشبع أهدأ — يوحّد هوية البطاقات مهما اختلف مصدر الصورة."""
    from PIL import ImageEnhance
    im = ImageEnhance.Contrast(im).enhance(1.08)
    im = ImageEnhance.Color(im).enhance(0.9)
    return im


def _vgrad(W, H, stops):
    """قناع تدرّج عمودي: stops = [(موضع 0..1، شفافية 0..255)]."""
    m = Image.new("L", (1, H))
    px = m.load()
    for y in range(H):
        k = y / max(1, H - 1)
        for (a, va), (b, vb) in zip(stops, stops[1:]):
            if a <= k <= b:
                t = (k - a) / max(1e-6, b - a)
                t = t * t * (3 - 2 * t)
                px[0, y] = int(va + (vb - va) * t)
                break
    return m.resize((W, H))


def looks_like_logo(jpg):
    """صورة ليست صورة خبر: شعار موقع أو رسم بألوان مسطحة قليلة أو صورة صغيرة جداً — نستخدم خلفية الهوية بدلها."""
    try:
        im = Image.open(io.BytesIO(jpg)).convert("RGB")
    except Exception:  # noqa: BLE001
        return True
    if im.width < 300 or im.height < 200:
        return True
    q = im.resize((64, 64)).quantize(colors=32)
    counts = sorted((c for c, _ in q.getcolors(64 * 64) or []), reverse=True)
    return sum(counts[:3]) / (64 * 64) > 0.62


def card_news4(photo_jpg, title, breaking=True, when_utc=None, tag=None, source=None, style="A"):
    source = source if SHOW_SOURCE else None  # إيهاب 06/11: لا اسم للمصدر على البطاقة
    """ثلاث هويات للمعاينة (1080×1350):
    A «شاشة الحدث»: صورة كاملة سينمائية، العنوان أبيض كبير فوق تدرّج أسود، لسان أحمر حاد بأسلوب الشاشات الإخبارية.
    B «الصحيفة»: صورة أعلى وورق عاجي أسفل، عنوان أسود ثقيل وسطر أحمر — رصانة الصحافة الكبرى.
    C «البطاقة العائمة»: صورة كاملة وبطاقة بيضاء عائمة بحواف مستديرة، عنوان كحلي ولسان أحمر يتقاطع مع حافتها."""
    if style == "A" and tag in (None, "عاجل", "خبر"):  # v6: قالب حسب نوع الخبر (tools/aka_card.py) — القديم احتياطاً عند أي خطأ
        try:
            from tools import aka_card
            return aka_card.card(photo_jpg, title, breaking=breaking, when_utc=when_utc, source=source, dim=_DIM[0])
        except Exception as e:  # noqa: BLE001
            print("::warning title=aka_card::", type(e).__name__, str(e)[:120])
    from PIL import ImageDraw as _D, ImageFilter
    W, H = 1080, 1350
    tag = tag or ("عاجل" if breaking else "خبر")
    RED, NAVY = (222, 18, 30), (11, 27, 63)
    kw = {"direction": "rtl", "language": "ar"} if RAQM else {}
    tmp = _D.Draw(Image.new("RGB", (8, 8)))
    kick, head = split_kicker(title)
    w = _when(when_utc)
    src_name = source if source and source != kick else None
    im = Image.new("RGB", (W, H), NAVY)

    def photo(h):
        if photo_jpg and not looks_like_logo(photo_jpg):
            from PIL import ImageFilter as _F
            src = Image.open(io.BytesIO(photo_jpg)).convert("RGB")
            if src.width >= 460 and src.height >= 300:  # ملء الإطار بالكامل بدل صورة صغيرة داخل إطار مغبّش
                return _grade(_cover(src, W, h).filter(_F.UnsharpMask(radius=1.6, percent=55, threshold=3)))
            return _grade(_photo_frame(photo_jpg, W, h))
        g = Image.new("RGB", (W, h), NAVY)
        dd = _D.Draw(g)
        for y in range(h):
            k = y / h
            dd.line([(0, y), (W, y)], fill=(int(20 - 9 * k), int(46 - 19 * k), int(104 - 41 * k)))
        lw = _logo_white(320)
        if lw:
            a = lw.split()[3].point(lambda v: int(v * 0.09))
            g.paste(Image.new("RGB", lw.size, (255, 255, 255)), (W // 2 - lw.width // 2, max(40, h // 2 - 420)), a)
        return g

    def badge(x_right, y, h=164):
        _paste_badge(im, x_right - h, y, h)

    label = {"عاجل": "عاجل", "رأي": "قراءة أكا ميديا", "تحليل": "تحليل", "منوعات": "منوعات"}.get(tag, "خبر")
    hot = tag == "عاجل"

    if style == "A":
        P = 70
        wide = False
        try:  # صورة عريضة (اجتماع، مؤتمر): ملء الإطار كله يقص الناس من الجانبين — تُعرض بثلثي البطاقة العلوية وتذوب بالأسفل الداكن
            if photo_jpg and not looks_like_logo(photo_jpg):
                _s = Image.open(io.BytesIO(photo_jpg))
                wide = _s.width / max(1, _s.height) > 1.15
        except Exception:  # noqa: BLE001
            wide = False
        if wide:
            im.paste(Image.new("RGB", (W, H), (4, 8, 18)), (0, 0))
            ph_h = int(H * 0.70)
            fade = Image.linear_gradient("L").resize((W, ph_h))  # 0 أعلى ← 255 أسفل
            fade = fade.point(lambda v: 255 if v < 150 else int(255 * (255 - v) / 105))  # الثلث الأخير يذوب في الخلفية بلا حافة
            im.paste(photo(ph_h), (0, 0), fade)
        else:
            im.paste(photo(H), (0, 0))
        f, sz, lines = _fit_font(tmp, head, W - 2 * P, 4, [84, 78, 72, 66, 60, 56], lambda s: _cairo(s, 900))
        lh = int(sz * 1.36)
        block = lh * len(lines)
        y_text = H - 150 - block
        y_tag = y_text - (62 + 26) - (54 if kick else 0)
        shade = _vgrad(W, H, [(0, 90), (0.18, 0), (max(0.2, (y_tag - 260) / H), 0), ((y_tag + 40) / H, 215), (1, 250)])
        im.paste(Image.new("RGB", (W, H), (4, 8, 18)), (0, 0), shade)
        d = _D.Draw(im)
        badge(W - P + 10, 52)
        ft = _cairo(38, 900)
        tw = d.textlength(_shape(label), font=ft, **kw)
        bw = int(tw + 52)
        x1 = W - P
        dim = hot and _DIM[0]
        fill = ((96, 8, 16) if dim else RED) if hot else ((196, 150, 54) if tag in ("رأي", "تحليل") else (255, 255, 255))
        d.polygon([(x1 - bw - 18, y_tag + 62), (x1 - bw, y_tag), (x1, y_tag), (x1, y_tag + 62)], fill=fill)
        _draw_rtl(d, x1 - 26, y_tag + 4, label, ft, (255, 170, 176) if dim else (NAVY if fill == (255, 255, 255) else (255, 255, 255)))
        if hot:  # نقطة «مباشر» تنبض مع الوميض
            cx, cy = x1 - bw - 44, y_tag + 31
            d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=(120, 20, 28) if dim else (255, 60, 70))
        if w:
            fw = _cairo(28, 700)
            _draw_rtl(d, x1 - bw - (66 if hot else 40), y_tag + 15, w, fw, (225, 230, 240))
        y = y_tag + 62 + 26
        if kick:
            _draw_rtl(d, W - P, y, kick, _cairo(38, 800), (255, 196, 70))
            y += 54
        for ln in lines:
            _draw_rtl(d, W - P, y, ln, f, (255, 255, 255))
            y += lh
        d.rectangle([0, H - 12, W, H], fill=((96, 8, 16) if _DIM[0] else RED) if hot else (34, 92, 220))
        fy = H - 84
        d.line([(P, fy - 18), (W - P, fy - 18)], fill=(255, 255, 255, 60), width=1)
        _draw_rtl(d, W - P, fy, src_name or "أكا ميديا", _cairo(28, 700), (200, 208, 224))
        d.text((P, fy + 1), "@akamedia_iq", font=_cairo(27, 600), fill=(160, 172, 196), **({"direction": "ltr"} if RAQM else {}))

    elif style == "B":
        P = 72
        PAPER, INK = (246, 242, 234), (18, 20, 26)
        loader = (lambda s: _ff("IBMPlexSansArabic-Bold.ttf", s)) if (FONTS_DIR / "IBMPlexSansArabic-Bold.ttf").exists() else (lambda s: _cairo(s, 800))
        f, sz, lines = _fit_font(tmp, head, W - 2 * P, 4, [70, 66, 62, 58, 54, 50], loader)
        lh = int(sz * 1.5)
        txt_h = 40 + 46 + (52 if kick else 0) + lh * len(lines) + 30 + 90
        ph_h = max(int(H * 0.5), H - txt_h)
        im.paste(photo(ph_h), (0, 0))
        im.paste(Image.new("RGB", (W, H - ph_h), PAPER), (0, ph_h))
        d = _D.Draw(im)
        top_sh = _vgrad(W, 180, [(0, 110), (1, 0)])
        im.paste(Image.new("RGB", (W, 180), (0, 0, 0)), (0, 0), top_sh)
        d = _D.Draw(im)
        badge(W - P + 12, 46)
        d.rectangle([0, ph_h, W, ph_h + 10], fill=RED if hot else NAVY)
        y = ph_h + 44
        ft = _cairo(34, 900)
        _draw_rtl(d, W - P, y, label, ft, RED if hot or tag == "خبر" else (170, 120, 30))
        lw_ = d.textlength(_shape(label), font=ft, **kw)
        if w:
            _draw_rtl(d, W - P - lw_ - 26, y + 6, "·  " + w, _cairo(27, 600), (110, 108, 104))
        y += 58
        if kick:
            _draw_rtl(d, W - P, y, kick, _cairo(34, 700), NAVY)
            y += 52
        for ln in lines:
            _draw_rtl(d, W - P, y, ln, f, INK)
            y += lh
        fy = H - 78
        d.line([(P, fy - 20), (W - P, fy - 20)], fill=(214, 208, 196), width=2)
        _draw_rtl(d, W - P, fy, src_name or "أكا ميديا", _cairo(27, 700), (90, 88, 84))
        d.text((P, fy + 1), "@akamedia_iq", font=_cairo(26, 600), fill=(130, 126, 118), **({"direction": "ltr"} if RAQM else {}))

    else:  # C
        M, P = 44, 52
        im.paste(photo(H), (0, 0))
        f, sz, lines = _fit_font(tmp, head, W - 2 * M - 2 * P, 4, [68, 64, 60, 56, 52, 48], lambda s: _cairo(s, 850))
        lh = int(sz * 1.42)
        card_h = 70 + (50 if kick else 0) + lh * len(lines) + 24 + 84
        cy0 = H - M - card_h
        shade = _vgrad(W, H, [(0, 80), (0.15, 0), (max(0.16, (cy0 - 240) / H), 0), (1, 150)])
        im.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), shade)
        d = _D.Draw(im)
        sh = Image.new("L", (W, H), 0)
        _D.Draw(sh).rounded_rectangle([M, cy0 + 14, W - M, H - M + 14], radius=34, fill=120)
        im.paste(Image.new("RGB", (W, H), (0, 0, 0)), (0, 0), sh.filter(ImageFilter.GaussianBlur(26)))
        d = _D.Draw(im)
        d.rounded_rectangle([M, cy0, W - M, H - M], radius=34, fill=(255, 255, 255))
        badge(W - M, 48)
        ft = _cairo(36, 900)
        tw = d.textlength(_shape(label), font=ft, **kw)
        pw = int(tw + 60 + (26 if hot else 0))
        px1 = W - M - P + 10
        d.rounded_rectangle([px1 - pw, cy0 - 33, px1, cy0 + 33], radius=33, fill=RED if hot or tag == "خبر" else (190, 140, 40))
        if hot:
            d.ellipse([px1 - 38, cy0 - 8, px1 - 22, cy0 + 8], fill=(255, 255, 255))
        _draw_rtl(d, px1 - 30 - (26 if hot else 0), cy0 - 28, label, ft, (255, 255, 255))
        y = cy0 + 56
        if kick:
            _draw_rtl(d, W - M - P, y, kick, _cairo(34, 800), RED)
            y += 50
        for ln in lines:
            _draw_rtl(d, W - M - P, y, ln, f, NAVY)
            y += lh
        fy = H - M - 66
        d.line([(M + P, fy - 16), (W - M - P, fy - 16)], fill=(228, 231, 238), width=2)
        right = (src_name or "أكا ميديا") + (f"  ·  {w}" if w else "")
        _draw_rtl(d, W - M - P, fy, right, _cairo(26, 700), (98, 108, 128))
        d.text((M + P, fy + 1), "@akamedia_iq", font=_cairo(25, 600), fill=(140, 148, 166), **({"direction": "ltr"} if RAQM else {}))

    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92, optimize=True, progressive=True)
    return buf.getvalue()


def card_digest(title, sub, date, heads):
    """بوستر الموجز (1080×1350): عنوان كبير، ثم أهم الأخبار مرقّمة بدوائر حمراء — يُشارك بسهولة في واتساب وفيسبوك."""
    from PIL import ImageDraw as _D, ImageFilter
    W, H, P = 1080, 1350, 72
    RED, NAVY = (222, 18, 30), (9, 22, 52)
    morning = "صباح" in title
    acc = (255, 190, 64) if morning else RED
    im = Image.new("RGB", (W, H), NAVY)
    d = _D.Draw(im)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=(int(14 - 6 * k), int(34 - 14 * k), int(80 - 34 * k)))
    d = _D.Draw(im)  # بلا شعار باهت بالخلفية: كان يتداخل مع التذييل، والشعار الحقيقي في القرص الأبيض أعلاه
    _paste_badge(im, W - P - 150 + 8, 44, 150)
    d = _D.Draw(im)
    _draw_rtl(d, W - P, 200, title, _cairo(104, 900), (255, 255, 255))
    _draw_rtl(d, W - P, 390, sub, _cairo(40, 800), acc)
    _draw_rtl(d, W - P, 448, date, _cairo(30, 600), (170, 184, 214))
    d.rectangle([P, 468, P + 120, 474], fill=acc)
    y = 526
    avail = H - 104 - y
    per = avail // max(1, len(heads))
    for i, h in enumerate(heads, 1):
        f, sz, lines = _fit_font(d, h, W - 2 * P - 92, 2, [42, 39, 36, 33], lambda s: _cairo(s, 800))
        lh = int(sz * 1.42)
        cy = y + 30
        cx = W - P - 30
        d.ellipse([cx - 30, cy - 30, cx + 30, cy + 30], fill=RED)
        num = str(i)
        fn = _cairo(34, 900)
        nw = d.textlength(num, font=fn)
        d.text((cx - nw / 2, cy - 26), num, font=fn, fill=(255, 255, 255))
        ty = y + max(0, (60 - lh * len(lines)) // 2) if len(lines) == 1 else y
        for ln in lines:
            _draw_rtl(d, W - P - 92, ty, ln, f, (255, 255, 255))
            ty += lh
        y += per
        if i < len(heads):
            d.line([(P, y - 18), (W - P - 92, y - 18)], fill=(40, 58, 98), width=2)
    d.rectangle([0, H - 12, W, H], fill=acc)
    fy = H - 86
    _draw_rtl(d, W - P, fy, "أكا ميديا", _cairo(30, 800), (220, 226, 240))
    d.text((P, fy + 2), "@akamedia_iq", font=_cairo(29, 700), fill=(170, 184, 214), **({"direction": "ltr"} if RAQM else {}))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92, optimize=True)
    return buf.getvalue()


def card_subscribe(link="t.me/akamedia_iq", bot=None):
    """بطاقة «اشترك» (1080×1350) لهوية «أكا ميديا»: قرص الشعار الأبيض كبيراً، الشعار اللفظي، دعوة قصيرة ورابط القناة."""
    from PIL import ImageDraw as _D
    W, H, P = 1080, 1350, 80
    RED, INK = (225, 6, 0), (31, 34, 39)
    im = Image.new("RGB", (W, H), INK)
    d = _D.Draw(im)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=(int(40 - 22 * k), int(43 - 24 * k), int(50 - 28 * k)))
    d.rectangle([0, 0, W, 14], fill=RED)
    D = 430
    _paste_badge(im, (W - D) // 2, 120, D, shadow=0.5)
    d = _D.Draw(im)

    def center(text, y, font, fill):
        tw = d.textlength(_shape(text), font=font, **({"direction": "rtl", "language": "ar"} if RAQM else {}))
        _draw_rtl(d, int((W + tw) / 2), y, text, font, fill)

    center("نرى أبعد... ونروي أعمق", 600, _cairo(62, 900), (255, 255, 255))
    center("أخبار العراق العاجلة لحظة بلحظة", 712, _cairo(40, 700), (200, 204, 212))
    center("عاجل خلال ثوانٍ • بلا تكرار ولا إشاعات", 790, _cairo(34, 600), (150, 156, 168))
    fl = _cairo(44, 800)
    lw_ = d.textlength(link, font=fl)
    bw, by = int(lw_ + 120), 900
    d.rounded_rectangle([(W - bw) // 2, by, (W + bw) // 2, by + 96], radius=48, fill=RED)
    d.text(((W - lw_) / 2, by + 14), link, font=fl, fill=(255, 255, 255), **({"direction": "ltr"} if RAQM else {}))
    center("اشترك وفعّل التنبيه 🔔" if not RAQM else "اشترك وفعّل التنبيه", 1030, _cairo(36, 700), (230, 232, 236))
    if bot:
        center("أخبار محافظتك توصلك بالخاص عبر البوت", 1096, _cairo(30, 600), (150, 156, 168))
        fb_ = _cairo(30, 700)
        hb = "@" + bot.lstrip("@")
        d.text(((W - d.textlength(hb, font=fb_)) / 2, 1146), hb, font=fb_, fill=(190, 196, 206), **({"direction": "ltr"} if RAQM else {}))
    d.line([(P, H - 120), (W - P, H - 120)], fill=(70, 74, 82), width=2)
    center("أكا ميديا | AKA MEDIA", H - 98, _cairo(32, 800), (200, 204, 212))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92, optimize=True)
    return buf.getvalue()
