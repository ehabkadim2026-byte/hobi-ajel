"""إرسال العاجل والمهم عن العراق والحشد إلى قناة/مجموعة تلغرام خاصة بالفريق، وموجز يومي الساعة 8 صباحاً بتوقيت بغداد.

التفعيل: سرّ MARSAD_TG_BOT_TOKEN في إعدادات GitHub (لا يوضع في الكود أو المحادثة).
معرّف القناة: MARSAD_TG_CHAT_ID (اختياري). إن لم يوجد، يكتشفه تلقائياً من آخر قناة/مجموعة أُضيف لها البوت مشرفاً
وكُتبت فيها رسالة، ويحفظه في data/tg_chat.json (مخبأ مع قاعدة البيانات).
كل حدث يُرسل مرة واحدة، ويُعاد فقط عند تطور جوهري (ارتفاع المستوى أو زيادة الجهات اثنتين فأكثر).
الحالة تُكتب في pwa/tg_status.json بلا توكن ولا معرّفات.
"""
import html as H
import json
import re
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
MAX_PER_RUN = 15
DEBUG = []
CHANNEL = "https://t.me/hassawassal"
RANK = {"عاجل": 3, "مهم": 2, "متابعة": 1}


def api(token, method, files=None, **params):
    if files:  # multipart لرفع صورة البطاقة
        b = uuid.uuid4().hex
        body = b""
        for k, v in params.items():
            body += f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
        for k, spec in files.items():
            fn, data = spec[0], spec[1]
            ctype = spec[2] if len(spec) > 2 else "image/jpeg"
            body += f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{fn}\"\r\nContent-Type: {ctype}\r\n\r\n".encode() + data + b"\r\n"
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
    """مرآة لما يظهر بالتطبيق كعاجل/مهم: العراق والحشد بكل مستويات عاجل ومهم، والمنطقة إذا المصدر نفسه وسمه عاجل."""
    seen = n.get("collected_utc")
    if not seen or datetime.fromisoformat(seen.replace("Z", "+00:00")) < now - timedelta(minutes=12):
        return False
    first = n.get("first_utc")  # أول نشر للخبر لدى أي مصدر مرصود: إذا انتشر قبل أكثر من 25 دقيقة فهو ليس «جديداً» للقناة
    if first and datetime.fromisoformat(first.replace("Z", "+00:00")) < now - timedelta(minutes=25):
        return False
    if n.get("about_iraq") or n.get("pmf"):
        return bool(n.get("source_flag")) or n.get("level") in ("عاجل", "مهم", "متابعة")
    return n.get("origin") != "أجنبي" and (bool(n.get("source_flag")) or n.get("level") in ("عاجل", "مهم"))


def meta_line(n):
    name, _ = src(n)
    meta = [name, bg(n.get("latest_utc")) + " بغداد", n.get("status") or "غير مؤكد"]
    if (n.get("n_sources") or 1) > 1:
        meta.append(f"{n['n_sources']} جهات")
    if n.get("pmf"):
        meta.append("الحشد الشعبي")
    return " · ".join(x for x in meta if x)


def is_breaking(n):
    """عاجل: وسمه المصدر عاجل، أو صنّفه النظام عاجل، أو تكرر نشره لدى 3 جهات فأكثر."""
    return rank(n) >= 3 or (n.get("n_sources") or 1) >= 3


VAGUE_RX = re.compile(r"(شاهد|بالفيديو|بالصور|فيديو|التفاصيل|تفاصيل|إليكم|اليكم|هذا ما|ماذا|لماذا|كيف|هكذا|إليك|اليك|تعرف|الكشف عن|كشف عن|مفاجأة|\?|؟|…|\.\.\.?$)")


def is_vague(title):
    """عنوان مبهم لا يكفي وحده: قصير، أو بصيغة «شاهد/التفاصيل/ماذا…»، أو ينتهي بنقطتين."""
    t = (title or "").strip()
    words = len(t.split())
    return words < 7 or bool(VAGUE_RX.search(t)) or t.endswith(":")


