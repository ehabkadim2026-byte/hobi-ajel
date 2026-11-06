"""«العاجل على مرحلتين» للمسار السريع + قراءة صور الوثائق الرسمية + قياس زمن أول إرسال.

المرحلة 1 (فوراً): الخبر الحرج (جهة رسمية مُصدِرة + «عاجل»/حدث أمني أو كبير/MUST_RX، أو ما يومض «عاجل» أصلاً) يُرسل بطاقةً ثابتة
«شاشة الحدث» بعنوان القواعد المجانية (بلا انتظار صياغة Gemini ولا تصيير الوميض ولا تنزيل صورة بطيء) — كل بوابات الجودة تبقى كما هي.
المرحلة 2 (بعد 30–120 ث، مرة واحدة للمنشور): تعديل المنشور نفسه — عنوان محرّر، سطر أو سطران من النص الكامل أو مصدر لاحق (منسوباً له)،
سطر المصدر ومن نقله، وسطر التحقق (بمنطق confirm.py: «✅ أكدته»/«☑️ تطابق» مرة لكل نوع، ضمن سقف 20 تعديلاً بالساعة)، وللعاجل
تتحول البطاقة إلى البطاقة المتحركة (editMessageMedia) بلا منشور إضافي. التعليق لا يتجاوز 1024.

القياس: LAT يجمع زمن «الرصد ← الإرسال» لكل منشور بالجلسة (fast = مرحلتان، normal = المسار العادي، radar = الرادارات) ووقت
الخطوات البطيئة التي أُجّلت (prep) — يظهر في fast_status.json تحت «lat».
"""
import base64
import html as H
import json
import re
import threading
import time
from datetime import datetime, timezone

LIMIT = 1024
ENRICH_MIN, ENRICH_MAX = 30, 120


