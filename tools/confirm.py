"""«✅ أكدته الجهة الرسمية»: خبر نشرناه من مصدر غير رسمي ثم نشرت جهة رسمية الخبر نفسه خلال 6 ساعات ← نعدّل تعليق منشورنا مرة
واحدة بسطر «✅ أكدته: <الجهة> — HH:MM بغداد» قرب سطر التحقق. لا حذف أبداً، ولا تعديل لمنشور أقدم من 6 ساعات أو منشور رسمي أصلاً.

السجل على إصدار fastlane، ملف لكل كاتب حتى لا يمسح أحدهما كتابة الآخر:
  posted_fast.json (المسار السريع) و posted_main.json (الجولة الرئيسية) = {"posts": [...], "edited": [...]}
  posts: {sig:{w,d}, message_id, posted_ts, official, confirmed, caption, kind(photo/animation/text), kb, lp, title, nid, src}
  edited: {mid, ts, ok, by, why, type(off/trust), cap} — كل محاولة تعديل (ناجحة أو فاشلة) تُسجَّل فلا تُعاد (مرة لكل نوع)، وتُحسب
  بسقف 20 تعديلاً بالساعة للنوعين معاً. cap = التعليق بعد التعديل الناجح (أساس أي تعديل لاحق من الكاتب الآخر).
«☑️ تطابق لدى مصدر موثوق: <مصدر>» (check_trusted): مصدر مستقل بطبقة «موثوقة» في source_trust.json نقل الخبر نفسه بأرقام متسقة.
"""
import html as H
import json
import re
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WINDOW_H = 6
KEEP_H = 48
MAX_EDITS_HOUR = 20
FILES = {"fast": "posted_fast.json", "main": "posted_main.json"}
LIMIT = {"photo": 1024, "animation": 1024, "text": 4096}
VERIFY_RX = re.compile(r"^(⏳|☑️|⚠️|✅) التحقق:")
# بحدود كلمة: بلا حدود كانت «نفت» تطابق «نفتح» و«تنفي» تطابق «تنفيذ» فتُعامل بيانات رسمية عادية كنفي
DENY_RX = re.compile(r"(?<![\u0600-\u06FF])[وف]?(?:لا صحة|لاصحة|عار[يٍ]? عن الصحة|غير صحيح[ةه]?|ينفي|تنفي|ننفي|نفى|نفت|نفي|تكذيب|يكذب|تكذب|"
                     r"شائعة|شائعات|مفبرك[ةه]?|مزيف[ةه]?)(?![\u0600-\u06FF])")
AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
TRUST_TAG = "☑️ تطابق لدى مصدر موثوق"
LOG = []  # آخر الأحداث (تُعرض في fast_status/tg_status)


def _log(msg):
    LOG.append(msg[:160])
    del LOG[:-30]
    print("::notice title=confirm::" + msg[:200])


def gh_get(name):
    try:
        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run(["gh", "release", "download", "fastlane", "-p", name, "-D", td, "--clobber"], capture_output=True, timeout=25)
            return json.loads((Path(td) / name).read_text(encoding="utf-8")) if r.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def gh_put(name, data):
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / name
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            subprocess.run(["gh", "release", "upload", "fastlane", str(p), "--clobber"], capture_output=True, timeout=25)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- الجهات الرسمية
_OFF = {}


