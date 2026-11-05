"""تحرير «أكا ميديا» بالقواعد — مجاني وفوري ولا يغيّر الحقائق.

ينظّف العنوان قبل النشر: يحذف تواقيع القنوات والهاشتاغات والإيموجي ووسوم «عاجل/خاص/بالفيديو» المكررة والروابط،
ويوحّد الترقيم والاقتباس والمسافات، ويقص الطول عند حد الكلمة. لا يضيف كلمة ولا يغيّر اسماً أو رقماً،
وإذا أفرغ التنظيف العنوان أو غيّر أرقامه نرجع للأصل.
"""
import re

from marsad.textnorm import strip_site_suffix

EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍←-⇿■-◿]+")
TAGS = re.compile(r"^\s*(?:[\[\(«]?\s*(?:عاجل|عــاجل|عاااجل|خاص|حصري|بالفيديو|بالصور|فيديو|صور|متابعة|مباشر|الآن|هام|مهم|تحديث)\s*[\]\)»]?\s*(?:[|:：\-–—/…]|\.{2,})+\s*)+")
TAGS_END = re.compile(r"\s*[|\-–—]\s*(?:عاجل|خاص|بالفيديو)\s*$")
HASHTAG = re.compile(r"#[\w_؀-ۿ]+")
URL = re.compile(r"https?://\S+|t\.me/\S+|www\.\S+|@[A-Za-z0-9_]{4,}")
SIGN = re.compile(r"\s*[|\-–—]\s*(?:(?:[؀-ۿA-Za-z0-9 .]{2,30})\s*(?:نيوز|news|نت|net|tv|تي ?في|الإخبارية|الاخبارية|الفضائية|برس|press|24|للأنباء|عراق)|الواجهة|الاولى|الأولى)\s*$", re.I)  # «… - الواجهة» (تدقيق 2969)
FOLLOW = re.compile(r"\s*[:،-]?\s*(?:تابعونا|للمزيد من الأخبار|لمزيد من التفاصيل|المزيد من التفاصيل|للمزيد|اشترك|رابط القناة|انضموا|التفاصيل في الرابط|التفاصيل بالرابط|التفاصيل عبر الرابط|اقرأ المزيد|اقرأ التفاصيل)\b.*$")  # «…الدينار: لمزيد من التفاصيل عبر الرابط» (تدقيق 2962)
DIGITS = re.compile(r"\d+")
PREFIX = re.compile(r"^(?:وكالة\s+)?[\w\u0600-\u06FF .]{2,28}?(?:نيوز|news|برس|press|الإخبارية|الاخبارية|للأنباء|تي في|TV)\s*[-–—|:]\s+", re.I)


def clean_headline(title, max_len=170):
    if not title:
        return title
    t = re.sub(r"ـ*[.*]+ـ*(?=[\u0600-\u06FF])", "", title)  # «القبـ.ـض» و«يـ*ـهدد» ← القبض، يهدد (تمويه الكلمات لتفادي الحظر)
    t = re.sub(r"ـ+\s?(?=ـ)", "", t)
    t = re.sub(r"(?<=[\u0621-\u064A])ـ+(?=[\u0621-\u064A])", "", t)  # التطويل بين الحروف يُحذف؛ «بـ6» و«لـ كوردستان» تبقى
    t = URL.sub(" ", t)
    t = t.replace(",,", "").replace("،،", "")
    t = PREFIX.sub("", t.strip())
    t = EMOJI.sub(" ", t)
    m = re.search(r"(?:\s+#[\w_؀-ۿ]+)+\s*$", t)  # سلسلة هاشتاغات آخر النص تُحذف، إلا إذا كانت تكملة الجملة («… في #بغداد»)
    if m and not re.search(r"(?:^|\s)(?:في|من|على|إلى|الى|عن|مع|بين|و|محافظة|مدينة|قضاء)\s*$", t[:m.start()]):
        t = t[:m.start()]
    t = HASHTAG.sub(lambda m: m.group(0)[1:].replace("_", " "), t)  # الهاشتاغ داخل الجملة جزء منها: «#الدولار يرتفع في #بغداد و#أربيل» (تدقيق 2883)
    t = FOLLOW.sub("", t)
    t = TAGS.sub("", t.strip())
    t = re.sub(r"^\s*(?:عاجل|خاص|هام|مهم)\s+(?=\S)", "", t)
    t = TAGS_END.sub("", t)
    t = SIGN.sub("", t)
    t = strip_site_suffix(t)  # «… » وكالة الانباء العراقية (واع) | اخبار العراق» (لقطة التطبيق 05/11)
    t = t.replace('"', "«", 1).replace('"', "»", 1) if t.count('"') >= 2 else t
    t = re.sub(r"\.{2,}", "…", t)
    t = re.sub(r"«\s+", "«", re.sub(r"\s+»", "»", t))
    t = re.sub(r"\s+([،,.:؛!؟?])", r"\1", t)
    t = re.sub(r"([،:؛])(?=\S)", r"\1 ", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" -–—|:،")
    if len(t) > max_len:
        cut = t[:max_len].rsplit(" ", 1)[0]
        t = cut.rstrip("،,:-") + "…"
    # حماية الحقائق: لا عنوان فارغ، ولا أرقام مفقودة
    if len(t) < 12 or sorted(DIGITS.findall(t)) != sorted(DIGITS.findall(URL.sub(" ", title))) and len(DIGITS.findall(t)) < len(DIGITS.findall(URL.sub(" ", title))):
        return " ".join(URL.sub(" ", title).split())[:max_len]
    return t