def fmt(n, update=False):
    """الخبر فقط، وأسفله دعوة القناة. رابط المصدر يُضاف فقط للعناوين المبهمة."""
    mark = "🔴 عاجل | " if is_breaking(n) else ""
    _, url = src(n)
    more = f"\n\n🔗 التفاصيل: {H.escape(url)}" if (url and is_vague(n["title"]) and "news.google.com" not in url) else ""
    return f"<b>{mark}{H.escape(n['title'][:800])}</b>{more}\n\nزورونا على الرابط للأخبار العاجلة 👇\n{CHANNEL}"


CARDS = PWA / "cards"
PENDING = DATA / "tg_pending.json"


def prepare_card(n):
    """يصنع بطاقة الخبر (صورة المصدر أو خلفية الهوية) ويحفظها في pwa/cards ليُنشر رابطها مع موقع التطبيق."""
    from tools import tg_card
    _, url = src(n)
    img = tg_card.find_image(url)
    DEBUG.append(f"{urllib.parse.urlparse(url).netloc}:{'img' if img else 'noimg'}")
    photo = None
    if img:
        try:
            photo = tg_card.fetch_jpeg(img)
        except Exception as e:  # noqa: BLE001
            DEBUG.append(f"imgfail:{type(e).__name__}")
    jpg = tg_card.news_card2(photo, n["title"], is_breaking(n), n.get("first_utc") or n.get("latest_utc"))
    CARDS.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9_]", "", n["id"])[:40] + f"_{int(datetime.now(timezone.utc).timestamp())}.jpg"
    (CARDS / name).write_bytes(jpg)
    return name, "source" if photo else "card"


