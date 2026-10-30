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
    y = 175
    for ln in lines:
        _draw_rtl(d, W - P, y, ln, fb, (245, 247, 250))
        y += int(size * 1.6)
    # التذييل
    d.line([(P, H - 120), (W - P, H - 120)], fill=(60, 70, 92), width=2)
    _draw_rtl(d, W - P, H - 100, meta, fs, (170, 180, 200))
    d.text((P, H - 100), footer, font=_font(30), fill=(120, 190, 255))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return buf.getvalue()


if __name__ == "__main__":
    Path("card_test.jpg").write_bytes(card("عاجل: رئيس الوزراء يوجه بفتح تحقيق عاجل في حادثة انقطاع الكهرباء عن عدة محافظات جنوبية", "🔴 عاجل".replace("🔴 ", ""),
                                           "السومرية نيوز · 14:32 بغداد · غير مؤكد", "t.me/hassawassal"))