def _official_maps():
    """قناة/نطاق ← اسم الجهة. علامة official في sources.json وحدها فضفاضة (قنوات فضائية وصحف وحسابات إخبارية موسومة رسمية)،
    فالجهة الرسمية هنا = رسمية في sources.json و(قناة ضمن «channels» بالمسار السريع، أو فئة «مصادر رسمية وأولية»، أو نطاق gov.iq)،
    عدا الإعلام الحكومي الناقل (واع، الشبكة) والوكالات."""
    if _OFF:
        return _OFF
    tg, dom = {}, {}
    try:
        from marsad.core import STATE_MEDIA
    except Exception:  # noqa: BLE001
        STATE_MEDIA = set()
    try:
        fl = json.loads((ROOT / "config" / "fastlane.json").read_text(encoding="utf-8"))
        agency = {c.lower() for c in fl.get("agency", [])}
        chans = {c.lower() for c in fl.get("channels", [])}
    except Exception:  # noqa: BLE001
        agency, chans = set(), set()
    for s in json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))["sources"]:
        if not s.get("official") or s["id"] in STATE_MEDIA:
            continue
        primary = s.get("category") == "مصادر رسمية وأولية" or ".gov.iq" in (s.get("url") or "")
        name = re.sub(r"\s*[—-]\s*(telegram|RSS|rss|يوتيوب)$", "", s.get("name") or "").strip()
        if not name or "وكالة" in name or "نينا" in name or "Google News" in name or "news.google" in (s.get("url") or ""):
            continue
        m = re.match(r"telegram:t\.me/([A-Za-z0-9_]+)$", s["id"])
        if m:
            if m.group(1).lower() not in agency and (primary or m.group(1).lower() in chans):
                tg[m.group(1).lower()] = name
            continue
        if not primary:
            continue
        host = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", s.get("url") or "").lower())
        if host and "." in host and host not in ("t.me", "facebook.com", "x.com", "twitter.com", "youtube.com", "instagram.com"):
            dom[host] = name
    _OFF.update({"tg": tg, "dom": dom})
    return _OFF


def official_name(ref):
    """ref = اسم قناة تلغرام أو رابط (t.me/x/123 أو موقع). يرجع اسم الجهة الرسمية أو None."""
    if not ref:
        return None
    m = _official_maps()
    r = ref.strip()
    t = re.match(r"^(?:https?://)?t\.me/(?:s/)?([A-Za-z0-9_]+)", r)
    if t:
        return m["tg"].get(t.group(1).lower())
    if "/" not in r and "." not in r:
        return m["tg"].get(r.lower())
    host = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", r).lower())
    return m["dom"].get(host)


# ---------------------------------------------------------------- التعليق
class _Chk(HTMLParser):
    OK = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a", "code", "pre", "tg-spoiler", "blockquote", "span"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.bad = [], False

    def handle_starttag(self, tag, attrs):
        if tag not in self.OK:
            self.bad = True
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            self.bad = True


def html_ok(s):
    c = _Chk()
    try:
        c.feed(s)
        c.close()
    except Exception:  # noqa: BLE001
        return False
    return not c.bad and not c.stack and not re.search(r"<[^>]*$", s)


def visible_len(s):
    """طول النص كما يعدّه تلغرام (وحدات UTF-16 بعد إزالة الوسوم)."""
    return len(H.unescape(re.sub(r"<[^>]+>", "", s)).encode("utf-16-le")) // 2


SHOW_LINES = False  # إيهاب 06/11 مساءً: لا أسطر تأكيد/تطابق بالمنشورات
SHOW_NAMES = False  # إيهاب 06/11: لا نذكر اسم أي مصدر بالمنشور — التأكيد يُذكر بلا اسم الجهة


def confirm_line(name, ts):
    who = f": {H.escape(name[:60])}" if SHOW_NAMES else " جهة رسمية"
    return f"✅ أكدته{who} — {datetime.fromtimestamp(ts, timezone.utc) + timedelta(hours=3):%H:%M} بغداد"


def trust_line(name):
    return f"{TRUST_TAG}: {H.escape(name[:60])}" if SHOW_NAMES else TRUST_TAG


def add_confirm(caption, line, kind="photo"):
    """يضيف السطر بعد سطر التحقق (أو بعد «📌 المصدر»، أو قبل دعوة القناة). None إذا لا يصح التعديل.
    سطر «☑️ تطابق» لا يُضاف إذا وُجد «✅ أكدته» (التأكيد الرسمي أولى) أو سطر تطابق سابق."""
    if not caption or "✅ أكدته" in caption or "❌ التحقق" in caption or not html_ok(caption):
        return None
    if line.startswith(TRUST_TAG) and TRUST_TAG in caption:
        return None
    lines = caption.split("\n")
    at = next((i + 1 for i, x in enumerate(lines) if VERIFY_RX.match(x)), None)
    if at is None:
        at = next((i + 1 for i, x in enumerate(lines) if x.startswith("📌 المصدر")), None)
    if at is None:
        at = next((i - 1 if i >= 1 and lines[i - 1] == "" else i for i, x in enumerate(lines) if x.startswith("زورونا")), len(lines))
    new = "\n".join(lines[:at] + [line] + lines[at:])
    if visible_len(new) > LIMIT.get(kind, 1024) or not html_ok(new):
        return None
    return new