# ───────── القياس ─────────
class Lat:
    def __init__(self):
        self.v = {}
        self.lock = threading.Lock()

    def add(self, kind, sec):
        if sec is None or sec < 0 or sec > 3600:
            return
        with self.lock:
            self.v.setdefault(kind, []).append(round(float(sec), 2))
            del self.v[kind][:-500]

    @staticmethod
    def _med(xs):
        s = sorted(xs)
        n = len(s)
        return None if not n else s[n // 2] if n % 2 else round((s[n // 2 - 1] + s[n // 2]) / 2, 2)

    def summary(self):
        with self.lock:
            out = {}
            for k, xs in self.v.items():
                s = sorted(xs)
                out[k] = {"n": len(s), "med_s": self._med(s), "p90_s": s[min(len(s) - 1, int(len(s) * 0.9))] if s else None, "last_s": xs[-1]}
            return out


LAT = Lat()
STATUS = {"fast_sent": 0, "enrich_ok": 0, "enrich_skip": 0, "enrich_fail": 0, "anim_ok": 0, "ocr_calls": 0, "ocr_used": 0, "ocr_skip": 0}


# ───────── الخبر الحرج ─────────
def critical(official, flag, first, loud_pre):
    """official = اسم جهة رسمية مُصدِرة (أو None)، flag = وسم «عاجل» في رأس المنشور، loud_pre = صيغة الوميض على عنوان القواعد."""
    from tools import tg_push as T
    from tools.tv_source import MUST_RX, SPECULATIVE_RX
    if loud_pre:
        return True
    if not official or not first:
        return False
    return bool(flag or T.SEC_RX.search(first) or T.EVENT_RX.search(first) or (MUST_RX.search(first) and not SPECULATIVE_RX.search(first)))


def fast_head(first):
    """العنوان بلا نموذج لغوي: قواعد التنظيف والفصحى نفسها التي يرجع لها edit_headline عند تعذر النموذج."""
    from tools.editorial import clean_headline, formal_rules
    return formal_rules(clean_headline(first, max_len=170))


def loud_of(text, first, head, flag=None):
    """صيغة الوميض «🔴 عاجل» كما بالمسار السريع (fastlane.loud) على عنوان معيّن."""
    from tools import tg_push as T
    if flag is None:  # المسار السريع يمرر وسماً مُصفّى (قنوات تسم كل شيء عاجلاً لا يُعتد بوسمها)
        flag = bool(re.match(r"^\W{0,6}(عاجل|عــاجل|عاااجل|⚡|🔴|🚨)", text[:40] or ""))
    return (flag or bool(T.SEC_RX.search(first) and T.iraq_strict(first))) and not T.NOT_URGENT_RX.search(head) \
        and bool(T.SEC_RX.search(head) or T.EVENT_RX.search(head) or T.URGENT_RX.search(head)) \
        and not (T.STATEMENT_RX.search(head) and not (T.SEC_RX.search(head) or T.EVENT_RX.search(head))) and T.iraq_strict(head)


def photo_within(fetch, url, budget=1.5, pool=None):
    """تنزيل الصورة بمهلة قصيرة: إذا تأخرت تُرسل البطاقة بلا صورة وتُضاف الصورة بالإثراء. يرجع (bytes|None, future|None)."""
    if not url:
        return None, None
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FT
    ex = pool or ThreadPoolExecutor(1)
    fut = ex.submit(fetch, url)
    try:
        return fut.result(timeout=budget), None
    except FT:
        return None, fut
    except Exception:  # noqa: BLE001
        return None, None


# ───────── الإثراء ─────────
_BAD_LINE = re.compile(r"(تابعونا|اشترك|رابط|للمزيد|انضموا|قناتنا|https?://|t\.me/|@\w{4,}|#)")


def detail_lines(full_text, head, n=2):
    """سطر أو سطران من النص الكامل يضيفان معلومة غير موجودة بالعنوان. نص المصدر كما هو بعد التنظيف — لا صياغة ولا إضافة."""
    from tools import tg_push as T
    from tools.editorial import clean_headline
    hw = T.title_sig(head)[0]
    out = []
    parts = []
    for ln in (full_text or "").split("\n"):
        parts += [x.strip() for x in re.split(r"(?<=[.؟!])\s+", ln) if x.strip()]
    for x in parts[1:] if parts and T.title_sig(parts[0])[0] and len(T.title_sig(parts[0])[0] & hw) >= max(2, len(hw) // 2) else parts:
        if _BAD_LINE.search(x):
            continue
        c = clean_headline(x, max_len=230)
        words = c.split()
        if not (6 <= len(words) <= 45) or T.offensive(c) or T.dialect(c) or T.EXCL_RX.search(c) or T.PROMO_RX.search(c):
            continue
        if T.incomplete(c) or re.search(r"(?:^|\s)(?:إن|أن|ان|بأن|بان|إنه|انه|أنه|قائلاً|قائلا|مضيفاً|مضيفا|وأضاف|واضاف)\s*[،,:]?$", c) or \
                (c.endswith("…") and not x.rstrip().endswith(("…", "..."))):
            continue  # سطر مبتور («وقال مصدر محلي لوكالة شفق نيوز، إن» 3463؛ قص النص الطويل بـ«…» 3453 — تدقيق 10:11 06/11)
        cw = T.title_sig(c)[0]
        if not cw or len(cw & hw) / max(1, len(cw)) >= 0.6:
            continue  # تكرار للعنوان
        if any(len(cw & T.title_sig(o)[0]) / max(1, len(cw)) >= 0.6 for o in out):
            continue
        out.append(c)
        if len(out) >= n:
            break
    return out


def visible_len(s):
    from tools.confirm import visible_len as v
    return v(s)


SHOW_VERIFY = False  # إيهاب 06/11 مساءً: لا «مؤكد/غير مؤكد/أكدته/تطابق» بالمنشور مطلقاً
SHOW_SOURCE = False  # إيهاب 06/11: لا نذكر اسم المصدر في نص الخبر (سطر التحقق «أكدته» يبقى)


def build_caption(head, loud, src, details=(), also=(), verify=None, keep=(), tags=(), channel="https://t.me/akamedia_iq"):
    """تعليق بقالب القناة: العنوان، التفاصيل، المصدر ومن نقله، سطر التحقق وسطور التأكيد السابقة، الوسوم، دعوة القناة. يقص حتى 1024."""
    details, also = list(details), list(also)
    while True:
        cap = f"<b>{'🔴 عاجل | ' if loud else ''}{H.escape(head)}</b>" + "".join("\n" + H.escape(d) for d in details) + \
              ((f"\n\n📌 المصدر: {H.escape(src)}" + (f" — ونقلته أيضاً: {H.escape('، '.join(also))}" if also else "")) if SHOW_SOURCE else "\n") + \
              (f"\n{verify}" if verify and SHOW_VERIFY else "") + "".join(f"\n{k}" for k in keep if SHOW_VERIFY) + \
              (("\n" + " ".join(tags)) if tags else "") + f"\n\nزورونا على الرابط للأخبار العاجلة 👇\n{channel}"
        if visible_len(cap) <= LIMIT:
            return cap
        if details:
            details.pop()
        elif also:
            also.pop()
        else:
            return None


def later_sources(job, recent, now=None):
    """منشورات القنوات المرصودة للخبر نفسه بعد منشورنا (بمطابقة confirm.matches الصارمة): [(ch, name, text, ts)]."""
    from tools import confirm as CF
    from tools import tg_push as T
    sig = T.title_sig(job["first"].translate(CF.AR_DIGITS))
    rec = {"sig": {"w": sorted(sig[0]), "d": sorted(sig[1])}}
    out, seen = [], {job["ch"].lower()}
    for r in recent:
        if r["ch"].lower() in seen or not r.get("first"):
            continue
        s2 = T.title_sig(r["first"].translate(CF.AR_DIGITS))
        if CF.matches(s2, rec):
            seen.add(r["ch"].lower())
            out.append(r)
    return out


def verify_for(job, others):
    """(سطر التحقق، نوع سجل confirm أو None، الجهة). الجهة الرسمية المُصدِرة أولى، ثم تأكيد رسمي لاحق، ثم مصدر مستقل «موثوق»."""
    from tools import confirm as CF
    from tools import reliability as R
    if job.get("official"):
        return "✅ التحقق: صادر عن جهة رسمية", None, None
    for r in others:
        name = CF.official_name(r["ch"])
        if name and not CF.DENY_RX.search(r.get("first") or ""):
            return CF.confirm_line(name, r["ts"]), "off", name
    ynet = R.net_of(job.get("ref") or job["ch"])
    for r in others:
        ref = r.get("ref") or r["ch"]
        if R.tier_of(ref) == "موثوقة" and R.net_of(ref) != ynet and not CF.official_name(ref) and not CF.DENY_RX.search(r.get("first") or ""):
            if CF.near_identical(r.get("first"), job["first"]):
                continue  # نسخ نص مصدرنا ليس تطابقاً مستقلاً
            return CF.trust_line(re.sub(r" — .*$", "", r.get("name") or r["ch"])), "trust", r["ch"]
    return "⏳ التحقق: غير مؤكد بعد — مصدر واحد" if not others else "⏳ التحقق: غير مؤكد بعد", None, None


def prepare(job, recent, edit_headline=None, anim=None, card=None, fetch=None, wm=None):
    """الخطوات البطيئة (بخيط خلفي): صياغة العنوان، التفاصيل، المصادر اللاحقة، التحقق، البطاقة المتحركة. يرجع خطة التعديل أو None."""
    from tools import tg_push as T
    t0 = time.time()
    head = job["head"]
    if edit_headline:
        try:
            h2 = edit_headline(job["first"], context=job["text"][:500])
            if h2 and not T.low_value(h2) and not T.incomplete(h2) and len(h2.split()) >= 5 and not T.offensive(h2) and not T.dialect(h2):
                head = h2
        except Exception:  # noqa: BLE001
            pass
    others = later_sources(job, recent)
    details = detail_lines(job["text"], head)
    if not details:
        for r in others[:2]:
            d = detail_lines(r.get("text") or "", head, n=1)
            if d:
                details = [d[0] + f" (بحسب {re.sub(r' — .*$', '', r.get('name') or r['ch'])})"]
                break
    also = [re.sub(r" — .*$", "", r.get("name") or r["ch"]) for r in others][:3]
    verify, vtyp, vname = verify_for(job, others)
    photo = job.get("photo")
    if photo is None and job.get("photo_future") is not None:
        try:
            photo = job["photo_future"].result(timeout=5)
        except Exception:  # noqa: BLE001
            photo = None
    if photo is None and job.get("img") and fetch:
        try:
            photo = fetch(job["img"])
        except Exception:  # noqa: BLE001
            photo = None
    if job.get("hold") and photo is None and job.get("photo_hold") is not None:
        photo = job["photo_hold"]
    if job.get("hold") and photo is not None and (wm is None or wm(photo) is not False):
        photo = None  # صورة من جهة غير رسمية: لا تُستخدم إلا إذا تأكدنا أنها بلا شعار وسيلة أخرى
    if photo is None and wm is not None:  # 06/11 (إيهاب: صمّم بصورة الحدث): صورة نظيفة من مصدر آخر نقل الخبر نفسه — الجهة الرسمية أولاً
        tries = 0
        for r in sorted(others, key=lambda r: not r.get("official")):
            b = r.get("img_bytes")
            if b is None and r.get("img") and fetch:
                try:
                    b = fetch(r["img"])
                except Exception:  # noqa: BLE001
                    b = None
            if not b:
                continue
            tries += 1
            if r.get("official") or wm(b) is False:
                photo = b
                break
            if tries >= 3:
                break
    if photo is None and not job.get("photo"):  # آخر خيار قبل خلفية الشعار: أرشيف مرخّص حسب الموضوع (إيهاب 06/11)
        try:
            from tools import archive_photo as _AP
            photo = _AP.pick(job.get("head") or "")
        except Exception:  # noqa: BLE001
            photo = None
    media = None
    if job["loud"] and anim:
        try:
            media = ("animation", anim(photo, head, job["when"], style="news4A", source=job["src"]))
        except Exception:  # noqa: BLE001
            media = None
    if media is None and card and (head != job["head"] or (photo is not None and job.get("photo") is None)):
        try:
            media = ("photo", card(photo, head, job["loud"], job["when"], source=job["src"], style="A"))
        except Exception:  # noqa: BLE001
            media = None
    return {"head": head, "details": details, "also": also, "verify": verify, "vtyp": vtyp, "vname": vname,
            "media": media, "photo_added": photo is not None and job.get("photo") is None, "prep_s": round(time.time() - t0, 2)}


KEEP_RX = re.compile(r"^(✅ أكدته|☑️ تطابق لدى مصدر موثوق)")


def apply(job, plan, ledger, api, token, chat_id):
    """في الخيط الرئيسي: يبني التعليق من آخر تعليق بالسجل (يحفظ «✅ أكدته»/«☑️ تطابق» إن أضيفا بعد النشر)، ويعدّل مرة واحدة."""
    from tools import confirm as CF
    if ledger is None:
        return False, "no_ledger"
    rec = next((r for r in ledger.data["posts"] if r.get("message_id") == job["mid"]), None)
    if rec is None:
        return False, "no_rec"
    if job["mid"] in ledger.edited_ids("enrich"):
        return False, "done"
    if ledger.edits_last_hour() >= CF.MAX_EDITS_HOUR:
        return False, "cap"
    cur = ledger.caption_of(rec)
    keep = [ln for ln in cur.split("\n") if KEEP_RX.match(ln)]
    verify = plan["verify"]
    vtyp = plan["vtyp"]
    if keep:  # سطر تأكيد أضيف بعد النشر (confirm.check): يبقى كما هو، ولا سطر تأكيد ثانٍ ولا «غير مؤكد» يناقضه
        vtyp = None
        verify = verify if verify and verify.startswith("✅ التحقق") else None
    elif vtyp and job["mid"] in ledger.edited_ids(vtyp):
        vtyp, verify = None, "⏳ التحقق: غير مؤكد بعد"  # جُرّب هذا النوع سابقاً (مرة لكل نوع)
    cap = build_caption(plan["head"], job["loud"], job["src"], plan["details"], plan["also"], verify, keep, job.get("tags") or ())
    if not cap or not CF.html_ok(cap):
        return False, "caption"
    media = plan.get("media")
    if cap == cur and not media:
        return False, "same"
    kw = {"chat_id": chat_id, "message_id": str(job["mid"])}
    if job.get("kb"):
        kw["reply_markup"] = job["kb"]
    ok, kind, why = False, rec.get("kind") or "photo", ""
    if media:
        mtype, data = media
        im = {"type": mtype, "media": "attach://m", "caption": cap, "parse_mode": "HTML"}
        if mtype == "animation":
            im.update(width=1080, height=1350)
        try:
            r = api(token, "editMessageMedia", files={"m": ("breaking.mp4" if mtype == "animation" else "card.jpg", data,
                                                            "video/mp4" if mtype == "animation" else "image/jpeg")},
                    media=json.dumps(im, ensure_ascii=False), **kw)
            ok, why = bool(r.get("ok")), str(r.get("description") or "")[:80]
            if ok:
                kind = mtype
                STATUS["anim_ok"] += int(mtype == "animation")
        except Exception as e:  # noqa: BLE001
            why = type(e).__name__
    if not ok:  # الوسائط تعذرت: تعديل التعليق وحده
        try:
            r = api(token, "editMessageCaption", caption=cap, parse_mode="HTML", **kw)
            ok, why = bool(r.get("ok")), str(r.get("description") or why)[:80]
        except Exception as e:  # noqa: BLE001
            ok, why = False, type(e).__name__
    ledger.mark(rec, ok, "إثراء", why, typ="enrich", cap=cap if ok else None)
    if ok:
        rec["kind"] = kind
        if vtyp:
            ledger.mark(rec, True, plan.get("vname") or "", "إثراء", typ=vtyp, cap=cap)
    ledger.save()
    return ok, why or ("media" if media else "caption")


class Enricher:
    """جدولة الإثراء: job يُضاف بعد الإرسال، ويُحضَّر بخيط خلفي عند حلول موعده، ويُطبق في الخيط الرئيسي (السجل لا يُلمس من خيطين)."""

    def __init__(self, after=45, workers=1, **deps):
        from concurrent.futures import ThreadPoolExecutor
        self.after = max(ENRICH_MIN, min(ENRICH_MAX - 15, after))
        self.jobs, self.ready = [], []
        self.deps = deps
        self.ex = ThreadPoolExecutor(workers, thread_name_prefix="enrich") if workers else None
        self.lock = threading.Lock()

    def add(self, job):
        job["due"] = job.get("sent_at", time.time()) + self.after
        self.jobs.append(job)

    def tick(self, recent, ledger, api, token, chat_id, now=None):
        now = now or time.time()
        for j in [j for j in self.jobs if j["due"] <= now]:
            self.jobs.remove(j)
            if now - j["sent_at"] > ENRICH_MAX:
                STATUS["enrich_skip"] += 1
                continue
            snap = [r for r in recent if r["ts"] >= j["src_ts"] - 60]
            if self.ex:
                self.ex.submit(self._prep, j, snap)
            else:
                self._prep(j, snap)
        with self.lock:
            ready, self.ready = self.ready, []
        n = 0
        for j, plan in ready:
            if plan is None or time.time() - j["sent_at"] > ENRICH_MAX + 30:
                STATUS["enrich_skip"] += 1
                continue
            ok, why = apply(j, plan, ledger, api, token, chat_id)
            if ok:
                STATUS["enrich_ok"] += 1
                LAT.add("prep", plan.get("prep_s"))
                n += 1
            elif why in ("same", "done", "cap"):
                STATUS["enrich_skip"] += 1
            else:
                STATUS["enrich_fail"] += 1
                print("::warning title=enrich::", why)
        return n

    def _prep(self, j, snap):
        try:
            plan = prepare(j, snap, **self.deps)
        except Exception as e:  # noqa: BLE001
            print("::warning title=enrich prep::", type(e).__name__)
            plan = None
        with self.lock:
            self.ready.append((j, plan))


# ───────── قراءة صور الوثائق الرسمية ─────────
OCR_PER_HOUR = 20
OCR_CALLS = []
WM_PROMPT = ("Look at this news photo. Does it contain a visible logo, watermark, bug or channel name of a TV channel, news agency, "
             "website or social-media page (usually in a corner, semi-transparent, or a banner/ticker)? Official government emblems that are "
             "part of the scene (flags, ministry signs on walls) do NOT count. Also answer YES if the image is mainly a screenshot of a "
             "social-media post or text, or carries a large overlaid caption, headline or date stamp. Answer with exactly one word: YES or NO.")
_WM_CACHE = {}
WM_CALLS = []


def watermarked(img, gem=None, gem_ok=None):
    """هل على الصورة شعار/علامة مائية لوسيلة إعلام أخرى؟ True/False، وNone إذا تعذّر الفحص (الحصة/النموذج).
    طلب إيهاب 05/11: لا تظهر شعارات القنوات الأخرى بمنشوراتنا. لا نغطيها بشعارنا (ذلك نسب لمحتوى غيرنا لأنفسنا)
    بل لا نستخدم الصورة الموسومة: البطاقة تنزل بتصميم النص، والصورة النظيفة فقط تُضاف بالإثراء."""
    if not img:
        return None
    import hashlib
    k = hashlib.sha1(img).hexdigest()
    if k in _WM_CACHE:
        return _WM_CACHE[k]
    now = time.time()
    WM_CALLS[:] = [t for t in WM_CALLS if t >= now - 3600]
    if len(WM_CALLS) >= 60 or (gem_ok is not None and not gem_ok()):
        return None
    if gem is None:
        from tools.editorial import gemini as gem
    WM_CALLS.append(now)
    try:
        out = gem(WM_PROMPT, max_tokens=64, temperature=0, parts=[{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img).decode()}}])
    except Exception:  # noqa: BLE001
        out = None
    v = None if not out else (True if "YES" in out.upper() else False if "NO" in out.upper() else None)
    if v is not None:
        _WM_CACHE[k] = v
        STATUS["wm_yes" if v else "wm_no"] = STATUS.get("wm_yes" if v else "wm_no", 0) + 1
    return v


