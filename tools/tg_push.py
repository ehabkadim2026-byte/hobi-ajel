"""إرسال العاجل والمهم عن العراق والحشد إلى قناة/مجموعة تلغرام خاصة بالفريق، وموجز يومي الساعة 8 صباحاً بتوقيت بغداد.

التفعيل: سرّ MARSAD_TG_BOT_TOKEN في إعدادات GitHub (لا يوضع في الكود أو المحادثة).
معرّف القناة: MARSAD_TG_CHAT_ID (اختياري). إن لم يوجد، يكتشفه تلقائياً من آخر قناة/مجموعة أُضيف لها البوت مشرفاً
وكُتبت فيها رسالة، ويحفظه في data/tg_chat.json (مخبأ مع قاعدة البيانات).
كل حدث يُرسل مرة واحدة، ويُعاد فقط عند تطور جوهري (ارتفاع المستوى أو زيادة الجهات اثنتين فأكثر).
الحالة تُكتب في pwa/tg_status.json بلا توكن ولا معرّفات.
"""
import html as H
import json
import os
import uuid
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PWA = ROOT / "pwa"
SENT = DATA / "tg_sent.json"
CHAT = DATA / "tg_chat.json"
STATUS = PWA / "tg_status.json"
APP_URL = "https://ehabkadim2026-byte.github.io/hobi-ajel/"
MAX_PER_RUN = 10
CHANNEL = "https://t.me/hassawassal"
RANK = {"عاجل": 3, "مهم": 2, "متابعة": 1}


def api(token, method, files=None, **params):
    if files:  # multipart لرفع صورة البطاقة
        b = uuid.uuid4().hex
        body = b""
        for k, v in params.items():
            body += f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        for k, (fn, data) in files.items():
            body += f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fn}\"\r\nContent-Type: image/jpeg\r\n\r\n".encode() + data + b"\r\n"
        body += f"--{b}--\r\n".encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=body,
                                     headers={"Content-Type": f"multipart/form-data; boundary={b}"})
    else:
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=urllib.parse.urlencode(params).encode())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def load(p, d):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def bg(iso):
    if not iso:
        return ""
    d = datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(hours=3)
    return d.strftime("%H:%M")


def src(n):
    s = (n.get("sources") or [{}])[0]
    name = (s.get("name") or "").replace(" — telegram", "").replace(" — RSS", "").replace(" (عبر Google News)", "")
    return name, s.get("url") or ""


def rank(n):
    return 3 if n.get("source_flag") else RANK.get(n.get("level"), 0)


def worthy(n, now):
    """العراق والحشد فقط. عاجل المصدر أو عاجل النظام يُرسل فوراً؛ المهم يحتاج جهة رسمية أو جهتين."""
    if not (n.get("about_iraq") or n.get("pmf")):
        return False
    seen = n.get("collected_utc")
    if not seen or datetime.fromisoformat(seen.replace("Z", "+00:00")) < now - timedelta(minutes=20):
        return False
    ns = n.get("n_sources") or 1
    official = n.get("status") == "مؤكد"
    if n.get("source_flag") or n.get("level") == "عاجل":
        return True
    if n.get("level") == "مهم" and (official or ns >= 2 or n.get("pmf")):
        return True
    return False


def meta_line(n):
    name, _ = src(n)
    meta = [name, bg(n.get("latest_utc")) + " بغداد", n.get("status") or "غير مؤكد"]
    if (n.get("n_sources") or 1) > 1:
        meta.append(f"{n['n_sources']} جهات")
    if n.get("pmf"):
        meta.append("الحشد الشعبي")
    return " · ".join(x for x in meta if x)


def fmt(n, update=False):
    """نص المنشور (HTML، أقل من 1024 حرفاً ليصلح تعليقاً على الصورة)."""
    _, url = src(n)
    head = "🔴 عاجل" if rank(n) >= 3 else "🟠 مهم"
    if update:
        head = "🔁 تحديث | " + head
    title = n["title"][:600]
    lines = [f"{head}", f"<b>{H.escape(title)}</b>"]
    if n.get("title_orig"):
        lines.append(f"<i>{H.escape(n['title_orig'][:220])}</i> — ترجمة آلية")
    lines.append("")
    lines.append(H.escape(meta_line(n)))
    if url:
        lines.append(f'🔗 <a href="{H.escape(url, quote=True)}">المصدر</a>')
    lines.append(f'📡 <a href="{CHANNEL}">عاجل هسه وصل</a> | {CHANNEL.replace("https://", "")}')
    return "\n".join(lines)


def post(token, chat_id, n, upd):
    """صورة المنشور الأصلي إن وُجدت، وإلا بطاقة بالعنوان، وإلا نص فقط."""
    from tools import tg_card
    cap = fmt(n, upd)
    _, url = src(n)
    img = tg_card.find_image(url)
    if img:
        try:
            api(token, "sendPhoto", chat_id=chat_id, photo=img, caption=cap, parse_mode="HTML")
            return "source"
        except Exception:  # noqa: BLE001
            pass
    try:
        head = "عاجل" if rank(n) >= 3 else "مهم"
        jpg = tg_card.card(n["title"], head, meta_line(n), CHANNEL.replace("https://", ""))
        api(token, "sendPhoto", files={"photo": ("hobi.jpg", jpg)}, chat_id=chat_id, caption=cap, parse_mode="HTML")
        return "card"
    except Exception:  # noqa: BLE001
        api(token, "sendMessage", chat_id=chat_id, text=cap, parse_mode="HTML", disable_web_page_preview="true")
        return "text"