# ---------------------------------------------------------------- السجل
class Ledger:
    def __init__(self, who, get=None, put=None):
        self.who, self.get, self.put = who, get or (lambda n: gh_get(n)), put or (lambda n, d: gh_put(n, d))
        d = self.get(FILES[who]) or {}
        self.data = {"posts": list(d.get("posts") or []), "edited": list(d.get("edited") or [])}
        self.other = {"posts": [], "edited": []}
        self.dirty = False
        self.refresh_other()

    def refresh_other(self):
        o = self.get(FILES["main" if self.who == "fast" else "fast"]) or {}
        self.other = {"posts": list(o.get("posts") or []), "edited": list(o.get("edited") or [])}

    def prune(self, now=None):
        now = now or time.time()
        self.data["posts"] = [p for p in self.data["posts"] if p.get("posted_ts", 0) >= now - KEEP_H * 3600][-800:]
        self.data["edited"] = [e for e in self.data["edited"] if e.get("ts", 0) >= now - KEEP_H * 3600][-800:]

    def add_post(self, message_id, sig, caption, kind, official, title="", kb=None, lp=None, nid=None, src=None, ts=None, src_ts=None):
        if not message_id or not sig:
            return
        w, d = (sig.get("w"), sig.get("d")) if isinstance(sig, dict) else sig
        self.data["posts"].append({"sig": {"w": sorted(w), "d": sorted(d)}, "message_id": int(message_id), "posted_ts": ts or time.time(),
                                   "official": bool(official), "confirmed": False, "caption": caption, "kind": kind, "kb": kb, "lp": lp,
                                   "title": (title or "")[:200], "nid": nid, "src": src, "src_ts": src_ts})
        self.prune()
        self.dirty = True

    def edited_ids(self, typ="off"):
        """منشورات عُدّلت (أو جُرّبت) بهذا النوع: «off» تأكيد رسمي (والسجلات القديمة بلا نوع)، «trust» تطابق مصدر موثوق."""
        return {e.get("mid") for e in self.data["edited"] + self.other["edited"] if (e.get("type") or "off") == typ}

    def caption_of(self, rec):
        """أحدث تعليق للمنشور: آخر تعديل ناجح من أي كاتب (حتى لا يمحو تعديلٌ سطراً أضافه الكاتب الآخر)، وإلا تعليق السجل."""
        last = max((e for e in self.data["edited"] + self.other["edited"] if e.get("mid") == rec.get("message_id") and e.get("ok") and e.get("cap")),
                   key=lambda e: e.get("ts", 0), default=None)
        return last["cap"] if last else (rec.get("caption") or "")

    def edits_last_hour(self, now=None):
        now = now or time.time()
        return sum(1 for e in self.data["edited"] + self.other["edited"] if e.get("ts", 0) >= now - 3600)

    def candidates(self, now=None, typ="off"):
        now = now or time.time()
        done = self.edited_ids(typ)
        if typ == "trust":  # «✅ أكدته» أولى: منشور أكدته جهة رسمية لا يحتاج سطر التطابق
            done |= {e.get("mid") for e in self.data["edited"] + self.other["edited"] if (e.get("type") or "off") == "off" and e.get("ok")}
        seen = set()
        for p in self.data["posts"] + self.other["posts"]:
            mid = p.get("message_id")
            if mid in seen or mid in done or p.get("official") or p.get("confirmed") or now - p.get("posted_ts", 0) > WINDOW_H * 3600:
                continue
            seen.add(mid)
            yield p

    def mark(self, rec, ok, by, why="", typ="off", cap=None):
        e = {"mid": rec.get("message_id"), "ts": time.time(), "ok": bool(ok), "by": by[:60], "why": why[:80], "type": typ}
        if ok and cap:
            e["cap"] = cap
        self.data["edited"].append(e)
        for p in self.data["posts"]:
            if p.get("message_id") == rec.get("message_id"):
                if typ == "off":
                    p["confirmed"] = bool(ok)
                elif ok:
                    p["caption"] = cap or p.get("caption")
        self.dirty = True

    def save(self):
        if self.dirty:
            self.prune()
            self.put(FILES[self.who], self.data)
            self.dirty = False


