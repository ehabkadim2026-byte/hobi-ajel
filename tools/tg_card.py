"""صورة الخبر لمنشورات تلغرام.

1) صورة المنشور الأصلي: لمصادر تلغرام نقرأ صفحة التضمين العامة t.me/<قناة>/<رقم>?embed=1،
   ولمصادر الويب نقرأ og:image من صفحة الخبر (لا نقرأ روابط Google News).
2) إن لم توجد صورة: بطاقة «هوبي عاجل» مولّدة بالعنوان (PIL)، بلا أي صورة مختلقة.
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


LOGO = ROOT / "assets" / "logo_hassawassal.png"


def brand(jpg_bytes):
    """يضيف شعار «هسه وصل» على الصورة (شارة بيضاء أسفل اليسار)."""
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
                                           "السومرية نيوز · 14:32 بغداد · غير مؤكد", "t.me/hassawassal"))


def _cover(im, W, H):
    r = max(W / im.width, H / im.height)
    im = im.resize((int(im.width * r) + 1, int(im.height * r) + 1), Image.LANCZOS)
    x, y = (im.width - W) // 2, max(0, int((im.height - H) * 0.35))
    return im.crop((x, y, x + W, y + H))


def news_card(photo_jpg, title, breaking=True, time_str="", handle="t.me/hassawassal"):
    """قالب الخبر الموحّد 1280×720 (أسلوب غرف الأخبار العربية الكبرى، بهوية «هسة وصل»):
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


def news_card2(photo_jpg, title, breaking=True, when_utc=None, handle="t.me/hassawassal"):
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
    _draw_rtl(d, W - P, H - bottom_bar + 13, "هسة وصل — أخبار العراق لحظة بلحظة", fs, (230, 232, 240))
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
