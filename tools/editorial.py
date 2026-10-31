"""تحرير «هسة وصل» بالقواعد — مجاني وفوري ولا يغيّر الحقائق.

ينظّف العنوان قبل النشر: يحذف تواقيع القنوات والهاشتاغات والإيموجي ووسوم «عاجل/خاص/بالفيديو» المكررة والروابط،
ويوحّد الترقيم والاقتباس والمسافات، ويقص الطول عند حد الكلمة. لا يضيف كلمة ولا يغيّر اسماً أو رقماً،
وإذا أفرغ التنظيف العنوان أو غيّر أرقامه نرجع للأصل.
"""
import re

EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍←-⇿■-◿]+")
TAGS = re.compile(r"^\s*(?:[\[\(«]?\s*(?:عاجل|عــاجل|عاااجل|خاص|حصري|بالفيديو|بالصور|فيديو|صور|متابعة|مباشر|الآن|هام|مهم|تحديث)\s*[\]\)»]?\s*(?:[|:：\-–—/…]|\.{2,})+\s*)+")
TAGS_END = re.compile(r"\s*[|\-–—]\s*(?:عاجل|خاص|بالفيديو)\s*$")
HASHTAG = re.compile(r"#[\w_؀-ۿ]+")
URL = re.compile(r"https?://\S+|t\.me/\S+|www\.\S+|@[A-Za-z0-9_]{4,}")
SIGN = re.compile(r"\s*[|\-–—]\s*(?:[؀-ۿA-Za-z0-9 .]{2,30})\s*(?:نيوز|news|نت|net|tv|تي ?في|الإخبارية|الاخبارية|الفضائية|برس|press|24|للأنباء|عراق)\s*$", re.I)
FOLLOW = re.compile(r"\s*(?:تابعونا|للمزيد من الأخبار|للمزيد|اشترك|رابط القناة|انضموا|التفاصيل في الرابط|التفاصيل بالرابط)\b.*$")
DIGITS = re.compile(r"\d+")


def clean_headline(title, max_len=170):
    if not title:
        return title
    t = URL.sub(" ", title)
    t = EMOJI.sub(" ", t)
    t = HASHTAG.sub(" ", t)
    t = FOLLOW.sub("", t)
    t = TAGS.sub("", t.strip())
    t = TAGS_END.sub("", t)
    t = SIGN.sub("", t)
    t = t.replace('"', "«", 1).replace('"', "»", 1) if t.count('"') >= 2 else t
    t = re.sub(r"\.{2,}", "…", t)
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
import os as _os
import urllib.request as _ur

BAIT = re.compile(r"(?:^|\s)(?:شاهد(?:وا)?|شوف|لن تصدق|لا يفوتك|صادم|صادمة|بالصور والفيديو|فيديو صادم|مفاجأة مدوية|مفاجأة|خطير جداً|خطير جدا|عاجل جداً|عاجل جدا|انفراد|حصرياً|حصريا)(?=\s|$|[:،.…])")
EXCL = re.compile(r"[!！]+")
QDUP = re.compile(r"([؟?]){2,}")


def formal_rules(t):
    t = BAIT.sub(" ", t)
    t = EXCL.sub("", t)
    t = QDUP.sub("؟", t)
    t = re.sub(r"\s*:\s*", ": ", t, count=1) if re.match(r"^[^:]{3,40}:", t) else t  # «الجهة: الخبر»
    t = re.sub(r"\s{2,}", " ", t).strip(" -–—|:،.…")
    return t


PROMPT = ("أنت محرر أخبار في قناة إخبارية عراقية رصينة. أعد صياغة العنوان التالي بعربية فصحى إخبارية رصينة وموجزة "
          "(سطر واحد، 10 إلى 24 كلمة)، بصيغة الإسناد المهنية (مثل: «وزارة الداخلية: ...» أو «أعلنت ... أن ...»).\n"
          "قواعد صارمة: لا تضف أي معلومة أو رقم أو اسم أو صفة غير موجودة؛ احتفظ بكل الأرقام والأسماء كما هي؛ "
          "احذف الإثارة والعامية وعلامات التعجب والهاشتاغات؛ لا تحكم على صحة الخبر؛ إذا كان العنوان رأياً أو ادعاءً فانسبه لقائله.\n"
          "أعد العنوان فقط بلا مقدمة ولا علامات تنصيص.\n\nالعنوان: ")


def _llm(title):
    key = _os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    model = _os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
    body = _json.dumps({"contents": [{"parts": [{"text": PROMPT + title}]}],
                        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 120}}).encode()
    req = _ur.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                      data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with _ur.urlopen(req, timeout=12) as r:
        d = _json.loads(r.read().decode())
    return d["candidates"][0]["content"]["parts"][0]["text"].strip().strip('"«»').split("\n")[0].strip()


def _safe(orig, new):
    """حارس الحقائق: نفس الأرقام، طول معقول، ونسبة كلمات مشتركة كافية (لا اختلاق)."""
    if not new or len(new) < 15 or len(new) > 220:
        return False
    if sorted(DIGITS.findall(orig)) != sorted(DIGITS.findall(new)):
        return False
    norm = lambda s: {w.strip("«»،.:؛\"'") .removeprefix("ال").removeprefix("و") for w in s.split() if len(w) > 2}
    a, b = norm(orig), norm(new)
    return bool(b) and len(a & b) / len(b) >= 0.45


LLM_STATS = {"ok": 0, "rejected": 0, "error": 0, "off": 0}


def edit_headline(title, max_len=170):
    base = formal_rules(clean_headline(title, max_len=max_len))
    try:
        new = _llm(base)
    except Exception:  # noqa: BLE001
        LLM_STATS["error"] += 1
        return base
    if new is None:
        LLM_STATS["off"] += 1
        return base
    new = formal_rules(clean_headline(new, max_len=max_len))
    if _safe(base, new):
        LLM_STATS["ok"] += 1
        return new
    LLM_STATS["rejected"] += 1
    return base
