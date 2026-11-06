"""النشر اليدوي الفوري للمحررين (مشرفي القناة) عبر البوت بالخاص:

/نشر <العنوان>            ← بطاقة «شاشة الحدث» بالقناة خلال ثوانٍ
/عاجل <العنوان>           ← نفسه لكن عاجل يومض
سطر اختياري: «المصدر: الجهة»  ← يظهر بالبطاقة والتعليق
صورة مرفقة وتعليقها يبدأ بالأمر ← تُستخدم صورةً للبطاقة

«بوابة المراسل» (بلا أمر): المحرر يرسل للبوت بالخاص بصمة صوتية (≤60 ث)، أو صورة كتاب/بيان رسمي (بتعليق أو بدونه)، أو ملاحظات نصية خام.
خلال ثوانٍ يفرّغ الصوت/يقرأ الصورة/ينظف الملاحظات (Gemini، سقف مستقل 30 بالساعة) ويرد بمسودة عنوان واحد بالفصحى + أزرار:
«🔴 انشر عاجل» «📰 انشر خبر» «✏️ تعديل» «✖️ إلغاء». لا شيء يُنشر بلا ضغطة زر. المسودة تنتهي بعد 30 دقيقة.
الصوت والصورة بالذاكرة فقط (لا يُحفظان بأي ملف). المسودات بالذاكرة: إعادة تشغيل المسار السريع تلغي المعلّق منها.

يعمل من حلقة المسار السريع (كل ~10 ثوانٍ، يقرأ الرسائل دون تأكيدها) ومن صندوق المحررين بالجولة الرئيسية احتياطاً (أوامر /نشر فقط).
المعالَج يُسجل في manual_done.json على إصدار fastlane حتى لا يُعالج مرتين. لا يقبل إلا من مشرفي القناة.
"""
import base64
import html as H
import json
import re
import secrets
import threading
import time
import urllib.request
from datetime import datetime, timezone

CMD = re.compile(r"^/(نشر|عاجل)(?:@\w+)?\s*", re.S)
SRC_LINE = re.compile(r"^(?:المصدر|مصدر)\s*[:：]\s*(.+)$")
SHARE_KB = json.dumps({"inline_keyboard": [[{"text": "↗️ شارك القناة", "url": "https://t.me/share/url?url=https%3A%2F%2Ft.me%2Fakamedia_iq"}]]})


def is_cmd(m):
    return bool(CMD.match((m.get("text") or m.get("caption") or "").strip()))


def _file(token, api, file_id, limit=12 * 1024 * 1024):
    """تنزيل ملف من تلغرام إلى الذاكرة فقط."""
    path = api(token, "getFile", file_id=file_id)["result"]["file_path"]
    with urllib.request.urlopen(f"https://api.telegram.org/file/bot{token}/{path}", timeout=20) as r:
        return r.read(limit + 1)[:limit]


def _photo(token, api, m):
    ph = m.get("photo")
    if not ph:
        return None
    try:
        fid = sorted(ph, key=lambda p: p.get("file_size") or 0)[-1]["file_id"]
        return _file(token, api, fid)
    except Exception:  # noqa: BLE001
        return None


def _parse_lines(body):
    src, lines = None, []
    for ln in (body or "").split("\n"):
        s = ln.strip()
        if not s:
            continue
        g = SRC_LINE.match(s)
        if g:
            src = g.group(1).strip()[:60]
        else:
            lines.append(s)
    return lines, src


def recent_sigs(T):
    return [x for x in T.fastlane_sigs() + T.fastlane_sigs("main_sigs.json") + T.fastlane_sigs("tv_sigs.json") if x.get("ts", 0) >= time.time() - 6 * 3600]


_RS = {"t": 0.0, "v": []}
RS_TTL = 120


def recent_sigs_cached(T):
    """للرادارات (العاجل على مرحلتين): ثلاثة تنزيلات من الإصدار (~3–6 ث) قبل كل إرسال تؤخر الزلزال؛ نسخة عمرها ≤ دقيقتين تكفي،
    ومنع تكرار الزلزال نفسه بحالة الرادار (معرّف الحدث)."""
    if time.time() - _RS["t"] > RS_TTL:
        _RS.update(t=time.time(), v=recent_sigs(T))
    return _RS["v"]