def matches(sig, rec):
    """الخبر نفسه، بحذر أشد من منع التكرار: التأكيد ادعاء أمام المتابعين، فالتطابق الضعيف لا يكفي."""
    from tools import tg_push as T
    w, d = sig
    pw, pd = set(rec["sig"]["w"]), set(rec["sig"]["d"])
    if not T.same_story((set(w), set(d)), rec["sig"]):
        return False
    nd = {x for x in d if not re.fullmatch(r"(19|20)\d\d", x)}
    npd = {x for x in pd if not re.fullmatch(r"(19|20)\d\d", x)}
    if nd and npd and not (nd & npd):
        return False  # أرقام مختلفة (حصيلة/مبلغ/موعد) = لا نقول «أكدته»
    return len(set(w) & pw) >= 3


def _edit(ledger, api, token, chat_id, rec, new, name, typ):
    kind = rec.get("kind") or "photo"
    kw = {"chat_id": chat_id, "message_id": str(rec["message_id"]), "parse_mode": "HTML"}
    if rec.get("kb"):
        kw["reply_markup"] = rec["kb"]  # بدون إعادة الأزرار يحذفها تلغرام مع التعديل
    try:
        if kind == "text":
            if rec.get("lp"):
                kw["link_preview_options"] = rec["lp"]
            else:
                kw["disable_web_page_preview"] = "true"
            r = api(token, "editMessageText", text=new, **kw)
        else:
            r = api(token, "editMessageCaption", caption=new, **kw)
        ok = bool(r.get("ok"))
        why = "" if ok else str(r.get("description") or "")[:80]
    except Exception as e:  # noqa: BLE001
        ok, why = False, f"{type(e).__name__}: {str(e).replace(token, '***')[:60]}"
    ledger.mark(rec, ok, name, why, typ=typ, cap=new if ok else None)
    if ok:
        rec["caption"] = new
    return ok, why


def check(ledger, api, token, chat_id, name, title, pub_ts, nid=None, now=None, max_edits=3):
    """جهة رسمية «name» نشرت «title» وقت pub_ts. يعدّل منشوراتنا المطابقة (غير الرسمية، أحدث من 6 ساعات، غير المعدّلة). يرجع عدد التعديلات."""
    from tools import tg_push as T
    now = now or time.time()
    if not SHOW_LINES:  # إيهاب 06/11 مساءً: لا نعدّل المنشور لإضافة «أكدته»
        return 0
    if not name or not title or DENY_RX.search(title):
        return 0  # نفي رسمي ليس تأكيداً
    sig = T.title_sig(title.translate(AR_DIGITS))
    n = 0
    for rec in list(ledger.candidates(now)):
        if n >= max_edits or ledger.edits_last_hour(now) >= MAX_EDITS_HOUR:
            break
        if abs(pub_ts - rec.get("posted_ts", 0)) > WINDOW_H * 3600:
            continue
        if not ((nid and rec.get("nid") == nid) or matches(sig, rec)):
            continue
        if DENY_RX.search(rec.get("title") or "") or (rec.get("src") and official_name(rec["src"]) == name):
            continue
        new = add_confirm(ledger.caption_of(rec), confirm_line(name, pub_ts), rec.get("kind") or "photo")
        if not new:
            ledger.mark(rec, False, name, "تعليق غير قابل للتعديل")
            _log(f"تخطي {rec.get('message_id')}: تعليق طويل/غير صالح")
            continue
        ok, why = _edit(ledger, api, token, chat_id, rec, new, name, "off")
        if ok:
            n += 1
            _log(f"أكدته {name}: منشور {rec['message_id']} — {(rec.get('title') or '')[:60]}")
        else:
            _log(f"فشل تعديل {rec['message_id']}: {why}")
    if n or ledger.dirty:
        ledger.save()
    return n


