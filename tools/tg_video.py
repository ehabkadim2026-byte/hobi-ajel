"""إعادة نشر فيديو من منشور تلغرام عام إلى قناة «هسة وصل» — يدوياً فقط، بعد أن يرسل المحرر الرابط للبوت.

المحرر يرسل للبوت بالخاص رابط منشور مثل https://t.me/<قناة>/<رقم> (ويقدر يكتب سطر عنوان فوقه إن أراد).
نقرأ صفحة المعاينة العامة للمنشور (نفس ما يراه أي زائر بلا حساب)، نأخذ رابط الفيديو والنص، ونرفعه للقناة
بعنوان محرَّر + «المصدر: <اسم القناة>» + دعوة القناة. لا نتابع القناة تلقائياً ولا ننشر شيئاً بلا رابط من المحرر.

الحدود: Bot API يرفع حتى 50 ميغابايت؛ والفيديوهات الكبيرة لا تظهر في المعاينة العامة أصلاً (تلغرام يعرض «افتح في التطبيق»)،
وكذلك القنوات التي فعّلت «تقييد حفظ المحتوى». في هذه الحالات نبلّغ المحرر ولا نتحايل.
"""
import html as H
import re
import urllib.request

from tools.discover import EXCLUDE
from tools.tg_push import CHANNEL, api

POST = re.compile(r"https?://(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z0-9_]{4,})/(\d+)")
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36"}
MAX = 48 * 1024 * 1024


def _get(url, limit=MAX + 1, timeout=60):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read(limit)


def _text(fragment):
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    t = re.sub(r"<[^>]+>", "", t)
    return H.unescape(t).strip()


def fetch_post(channel, msg_id):
    page = _get(f"https://t.me/{channel}/{msg_id}?embed=1&mode=tme", limit=800_000, timeout=20).decode("utf-8", "replace")
    vids = re.findall(r'<video[^>]+src="([^"]+)"', page)
    m = re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', page, re.S)
    name = re.search(r'class="tgme_widget_message_owner_name"[^>]*>(?:<span[^>]*>)?(.*?)</', page, re.S)
    too_big = "too big" in page.lower() or "tgme_widget_message_video_unsupported" in page
    restricted = "restricted" in page.lower() and not vids
    return {"video": H.unescape(vids[0]) if vids else None, "text": _text(m.group(1)) if m else "",
            "name": _text(name.group(1)) if name else channel, "too_big": too_big, "restricted": restricted}


def handle(token, chat_id, editor_cid, reply_to, text):
    """يرجع True إذا كانت الرسالة رابط منشور تلغرام وعالجناها (نجاحاً أو فشلاً مع إبلاغ المحرر)."""
    m = POST.search(text or "")
    if not m:
        return False
    channel, msg_id = m.group(1), m.group(2)
    if channel.lower() in ("hassawassal",):
        return False

    def tell(msg):
        api(token, "sendMessage", chat_id=editor_cid, reply_to_message_id=reply_to, text=msg)

    try:
        post = fetch_post(channel, msg_id)
    except Exception as e:  # noqa: BLE001
        tell(f"⚠️ ما كدرت أفتح المنشور ({type(e).__name__}). تأكد إن القناة عامة والرابط صحيح.")
        return True
    if EXCLUDE.search(channel + " " + post["name"]):
        tell("⛔ هذه القناة ضمن الجهات المستبعدة بقرار ثابت، ما ننشر منها.")
        return True
    if not post["video"] and not (post["too_big"] or post["restricted"]):
        return False  # منشور بلا فيديو: يكمل كإدخال يدوي عادي للرصد
    if not post["video"]:
        why = ("الفيديو كبير، وتلغرام ما يعرضه بالمعاينة العامة (يفتح بس بالتطبيق)" if post["too_big"]
               else "القناة مقيّدة الحفظ أو المنشور بدون فيديو")
        tell(f"⚠️ ما لكيت فيديو قابل للنشر بهذا المنشور: {why}. ما راح أتحايل على القيد.")
        return True
    try:
        data = _get(post["video"])
    except Exception as e:  # noqa: BLE001
        tell(f"⚠️ فشل تحميل الفيديو ({type(e).__name__}).")
        return True
    if len(data) > MAX:
        tell("⚠️ الفيديو أكبر من 48 ميغابايت (حد بوت تلغرام للرفع). ما أكدر أنشره.")
        return True
    from tools.editorial import edit_headline
    own = POST.sub("", text).strip()  # إذا كتب المحرر عنواناً فوق الرابط نعتمده
    raw = own if len(own) >= 8 else next((ln.strip() for ln in post["text"].split("\n") if len(ln.strip()) >= 8), post["text"][:200])
    head = edit_headline(raw) if raw else ""
    cap = (f"<b>{H.escape(head)}</b>\n\n" if head else "") + f"🎥 المصدر: {H.escape(post['name'])}\n\nزورونا على الرابط للأخبار العاجلة 👇\n{CHANNEL}"
    try:
        r = api(token, "sendVideo", files={"video": ("video.mp4", data, "video/mp4")}, chat_id=chat_id, caption=cap[:1024],
                parse_mode="HTML", supports_streaming="true")
    except Exception as e:  # noqa: BLE001
        r = {"ok": False, "description": f"{type(e).__name__}: {str(e).replace(token, '***')}"}
    if r.get("ok"):
        tell(f"✅ انتشر الفيديو بالقناة ({len(data) // 1024 // 1024 or 1} ميغا) مع ذكر المصدر «{post['name']}».")
    else:
        tell(f"⚠️ تلغرام رفض النشر: {r.get('description', '')[:150]}")
    return True