OCR_PROMPT = (
    "هذه صورة نشرتها قناة جهة رسمية عراقية بلا نص تقريباً. اقرأ الصورة فقط ولا تخمّن ولا تضف شيئاً غير مكتوب فيها.\n"
    "أعد JSON فقط بالمفاتيح:\n"
    '{"readable": true/false (هل النص مقروء بوضوح), "document": true/false (كتاب أو بيان أو أمر أو إعلان رسمي مكتوب، لا صورة فعالية أو تصميم تهنئة),'
    ' "issuer": "الجهة المصدرة كما كُتبت في الترويسة", "date": "تاريخ الوثيقة كما كُتب أو فارغ",'
    ' "public": true/false (قرار أو إعلان يمس الناس أو الشأن العام: دوام، عطلة، رواتب، قبول، أسعار، إجراء أمني أو حكومي أو قضائي)،'
    ' "decision": "جوهر القرار بجملة خبرية واحدة بكلمات الوثيقة نفسها (8–20 كلمة)",'
    ' "text": "نسخ حرفي لأهم سطرين أو ثلاثة من متن الوثيقة"}\n'
    "إذا كانت غير مقروءة أو ليست وثيقة فاجعل readable أو document false واترك الباقي فارغاً.")


def ocr_ok(now=None):
    now = now or time.time()
    OCR_CALLS[:] = [t for t in OCR_CALLS if t >= now - 3600]
    return len(OCR_CALLS) < OCR_PER_HOUR