def send_card(token, chat_id, head, hot, src=None, extra="", photo=None, ref="manual:0", editor_name="محرر", api=None, two_stage=False):
    """المسار الموحد للنشر اليدوي/بوابة المراسل/الرادارات: فحص التكرار ← بطاقة (يومض للعاجل) ← بصمة مشتركة ← تغذية التطبيق وتنبيه الهاتف.
    two_stage (الرادارات): العاجل يُرسل بطاقة ثابتة فوراً ثم تتحول للمتحركة بتعديل المنشور نفسه (editMessageMedia) — لا منشور ثانٍ.
    يرجع (ok, رسالة, message_id)."""
    from tools import tg_push as T, tg_card
    from tools import fastbreak as FB
    api = api or T.api
    t0 = time.time()
    sig = T.title_sig(head)
    if any(T.same_story(sig, x) for x in (recent_sigs_cached(T) if two_stage else recent_sigs(T))):
        return False, "⚠️ هذا الخبر منشور بالقناة خلال آخر 6 ساعات، فما نشرته حتى ما يتكرر. إذا بيه تطور جديد اكتب العنوان بالتفصيل الجديد.", None
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cap = f"<b>{'🔴 عاجل | ' if hot else ''}{H.escape(head)}</b>" + (f"\n{H.escape(extra)}" if extra else "") + \
          (f"\n\n📌 المصدر: {H.escape(src)}" if src and tg_card.SHOW_SOURCE else "") + f"\n\nزورونا على الرابط للأخبار العاجلة 👇\n{T.CHANNEL}"
    r = {"ok": False}
    if hot and not two_stage:
        try:
            anim = tg_card.breaking_anim(photo, head, when, style="news4A", source=src)
            r = api(token, "sendAnimation", files={"animation": ("breaking.mp4", anim, "video/mp4")}, chat_id=chat_id, caption=cap[:1024],
                    parse_mode="HTML", reply_markup=SHARE_KB, width="1080", height="1350", disable_notification="false")
        except Exception:  # noqa: BLE001
            r = {"ok": False}
    if not r.get("ok"):
        card = tg_card.card_news4(photo, head, hot, when, source=src, style="A")
        r = api(token, "sendPhoto", files={"photo": ("card.jpg", card)}, chat_id=chat_id, caption=cap[:1024], parse_mode="HTML",
                reply_markup=SHARE_KB, disable_notification="false" if hot else "true")
    if not r.get("ok"):
        return False, "تعذر النشر: " + str(r.get("description"))[:100], None
    mid = r["result"]["message_id"]
    FB.LAT.add("radar" if two_stage else "manual", time.time() - t0)
    if hot and two_stage:  # المرحلة 2: البطاقة المتحركة بالمنشور نفسه (مرة واحدة؛ فشلها يُبقي البطاقة الثابتة)
        try:
            t1 = time.time()
            anim = tg_card.breaking_anim(photo, head, when, style="news4A", source=src)
            im = {"type": "animation", "media": "attach://m", "caption": cap[:1024], "parse_mode": "HTML", "width": 1080, "height": 1350}
            ru = api(token, "editMessageMedia", files={"m": ("breaking.mp4", anim, "video/mp4")}, chat_id=chat_id, message_id=str(mid),
                     media=json.dumps(im, ensure_ascii=False), reply_markup=SHARE_KB)
            if ru.get("ok"):
                FB.STATUS["anim_ok"] += 1
                FB.LAT.add("prep", time.time() - t1)
        except Exception:  # noqa: BLE001
            pass
    entry = {"w": sorted(sig[0]), "d": sorted(sig[1]), "ts": time.time(), "id": ref, "title": head[:200], "by": editor_name}
    if two_stage:
        _RS["v"].append(entry)
    T.publish_main_sigs([x for x in T.fastlane_sigs("tv_sigs.json")] + [entry], "tv_sigs.json")  # بصمة مشتركة: لا يكرره أي مسار
    try:  # تغذية لحظية للتطبيق (+ تنبيه الهاتف عبر web_push)
        from tools import live_feed
        live_feed.publish(token, {"id": ref.replace(":", "/", 1), "title": head, "t": when, "urgent": hot, "src": src or "أكا ميديا",
                                  "url": f"https://t.me/akamedia_iq/{mid}", "msg": mid})
    except Exception:  # noqa: BLE001
        pass
    return True, f"✅ نُشر بالقناة ({'عاجل يومض' if hot else 'خبر'}): {head}", mid