# ───────────── تحرير رصين ─────────────
# طبقتان: (1) قواعد مجانية دائمة: تحذف لغة الإثارة والطُعم وعلامات التعجب وتوحّد صيغة الإسناد.
# (2) إعادة صياغة بنموذج لغوي (Gemini، طبقته المجانية) إذا وُجد المفتاح GEMINI_API_KEY في أسرار GitHub؛
#     مع حارس حقائق: نفس الأرقام، لا أسماء جديدة، طول معقول — وإلا نرجع لنتيجة القواعد.
import json as _json
from marsad.textnorm import norm_ar
import os as _os
import urllib.request as _ur

BAIT = re.compile(r"(?:^|\s)(?:شاهد(?:وا)?|شوف|لن تصدق|لا يفوتك|صادم|صادمة|بالصور والفيديو|فيديو صادم|مفاجأة مدوية|مفاجأة|خطير جداً|خطير جدا|عاجل جداً|عاجل جدا|انفراد|حصرياً|حصريا)(?=\s|$|[:،.…])")
EXCL = re.compile(r"[!！]+")
QDUP = re.compile(r"([؟?]){2,}")


# أخطاء إملائية/نحوية متكررة في عناوين المصادر (فحص 4، تدقيق 18:15 04/11: 3060 «المحافطة»، 3037 «رئيس الوزراء على الزيدي»، 3002 «ترفض رفض قاطع»)
TYPOS = [(re.compile(r"(?<![\u0600-\u06FF])(ال)?محافطة"), r"\1محافظة"), (re.compile(r"(رئيس (?:مجلس )?الوزراء|الرئيس|السيد)\s+على\s+(?=(?:فالح\s+)?الزيدي)"), r"\1 علي "),
         (re.compile(r"(ي|ت|ن)رفض رفض قاطع(?![\u0600-\u06FF])"), r"\1رفض رفضاً قاطعاً"), (re.compile(r"\*+"), "")]


def formal_rules(t):
    for rx, rep in TYPOS:
        t = rx.sub(rep, t)
    t = re.sub(r"^\s*(?:هسه|هسة)\s+وصل\s*[.…:|\-–—]*\s*", "", t)
    t = BAIT.sub(" ", t)
    t = EXCL.sub("", t)
    t = QDUP.sub("؟", t)
    t = re.sub(r"\s*:\s*", ": ", t, count=1) if re.match(r"^[^:]{3,40}:", t) else t  # «الجهة: الخبر»
    t = re.sub(r"\s{2,}", " ", t).strip(" -–—|:،.…")
    return t


