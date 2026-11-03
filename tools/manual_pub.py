"""النشر اليدوي الفوري للمحررين (مشرفي القناة) عبر البوت بالخاص:

/نشر <العنوان>            ← بطاقة «شاشة الحدث» بالقناة خلال ثوانٍ
/عاجل <العنوان>           ← نفسه لكن عاجل يومض
سطر اختياري: «المصدر: الجهة»  ← يظهر بالبطاقة والتعليق
صورة مرفقة وتعليقها يبدأ بالأمر ← تُستخدم صورةً للبطاقة

يعمل من حلقة المسار السريع (كل ~10 ثوانٍ، يقرأ الرسائل دون تأكيدها) ومن صندوق المحررين بالجولة الرئيسية احتياطاً.
المعالَج يُسجل في manual_done.json على إصدار fastlane حتى لا يُنشر مرتين. لا يقبل إلا من مشرفي القناة.
"""
import html as H
import json
import re
import time
import urllib.request
from datetime import datetime, timezone

CMD = re.compile(r"^/(نشر|عاجل)(?:@\w+)?\s*", re.S)


def is_cmd(m):
    return bool(CMD.match((m.get("text") or m.get("caption") or "").strip()))


def _photo(token, api, m):
    ph = m.get("photo")
    if not ph:
        return None
    try:
        fid = sorted(ph, key=lambda p: p.get("file_size") or 0)[-1]["file_id"]
        path = api(token, "getFile", file_id=fid)["result"]["file_path"]
        return urllib.request.urlopen(f"https://api.telegram.org/file/bot{token}/{path}", timeout=20).read()
    except Exception:  # noqa: BLE001
        return None


def publish(token, chat_id, m, editor_name="محرر"):
    """ينشر رسالة المحرر. يرجع (ok, رسالة للمحرر)."""
    from tools import tg_push as T, tg_card
    from tools.editorial import edit_headline
    raw = (m.get("text") or m.get("caption") or "").strip()
    mm = CMD.match(raw)
    if not mm:
        return False, ""
    hot = mm.group(1) == "عاجل"
    body = raw[mm.end():].strip()
    src = None
    lines = []
    for ln in body.split("\n"):
        s = ln.strip()
        if not s:
            continue
        g = re.match(r"^(?:المصدر|مصدر)\s*[:：]\s*(.+)$", s)
        if g:
            src = g.group(1).strip()[:60]
        else:
            lines.append(s)
    if not lines or len(lines[0].split()) < 4:
        return False, "الصيغة: /نشر عنوان الخبر (4 كلمات فأكثر)\nسطر اختياري: المصدر: الجهة\nوللعاجل: /عاجل بدل /نشر. وتكدر ترفق صورة وتكتب الأمر بتعليقها."
    head = lines[0][:220]
    try:
        head = edit_headline(head, context=" ".join(lines)[:500]) or head
    except Exception:  # noqa: BLE001
        pass
    sig = T.title_sig(head)
    recent = [x for x in T.fastlane_sigs() + T.fastlane_sigs("main_sigs.json") + T.fastlane_sigs("tv_sigs.json") if x.get("ts", 0) >= time.time() - 6 * 3600]
    if any(T.same_story(sig, x) for x in recent):
        return False, "⚠️ هذا الخبر منشور بالقناة خلال آخر 6 ساعات، فما نشرته حتى ما يتكرر. إذا بيه تطور جديد اكتب العنوان بالتفصيل الجديد."
    photo = _photo(token, T.api, m)
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    card = tg_card.card_news4(photo, head, hot, when, source=src, style="A")
    extra = "\n".join(lines[1:3])
    cap = f"<b>{'🔴 عاجل | ' if hot else ''}{H.escape(head)}</b>" + (f"\n{H.escape(extra)}" if extra else "") + \
          (f"\n\n📌 المصدر: {H.escape(src)}" if src else "") + f"\n\nزورونا على الرابط للأخبار العاجلة 👇\n{T.CHANNEL}"
    kb = json.dumps({"inline_keyboard": [[{"text": "↗️ شارك القناة", "url": "https://t.me/share/url?url=https%3A%2F%2Ft.me%2Fhassawassal"}]]})
    r = {"ok": False}
    if hot:
        try:
            anim = tg_card.breaking_anim(photo, head, when, style="news4A", source=src)
            r = T.api(token, "sendAnimation", files={"animation": ("breaking.mp4", anim, "video/mp4")}, chat_id=chat_id, caption=cap[:1024],
                      parse_mode="HTML", reply_markup=kb, width="1080", height="1350", disable_notification="false")
        except Exception:  # noqa: BLE001
            r = {"ok": False}
    if not r.get("ok"):
        r = T.api(token, "sendPhoto", files={"photo": ("card.jpg", card)}, chat_id=chat_id, caption=cap[:1024], parse_mode="HTML",
                  reply_markup=kb, disable_notification="false" if hot else "true")
    if not r.get("ok"):
        return False, "تعذر النشر: " + str(r.get("description"))[:100]
    entry = {"w": sorted(sig[0]), "d": sorted(sig[1]), "ts": time.time(), "id": f"manual:{m.get('message_id')}", "title": head[:200], "by": editor_name}
    T.publish_main_sigs([x for x in T.fastlane_sigs("tv_sigs.json")] + [entry], "tv_sigs.json")  # بصمة مشتركة: لا يكرره أي مسار
    return True, f"✅ نُشر بالقناة ({'عاجل يومض' if hot else 'خبر'}): {head}"


