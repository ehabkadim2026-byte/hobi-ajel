"""إشعارات فيسبوك من هاتف المحرر → الرصد (مجاني، بلا كشط وبلا مفاتيح إضافية).

الهاتف (تطبيق MacroDroid) يلتقط إشعار فيسبوك لصفحة يتابعها المحرر، ويرسل نصه بطلب HTTP إلى ntfy.sh (خدمة مجانية بلا حساب)
على «موضوع» سري مشتق من توكن البوت. كل جولة رصد تقرأ الجديد من الموضوع وتدخله القاعدة بنوع «إشعار فيسبوك».
الحماية: كل رسالة يجب أن تبدأ بكلمة سر قصيرة (مشتقة أيضاً من التوكن)؛ غيرها يُهمل. الموضوع وكلمة السر يُرسلان
للمحرر بالخاص عبر البوت مرة واحدة، ولا يُكتبان في المستودع أو السجلات.
"""
import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.tg_push import api, load, SENT  # noqa: E402

SETUP = """📲 ربط إشعارات فيسبوك بالرصد (مرة واحدة)

١. نزّل تطبيق MacroDroid من Google Play.
٢. Add Macro ← Trigger: Notification ← Notification Received ← اختر تطبيق Facebook.
٣. Action: Connectivity ← HTTP Request:
   • Method: POST
   • URL: {url}
   • Content body (Text):
{pw} | [not_title] | [not_text]
   (الأقواس [not_title] و[not_text] تختارها من زر «…» بجانب الحقل: Notification Title / Notification Text)
٤. احفظ الماكرو وفعّله، واسمح للتطبيق بقراءة الإشعارات.
٥. من فيسبوك: تابع الصفحات المهمة ← الإشعارات ← «كل المنشورات».

بعدها كل إشعار يوصل الرصد خلال دقيقتين موسوماً «إشعار فيسبوك».
⚠️ لا تشارك هذا الرابط أو الكلمة مع أحد."""


import re  # noqa: E402

# خصوصية: لا يدخل الرصد إلا إشعار «صفحة نشرت». كل ما يخص حسابك الشخصي يُرمى ولا يُخزن أبداً.
PERSONAL = re.compile(r"(منشورك|منشورِك|صورتك|تعليقك|قصتك|على منشور لك|ذكرك|أشار إليك|اشار اليك|إشارة إليك|طلب صداقة|طلب الصداقة|صديق|أصدقاء|عيد ميلاد|ذكريات|"
                      r"أعجب|اعجب|تفاعل|رسالة|رسائل|مجموعة|حدث|دعاك|دعوة|سوق|Marketplace|your post|your photo|your comment|mentioned you|tagged you|"
                      r"friend|birthday|memories|reacted|liked|message|invited|group|event)", re.I)
POSTED = re.compile(r"(نشر|نشرت|شارك|شاركت|بث مباشر|بثاً مباشراً|أضاف|أضافت|posted|shared|is live|went live|added|updated)", re.I)


def allowed(page, text):
    """القائمة البيضاء في config/fb_pages.json (إن وُجدت) لها الأولوية؛ وإلا: «صفحة نشرت» وليس إشعاراً شخصياً."""
    try:
        wl = json.loads((ROOT / "config" / "fb_pages.json").read_text(encoding="utf-8")).get("pages", [])
    except Exception:  # noqa: BLE001
        wl = []
    blob = page + " " + text
    if PERSONAL.search(blob):
        return False
    if wl:
        return any(w and w in blob for w in wl)
    return bool(POSTED.search(blob))


def secrets(token):
    h = hashlib.sha256((token + "|rasid-fb").encode()).hexdigest()
    return "rasid-" + h[:24], h[24:30]


def main():
    token = os.environ.get("MARSAD_TG_BOT_TOKEN", "").strip()
    if not token:
        return
    topic, pw = secrets(token)
    sent = load(SENT, {})
    stats = {"new": 0, "rejected": 0}
    try:
        chats = list((sent.get("_editor_chats") or {}).values())
        if chats and not sent.get("_fb_setup_sent"):
            for c in chats[:1]:
                api(token, "sendMessage", chat_id=c, text=SETUP.format(url=f"https://ntfy.sh/{topic}", pw=pw), disable_web_page_preview="true")
            sent["_fb_setup_sent"] = True
            stats["setup_sent"] = True
        since = sent.get("_ntfy_since") or "12h"
        with urllib.request.urlopen(urllib.request.Request(f"https://ntfy.sh/{topic}/json?poll=1&since={since}",
                                                           headers={"User-Agent": "rasid"}), timeout=20) as r:
            lines = r.read().decode("utf-8", "replace").splitlines()
        items = []
        for ln in lines:
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            if ev.get("event") != "message":
                continue
            sent["_ntfy_since"] = ev["id"]
            msg = (ev.get("message") or "").strip()
            if not msg.startswith(pw):
                stats["rejected"] += 1
                continue
            parts = [p.strip() for p in msg[len(pw):].strip(" |").split("|", 1)]
            page, text = (parts[0], parts[1]) if len(parts) == 2 else ("فيسبوك", parts[0])
            if len(text) < 10 or not allowed(page, text):
                stats["filtered_private"] = stats.get("filtered_private", 0) + 1
                continue
            items.append({"source_id": "fb:notifications", "source_name": f"إشعار فيسبوك — {page[:60]}",
                          "url": f"https://fb-notification.hobi-ajel.local/{ev['id']}", "platform": "facebook_notif",
                          "title": text.split("\n")[0][:220], "text": text,
                          "published_utc": datetime.fromtimestamp(ev["time"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                          "date_confirmed": True})
        if items:
            from marsad import core
            con = core.connect()
            con.execute("INSERT OR IGNORE INTO sources(id, name, url, platform, category, region, lang, method, official, status, added_by) "
                        "VALUES('fb:notifications', 'إشعارات فيسبوك (هاتف المحرر)', 'https://www.facebook.com', 'facebook', 'إشعارات فيسبوك', 'العراق', 'ar', 'manual', 0, 'يعمل', 'MacroDroid')")
            core.ingest_batch(con, {"items": items})
            con.commit()
            stats["new"] = len(items)
        from tools.tg_push import SENT as _S
        _S.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        stats["error"] = f"{type(e).__name__}: {str(e).replace(token, '***').replace(topic, '<topic>')[:150]}"
    print(f"::notice title=fb_inbox::{json.dumps(stats, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