def _doc_date(s, now):
    m = re.search(r"(\d{1,2})\s*[/\\\-.]\s*(\d{1,2})\s*[/\\\-.]\s*(20\d\d)", (s or "").translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")))
    if not m:
        return None
    d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return datetime(y, mo, d, tzinfo=timezone.utc).timestamp()
    except ValueError:
        try:
            return datetime(y, d, mo, tzinfo=timezone.utc).timestamp()
        except ValueError:
            return None


def ocr_doc(img, issuer_hint="", gem=None, gem_ok=None, now=None):
    """يرجع (dict|None, code). dict = {head, text, issuer, date}. code للسجل: ocr_cap/ocr_unavailable/ocr_unreadable/ocr_not_doc/
    ocr_not_public/ocr_unsafe/ocr_old/ocr. لا عنوان إلا من كلمات الوثيقة (حارس editorial._safe)."""
    from tools.editorial import _safe, clean_headline, formal_rules
    now = now or time.time()
    if not img:
        return None, "ocr_noimg"
    if not ocr_ok(now) or (gem_ok is not None and not gem_ok()):
        STATUS["ocr_skip"] += 1
        return None, "ocr_cap"
    if gem is None:
        from tools.editorial import gemini as gem
    OCR_CALLS.append(now)
    STATUS["ocr_calls"] += 1
    try:
        out = gem(OCR_PROMPT, max_tokens=400, temperature=0, parts=[{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img).decode()}}],
                  timeout=20)
    except TypeError:
        out = gem(OCR_PROMPT, max_tokens=400, temperature=0, parts=[{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img).decode()}}])
    if out is None:
        return None, "ocr_unavailable"
    try:
        g = re.search(r"\{.*\}", out, re.S)
        d = json.loads(g.group(0) if g else out)
    except Exception:  # noqa: BLE001
        return None, "ocr_unreadable"
    if not d.get("readable"):
        return None, "ocr_unreadable"
    if not d.get("document"):
        return None, "ocr_not_doc"
    if not d.get("public"):
        return None, "ocr_not_public"
    issuer = " ".join(str(d.get("issuer") or "").split())[:60]
    dec = " ".join(str(d.get("decision") or "").split())
    txt = " ".join(str(d.get("text") or "").split())[:900]
    if not dec or not txt or len(dec.split()) < 5:
        return None, "ocr_unreadable"
    dt = _doc_date(d.get("date"), now)
    if dt and now - dt > 7 * 86400:
        return None, "ocr_old"  # كتاب قديم أعيد نشره: ليس خبراً جديداً
    issuer = issuer or issuer_hint
    head = formal_rules(clean_headline((issuer + ": " if issuer and issuer not in dec[:40] else "") + dec, max_len=170))
    base = txt + " " + issuer + " " + (issuer_hint or "")
    if not _safe(base, head, need=""):
        return None, "ocr_unsafe"  # كلمة أو رقم ليس في نص الوثيقة المنسوخ: لا ننشر ما لم يُقرأ فعلاً
    STATUS["ocr_used"] += 1
    return {"head": head, "text": head + "\n" + txt, "issuer": issuer, "date": d.get("date") or ""}, "ocr"
