"""مختبر القوالب (06/11): ثلاثة اتجاهات جديدة كلياً لبطاقة الخبر — للعرض على إيهاب قبل اعتماد واحد.

A «شريط الأخبار»: صورة الحدث كاملة + شريط سفلي بأسلوب نشرات التلفزيون (كتلة «عاجل» حمراء + شريط العنوان + ساعة).
B «الصحيفة»: صورة الحدث بأعلى 60% + ورقة فاتحة بعنوان أسود كبير، خط أحمر رفيع، وسم الموضوع، والوقت.
C «الإطار الجريء»: صورة كاملة بتدرج داكن، عنوان أبيض ضخم، والكلمة الأهم مظللة بالأحمر (قلم تظليل).
كل الاتجاهات: 1080×1350، شعار أكا أصغر، بلا اسم مصدر.
"""
import io
import re
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw, ImageFilter

from tools import tg_card as C

W, H = 1080, 1350
RED, INK, PAPER, NAVY = (226, 24, 38), (14, 16, 22), (246, 243, 236), (13, 35, 71)
KW = {"direction": "rtl", "language": "ar"} if C.RAQM else {}


def F(name, s):
    return C._ff(name, s)


def tw(d, t, f):
    return d.textlength(C._shape(t), font=f, **KW)


def photo(jpg, w, h):
    if not jpg:  # بلا صورة: تدرّج الهوية مع شعار أكا خافت (أفضل من الكحلي المسطح) — آخر خيار بعد مصادر الخبر والأرشيف
        try:
            from tools import aka_card
            return C._cover(aka_card._backdrop("news", RED), w, h)
        except Exception:  # noqa: BLE001
            return Image.new("RGB", (w, h), NAVY)
    return C._grade(C._cover(Image.open(io.BytesIO(jpg)).convert("RGB"), w, h))


def when_txt(when_utc):
    try:
        t = datetime.fromisoformat((when_utc or "").replace("Z", "+00:00")) + timedelta(hours=3)
    except Exception:  # noqa: BLE001
        t = datetime.now(timezone.utc) + timedelta(hours=3)
    return t.strftime("%H:%M")


def fit(d, text, width, lines_max, sizes, font):
    return C._fit_font(d, text, width, lines_max, sizes, lambda s: F(font, s))


def logo(im, x, y, h):
    try:
        C._paste_badge(im, x, y, h)
    except Exception:  # noqa: BLE001
        pass


def card_A(jpg, title, breaking=True, when_utc=None, kind=None):
    """شريط الأخبار التلفزيوني."""
    im = photo(jpg, W, H)
    g = Image.new("L", (1, H))
    for y in range(H):
        g.putpixel((0, y), int(max(0, (y - H * 0.45) / (H * 0.55)) ** 1.6 * 235))
    im = Image.composite(Image.new("RGB", (W, H), (6, 8, 12)), im, g.resize((W, H)))
    d = ImageDraw.Draw(im)
    logo(im, 48, 48, 104)
    # كتلة العنوان: شريط أبيض بعرض الصورة وفوقه لسان أحمر «عاجل/الموضوع»
    f, sz, lines = fit(d, title, W - 150, 3, [76, 70, 64, 58, 52], "Alexandria-Black.ttf")
    lh = int(sz * 1.42)
    box_h = lh * len(lines) + 70
    y0 = H - 118 - box_h
    d.rectangle([0, y0, W, y0 + box_h], fill=(255, 255, 255))
    d.rectangle([W - 22, y0, W, y0 + box_h], fill=RED)
    tag = "عاجل" if breaking else (kind or "أخبار")
    ft = F("Alexandria-Black.ttf", 44)
    tw_ = tw(d, tag, ft) + 56
    d.rectangle([W - 22 - tw_, y0 - 74, W - 22, y0], fill=RED)
    C._draw_rtl(d, W - 50, y0 - 66, tag, ft, (255, 255, 255))
    y = y0 + 34
    for ln in lines:
        C._draw_rtl(d, W - 62, y, ln, f, INK)
        y += lh
    # الشريط السفلي: الساعة + المعرّف (أسلوب نشرة)
    d.rectangle([0, H - 118, W, H], fill=(10, 12, 18))
    fm = F("IBMPlexSansArabic-SemiBold.ttf", 36)
    d.rectangle([0, H - 118, 210, H], fill=RED)
    d.text((105, H - 59), when_txt(when_utc), font=F("Alexandria-Black.ttf", 46), fill=(255, 255, 255), anchor="mm")
    C._draw_rtl(d, W - 48, H - 86, "أكا ميديا  |  t.me/akamedia_iq", fm, (220, 224, 232))
    return _jpg(im)