def publish(token, chat_id, m, editor_name="محرر"):
    """ينشر رسالة المحرر (/نشر أو /عاجل). يرجع (ok, رسالة للمحرر)."""
    from tools import tg_push as T
    from tools.editorial import edit_headline
    raw = (m.get("text") or m.get("caption") or "").strip()
    mm = CMD.match(raw)
    if not mm:
        return False, ""
    hot = mm.group(1) == "عاجل"
    lines, src = _parse_lines(raw[mm.end():].strip())
    if not lines or len(lines[0].split()) < 4:
        return False, "الصيغة: /نشر عنوان الخبر (4 كلمات فأكثر)\nسطر اختياري: المصدر: الجهة\nوللعاجل: /عاجل بدل /نشر. وتكدر ترفق صورة وتكتب الأمر بتعليقها."
    head = lines[0][:220]
    try:
        head = edit_headline(head, context=" ".join(lines)[:500]) or head
    except Exception:  # noqa: BLE001
        pass
    ok, msg, _ = send_card(token, chat_id, head, hot, src, "\n".join(lines[1:3]), _photo(token, T.api, m), f"manual:{m.get('message_id')}", editor_name)
    return ok, msg


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
            p.write_text(json.dumps(sorted(ids)[-3000:]), encoding="utf-8")  # تحديثات تلغرام المعلقة تبقى 24 ساعة: نافذة واسعة حتى لا يُعاد شيء بعد إعادة التشغيل
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


# ───────────────────────── بوابة المراسل ─────────────────────────
DRAFT_TTL = 30 * 60
VOICE_MAX = 60
MSG_MAX_AGE = 30 * 60  # رسالة أقدم من 30 دقيقة (مثلاً بعد إعادة تشغيل) لا تُحوَّل لمسودة
INS_PER_HOUR = 30  # سقف Gemini مستقل لبوابة المراسل (لا يأكل من سقف المسار السريع)
INS_CALLS = []
DRAFTS = {}  # id → مسودة (بالذاكرة فقط)
_LOCK = threading.RLock()
STATUS = {"drafts": 0, "published": 0, "cancelled": 0, "expired": 0, "failed": 0, "gem_cap": 0, "ignored": 0}
URL_RX = re.compile(r"https?://\S+|t\.me/\S+")
AR_DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

INS_PROMPT = (
    "أنت محرر في قناة أخبار عاجلة عراقية رصينة تكتب بالعربية الفصحى المهنية. أرسل لك مراسل القناة {kind}.\n"
    "المطلوب بدقة تامة:\n"
    "1) transcript: {tr}\n"
    "2) headline: عنوان خبري واحد بالفصحى (8 إلى 18 كلمة) بصيغة الإسناد المهنية («أعلنت وزارة ... أن ...» أو «الجهة: ...»). "
    "ممنوع: العامية، المبالغة، كلمة «عاجل»، الرموز، وأي معلومة أو رقم أو اسم أو مكان أو جهة غير موجودة حرفياً بالمدخل. "
    "انقل الأرقام والأسماء كما وردت تماماً.\n"
    "3) details: سطر أو سطران اختياريان من المدخل نفسه فقط (قائمة، وقد تكون فارغة).\n"
    "4) source: الجهة المصدر إذا ذُكرت صراحة بالمدخل، وإلا \"\".\n"
    "{doc}"
    "5) ok: false إذا كان المدخل غير مسموع/غير مقروء أو لا يحتوي خبراً واضحاً.\n"
    "أجب بكائن JSON فقط بلا أي نص آخر: {{\"transcript\": \"\", \"headline\": \"\", \"details\": [], \"source\": \"\", {docf}\"ok\": true}}"
)
KINDS = {
    "voice": ("بصمة صوتية (قد تكون باللهجة العراقية)", "التفريغ الحرفي للكلام كما قيل، بلا إضافة. إذا تعذر السماع اكتب \"\".", ""),
    "photo": ("صورة كتاب أو بيان أو وثيقة{cap}", "النص الأساسي المقروء من الصورة (الجهة، التاريخ، المضمون) كما ورد.",
              "   issuer: الجهة المُصدِرة كما تظهر، date: التاريخ كما يظهر، official: \"نعم\" إذا بدت وثيقة رسمية أصلية (ترويسة/ختم/توقيع/رقم كتاب) "
              "أو \"لا\" أو \"غير واضح\" — لا تخمّن.\n"),
    "text": ("ملاحظات نصية خام", "النص كما هو بعد تصحيح الأخطاء الإملائية فقط.", ""),
}