def done_ids():
    from tools.tg_push import fastlane_sigs
    d = fastlane_sigs("manual_done.json")
    return set(d) if isinstance(d, list) else set()


def mark_done(ids):
    import subprocess
    import tempfile
    from pathlib import Path
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "manual_done.json"
            p.write_text(json.dumps(sorted(ids)[-500:]), encoding="utf-8")
            subprocess.run(["gh", "release", "upload", "fastlane", str(p), "--clobber"], capture_output=True, timeout=25)
    except Exception:  # noqa: BLE001
        pass


_ED = {"t": 0, "ids": {}}


def editors(token, chat_id):
    from tools.tg_push import api
    if time.time() - _ED["t"] > 3600:
        try:
            adm = api(token, "getChatAdministrators", chat_id=chat_id).get("result", [])
            _ED["ids"] = {str(a["user"]["id"]): a["user"].get("first_name") or "محرر" for a in adm if not a["user"].get("is_bot")}
            _ED["t"] = time.time()
        except Exception:  # noqa: BLE001
            pass
    return _ED["ids"]


def poll(token, chat_id, seen):
    """من حلقة المسار السريع: يقرأ الرسائل المعلقة بلا تأكيد (offset) حتى يبقى صندوق المحررين يستلمها، وينشر أوامر /نشر و/عاجل فوراً."""
    from tools.tg_push import api
    try:
        ups = api(token, "getUpdates", timeout=0, limit=100, allowed_updates=json.dumps(["message"])).get("result", [])
    except Exception:  # noqa: BLE001
        return 0
    eds = None
    n = 0
    for u in ups:
        m = u.get("message") or {}
        if (m.get("chat") or {}).get("type") != "private" or not is_cmd(m):
            continue
        key = f"{m['chat']['id']}:{m['message_id']}"
        if key in seen:
            continue
        eds = eds if eds is not None else editors(token, chat_id)
        uid = str((m.get("from") or {}).get("id"))
        seen.add(key)
        if uid not in eds:
            continue
        ok, msg = publish(token, chat_id, m, eds.get(uid, "محرر"))
        n += int(ok)
        try:
            api(token, "sendMessage", chat_id=m["chat"]["id"], reply_to_message_id=m["message_id"], text=msg[:1000])
        except Exception:  # noqa: BLE001
            pass
        mark_done(seen)
    return n