def card_B(jpg, title, breaking=True, when_utc=None, kind=None):
    """الصحيفة: صورة أعلى + ورقة فاتحة بعنوان أسود."""
    im = Image.new("RGB", (W, H), PAPER)
    ph_h = int(H * 0.58)
    im.paste(photo(jpg, W, ph_h), (0, 0))
    d = ImageDraw.Draw(im)
    logo(im, 44, 44, 96)
    if breaking:
        fb = F("Alexandria-Black.ttf", 40)
        bw = tw(d, "عاجل", fb) + 64
        d.rounded_rectangle([W - 44 - bw, ph_h - 34, W - 44, ph_h + 34], 34, fill=RED)
        d.ellipse([W - 44 - bw + 22, ph_h - 8, W - 44 - bw + 38, ph_h + 8], fill=(255, 255, 255))
        C._draw_rtl(d, W - 70, ph_h - 26, "عاجل", fb, (255, 255, 255))
    y = ph_h + 66
    if kind:
        fk = F("Alexandria-Black.ttf", 34)
        C._draw_rtl(d, W - 64, y, kind, fk, RED)
        y += 62
    f, sz, lines = fit(d, title, W - 128, 4, [74, 68, 62, 56, 50], "Alexandria-Black.ttf")
    lh = int(sz * 1.45)
    for ln in lines:
        C._draw_rtl(d, W - 64, y, ln, f, INK)
        y += lh
    d.rectangle([64, H - 112, W - 64, H - 109], fill=(210, 204, 192))
    fm = F("IBMPlexSansArabic-SemiBold.ttf", 34)
    C._draw_rtl(d, W - 64, H - 92, f"بغداد {when_txt(when_utc)}", fm, (90, 92, 100))
    d.text((64, H - 92), "@akamedia_iq", font=fm, fill=RED)
    return _jpg(im)


def card_C(jpg, title, breaking=True, when_utc=None, kind=None, key=None):
    """الإطار الجريء: صورة كاملة، عنوان ضخم، كلمة مظللة بالأحمر."""
    im = photo(jpg, W, H)
    g = Image.new("L", (1, H))
    for y in range(H):
        g.putpixel((0, y), int(min(1, max(0, (y - H * 0.30) / (H * 0.55))) ** 1.3 * 245))
    im = Image.composite(Image.new("RGB", (W, H), (8, 6, 10)), im, g.resize((W, H)))
    d = ImageDraw.Draw(im)
    pad = 26
    d.rectangle([pad, pad, W - pad, H - pad], outline=(255, 255, 255), width=3)
    logo(im, 60, 60, 92)
    if breaking:
        fb = F("Alexandria-Black.ttf", 40)
        bw = tw(d, "عاجل", fb) + 50
        d.rectangle([W - 60 - bw, 66, W - 60, 136], fill=RED)
        C._draw_rtl(d, W - 85, 74, "عاجل", fb, (255, 255, 255))
    f, sz, lines = fit(d, title, W - 170, 4, [92, 84, 76, 68, 60], "Alexandria-Black.ttf")
    lh = int(sz * 1.5)
    words = title.split()
    key = key or max((w for w in words if len(w) > 3), key=len, default="")
    y = H - 150 - lh * len(lines)
    for ln in lines:
        x_r = W - 85
        if key and key in ln.split():  # تظليل الكلمة الأهم: مستطيل أحمر خلفها
            pre = " ".join(ln.split()[: ln.split().index(key)])
            x0 = x_r - (tw(d, pre + " ", f) if pre else 0)
            kw_ = tw(d, key, f)
            d.rectangle([x0 - kw_ - 12, y + sz * 0.18, x0 + 8, y + sz * 1.22], fill=RED)
        C._draw_rtl(d, x_r, y, ln, f, (255, 255, 255))
        y += lh
    fm = F("IBMPlexSansArabic-SemiBold.ttf", 34)
    C._draw_rtl(d, W - 85, H - 108, f"{kind + ' · ' if kind else ''}{when_txt(when_utc)} بغداد", fm, (210, 212, 220))
    d.text((85, H - 108), "@akamedia_iq", font=fm, fill=(255, 255, 255))
    return _jpg(im)


def _jpg(im):
    b = io.BytesIO()
    im.convert("RGB").save(b, "JPEG", quality=90)
    return b.getvalue()


def main():
    """3 أخبار حقيقية حديثة بصورها × 3 اتجاهات ← card_lab_sheet.jpg + الملفات المنفردة."""
    import json
    from pathlib import Path
    from tools import tg_push as T
    from tools import aka_card as AC
    root = Path(__file__).resolve().parent.parent
    news = json.loads((root / "pwa" / "news.json").read_text(encoding="utf-8"))
    out = root / "data" / "card_lab"
    out.mkdir(parents=True, exist_ok=True)
    picks = []
    for n in news:
        if len(picks) >= 3:
            break
        if not n.get("about_iraq") or (n.get("n_sources") or 0) < 4:
            continue
        ph = T.pick_photo(n)
        if not ph:
            continue
        picks.append((n, ph))
    tiles = []
    for i, (n, ph) in enumerate(picks):
        head = T.headline(n)
        k = AC.kind_of(head)
        kind = AC.KINDS.get(k, (None,))[0] if hasattr(AC, "KINDS") and k else None
        br = T.is_breaking(n) or i == 0
        for name, fn in (("A", card_A), ("B", card_B), ("C", card_C)):
            jpg = fn(ph, head, br, n.get("first_utc"), kind if isinstance(kind, str) else None)
            (out / f"lab_{i}_{name}.jpg").write_bytes(jpg)
            tiles.append(Image.open(io.BytesIO(jpg)).resize((540, 675)))
    if tiles:
        sh = Image.new("RGB", (540 * 3, 675 * (len(tiles) // 3)), "white")
        for k, t in enumerate(tiles):
            sh.paste(t, ((k % 3) * 540, (k // 3) * 675))
        sh.save(out / "card_lab_sheet.jpg", quality=85)
    print(f"::notice title=card_lab::{len(picks)} أخبار × 3 اتجاهات")


if __name__ == "__main__":
    main()