def ins_ok():
    now = time.time()
    INS_CALLS[:] = [t for t in INS_CALLS if t >= now - 3600]
    if len(INS_CALLS) >= INS_PER_HOUR:
        return False
    INS_CALLS.append(now)
    return True


def _gem(prompt, parts=None):
    from tools.editorial import gemini
    return gemini(prompt, max_tokens=700, temperature=0.1, parts=parts, timeout=40)


def _json_out(s):
    if not s:
        return None
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s.strip())
    g = re.search(r"\{.*\}", s, re.S)
    try:
        d = json.loads(g.group(0) if g else s)
        return d if isinstance(d, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _digits(t):
    return set(re.findall(r"\d+", (t or "").translate(AR_DIG).replace(",", "").replace("،", "")))


def understand(kind, data=None, mime=None, text=""):
    """يرجع (dict, سبب الفشل). dict: transcript, headline, details, source, issuer, date, official."""
    if not ins_ok():
        STATUS["gem_cap"] += 1
        return None, "cap"
    k = KINDS[kind]
    cap = (" مع تعليق المراسل: «" + text[:400] + "»") if (kind == "photo" and text) else ""
    prompt = INS_PROMPT.format(kind=k[0].format(cap=cap), tr=k[1], doc=k[2],
                               docf="\"issuer\": \"\", \"date\": \"\", \"official\": \"\", " if kind == "photo" else "")
    parts = [{"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode()}}] if data else None
    if kind == "text":
        prompt += "\n\nالملاحظات:\n" + text[:1500]
    out = _json_out(_gem(prompt, parts))
    if not out:
        return None, "gem"
    if out.get("ok") is False or not str(out.get("headline") or "").strip():
        return None, "unclear"
    return out, None


def _check(head, basis):
    """فحوص الجودة على المسودة: يرجع (حاجب أو None، تحذيرات)."""
    from tools import tg_push as T
    if T.offensive(head):
        return "❌ المسودة فيها إساءة أو اتهام لشخص مسمّى بلا جهة رسمية (قاعدة المالك)، فما تُنشر.", []
    if T.EXCL_RX.search(head):
        return "❌ تصريح جهة مستبعدة من القناة، فما يُنشر.", []
    warn = []
    extra = _digits(head) - _digits(basis)
    if extra:
        warn.append("⚠️ رقم بالعنوان غير موجود بالمدخل: " + "، ".join(sorted(extra)) + " — راجعه أو اضغط تعديل.")
    if T.dialect(head):
        warn.append("⚠️ بالعنوان كلمة عامية — يُفضّل تعديله.")
    if T.low_value(head) or T.incomplete(head):
        warn.append("⚠️ العنوان قد لا يكون خبراً مكتملاً — راجعه.")
    try:
        if any(T.same_story(T.title_sig(head), x) for x in recent_sigs(T)):
            warn.append("⚠️ يشبه خبراً منشوراً خلال 6 ساعات — النشر سيُرفض إلا بتفصيل جديد.")
    except Exception:  # noqa: BLE001
        pass
    return None, warn


def _kb(did):
    return json.dumps({"inline_keyboard": [[{"text": "🔴 انشر عاجل", "callback_data": f"i:h:{did}"}, {"text": "📰 انشر خبر", "callback_data": f"i:n:{did}"}],
                                           [{"text": "✏️ تعديل", "callback_data": f"i:e:{did}"}, {"text": "✖️ إلغاء", "callback_data": f"i:x:{did}"}]]})


def new_draft(token, api, owner, chat, head, details=(), src=None, photo=None, note="", warn=(), kind="text", group=None, reply_to=None):
    """ينشئ مسودة ويرسلها للمحرر بأزرار النشر. يُستخدم أيضاً من الرادارات (الدولار) بمفتاح group مشترك بين المحررين."""
    did = secrets.token_hex(3)
    d = {"id": did, "owner": str(owner), "chat": chat, "head": head.strip()[:220], "details": [x.strip()[:200] for x in details if x and x.strip()][:2],
         "src": (src or "").strip()[:60] or None, "photo": photo, "kind": kind, "ts": time.time(), "state": "open", "group": group, "msg": None}
    body = f"📝 مسودة #{did} — تنتهي بعد 30 دقيقة\n\n<b>{H.escape(d['head'])}</b>" + \
           ("".join("\n" + H.escape(x) for x in d["details"])) + (f"\n📌 المصدر: {H.escape(d['src'])}" if d["src"] and __import__('tools.tg_card', fromlist=['x']).SHOW_SOURCE else "") + \
           (f"\n\n{note}" if note else "") + ("".join("\n" + w for w in warn)) + "\n\nما يُنشر شيء إلا بضغطة زر."
    kw = {"reply_to_message_id": reply_to} if reply_to else {}
    try:
        r = api(token, "sendMessage", chat_id=chat, text=body[:4000], parse_mode="HTML", reply_markup=_kb(did), **kw)
        d["msg"] = (r.get("result") or {}).get("message_id")
    except Exception:  # noqa: BLE001
        return None
    with _LOCK:
        DRAFTS[did] = d
        STATUS["drafts"] += 1
    return did


def _expire():
    now = time.time()
    with _LOCK:
        for k in [k for k, d in DRAFTS.items() if now - d["ts"] > DRAFT_TTL + 3600]:
            DRAFTS.pop(k, None)  # تنظيف الذاكرة (الصورة تُحذف معها)


def insider_kind(m):
    """نوع مدخل بوابة المراسل أو None (رسائل أخرى تبقى لصندوق المحررين: روابط، فيديو، تحويل، أوامر)."""
    if m.get("forward_origin") or m.get("forward_from_chat") or m.get("forward_date"):
        return None
    if m.get("voice") or (m.get("audio") and (m["audio"].get("duration") or 0) <= VOICE_MAX):
        return "voice"
    if m.get("photo") or ((m.get("document") or {}).get("mime_type") or "").startswith("image/"):
        cap = (m.get("caption") or "").strip()
        return None if cap.startswith("/") or URL_RX.search(cap) else "photo"
    t = (m.get("text") or "").strip()
    if not t or t.startswith("/") or t in ("مساعدة",) or URL_RX.search(t) or len(t.split()) < 4:
        return None
    return "text"


def _await_edit(uid, m):
    """رد المحرر بنص مصحح على مسودة طلب تعديلها."""
    rep = (m.get("reply_to_message") or {}).get("message_id")
    with _LOCK:
        cands = [d for d in DRAFTS.values() if d["owner"] == uid and d["state"] == "edit" and time.time() - d["ts"] <= DRAFT_TTL]
    if rep:
        hit = [d for d in cands if d["msg"] == rep]
        return hit[0] if hit else None
    return max(cands, key=lambda d: d["ts"]) if cands else None


def handle_message(token, chat_id, m, uid, editor_name, api):
    """رسالة محرر غير أمر: تعديل مسودة، أو مدخل جديد لبوابة المراسل. يرجع True إذا عولجت."""
    cid = m["chat"]["id"]
    old = _await_edit(uid, m) if (m.get("text") or "").strip() and not (m.get("text") or "").startswith("/") else None
    if old:
        lines, src = _parse_lines(m["text"])
        if not lines or len(lines[0].split()) < 4:
            api(token, "sendMessage", chat_id=cid, text="اكتب العنوان المصحح بسطر واحد (4 كلمات فأكثر)، وسطرين اختياريين للتفاصيل، وسطر «المصدر: …» اختياري.")
            return True
        block, warn = _check(lines[0], m["text"])
        if block:
            api(token, "sendMessage", chat_id=cid, text=block)
            return True
        with _LOCK:
            old["state"] = "replaced"
        new_draft(token, api, uid, cid, lines[0], lines[1:3], src or old["src"], old["photo"], warn=warn, kind=old["kind"], group=old["group"],
                  reply_to=m["message_id"])
        return True
    kind = insider_kind(m)
    if not kind:
        return False
    if time.time() - (m.get("date") or time.time()) > MSG_MAX_AGE:
        return True  # قديمة: لا مسودة (تُعلَّم معالَجة)
    text = (m.get("text") or m.get("caption") or "").strip()
    data = mime = photo = None
    try:
        if kind == "voice":
            v = m.get("voice") or m.get("audio")
            if (v.get("duration") or 0) > VOICE_MAX:
                api(token, "sendMessage", chat_id=cid, reply_to_message_id=m["message_id"], text=f"البصمة أطول من {VOICE_MAX} ثانية. سجّل الخبر بأقل من دقيقة.")
                return True
            data, mime = _file(token, api, v["file_id"], 4 * 1024 * 1024), (v.get("mime_type") or "audio/ogg")
        elif kind == "photo":
            if m.get("photo"):
                data, mime = _photo(token, api, m), "image/jpeg"
            else:
                data, mime = _file(token, api, m["document"]["file_id"]), m["document"]["mime_type"]
            photo = data if mime == "image/jpeg" else None
            if not data:
                raise ValueError("photo")
    except Exception:  # noqa: BLE001
        api(token, "sendMessage", chat_id=cid, reply_to_message_id=m["message_id"], text="تعذر تنزيل الملف من تلغرام. أعد الإرسال.")
        STATUS["failed"] += 1
        return True
    out, why = understand(kind, data, mime, text)
    data = None  # لا نبقي الصوت بالذاكرة بعد الفهم
    if not out:
        STATUS["failed"] += 1
        if kind == "text" and why in ("cap", "gem"):  # بلا نموذج: الملاحظة نفسها مسودة بعد تنظيف بسيط
            from tools.editorial import clean_headline
            lines, src = _parse_lines(text)
            head = clean_headline(lines[0]) if lines else ""
            if len(head.split()) >= 4:
                block, warn = _check(head, text)
                if block:
                    api(token, "sendMessage", chat_id=cid, text=block)
                    return True
                new_draft(token, api, uid, cid, head, lines[1:3], src, None, note="(بلا صياغة آلية: النموذج غير متاح الآن)", warn=warn, kind=kind,
                          reply_to=m["message_id"])
                return True
        msg = {"cap": "⏳ وصلنا سقف الصياغة الآلية لهذه الساعة.", "gem": "تعذر الفهم الآلي الآن (النموذج غير متاح).",
               "unclear": "ما كدرت أطلع خبر واضح من المدخل."}[why]
        if kind == "voice":
            msg = "❌ تعذر تفريغ البصمة الصوتية. " + msg + " اكتب الخبر نصاً أو استخدم /نشر."
        elif kind == "photo":
            msg = "❌ تعذرت قراءة الصورة. " + msg + " اكتب الخبر نصاً أو أرسل الصورة بتعليق «/نشر العنوان»."
        else:
            msg += " استخدم /نشر العنوان."
        api(token, "sendMessage", chat_id=cid, reply_to_message_id=m["message_id"], text=msg)
        return True
    head = re.sub(r"^\W*(?:عاجل|عــاجل)\s*[|:：-]?\s*", "", str(out.get("headline") or "")).strip().strip('"«»')
    basis = " ".join(str(out.get(k) or "") for k in ("transcript", "issuer", "date")) + " " + text
    block, warn = _check(head, basis)
    if block:
        api(token, "sendMessage", chat_id=cid, reply_to_message_id=m["message_id"], text=block)
        return True
    note = ""
    tr = str(out.get("transcript") or "").strip()
    if tr:
        note = ("🎙 التفريغ: " if kind == "voice" else "📄 المقروء: " if kind == "photo" else "🗒 الملاحظات: ") + H.escape(tr[:500])
    if kind == "photo":
        note += f"\n🏛 الجهة: {H.escape(str(out.get('issuer') or 'غير واضحة'))} — 📅 التاريخ: {H.escape(str(out.get('date') or 'غير واضح'))}" + \
                f"\n🔎 تبدو وثيقة رسمية؟ {H.escape(str(out.get('official') or 'غير واضح'))} (تقدير آلي، تحقق منه)"
    details = out.get("details") if isinstance(out.get("details"), list) else []
    new_draft(token, api, uid, cid, head, [str(x) for x in details], str(out.get("source") or "") or None, photo, note=note, warn=warn, kind=kind,
              reply_to=m["message_id"])
    return True


def _answer(token, api, cq, text):
    try:
        api(token, "answerCallbackQuery", callback_query_id=cq["id"], text=text[:190])
    except Exception:  # noqa: BLE001
        pass


def handle_callback(token, chat_id, cq, eds, api):
    """ضغطة زر على مسودة. يرجع True إذا نُشر شيء."""
    data = cq.get("data") or ""
    g = re.match(r"^i:([hnex]):([0-9a-f]{6})$", data)
    if not g:
        return False
    uid = str((cq.get("from") or {}).get("id"))
    if uid not in eds:
        _answer(token, api, cq, "للمحررين فقط.")
        return False
    act, did = g.groups()
    cid = ((cq.get("message") or {}).get("chat") or {}).get("id") or uid
    with _LOCK:
        d = DRAFTS.get(did)
        if not d or d["owner"] != uid:
            _answer(token, api, cq, "المسودة غير موجودة (انتهت أو أُعيد تشغيل النظام). أعد الإرسال.")
            return False
        if time.time() - d["ts"] > DRAFT_TTL:
            d["state"] = "expired"
            STATUS["expired"] += 1
        grp_done = d["group"] and any(x["group"] == d["group"] and x["state"] == "done" for x in DRAFTS.values())
        if d["state"] in ("done", "cancelled", "expired", "replaced", "busy") or grp_done:
            _answer(token, api, cq, {"done": "نُشر سابقاً.", "cancelled": "أُلغيت.", "expired": "انتهت صلاحية المسودة (30 دقيقة). أعد الإرسال.",
                                     "replaced": "استُبدلت بمسودة أحدث.", "busy": "جارٍ النشر…"}.get(d["state"], "نُشر سابقاً."))
            return False
        if act in "hn":
            d["state"] = "busy"  # قفل ضد الضغط المزدوج قبل الإرسال
    if act == "x":
        d["state"] = "cancelled"
        STATUS["cancelled"] += 1
        _answer(token, api, cq, "أُلغيت المسودة.")
        _strip_kb(token, api, d)
        return False
    if act == "e":
        d["state"] = "edit"
        d["ts"] = time.time()
        _answer(token, api, cq, "أرسل النص المصحح.")
        api(token, "sendMessage", chat_id=cid, reply_to_message_id=d["msg"],
            text="✏️ أرسل العنوان المصحح كرد على هذه المسودة (السطر الأول عنوان، وسطران اختياريان للتفاصيل، وسطر «المصدر: …» اختياري)، وأرجعلك المسودة بالأزرار.")
        return False
    _answer(token, api, cq, "جارٍ النشر…")
    try:
        ok, msg, _mid = send_card(token, chat_id, d["head"], act == "h", d["src"], "\n".join(d["details"]), d["photo"], f"insider:{did}", eds.get(uid, "محرر"), api=api)
    except Exception as e:  # noqa: BLE001
        ok, msg = False, f"تعذر النشر: {type(e).__name__}"
    with _LOCK:
        d["state"] = "done" if ok else "open"
        if ok:
            d["photo"] = None
            STATUS["published"] += 1
    if ok:
        _strip_kb(token, api, d)
    try:
        api(token, "sendMessage", chat_id=cid, reply_to_message_id=d["msg"], text=msg[:1000])
    except Exception:  # noqa: BLE001
        pass
    return ok


def _strip_kb(token, api, d):
    try:
        api(token, "editMessageReplyMarkup", chat_id=d["chat"], message_id=d["msg"], reply_markup=json.dumps({"inline_keyboard": []}))
    except Exception:  # noqa: BLE001
        pass


# allowed_updates يحفظه تلغرام للبوت حتى الطلب التالي، والتحديث غير المسموح وقت وصوله يُسقط نهائياً: كانت هذه الحلقة (كل ~8 ث)
# تطلب ["message"] ثم ["message","callback_query"] فتُسقط channel_post لقناة الرصد التلفزيوني (tv_source عبر tg_inbox) منذ 03/11،
# وtg_inbox يطلب ["message","channel_post"] فيُسقط ضغطات الأزرار بين الدورتين. الآن كل القرّاء يطلبون الاتحاد نفسه (tg_push.ALLOWED_UPDATES).
from tools.tg_push import ALLOWED_UPDATES as ALLOWED  # noqa: E402
_POOL = {"ex": None}


def _bg(fn, *a):
    from concurrent.futures import ThreadPoolExecutor
    if _POOL["ex"] is None:
        _POOL["ex"] = ThreadPoolExecutor(2, thread_name_prefix="insider")

    def run():
        try:
            fn(*a)
        except Exception as e:  # noqa: BLE001
            STATUS["failed"] += 1
            print("::warning title=insider::", type(e).__name__)
    _POOL["ex"].submit(run)


def poll(token, chat_id, seen, api=None, bg=True, save=None):
    """من حلقة المسار السريع: يقرأ الرسائل المعلقة بلا تأكيد (offset) حتى يبقى صندوق المحررين يستلمها؛ ينشر أوامر /نشر و/عاجل فوراً،
    ويحوّل مدخلات بوابة المراسل لمسودات (بخيط خلفي حتى لا تتأخر الحلقة)، وينفذ أزرار المسودات."""
    from tools import tg_push as T
    api = api or T.api
    save = save or mark_done
    _expire()
    try:
        ups = api(token, "getUpdates", timeout=0, limit=100, allowed_updates=ALLOWED).get("result", [])
    except Exception:  # noqa: BLE001
        return 0
    eds = None
    n = 0
    changed = False
    for u in ups:
        cq = u.get("callback_query")
        if cq:
            key = f"cb:{cq.get('id')}"
            if key in seen or not str(cq.get("data") or "").startswith("i:"):
                continue
            seen.add(key)
            changed = True
            eds = eds if eds is not None else editors(token, chat_id)
            n += int(handle_callback(token, chat_id, cq, eds, api))
            continue
        m = u.get("message") or {}
        if (m.get("chat") or {}).get("type") != "private":
            continue
        key = f"{m['chat']['id']}:{m['message_id']}"
        if key in seen:
            continue
        cmd = is_cmd(m)
        if not cmd and not (insider_kind(m) or ((m.get("text") or "").strip() and DRAFTS)):
            continue  # ليست لنا: تبقى لصندوق المحررين (روابط، فيديو، اشتراكات)
        eds = eds if eds is not None else editors(token, chat_id)
        uid = str((m.get("from") or {}).get("id"))
        if uid not in eds:
            STATUS["ignored"] += int(not cmd)
            if cmd:
                seen.add(key)
            continue  # غير المشرفين: لا شيء (اشتراكات المتابعين يعالجها صندوق المحررين)
        if cmd:
            seen.add(key)
            changed = True
            ok, msg = publish(token, chat_id, m, eds.get(uid, "محرر"))
            n += int(ok)
            try:
                api(token, "sendMessage", chat_id=m["chat"]["id"], reply_to_message_id=m["message_id"], text=msg[:1000])
            except Exception:  # noqa: BLE001
                pass
            continue
        if not insider_kind(m) and not _await_edit(uid, m):
            continue
        seen.add(key)
        changed = True
        if bg:
            _bg(handle_message, token, chat_id, m, uid, eds.get(uid, "محرر"), api)
        else:
            handle_message(token, chat_id, m, uid, eds.get(uid, "محرر"), api)
    if changed:
        save(seen)
    return n
