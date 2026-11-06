"""«نشرة دقيقة»: فيديو عمودي يومي 9:16 (1080×1920، 30 إطاراً) لأهم 5 أخبار عراقية بآخر 24 ساعة، يُصنع تلقائياً ويُرسل للمحررين بالخاص
لنشره على تيك توك وريلز (لا ننشر على تلك المنصات بأنفسنا).

الحركة من مكتبة HOBI المعتمدة (v1.1): حركة 1 «طلوع الكلام» (كل سطر يدخل وحدة كاملة — آمن مع النفي)، حركة 5 «عدّاد الأرقام»
(عدد الجهات الناشرة الحقيقي)، حركة 12 «تاك حالة» (نوع الخبر ونقطة حيّة). الصوت: صامت حتى يرسل إيهاب مقطوعته (assets/music/reel.mp3 إن وُجد).
"""
import functools
import io
import json
import math
import re
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
W, H, FPS = 1080, 1920, 30
XR, XL = W - 150, 70   # منطقة آمنة: عمود أزرار تيك توك/ريلز يميناً (150) وشريط الوصف أسفل (تحت 1520) لا يغطي النص
SAFE_BOTTOM = 1520
FD = ROOT / "assets" / "fonts"
NAVY, INK, RED, GOLD, PAPER = (16, 10, 14), (8, 8, 12), (226, 24, 38), (226, 24, 38), (255, 255, 255)  # هوية أكا: حبر داكن + أحمر (05/11)
KW = dict(direction="rtl", language="ar")


# ---------------- مكتبة HOBI: التسهيل والتقدم (نفس الأرقام المعتمدة)
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def bezier(p1x, p1y, p2x, p2y):
    def f(x):
        x = clamp(x)
        lo, hi = 0.0, 1.0
        for _ in range(26):
            m = (lo + hi) / 2
            bx = 3 * (1 - m) ** 2 * m * p1x + 3 * (1 - m) * m * m * p2x + m ** 3
            lo, hi = (m, hi) if bx < x else (lo, m)
        m = (lo + hi) / 2
        return 3 * (1 - m) ** 2 * m * p1y + 3 * (1 - m) * m * m * p2y + m ** 3
    return f


EXPO_OUT, EXPO_IN, MOVE = bezier(0.16, 1, 0.3, 1), bezier(0.7, 0, 0.84, 0), bezier(0.65, 0, 0.35, 1)


def prog(t, start, dur, ease=EXPO_OUT):
    if t <= start:
        return 0.0
    if dur <= 0 or t >= start + dur:
        return 1.0
    return ease((t - start) / dur)


def f2s(n):
    return n / FPS


@functools.lru_cache(maxsize=64)
def font(kind, size):
    if kind == "num":
        return ImageFont.truetype(str(FD / "Alexandria-Black.ttf"), size, layout_engine=ImageFont.Layout.RAQM)
    f = ImageFont.truetype(str(FD / "Cairo-VF.ttf"), size, layout_engine=ImageFont.Layout.RAQM)
    f.set_variation_by_axes([{"black": 900, "bold": 800, "semi": 650, "med": 550}[kind], 0])
    return f


