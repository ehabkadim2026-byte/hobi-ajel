"""ربط حساب الرصد (رقم إيهاب الثاني) بالباركود — مرة واحدة.

يولّد باركود دخول تلغرام ويرسله لمشرفي القناة بالخاص عبر البوت. إيهاب يصوّره من تطبيق الرقم الثاني
(الإعدادات ← الأجهزة ← ربط جهاز). لا رمز ولا كلمة سر تمر بهذا السكربت.
الجلسة تُشفّر بمفتاح مشتق من سرّ البوت وتُرفع لإصدار fastlane باسم tg_user.session.enc — لا تُطبع في السجلات أبداً.
"""
import asyncio
import base64
import hashlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import qrcode  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402
from telethon import TelegramClient  # noqa: E402
from telethon.errors import SessionPasswordNeededError  # noqa: E402
from telethon.sessions import StringSession  # noqa: E402

from tools.tg_push import api  # noqa: E402

TOKEN = os.environ["MARSAD_TG_BOT_TOKEN"].strip()
CHAT = os.environ.get("MARSAD_TG_CHAT_ID", "").strip() or "-1004327422297"
import re  # noqa: E402

_RAW = os.environ.get("TG_API_ID", "") + " " + os.environ.get("TG_API_HASH", "")
_h = re.search(r"\b[0-9a-fA-F]{32}\b", _RAW)
_i = re.search(r"\b\d{5,12}\b", re.sub(r"\b[0-9a-fA-F]{32}\b", " ", _RAW))
if not (_h and _i):
    print("::error::لم يُعثر على api_id (رقم) و api_hash (32 حرفاً) في الأسرار — راجع القيم")
    sys.exit(3)
API_ID, API_HASH = int(_i.group(0)), _h.group(0)  # يتحمل تبديل الخانتين أو لصق نص زائد مع القيمة


def key():
    return base64.urlsafe_b64encode(hashlib.sha256(("rasid-session:" + TOKEN).encode()).digest())


def admins():
    adm = api(TOKEN, "getChatAdministrators", chat_id=CHAT).get("result", [])
    return [a["user"]["id"] for a in adm if not a["user"].get("is_bot")]


def dm(text, photo=None):
    for uid in admins():
        try:
            if photo:
                api(TOKEN, "sendPhoto", files={"photo": ("qr.png", photo)}, chat_id=uid, caption=text[:1000])
            else:
                api(TOKEN, "sendMessage", chat_id=uid, text=text[:4000])
        except Exception:  # noqa: BLE001
            pass


def qr_png(url):
    img = qrcode.make(url, box_size=10, border=3)
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


async def main():
    client = TelegramClient(StringSession(), API_ID, API_HASH, device_model="Rasid Monitor", app_version="1.0")
    await client.connect()
    qr = await client.qr_login()
    ok = False
    for attempt in range(6):
        dm("🔐 ربط حساب الرصد — المحاولة " + str(attempt + 1) + "/6\n"
           "من تلغرام الرقم الثاني: الإعدادات ← الأجهزة ← ربط جهاز سطح مكتب، وصوّر هذا الباركود خلال 25 ثانية.\n"
           "إذا انتهى الوقت يوصلك باركود جديد تلقائياً.", qr_png(qr.url))
        try:
            await qr.wait(timeout=28)
            ok = True
            break
        except SessionPasswordNeededError:
            dm("⚠️ الرقم الثاني عليه «التحقق بخطوتين» (كلمة سر). ما ندخل كلمات سر بالنظام. "
               "أطفِه مؤقتاً من تلغرام الرقم الثاني (الإعدادات ← الخصوصية والأمان ← التحقق بخطوتين) وگول لـ Claude يعيد الربط، وبعدها رجّعه.")
            await client.disconnect()
            return 2
        except asyncio.TimeoutError:
            await qr.recreate()
    if not ok:
        dm("⌛ ما تم تصوير الباركود. گول لـ Claude يعيد المحاولة.")
        await client.disconnect()
        return 1
    me = await client.get_me()
    enc = Fernet(key()).encrypt(client.session.save().encode())
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "tg_user.session.enc"
        p.write_bytes(enc)
        subprocess.run(["gh", "release", "upload", "fastlane", str(p), "--clobber"], check=True, capture_output=True, timeout=60)
    dm(f"✅ تم ربط حساب الرصد ({me.first_name or ''}). الحساب راح يشترك بالقنوات بالتدريج ويبدي يستلم الأخبار لحظة نزولها.")
    await client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
