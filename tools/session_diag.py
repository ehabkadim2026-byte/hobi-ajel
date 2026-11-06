"""تشخيص جلسة حساب الرصد (بلا طباعة أسرار): هل تنزل، تُفك، والحساب مخوّل؟"""
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import tg_user_listener as UL
tok = os.environ.get("MARSAD_TG_BOT_TOKEN", "")
api_id, api_hash = UL._creds()
print("creds:", bool(api_id), bool(api_hash), "token:", bool(tok))
ss = UL._session(tok)
print("session:", "ok" if ss else "NONE")
if ss and api_id:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    async def m():
        c = TelegramClient(StringSession(ss), api_id, api_hash)
        await c.connect()
        print("authorized:", await c.is_user_authorized())
        await c.disconnect()
    asyncio.run(m())