@functools.lru_cache(maxsize=512)
def text_patch(text, kind, size, color):
    f = font(kind, size)
    pad = int(size * 0.3)
    asc, desc = f.getmetrics()
    l, t, r, b = f.getbbox(text, **KW)
    im = Image.new("RGBA", (int(r - min(0, l) + 2 * pad), int(asc + desc + 2 * pad)), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((pad - min(0, l), pad), text, font=f, fill=color, **KW)
    return im, pad + asc


def fade(im, a):
    if a >= 0.999:
        return im
    im = im.copy()
    im.putalpha(im.getchannel("A").point(lambda v: int(v * clamp(a))))
    return im


def wrap(text, kind, size, maxw):
    f = font(kind, size)
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if f.getlength(t, **KW) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def rise_line(cv, t, text, kind, size, color, xr, base_y, start, exit_at=None):
    """حركة 1 (v1.1): السطر كاملاً يطلع من تحت ويظهر تدريجياً كوحدة واحدة (بلا قص للحروف)، محاذاة يمين."""
    p, base = text_patch(text, kind, size, color)
    pr = prog(t, start, f2s(11))
    if pr <= 0:
        return
    dy, a = (1 - pr) * size * 0.35, clamp(pr * 1.4)
    if exit_at is not None and t >= exit_at:
        pe = prog(t, exit_at, f2s(8), EXPO_IN)
        if pe >= 1:
            return
        dy, a = pe * size * 0.35, 1 - pe
    cv.alpha_composite(fade(p, a), (int(xr - p.width + int(size * 0.3)), int(base_y - base + dy)))


def counter(cv, t, value, suffix, xr, base_y, start, dur=1.2):
    """حركة 5: الرقم يعدّ تصاعدياً ويتباطأ آخر الإطارات (قيمة حقيقية فقط)."""
    if t < start:
        return
    v = int(round(value * bezier(0.25, 0.1, 0.25, 1)(clamp((t - start) / dur))))
    p, base = text_patch(f"{v}", "num", 96, GOLD)
    a = clamp((t - start) / f2s(3))
    x = int(xr - p.width + 29)
    cv.alpha_composite(fade(p, a), (x, int(base_y - base)))
    s, sb = text_patch(suffix, "semi", 44, (190, 204, 228))
    cv.alpha_composite(fade(s, a), (int(x - s.width + 30), int(base_y - sb - 6)))


@functools.lru_cache(maxsize=16)
def pill(text, fill, fg):
    tp, base = text_patch(text, "bold", 46, fg)
    box = tp.getchannel("A").getbbox()
    tw, th = box[2] - box[0], box[3] - box[1]
    h, w = th + 40, tw + 120
    SS = 3
    im = Image.new("RGBA", (w * SS, h * SS), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, w * SS - 1, h * SS - 1], h * SS // 2, fill=fill)
    im = im.resize((w, h), Image.LANCZOS)
    im.alpha_composite(tp.crop(box), (34, (h - th) // 2))
    return im, (w - 42, h // 2)


def pill_tag(cv, t, text, fill, fg, dot, xr, y, start):
    """حركة 12: كبسولة تنزلق من اليمين ونقطة حيّة تنبض."""
    if t < start:
        return
    im, (dx, dy) = pill(text, fill, fg)
    im = im.copy()
    pr = prog(t, start, f2s(12))
    x = (W + 40) + (xr - im.width - (W + 40)) * pr
    d = ImageDraw.Draw(im)
    ph = ((t - start) % 0.9) / 0.9
    r = 11 + 18 * ph
    d.ellipse([dx - r, dy - r, dx + r, dy + r], outline=dot + (int(200 * (1 - ph)),), width=4)
    d.ellipse([dx - 11, dy - 11, dx + 11, dy + 11], fill=dot + (255,))
    cv.alpha_composite(im, (int(x), int(y)))


# ---------------- الخلفية والحبيبات (من المكتبة: حبيبات 7% تتحرك 15 إطاراً/ث)
@functools.lru_cache(maxsize=4)
def grain(k):
    g = np.random.default_rng(7 + k).normal(128, 14, (H // 2, W // 2)).clip(0, 255).astype(np.uint8)
    im = Image.fromarray(g, "L").resize((W, H), Image.NEAREST).convert("RGBA")
    im.putalpha(18)
    return im


@functools.lru_cache(maxsize=2)
def bg_base():
    im = Image.new("RGBA", (W, H), NAVY + (255,))
    d = ImageDraw.Draw(im)
    for y in range(H):
        k = y / H
        d.line([(0, y), (W, y)], fill=(int(58 - 46 * k), int(14 - 8 * k), int(22 - 14 * k), 255))  # نبيذي داكن ← حبر (هوية أكا) بدل الكحلي
    return im


@functools.lru_cache(maxsize=4)
def logo_white(h):
    """شعار «أكا ميديا» الحقيقي داخل قرص أبيض (قطره ≈ 1.6×h) — لا يوضع الشعار مباشرة على الخلفية الداكنة."""
    from tools.tg_card import _logo_badge
    return _logo_badge(int(h * 1.6)).copy()


def photo_layer(jpg):
    """صورة الخبر للنصف العلوي (1080×1060). الصغيرة تُعرض بحجمها فوق نسخة مغبّشة منها."""
    PH = 860
    if not jpg:
        return None
    src = Image.open(io.BytesIO(jpg)).convert("RGB")
    def cover(im, w, h):
        s = max(w / im.width, h / im.height)
        im = im.resize((int(im.width * s) + 1, int(im.height * s) + 1), Image.LANCZOS)
        return im.crop(((im.width - w) // 2, (im.height - h) // 2, (im.width - w) // 2 + w, (im.height - h) // 2 + h))
    if src.width >= 760:
        out = cover(src, int(W * 1.06), int(PH * 1.06))
    else:
        out = ImageEnhance.Brightness(cover(src, int(W * 1.06), int(PH * 1.06)).filter(ImageFilter.GaussianBlur(30))).enhance(0.5)
        k = min(PH * 0.8 / src.height, W * 0.86 / src.width, 2.0)
        fg = src.resize((int(src.width * k), int(src.height * k)), Image.LANCZOS)
        out.paste(fg, ((out.width - fg.width) // 2, int(PH * 0.12)))
    return out.convert("RGBA")


# ---------------- المشاهد
def scene_intro(cv, t, day_txt, n=5, period="اليوم"):
    cv.alpha_composite(bg_base())
    lw = logo_white(150)
    a = clamp(prog(t, 0.05, f2s(12)) * 1.3)
    cv.alpha_composite(fade(lw, a), ((W - lw.width) // 2, 440))
    pill_tag(cv, t, "نشرة دقيقة", RED + (255,), PAPER, (255, 255, 255), XR, 760, 0.25)
    rise_line(cv, t, f"أهم {n} أخبار", "black", 124, PAPER, XR, 1030, 0.45, exit_at=2.2)
    rise_line(cv, t, f"في العراق {period}", "black", 124, GOLD, XR, 1205, 0.6, exit_at=2.25)
    rise_line(cv, t, day_txt, "semi", 48, (190, 204, 228), XR, 1335, 0.8, exit_at=2.3)


def scene_story(cv, t, i, n, s, ph):
    PH = 860
    cv.alpha_composite(bg_base())
    if ph is not None:
        k = prog(t, 0, s["dur"], MOVE)  # دفع بطيء باتجاه واحد (4%) لا تكبير مستمر بلا معنى
        sc = 1.0 + 0.04 * k
        im = ph.resize((int(ph.width * sc / 1.06), int(ph.height * sc / 1.06)), Image.BILINEAR)
        cv.alpha_composite(im.crop(((im.width - W) // 2, (im.height - PH) // 2, (im.width - W) // 2 + W, (im.height - PH) // 2 + PH)), (0, 0))
        gr = Image.new("L", (1, 420))
        for y in range(420):
            gr.putpixel((0, y), int(255 * (y / 420) ** 1.6))
        cv.paste(Image.new("RGBA", (W, 420), NAVY + (255,)), (0, PH - 420), gr.resize((W, 420)))
    else:  # بلا صورة: رقم الخبر ضخماً باهتاً كعنصر بصري يملأ الفراغ
        big, bb = text_patch(f"{i + 1:02d}", "num", 520, (255, 255, 255, 18))
        pr = prog(t, 0, f2s(14))
        cv.alpha_composite(fade(big, pr), (int(XL - 40), int(150 + (1 - pr) * 40)))
    # شريط التقدم أعلى الشاشة (5 مقاطع)
    d = ImageDraw.Draw(cv)
    seg = (W - 120 - 4 * 14) / n
    for j in range(n):
        x1 = W - 60 - j * (seg + 14)
        d.rounded_rectangle([x1 - seg, 70, x1, 80], 5, fill=(255, 255, 255, 70))
        fill = 1.0 if j < i else (clamp(t / s["dur"]) if j == i else 0)
        if fill:
            d.rounded_rectangle([x1 - seg * fill, 70, x1, 80], 5, fill=(255, 255, 255, 235))
    lw = logo_white(70)
    cv.alpha_composite(lw, (W - 60 - lw.width, 110))
    num, nb = text_patch(f"{i + 1:02d}", "num", 74, GOLD)
    cv.alpha_composite(num, (40, 100 - nb + 74))
    lh = int(s["size"] * 1.42)
    block = 150 + lh * len(s["lines"]) + 200
    top = 860 if ph is not None else int(max(760, min(SAFE_BOTTOM - block, (H - block) / 2 + 60)))
    pill_tag(cv, t, s["tag"], s["tag_fill"], PAPER, s["dot"], XR, top, 0.1)
    y = top + 150
    for k_, ln in enumerate(s["lines"]):
        rise_line(cv, t, ln, "black", s["size"], PAPER, XR, y, 0.3 + f2s(4) * k_, exit_at=s["dur"] - 0.35)
        y += lh
    counter(cv, t, s["n_sources"], "مصدراً تناول الخبر", XR, y + 40, 0.9)
    if s.get("src") and False:  # إيهاب 06/11: لا اسم للمصدر
        rise_line(cv, t, s["src"], "med", 38, (160, 176, 205), XR, y + 120, 1.2)


def scene_outro(cv, t):
    cv.alpha_composite(bg_base())
    lw = logo_white(220)
    p = prog(t, 0.05, f2s(14))
    cv.alpha_composite(fade(lw, p), ((W - lw.width) // 2, int(560 + (1 - p) * 60)))
    rise_line(cv, t, "الخبر أول بأول", "black", 110, PAPER, W // 2 + 330, 1050, 0.35)
    pill_tag(cv, t, "t.me/akamedia_iq", (255, 255, 255, 255), INK, RED, W // 2 + 260, 1180, 0.6)


def wipe(cv, p):
    """انتقال: شريط أحمر يمسح من اليمين لليسار (اتجاه القراءة) ثم يكشف المشهد التالي."""
    d = ImageDraw.Draw(cv)
    if p < 0.5:
        x = W - W * (p / 0.5)
        d.rectangle([x, 0, W, H], fill=RED + (255,))
    else:
        x = W - W * ((p - 0.5) / 0.5)
        d.rectangle([0, 0, x, H], fill=RED + (255,))


# ---------------- اختيار الأخبار
def pick(news, k=10, hours=12):
    from tools import tg_push as T
    from tools.editorial import clean_headline, pick_best
    from tools.learn import topic
    T.build_idf([x.get("title") or "" for x in news])
    now = datetime.now(timezone.utc)
    cands = [n for n in news if n.get("about_iraq") and T.iraq_title(n.get("title") or "") and not T.far_title(n.get("title") or "")
             and (n.get("latest_utc") or "") >= (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M")
             and n.get("vstatus") != "ثبت عدم صحته" and n.get("ctype") != "تحليل/رأي"]
    out = []
    for n in sorted(cands, key=lambda x: -(x.get("n_sources") or 1)):
        sig = T.title_sig(n["title"])
        if any(T.same_story(sig, {"w": sorted(o["_sig"][0]), "d": sorted(o["_sig"][1])}) for o in out):
            continue
        title = clean_headline(pick_best([n["title"]] + list(n.get("alts") or [])))
        title = re.sub(r"^\W*(?:مصدر|مصادر|خاص|عاجل|حصري|بالفيديو|بالصور)\s*[:：|]\s*", "", title)  # «مصدر: النزاهة…»
        if "|" in title:  # «كوردستان 24 | كتلة …» اسم مصدر قبل الفاصل
            title = max((p.strip() for p in title.split("|")), key=lambda p: len(p.split()))
        # مراجعة 06/11 قبل النشر بالقناة: خبر رياضي أجنبي (رونالدو) وعنوان بلا واقعة دخلا «أهم أخبار العراق»
        if len(title.split()) < 6 or not T.iraq_strict(title) or T.low_value(title) or T.incomplete(title.rstrip("…").strip()) or T.analyst(title):
            continue
        unver = n.get("vstatus") in (None, "غير متحقق") and not n.get("official")
        out.append({"_sig": sig, "n": n, "title": title[:150], "n_sources": n.get("n_sources") or 1,
                    "tag": "غير مؤكد" if unver else topic(title) if topic(title) != "عام" else "خبر",
                    "src": T.src_label(n)})
        if len(out) >= k:
            break
    return out


def render(items, out_path, day_txt, music=None, period="اليوم"):
    from tools import tg_push as T
    scenes = [("intro", 2.6, None)]
    for i, it in enumerate(items):
        ph = None
        try:
            jpg = T.news_photo(it["n"])
            if jpg:
                from tools import fastbreak as _FB
                _g = Image.open(io.BytesIO(jpg)).convert("L").resize((64, 64))
                if sum(_g.getdata()) / 4096 < 45 or _FB.watermarked(jpg) is not False:  # غير مؤكد = لا نستخدمها  # صورة مظلمة أو عليها شعار قناة أخرى
                    jpg = None
            ph = photo_layer(jpg)
        except Exception:  # noqa: BLE001
            ph = None
        size = 72
        lines = wrap(it["title"], "black", size, XR - XL)
        while len(lines) > 4 and size > 54:
            size -= 6
            lines = wrap(it["title"], "black", size, XR - XL)
        dur = max(4.2, min(6.0, 2.6 + 0.09 * len(it["title"].split()) + 0.5))  # وقت قراءة كافٍ حسب طول العنوان
        it.update({"lines": lines[:4], "size": size, "dur": dur,
                   "tag_fill": (110, 112, 120, 255) if it["tag"] == "غير مؤكد" else (226, 24, 38, 255),
                   "dot": (255, 196, 92) if it["tag"] == "غير مؤكد" else (255, 255, 255)})
        scenes.append(("story", dur, (i, it, ph)))
    scenes.append(("outro", 3.0, None))
    total = sum(s[1] for s in scenes)
    ff = os.environ.get("FFMPEG") or "ffmpeg"
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        pass
    audio = ["-stream_loop", "-1", "-i", str(music)] if music and Path(music).exists() else ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    cmd = [ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", *audio,
           "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-shortest", "-t", f"{total:.2f}", "-movflags", "+faststart", str(out_path)]
    if music and Path(music).exists():
        cmd[cmd.index("-c:a"):cmd.index("-c:a")] = ["-af", f"volume=0.9,afade=t=out:st={max(0, total - 1.6):.2f}:d=1.6"]  # لا تعليق صوتي: الموسيقى هي الصوت الوحيد (مقطوعة إيهاب «نهاوند الفجر» من 1:26.7، مطبّعة -16 LUFS)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    fno, WIPE = 0, 6
    stills = []
    for si, (kind, dur, data) in enumerate(scenes):
        nf = int(round(dur * FPS))
        for f in range(nf):
            t = f / FPS
            cv = Image.new("RGBA", (W, H), NAVY + (255,))
            if kind == "intro":
                scene_intro(cv, t, day_txt, len(items), period)
            elif kind == "story":
                scene_story(cv, t, data[0], len(items), data[1], data[2])
            else:
                scene_outro(cv, t)
            cv.alpha_composite(grain((fno // 2) % 4))
            if si < len(scenes) - 1 and f >= nf - WIPE // 2:
                wipe(cv, (f - (nf - WIPE // 2)) / WIPE)
            elif si > 0 and f < WIPE // 2:
                wipe(cv, 0.5 + f / WIPE)
            if f in (int(nf * 0.15), int(nf * 0.6)):
                stills.append(cv.convert("RGB").resize((270, 480)))
            proc.stdin.write(cv.convert("RGB").tobytes())
            fno += 1
    proc.stdin.close()
    proc.wait()
    sheet = Image.new("RGB", (270 * min(8, len(stills)), 480 * math.ceil(len(stills) / 8)), (0, 0, 0))
    for k, s in enumerate(stills):
        sheet.paste(s, ((k % 8) * 270, (k // 8) * 480))
    sheet.save(str(out_path).replace(".mp4", "_sheet.jpg"), quality=85)
    return total


AR_M = ["كانون الثاني", "شباط", "آذار", "نيسان", "أيار", "حزيران", "تموز", "آب", "أيلول", "تشرين الأول", "تشرين الثاني", "كانون الأول"]
AR_D = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


def main():
    from tools import tg_push as T
    news = json.loads((ROOT / "pwa" / "news.json").read_text(encoding="utf-8"))
    hours = int(os.environ.get("REEL_HOURS", "12"))
    items = pick(news, k=int(os.environ.get("REEL_K", "10")), hours=hours)
    if len(items) < 6:  # ساعات هادئة: توسيع النافذة بدل ريل ناقص
        items = pick(news, k=int(os.environ.get("REEL_K", "10")), hours=hours + 6)
    if len(items) < 3:
        print("::warning title=reel::أقل من 3 أخبار مناسبة")
        return
    b = datetime.now(timezone.utc) + timedelta(hours=3)
    day_txt = f"{AR_D[b.weekday()]} {b.day} {AR_M[b.month - 1]} {b.year}"
    half = "صباحية" if b.hour < 15 else "مسائية"
    period = f"خلال {hours} ساعة"
    out = ROOT / "data" / f"reel_{b.strftime('%Y%m%d_%H')}.mp4"
    out.parent.mkdir(exist_ok=True)
    music = ROOT / "assets" / "music" / "reel.mp3"
    total = render(items, out, day_txt, music if music.exists() else None, period)
    size = out.stat().st_size / 1e6
    print(f"::notice title=reel::{len(items)} أخبار، {total:.1f} ث، {size:.1f} MB")
    token = os.environ.get("MARSAD_TG_BOT_TOKEN", "").strip()
    sent = T.load(T.SENT, {})
    cap = (f"🎬 نشرة دقيقة — {day_txt}\n{len(items)} أخبار · {total:.0f} ثانية · 1080×1920\n\n"
           + "\n".join(f"{k + 1}. {it['title'][:90]}" for k, it in enumerate(items))
           + "\n\nجاهز للنشر على تيك توك وريلز. " + ("بدون موسيقى (أرسل مقطوعة لإضافتها)." if not music.exists() else "مع الموسيقى المعتمدة."))
    if token and os.environ.get("REEL_TO_CHANNEL") == "1":  # إيهاب 06/11: ريل أهم 10 أخبار كل 12 ساعة بالقناة (مجدول + يدوي)
        ccap = (f"🎬 <b>أهم {len(items)} أخبار في العراق {period}</b> — النشرة ال{half}، {day_txt}\n\n"
                + "\n".join(f"{k + 1}. {it['title'][:100]}" for k, it in enumerate(items))
                + f"\n\nتابعونا لحظة بلحظة 👇\n{T.CHANNEL}")
        chat = os.environ.get("MARSAD_TG_CHAT_ID", "").strip() or "-1004327422297"  # المعرّف الرقمي للقناة
        r = T.api(token, "sendVideo", files={"video": (out.name, out.read_bytes(), "video/mp4")}, chat_id=chat, caption=ccap[:1024],
                  parse_mode="HTML", width="1080", height="1920", supports_streaming="true")
        print("::notice title=reel channel::", bool(r.get("ok")), (r.get("result") or {}).get("message_id"))
    if token:
        for c in (sent.get("_editor_chats") or {}).values():
            try:
                T.api(token, "sendVideo", files={"video": (out.name, out.read_bytes(), "video/mp4")}, chat_id=c, caption=cap[:1024],
                      width="1080", height="1920", supports_streaming="true")
            except Exception as e:  # noqa: BLE001
                print("::warning title=reel send::", type(e).__name__)


if __name__ == "__main__":
    main()