def url_ok(u, timeout=6):
    try:
        req = urllib.request.Request(u, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def send_pending(token, chat_id):
    """بعد نشر الموقع: رسالة نصية قابلة للنسخ بالكامل، وصورة البطاقة كبيرة فوق النص (معاينة الرابط).
    إذا لم يصبح رابط البطاقة متاحاً خلال المهلة نرسلها صورةً مع تعليق (احتياط)."""
    import time as _t
    pend = load(PENDING, [])
    done = {"preview": 0, "photo": 0, "text": 0}
    deadline = _t.time() + 60
    for p in pend:
        cu = APP_URL + "cards/" + p["card"]
        ok = False
        while _t.time() < deadline:
            if url_ok(cu):
                ok = True
                break
            _t.sleep(4)
        try:
            if ok:
                api(token, "sendMessage", chat_id=chat_id, text=p["text"], parse_mode="HTML",
                    link_preview_options=json.dumps({"url": cu, "prefer_large_media": True, "show_above_text": True}))
                done["preview"] += 1
            else:
                api(token, "sendPhoto", files={"photo": (p["card"], (CARDS / p["card"]).read_bytes())}, chat_id=chat_id, caption=p["text"][:1024], parse_mode="HTML")
                done["photo"] += 1
        except Exception as e:  # noqa: BLE001
            DEBUG.append(f"sendfail:{type(e).__name__}:{str(e)[:60]}")
            try:
                api(token, "sendMessage", chat_id=chat_id, text=p["text"], parse_mode="HTML", disable_web_page_preview="true")
                done["text"] += 1
            except Exception:  # noqa: BLE001
                pass
    PENDING.write_text("[]", encoding="utf-8")
    return done


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


def watch_alerts(token, sent, news, now):
    """تنبيهات قوائم المتابعة بالخاص للمحررين (لا للقناة العامة): حدث واحد = تنبيه واحد، وتحديث واحد إذا صار عاجلاً."""
    chats = list((sent.get("_editor_chats") or {}).values())
    if not chats:
        return {"chats": 0}
    try:
        names = {f["id"]: f["name"] for f in json.loads((ROOT / "config" / "follow.json").read_text(encoding="utf-8"))["follow"]}
    except Exception:  # noqa: BLE001
        names = {}
    wa = sent.setdefault("_walert", {})
    n_sent = 0
    for n in sorted(news, key=lambda n: n.get("collected_utc") or ""):
        hits = n.get("watch") or []
        if not hits:
            continue
        seen = n.get("collected_utc")
        if not seen or datetime.fromisoformat(seen.replace("Z", "+00:00")) < now - timedelta(minutes=15):
            continue
        direct = any(h.get("prov") in ("رصد مباشر", "إدخال يدوي") for h in hits)
        worthy_w = direct or is_breaking(n) or n.get("level") in ("عاجل", "مهم") or n.get("vstatus") == "متنازع عليه"
        if not worthy_w:
            continue
        prev = wa.get(n["id"])
        upd = prev is not None
        if prev and (prev.get("b") or not is_breaking(n)):
            continue
        tags = " · ".join(dict.fromkeys(names.get(h["id"], h["id"]) for h in hits))
        prov = next((h["prov"] for h in hits if h.get("prov")), "رصد موضوعي")
        _, url = src(n)
        txt = (f"{'🔁 تحديث | ' if upd else ''}👁 <b>{H.escape(tags)}</b>\n{'🔴 ' if is_breaking(n) else ''}{H.escape(n['title'][:500])}\n\n"
               f"{H.escape(prov)} · {H.escape(n.get('vstatus') or '')} · {H.escape(src(n)[0])} · {bg(n.get('latest_utc'))} بغداد"
               + (f"\n🔗 <a href=\"{H.escape(url, quote=True)}\">المصدر</a>" if url else "") + f"\n🆔 {n['id']}")
        for c in chats:
            try:
                api(token, "sendMessage", chat_id=c, text=txt, parse_mode="HTML", disable_web_page_preview="true")
            except Exception:  # noqa: BLE001
                pass
        wa[n["id"]] = {"t": now.timestamp(), "b": is_breaking(n)}
        n_sent += 1
        if n_sent >= 12:
            break
    # ملخص المتابعة اليومي 8 صباحاً بغداد
    bgd = now + timedelta(hours=3)
    today = bgd.strftime("%Y-%m-%d")
    if bgd.hour == 8 and sent.get("_wdigest") != today:
        day = [n for n in news if n.get("watch") and n.get("latest_utc") and datetime.fromisoformat(n["latest_utc"].replace("Z", "+00:00")) >= now - timedelta(hours=24)]
        by = {}
        for n in day:
            for h in n["watch"]:
                by.setdefault(h["id"], []).append(n)
        lines = [f"👁 ملخص قوائم المتابعة — {bgd.strftime('%Y/%m/%d')}", ""]
        for wid, lst in sorted(by.items(), key=lambda kv: -len(kv[1]))[:15]:
            lst = sorted(lst, key=lambda n: (-(n.get("n_sources") or 1)))[:3]
            lines.append(f"<b>{H.escape(names.get(wid, wid))}</b> — {len(by[wid])} حدث")
            for n in lst:
                _, u = src(n)
                lines.append(f"• <a href=\"{H.escape(u, quote=True)}\">{H.escape(n['title'][:120])}</a> ({H.escape(n.get('vstatus') or '')})" if u else f"• {H.escape(n['title'][:120])}")
            lines.append("")
        lines.append(f"التفاصيل: {APP_URL}#watch")
        for c in chats:
            try:
                api(token, "sendMessage", chat_id=c, text="\n".join(lines)[:4000], parse_mode="HTML", disable_web_page_preview="true")
            except Exception:  # noqa: BLE001
                pass
        sent["_wdigest"] = today
    return {"chats": len(chats), "sent": n_sent}


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
        chat_id = os.environ.get("MARSAD_TG_CHAT_ID", "").strip() or chat.get("id") or "@hassawassal"  # القناة عامة: اسمها يكفي
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
        status["chat_title"] = chat.get("title") or "عاجل هسه وصل"
        news = load(PWA / "news.json", [])
        sent = load(SENT, {})
        first_run = not sent.get("_init")
        out = []
        for n in sorted(news, key=lambda n: n.get("collected_utc") or ""):
            prev = sent.get(n["id"])
            if prev is None:
                if worthy(n, now):
                    out.append((n, False))
            elif is_breaking(n) and not prev.get("b", prev.get("r", 0) >= 3 or prev.get("n", 1) >= 3):
                # خبر نُشر سابقاً ثم تكرر لدى 3 جهات فأكثر: يُعاد مرة واحدة بوسم عاجل
                lu = n.get("latest_utc")
                if lu and datetime.fromisoformat(lu.replace("Z", "+00:00")) >= now - timedelta(minutes=15):
                    out.append((n, True))
        status["candidates"] = len(out)
        if first_run:  # أول تشغيل: لا نغرق القناة بالقديم؛ نرسل رسالة ترحيب ونعلّم الموجود كمُرسل
            for n, _ in out:
                sent[n["id"]] = {"r": rank(n), "n": n.get("n_sources") or 1, "t": now.timestamp()}
            sent["_init"] = True
            out = []
        status["images"] = {}
        pend = []
        # العاجل أولاً ثم الأحدث
        for n, upd in sorted(out[-MAX_PER_RUN:], key=lambda x: (not is_breaking(x[0]), x[0].get("collected_utc") or "")):
            try:
                card, kind = prepare_card(n)
            except Exception as e:  # noqa: BLE001
                DEBUG.append(f"cardfail:{type(e).__name__}")
                continue
            status["images"][kind] = status["images"].get(kind, 0) + 1
            pend.append({"id": n["id"], "card": card, "text": fmt(n, upd)})
            sent[n["id"]] = {"r": rank(n), "n": n.get("n_sources") or 1, "t": now.timestamp(), "b": is_breaking(n)}
            status["sent_now"] += 1
        PENDING.write_text(json.dumps(pend, ensure_ascii=False), encoding="utf-8")
        SENT.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")
        # موجز 8 صباحاً بغداد، مرة واحدة يومياً
        bgd = now + timedelta(hours=3)
        today = bgd.strftime("%Y-%m-%d")
        if bgd.hour == 8 and sent.get("_digest") != today:
            api(token, "sendMessage", chat_id=chat_id, text=digest(news, now), disable_web_page_preview="true")
            sent["_digest"] = today
            status["digest"] = today
        status["watch_alerts"] = watch_alerts(token, sent, news, now)
        cut = now.timestamp() - 3 * 86400
        sent = {k: v for k, v in sent.items() if k.startswith("_") or v.get("t", 0) >= cut}
        wa = sent.get("_walert", {})
        sent["_walert"] = {k: v for k, v in wa.items() if v.get("t", 0) >= cut}
        SENT.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if token:
            msg = msg.replace(token, "***")
        status["error"] = f"{type(e).__name__}: {msg}"[:200]
    status["img_debug"] = DEBUG[-12:]
    STATUS.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    print({k: v for k, v in status.items()})


def send_main():
    token = os.environ.get("MARSAD_TG_BOT_TOKEN", "").strip()
    if not token:
        return
    chat = load(CHAT, {})
    chat_id = os.environ.get("MARSAD_TG_CHAT_ID", "").strip() or chat.get("id") or "@hassawassal"
    try:
        r = send_pending(token, chat_id)
    except Exception as e:  # noqa: BLE001
        r = {"error": f"{type(e).__name__}: {str(e).replace(token, '***')[:150]}"}
    print(f"::notice title=tg_send::{json.dumps({**r, 'debug': DEBUG[-6:]}, ensure_ascii=False)}")


if __name__ == "__main__":
    if "--send" in sys.argv:
        send_main()
    else:
        main()