PROMPT = ("أنت محرر أخبار في قناة إخبارية عراقية رصينة. أعد صياغة العنوان التالي بعربية فصحى إخبارية رصينة وموجزة "
          "(سطر واحد، 9 إلى 18 كلمة؛ إذا كان العنوان فقرة طويلة فاختصره إلى جوهر الخبر)، بصيغة الإسناد المهنية (مثل: «وزارة الداخلية: ...» أو «أعلنت ... أن ...»).\n"
          "قواعد صارمة: لا تضف أي معلومة أو رقم أو اسم أو صفة أو كلمة توضيحية غير موجودة في العنوان (لا تضف مكاناً ولا جهة ولا تفصيلاً)؛ "
          "اكتب الأرقام بالأرقام كما وردت تماماً؛ احتفظ بكل الأسماء كما هي؛ لا تحوّل «قانون» إلى «مشروع قانون» ولا العكس؛ "
          "احذف الإثارة والعامية وعلامات التعجب والهاشتاغات؛ لا تحكم على صحة الخبر؛ إذا كان العنوان رأياً أو ادعاءً فانسبه لقائله.\n"
          "أعد العنوان فقط بلا مقدمة ولا علامات تنصيص.\n\nالعنوان: ")


def os_key():
    return bool(_os.environ.get("GEMINI_API_KEY", "").strip())


MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemma-4-31b-it", "gemma-4-26b-a4b-it",
          "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.8-flash"]
_EXHAUSTED = set()  # نموذج خلصت حصته اليومية بهذه الجولة: ننتقل للتالي (لكل نموذج حصة مجانية مستقلة)
_EXH_AT = {}  # 429 (حد الدقيقة غالباً) يوقف النموذج 10 دقائق فقط: المسار السريع يعمل 5.5 ساعات، وكان 429 واحد يطفئ حكم الأهمية لبقية الجولة
EXH_RETRY_SEC = 600


def gemini(prompt, max_tokens=120, temperature=0.2, parts=None, timeout=12):
    """parts: أجزاء وسائط اختيارية قبل النص (مثل {"inline_data": {"mime_type": ..., "data": base64}}) — بوابة المراسل (صوت/صورة)."""
    key = _os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    import urllib.error as _ue
    import time as _t
    for m, at in list(_EXH_AT.items()):
        if _t.time() - at >= EXH_RETRY_SEC:
            _EXH_AT.pop(m, None)
            _EXHAUSTED.discard(m)
    last = None
    for model in ([_os.environ["GEMINI_MODEL"]] if _os.environ.get("GEMINI_MODEL") else MODELS):
        if model in _EXHAUSTED:
            continue
        body = _json.dumps({"contents": [{"parts": list(parts or []) + [{"text": prompt}]}],
                            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}).encode()
        req = _ur.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                          data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            with _ur.urlopen(req, timeout=timeout) as r:
                d = _json.loads(r.read().decode())
            return d["candidates"][0]["content"]["parts"][0]["text"]
        except _ue.HTTPError as e:
            last = e
            if e.code in (429, 404, 403):
                _EXHAUSTED.add(model)
                if e.code == 429:
                    _EXH_AT[model] = _t.time()
            continue  # 500/503 (عطل مؤقت عند Google) أو حصة: نجرّب النموذج التالي بدل إيقاف الوكيل
        except (_ue.URLError, TimeoutError, KeyError, IndexError, ValueError) as e:
            last = e
            continue
    if last:
        LLM_STATS["error"] = LLM_STATS.get("error", 0) + 0  # يُحسب عند المستدعي
    return None


def _llm(title, context=""):
    extra = ("\n\nنص الخبر للمرجع فقط (استعمله لتوضيح العنوان دون إضافة تفاصيل ثانوية): " + context[:500]) if context else ""
    out = gemini(PROMPT + title + extra)
    if out is None:
        return None
    return out.strip().strip('"«»').split("\n")[0].strip()


# كلمات الصياغة المسموح للنموذج إضافتها (إسناد وربط فقط) — أي كلمة جديدة غيرها = رفض الصياغة
STYLE_OK = set("""أعلن أعلنت يعلن تعلن أكد أكدت يؤكد تؤكد قال قالت يقول تقول ذكر ذكرت أفاد أفادت أوضح أوضحت كشف كشفت تكشف يكشف
نفى نفت ينفي تنفي أن إن التي الذي الذين اللذين أي يقضي تقضي بشأن حول خلال إلى على في من عن مع بعد قبل وزارة وزير رسميا رسمياً
عن صدور اليوم هذا هذه ذلك تلك كما وفق وفقاً بحسب حسب عبر لدى بين نحو قرابة ضمن تم جرى
تضم يضم تشمل يشمل عقب إثر جراء بسبب لها له فيها فيه منها منه عدم انطلاق إطلاق بدء إجراء""".split())


