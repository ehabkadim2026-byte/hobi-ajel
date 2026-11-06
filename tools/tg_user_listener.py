"""مستمع لحظي عبر حساب الرصد (رقم إيهاب الثاني) — يعمل كخيط داخل المسار السريع.

- يفك الجلسة المشفرة (tg_user.session.enc على إصدار fastlane) بمفتاح مشتق من سرّ البوت. لا يطبع الجلسة أبداً.
- يستمع لمنشورات القنوات المرصودة لحظة نزولها ويضعها في طابور PUSH، فتعالجها حلقة المسار السريع بنفس الفلاتر فوراً.
- يشترك بالقنوات بالتدريج: حد 8 قنوات كل جولة تشغيل (~6 ساعات) وبفاصل 3–6 دقائق، حتى لا يُعامل الحساب كبرنامج مزعج.
- لا يرسل أي رسالة من الحساب، ولا يتفاعل، ولا يغادر قنوات. عند أي خطأ يتوقف بهدوء ويبقى الفحص العادي (t.me/s) يعمل.
"""
import asyncio
import base64
import hashlib
import io
import os
import queue
import random
import subprocess
import tempfile
import threading
import time
from pathlib import Path

PUSH = queue.Queue()
WAKE = threading.Event()
STATUS = {"state": "off", "joined": 0, "join_errors": 0, "pushed": 0, "err": None}
VIEWS_CHANNEL = "akamedia_iq"
JOIN_PER_RUN = 15  # 05/11: توسيع 60 قناة؛ بفاصل 3–6 دقائق (آمن من حظر تلغرام)


def _key(token):
    return base64.urlsafe_b64encode(hashlib.sha256(("rasid-session:" + token).encode()).digest())


def _session(token):
    try:
        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run(["gh", "release", "download", "fastlane", "-p", "tg_user.session.enc", "-D", td, "--clobber"],
                               capture_output=True, timeout=60)
            p = Path(td) / "tg_user.session.enc"
            if r.returncode != 0 or not p.exists():
                return None
            from cryptography.fernet import Fernet
            return Fernet(_key(token)).decrypt(p.read_bytes()).decode()
    except Exception:  # noqa: BLE001
        return None


def _creds():
    import re
    raw = os.environ.get("TG_API_ID", "") + " " + os.environ.get("TG_API_HASH", "")
    h = re.search(r"\b[0-9a-fA-F]{32}\b", raw)
    i = re.search(r"\b\d{5,12}\b", re.sub(r"\b[0-9a-fA-F]{32}\b", " ", raw))
    return (int(i.group(0)), h.group(0)) if (h and i) else (None, None)