def digest(news, now):
    day = [n for n in news if n.get("latest_utc") and datetime.fromisoformat(n["latest_utc"].replace("Z", "+00:00")) >= now - timedelta(hours=24)]
    top = sorted([n for n in day if n.get("about_iraq") and n.get("origin") != "أجنبي"],
                 key=lambda n: (-(n.get("n_sources") or 1), -rank(n)))[:10]
    pmf = sorted([n for n in day if n.get("pmf")], key=lambda n: -(n.get("n_sources") or 1))[:4]
    frn = sorted([n for n in day if n.get("origin") == "أجنبي"], key=lambda n: n.get("latest_utc") or "", reverse=True)[:4]
    d = (now + timedelta(hours=3)).strftime("%Y/%m/%d")
    out = [f"🗞 موجز هوبي عاجل — {d}", "", "أبرز أحداث العراق خلال 24 ساعة (حسب عدد الجهات الناشرة):"]
    for i, n in enumerate(top, 1):
        out.append(f"{i}. {n['title']} — {n.get('n_sources') or 1} جهات")
    if pmf:
        out += ["", "الحشد الشعبي:"] + [f"• {n['title']}" for n in pmf]
    if frn:
        out += ["", "الصحافة الأجنبية عن العراق (ترجمة آلية):"] + [f"• {n['title']} — {src(n)[0]}" for n in frn]
    out += ["", "كثرة الجهات تعني انتشاراً لا تأكيداً.", f"التفاصيل والمصادر: {APP_URL}", f"📡 تابعونا: {CHANNEL}"]
    return "\n".join(out)[:4000]


def main():
    now = datetime.now(timezone.utc)
    status = {"enabled": False, "updated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "sent_now": 0, "candidates": 0, "chat_title": None, "error": None}
    token = os.environ.get("MARSAD_TG_BOT_TOKEN", "").strip()
    if not token:
        status["error"] = "غير مفعّل: أضف السر MARSAD_TG_BOT_TOKEN في إعدادات GitHub"
        STATUS.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
        print(status)
        return
    try:
        chat = load(CHAT, {})
        chat_id = os.environ.get("MARSAD_TG_CHAT_ID", "").strip() or chat.get("id")
        if not chat_id:
            ups = api(token, "getUpdates", timeout=0).get("result", [])
            for u in reversed(ups):
                c = (u.get("channel_post") or u.get("message") or (u.get("my_chat_member") or {}) or {}).get("chat") or {}
                if c.get("type") in ("channel", "supergroup", "group"):
                    chat = {"id": c["id"], "title": c.get("title")}
                    CHAT.write_text(json.dumps(chat, ensure_ascii=False), encoding="utf-8")
                    chat_id = c["id"]
                    break
        if not chat_id:
            status["error"] = "البوت شغّال بس ما لكى قناة: أضفه مشرفاً للقناة واكتب فيها أي رسالة"
            STATUS.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
            print(status)
            return
        status["enabled"] = True
        status["chat_title"] = chat.get("title")
        news = load(PWA / "news.json", [])
        sent = load(SENT, {})
        first_run = not sent.get("_init")
        out = []
        for n in sorted(news, key=lambda n: n.get("collected_utc") or ""):
            if not worthy(n, now):
                continue
            prev = sent.get(n["id"])
            if prev is None:
                out.append((n, False))
            elif rank(n) > prev["r"] or (n.get("n_sources") or 1) >= prev["n"] + 2:
                out.append((n, True))
        status["candidates"] = len(out)
        if first_run:  # أول تشغيل: لا نغرق القناة بالقديم؛ نرسل رسالة ترحيب ونعلّم الموجود كمُرسل
            for n, _ in out:
                sent[n["id"]] = {"r": rank(n), "n": n.get("n_sources") or 1, "t": now.timestamp()}
            api(token, "sendMessage", chat_id=chat_id, text="✅ تم ربط قناة الفريق بمنصة «هوبي عاجل». من الآن تصلكم هنا الأخبار العاجلة والمهمة عن العراق والحشد الشعبي فور رصدها، وموجز يومي الساعة 8 صباحاً.\n" + APP_URL)
            sent["_init"] = True
            out = []
        status["images"] = {}
        for n, upd in out[-MAX_PER_RUN:]:
            kind = post(token, chat_id, n, upd)
            status["images"][kind] = status["images"].get(kind, 0) + 1
            sent[n["id"]] = {"r": rank(n), "n": n.get("n_sources") or 1, "t": now.timestamp()}
            status["sent_now"] += 1
            SENT.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")
        # موجز 8 صباحاً بغداد، مرة واحدة يومياً
        bgd = now + timedelta(hours=3)
        today = bgd.strftime("%Y-%m-%d")
        if bgd.hour == 8 and sent.get("_digest") != today:
            api(token, "sendMessage", chat_id=chat_id, text=digest(news, now), disable_web_page_preview="true")
            sent["_digest"] = today
            status["digest"] = today
        cut = now.timestamp() - 3 * 86400
        sent = {k: v for k, v in sent.items() if k.startswith("_") or v.get("t", 0) >= cut}
        SENT.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if token:
            msg = msg.replace(token, "***")
        status["error"] = f"{type(e).__name__}: {msg}"[:200]
    STATUS.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    print({k: v for k, v in status.items()})


if __name__ == "__main__":
    main()