def _stem(w):
    w = norm_ar(w.strip("«»،.:؛\"'()!؟?-–—"))
    for p in ("وال", "بال", "لل", "فال", "كال", "ال", "و", "ب", "ل", "ف"):
        if w.startswith(p) and len(w) - len(p) >= 3:
            w = w[len(p):]
            break
    for suf in ("ات", "ين", "ون", "ها", "هم", "ه", "ة"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[:-len(suf)]
            break
    return w


def _why(orig, new):
    if sorted(DIGITS.findall(orig)) != sorted(DIGITS.findall(new)):
        return "أرقام"
    have = {_stem(w) for w in orig.split()}
    ok_style = {_stem(w) for w in STYLE_OK} | {norm_ar(w) for w in STYLE_OK}
    return " ".join(w for w in new.split() if _stem(w) not in have and _stem(w) not in ok_style and len(_stem(w)) >= 3)[:80]


def _safe(orig, new, need=None):
    """حارس الحقائق: كل رقم في الصياغة موجود في الأصل، وأرقام «need» (العنوان) كلها محفوظة، ولا كلمة مضمونية جديدة."""
    if not new or len(new) < 15 or len(new) > 260:
        return False
    nd, od = set(DIGITS.findall(new)), set(DIGITS.findall(orig))
    if not nd <= od or not set(DIGITS.findall(orig if need is None else need)) <= nd:
        return False
    have = {_stem(w) for w in orig.split()}
    ok_style = {_stem(w) for w in STYLE_OK} | {norm_ar(w) for w in STYLE_OK}
    for w in new.split():
        st = _stem(w)
        if len(st) < 3 or st in have or st in ok_style or norm_ar(w.strip("«»،.:؛\"'")) in ok_style:
            continue
        core = lambda x: x[1:] if len(x) >= 4 and x[0] in "نيتأا" else x  # نرفض/يرفض/ترفض ← رفض
        if any(len(st) >= 3 and (core(st) in core(h) or core(h) in core(st)) and abs(len(core(st)) - len(core(h))) <= 2
               for h in have if len(h) >= 3):
            continue  # نفس الجذر بصيغة صرفية قريبة (ينفي/نفى، تصوت/التصويت، نرفض/رفض)
        skel = lambda x: re.sub("[اويى]", "", core(x))
        if len(skel(st)) >= 3 and any(skel(st) == skel(h) for h in have if len(h) >= 3):
            continue  # نقبل/قبول، يواجه/مواجهة (نفس الحروف الأصلية)
        return False
    return True


LLM_STATS = {"ok": 0, "rejected": 0, "error": 0, "off": 0}
REJECTS = []


def edit_headline(title, max_len=170, context=""):
    base = formal_rules(clean_headline(title, max_len=max_len))
    try:
        new = _llm(base, context)
    except Exception:  # noqa: BLE001
        LLM_STATS["error"] += 1
        return base
    if new is None:
        LLM_STATS["off"] += 1
        return base
    new = formal_rules(clean_headline(new, max_len=max_len))
    if _safe(base + " " + clean_headline(context or "", max_len=600), new, need=base):
        LLM_STATS["ok"] += 1
        return new
    LLM_STATS["rejected"] += 1
    if len(REJECTS) < 4:
        REJECTS.append({"in": base[:120], "out": new[:140], "why": _why(base, new)})
    return base


BAD_FRAG = re.compile(r"(،\s?\S{1,3}\s)|(\S{1,3}،\s?\S)|[#@]|عاجل|متداول|شاهد")


def title_score(t):
    """أفضل عنوان بين صياغات المصادر: طول خبري (9–20 كلمة)، بلا تمويه أو هاشتاغ أو «عاجل»، ويبدأ بالجهة أو الحدث."""
    c = clean_headline(t or "")
    w = len(c.split())
    if w < 5:
        return -99
    sc = -abs(w - 14) * 0.6
    sc -= 6 * len(BAD_FRAG.findall(t or ""))
    if ":" in c[:40]:
        sc += 2  # صيغة «الجهة: الخبر»
    if c.endswith("؟") or c.endswith("…"):
        sc -= 3
    return sc


def pick_best(titles):
    titles = [t for t in titles if t]
    return max(titles, key=title_score) if titles else ""


AGENT_PROMPT = ("أنت محرر ديسك أخبار في قناة عراقية رصينة. من العنوان ونص الخبر التاليين اكتب سطرين فقط:\n"
                "السطر 1: عنوان إخباري رصين موجز (9–16 كلمة) بصيغة الإسناد المهنية.\n"
                "السطر 2: جملة مقدمة واحدة (12–28 كلمة) تضيف أهم تفصيل موجود في النص ولم يرد في العنوان (من/أين/متى/لماذا/الخطوة التالية).\n"
                "قواعد صارمة: لا تضف أي معلومة أو رقم أو اسم غير موجود في النص؛ اكتب الأرقام كما وردت؛ لا رأي ولا تهويل ولا اتهام؛ "
                "إذا كان ادعاءً فانسبه لقائله؛ إذا لم يوجد تفصيل إضافي مفيد فاكتب في السطر 2 كلمة: لا\n"
                "أعد السطرين فقط بلا ترقيم ولا علامات تنصيص.\n\n")


def agent_write(title, context):
    """وكيل التحرير للقناة: عنوان + جملة مقدمة من نص الخبر، كلاهما يمر بحارس الحقائق. يرجع (عنوان، مقدمة أو "")."""
    base = formal_rules(clean_headline(title, max_len=200))
    ctx = clean_headline(context or "", max_len=700)
    try:
        out = gemini(AGENT_PROMPT + f"العنوان: {base}\nالنص: {ctx}", max_tokens=200)
    except Exception:  # noqa: BLE001
        LLM_STATS["error"] += 1
        return base, ""
    if not out:
        return base, ""
    lines = [ln.strip().strip('"«»').lstrip("0123456789.-) ").strip() for ln in out.strip().split("\n") if ln.strip()]
    head = formal_rules(clean_headline(lines[0], max_len=200)) if lines else ""
    lead = lines[1] if len(lines) > 1 else ""
    ref = base + " " + ctx
    if not (head and _safe(ref, head, need=base)):
        LLM_STATS["rejected"] += 1
        head = base
    else:
        LLM_STATS["ok"] += 1
    if lead in ("لا", "لا يوجد") or len(lead.split()) < 8 or not _safe(ref, lead, need="") or lead[:30] in head:
        lead = ""
    return head, lead.rstrip(".") + ("." if lead else "")


_URL = re.compile(r"https?://\S+|t\.me/\S+|www\.\S+")
_SIG = re.compile(r"(الدائرة الاعلامية|المكتب الاعلامي|المكتب الإعلامي|الدائرة الإعلامية|تابعونا|للاشتراك|رابط القناة)")


def complete_line(text):
    """العنوان الكامل من منشور متعدد الأسطر: إذا السطر الأول اسم متحدث/جهة فقط («رئيس الوزراء علي الزيدي» أو ينتهي بـ«:»)
    أو شذرة تبدأ بنقطة «•»، نضمه للسطر التالي («الجهة: الكلام»)."""
    lines = [_URL.sub("", ln).strip(" -–|🔻🔴📌⭕️🚨•▪️◾️") for ln in (text or "").split("\n")]
    lines = [ln for ln in lines if ln and not _SIG.search(ln[:40]) and not re.fullmatch(r"[#\W\d]*(عاجل|عــاجل)?[#\W]*", ln)
             and not re.fullmatch(r"(?:#[\w_؀-ۿ]+[\s\W]*)+", ln)]  # سطر هاشتاغات فقط ليس تكملة للعنوان (تدقيق 2884)
    if not lines:
        return ""
    lines = [re.sub(r"^\W*(عاجل|عــاجل|خاص|متابعة)\s*[|:\-–_/]*\s*", "", ln).strip() for ln in lines]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""
    first = lines[0]
    if (len(first.split()) < 7 or first.endswith(":")) and len(lines) > 1:
        nxt = lines[1]
        return (first.rstrip(":： ") + ": " + nxt)[:240] if len(nxt.split()) >= 3 else first
    return first