async def _run(token, channels, stop_at, views_cb=None):
    from telethon import TelegramClient, events
    from telethon.sessions import StringSession
    from telethon.tl.functions.channels import JoinChannelRequest
    from telethon.errors import FloodWaitError
    api_id, api_hash = _creds()
    ss = None
    for attempt in range(8):  # 07/11: تنزيل الجلسة فشل مرة عابرة فبقيت جلسة 6 ساعات بلا مستمع («no-session») — نعيد المحاولة
        ss = _session(token)
        if ss or not api_id:
            break
        STATUS.update(state=f"no-session-retry{attempt + 1}")
        await asyncio.sleep(min(30 * (attempt + 1), 120))
    if not (api_id and ss):
        STATUS.update(state="no-session")
        return
    client = TelegramClient(StringSession(ss), api_id, api_hash, device_model="Rasid Monitor", app_version="1.0")
    await client.connect()
    if not await client.is_user_authorized():
        STATUS.update(state="unauthorized")
        await client.disconnect()
        return
    wanted = {c.lower() for c in channels}
    joined = set()
    async for d in client.iter_dialogs():
        u = getattr(d.entity, "username", None)
        if u and getattr(d, "is_channel", False):
            joined.add(u.lower())
    STATUS.update(state="listening", joined=len(joined & wanted))

    @client.on(events.NewMessage(incoming=True))
    async def on_msg(ev):
        rx = time.time()  # لحظة الوصول (قبل تنزيل الصورة) لقياس «الرصد ← الإرسال»
        try:
            chat = await ev.get_chat()
            u = (getattr(chat, "username", None) or "").lower()
            if u not in wanted or not getattr(chat, "broadcast", False):
                return
            m = ev.message
            text = (m.message or "").strip()
            if not text and not m.photo:
                return  # صورة بلا نص تبقى: قد تكون كتاباً رسمياً (قراءة الوثيقة بالمسار السريع)
            img = None
            if m.photo:
                try:
                    b = io.BytesIO()
                    await client.download_media(m, file=b, thumb=-1)
                    img = b.getvalue() or None
                except Exception:  # noqa: BLE001
                    img = None
            PUSH.put({"ch": u, "id": m.id, "text": text, "t": m.date, "img_bytes": img, "img": None, "rx": rx})
            STATUS["pushed"] += 1
            WAKE.set()
        except Exception as e:  # noqa: BLE001
            STATUS["err"] = type(e).__name__

    # اشتراك تدريجي بالقنوات غير المشترك بها (الأهم أولاً حسب ترتيب القائمة)
    todo = [c for c in channels if c.lower() not in joined]
    n = 0
    next_views = time.time() + 120
    while time.time() < stop_at and client.is_connected():
        if views_cb and time.time() >= next_views:
            # مشاهدات منشورات قناتنا (قراءة فقط، القناة عامة): نتعلم أي نوع خبر وأي ساعة تجيب تفاعلاً — طلب إيهاب 05/11 (مقترح 6)
            next_views = time.time() + 1800
            try:
                rows = []
                for m in await client.get_messages(VIEWS_CHANNEL, limit=150):
                    if m.date and (m.message or m.photo):
                        rows.append({"id": m.id, "t": m.date.strftime("%Y-%m-%dT%H:%M:%SZ"), "views": m.views or 0,
                                     "fwd": m.forwards or 0, "text": (m.message or "")[:160]})
                threading.Thread(target=views_cb, args=(rows,), daemon=True).start()  # الرفع بخيط منفصل: لا يوقف استقبال المنشورات
                STATUS["views_at"] = time.strftime("%H:%M:%S", time.gmtime())
            except Exception as e:  # noqa: BLE001
                STATUS["views_err"] = type(e).__name__
        if todo and n < JOIN_PER_RUN:
            c = todo.pop(0)
            try:
                await client(JoinChannelRequest(c))
                n += 1
                STATUS["joined"] += 1
            except FloodWaitError as e:
                STATUS["join_errors"] += 1
                await asyncio.sleep(min(e.seconds + 5, 3600))
                continue
            except Exception:  # noqa: BLE001
                STATUS["join_errors"] += 1
            await asyncio.sleep(random.uniform(180, 360))
        else:
            await asyncio.sleep(30)
    await client.disconnect()
    STATUS["state"] = "stopped"


def start(token, channels, stop_at, views_cb=None):
    """يشغّل المستمع بخيط خلفي. يرجع فوراً؛ إن فشل لأي سبب يبقى المسار السريع يعمل بالفحص العادي."""
    def target():
        try:
            asyncio.run(_run(token, channels, stop_at, views_cb))
        except Exception as e:  # noqa: BLE001
            STATUS.update(state="crashed", err=type(e).__name__)
    try:
        import telethon  # noqa: F401
    except ImportError:
        STATUS["state"] = "no-telethon"
        return
    threading.Thread(target=target, daemon=True).start()


def drain():
    """يسحب كل ما وصل لحظياً: {قناة: [منشورات]}."""
    out = {}
    while True:
        try:
            p = PUSH.get_nowait()
        except queue.Empty:
            break
        out.setdefault(p.pop("ch"), []).append(p)
    WAKE.clear()
    return out