def near_identical(a, b):
    """نص منسوخ تقريباً (البصمة شبه متطابقة) — نسخ لا تأكيد مستقل."""
    from tools import tg_push as T
    wa, wb = T.title_sig((a or "").translate(AR_DIGITS))[0], T.title_sig((b or "").translate(AR_DIGITS))[0]
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.8


def check_trusted(ledger, api, token, chat_id, name, title, pub_ts, ref, nid=None, now=None, max_edits=3):
    """مصدر مستقل بطبقة «موثوقة» (source_trust.json) نشر «title» وقت pub_ts ← «☑️ تطابق لدى مصدر موثوق: name» على منشوراتنا للخبر نفسه
    مرة واحدة. شروط صارمة: ليس نفياً، مطابقة confirm.matches (تشمل اتفاق الأرقام)، شبكة مختلفة عن مصدر منشورنا (لا قناة وموقع وتلفزيون
    الجهة نفسها)، وليس نسخاً (نص شبه متطابق نُشر بعد مصدرنا أو خلال دقيقتين منه). «✅ أكدته» أولى ويمنع هذا السطر."""
    if not SHOW_LINES:
        return 0
    from tools import reliability as R
    from tools import tg_push as T
    now = now or time.time()
    if not name or not title or DENY_RX.search(title) or R.tier_of(ref, name) != "موثوقة" or official_name(ref or ""):
        return 0
    ynet = R.net_of(ref, name)
    sig = T.title_sig(title.translate(AR_DIGITS))
    n = 0
    for rec in list(ledger.candidates(now, typ="trust")):
        if n >= max_edits or ledger.edits_last_hour(now) >= MAX_EDITS_HOUR:
            break
        if abs(pub_ts - rec.get("posted_ts", 0)) > WINDOW_H * 3600:
            continue
        if not matches(sig, rec) or DENY_RX.search(rec.get("title") or ""):  # العنقود نفسه (nid) لا يكفي هنا: المطابقة والأرقام شرط دائماً
            continue
        xnet = R.net_of(rec.get("src") or "")
        if not ynet or ynet == xnet:
            continue  # الشبكة نفسها (قناة الجهة وموقعها) ليست مصدراً مستقلاً
        xts = rec.get("src_ts") or rec.get("posted_ts", 0)
        if near_identical(title, rec.get("title") or "") and (pub_ts >= xts or abs(pub_ts - xts) < 120):
            continue  # نسخ نص مصدرنا
        new = add_confirm(ledger.caption_of(rec), trust_line(name), rec.get("kind") or "photo")
        if not new:
            ledger.mark(rec, False, name, "تعليق غير قابل للتعديل", typ="trust")
            continue
        ok, why = _edit(ledger, api, token, chat_id, rec, new, name, "trust")
        if ok:
            n += 1
            _log(f"تطابق {name}: منشور {rec['message_id']} — {(rec.get('title') or '')[:60]}")
        else:
            _log(f"فشل تعديل تطابق {rec['message_id']}: {why}")
    if n or ledger.dirty:
        ledger.save()
    return n


def official_hits(n):
    """للجولة الرئيسية: الجهات الرسمية المُصدِرة في عنقود الخبر [(الاسم، وقت النشر)]."""
    out, seen = [], set()
    for e in (n.get("timeline") or []) + (n.get("sources") or []):
        name = official_name(e.get("url") or "")
        t = e.get("pub") or e.get("time")
        if not name or not t or name in seen:
            continue
        try:
            ts = datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        seen.add(name)
        out.append((name, ts))
    return out
