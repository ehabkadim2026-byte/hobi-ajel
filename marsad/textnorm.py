"""توحيد النص العربي والروابط والتوقيت — بلا مكتبات خارجية."""
import hashlib
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

BAGHDAD = timezone(timedelta(hours=3))  # بلا توقيت صيفي

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"
_TRANS = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي", "ی": "ي", "ئ": "ي",
    "ة": "ه", "ؤ": "و",
    "ک": "ك", "گ": "ك", "چ": "ج", "پ": "ب", "ڤ": "ف",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
})
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")

STOP = set("""
في من على الى إلى عن مع هذا هذه ذلك تلك التي الذي الذين ان أن إن او أو ثم قد لا ما لم لن كل بعد قبل عند
حول خلال بين ضد عبر كما بشان بشأن وفق اليوم امس غدا عاجل بالفيديو بالوثيقه بالصور فيديو للمزيد
the a an of in on to for and or is are was were by with from at as
""".split())


def norm_ar(text: str) -> str:
    if not text:
        return ""
    t = unicodedata.normalize("NFKC", text)
    t = _DIACRITICS.sub("", t).replace(_TATWEEL, "")
    t = t.translate(_TRANS).lower()
    t = _PUNCT.sub(" ", t)
    return _WS.sub(" ", t).strip()


PROTECTED = set("بغداد بابل بصره بعقوبه بيجي بلد بدره بلدروز بعشيقه بارزاني باكستان بريطانيا بلجيكا لبنان ليبيا".split())


def _stem(w: str) -> str:
    # تجريد خفيف للسوابق الشائعة؛ يكفي للمقارنة لا للتحليل الصرفي. أسماء الأماكن محمية.
    if w in PROTECTED:
        return w
    for p in ("وال", "بال", "كال", "فال", "لل", "ال"):
        if w.startswith(p) and len(w) - len(p) >= 3:
            return w[len(p):]
    if len(w) >= 5 and w[0] in "وبفل" and not w.startswith("ال") and w[1:] not in PROTECTED:
        return w[1:]
    if len(w) >= 6 and w[0] == "و" and w[1:] in PROTECTED:
        return w[1:]
    return w


def tokens(text: str) -> list:
    return [_stem(w) for w in norm_ar(text).split() if w not in STOP and len(w) > 1]


def fingerprint(text: str) -> str:
    return hashlib.sha1(" ".join(sorted(set(tokens(text)))).encode()).hexdigest()[:16]


_TRACK = re.compile(r"^(utm_|fbclid|gclid|mibextid|igshid|ref|s|si|amp)", re.I)


def canonical_url(url: str) -> str:
    if not url:
        return ""
    u = urlsplit(url.strip())
    host = (u.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m.") and "facebook" in host:
        host = host[2:]
    path = quote(unquote(u.path), safe="/%-._~")  # يحل مشكلة الروابط العربية المرمّزة مرتين
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    q = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=False) if not _TRACK.match(k)]
    return urlunsplit(("https", host, path, urlencode(sorted(q)), ""))


def parse_time(value):
    """يرجع datetime بتوقيت UTC أو None. لا يخترع ساعة لتاريخ يوم فقط."""
    if not value:
        return None, "unknown"
    s = str(value).strip()
    fmts = [
        ("%Y-%m-%dT%H:%M:%S%z", "exact"), ("%Y-%m-%dT%H:%M%z", "exact"),
        ("%a, %d %b %Y %H:%M:%S %Z", "exact"), ("%a, %d %b %Y %H:%M:%S %z", "exact"),
        ("%Y-%m-%d %H:%M:%S", "exact"), ("%Y-%m-%d", "day"),
    ]
    s2 = s.replace("Z", "+00:00") if s.endswith("Z") else s
    for f, prec in fmts:
        try:
            d = datetime.strptime(s2 if "%z" in f else s, f)
        except ValueError:
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc), prec
    try:
        d = datetime.fromisoformat(s2)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc), "exact"
    except ValueError:
        return None, "unknown"


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def to_baghdad(iso_utc, precision="exact"):
    if not iso_utc:
        return "غير متوفر"
    d = datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(BAGHDAD)
    return d.strftime("%Y-%m-%d") if precision == "day" else d.strftime("%Y-%m-%d %H:%M")


def now_utc():
    return datetime.now(timezone.utc)


# ───────── ذيل اسم الناشر في العناوين ─────────
# Google News يرسل «العنوان » وكالة الانباء العراقية (واع) | اخبار العراق - وكالة الانباء العراقية (واع)»: فصل « - الناشر» وحده
# كان يُبقي «… » وكالة الانباء العراقية (واع) | اخبار العراق» عنواناً للعنقود (لقطة التطبيق 05/11). الفاصل « » » بمسافتين أو « | »
# (لا «»» الملتصقة بنهاية اقتباس) وذيل قصير يشبه اسم موقع يُحذف، ويتكرر حتى لا يبقى ذيل.
_SITE_SEP = re.compile(r"\s+(?:»|\||::|–|—)\s+(?=[^»|]*$)")
# ذيل «اسم موقع» فقط: يبدأ بنوع الوسيلة (وكالة/صحيفة/إذاعة…، أو «قناة/موقع» + اسم واحد)، أو فيه علامة اسم وسيلة (نيوز، برس، الإخبارية، (واع)…)،
# أو اسم وسيلة عراقية معروفة كاملاً، أو «أخبار العراق» — لا كلمات عامة («العراقية»، «عاجل») قد تكون جزءاً من الخبر
_SITE_WORDS = re.compile(r"^(?:وكالة|صحيفة|جريدة|مجلة|راديو|إذاعة|اذاعة)\s|^شبكة ال(?:إ|ا)علام العراقي|^(?:موقع|قناة|بوابة)\s+\S+$|(?:نيوز|news|برس|press|الإخبارية|الاخبارية|الفضائية|"
                         r"\(واع\)|\bINA\b|\btv\b|تي ?في)|^(?:أ|ا)خبار (?:العراق|اليوم|محلية)$|"
                         r"^(?:السومرية|شفق|المدى|الصباح|بغداد اليوم|روداو|رووداو|964|المربد|الفرات|دجلة|الرابعة|الشرقية|المسلة|العالم الجديد|"
                         r"كوردستان ?24|كردستان ?24|الغد برس|ألترا عراق|الترا عراق|المعلومة|العهد)(?:\s|$)", re.I)


def strip_site_suffix(title, outlet=None):
    """يحذف ذيول اسم الموقع/الناشر من آخر العنوان («… » وكالة الانباء العراقية (واع) | اخبار العراق»). لا يمس فاصلاً داخل الجملة:
    الذيل يُحذف فقط إذا كان قصيراً (≤ 6 كلمات) ويشبه اسم ناشر (كلمة موقع، أو اسم الناشر نفسه)، ويبقى من العنوان 4 كلمات فأكثر."""
    t = (title or "").strip()
    on = norm_ar(outlet or "")
    for _ in range(4):
        m = None
        for m in _SITE_SEP.finditer(t):
            pass
        if not m:
            break
        head, tail = t[:m.start()].strip(), t[m.end():].strip()
        tn = norm_ar(tail)
        pubish = bool(_SITE_WORDS.search(tail)) or bool(on and tn and (tn in on or on in tn))
        if not (pubish and len(tail.split()) <= 6 and len(head.split()) >= 4):
            break
        t = head
    if on:  # «العنوان - الناشر» بلا مسافات حول الشرطة أو اسم الناشر ملتصق بآخر العنوان بعد « - »
        m2 = re.search(r"\s+[-–—]\s+([^-–—]{2,60})$", t)
        if m2 and norm_ar(m2.group(1)) == on and len(t[:m2.start()].split()) >= 4:
            t = t[:m2.start()].strip()
    m3 = re.search(r"\s+وكالة\s+[\u0600-\u06FF ]{2,30}?\s*\([^()]{2,12}\)\s*$", t)  # «… «اقتباس» وكالة الانباء العراقية (واع)» بلا فاصل
    if m3 and len(t[:m3.start()].split()) >= 4:
        t = t[:m3.start()].strip()
    if on and len(on.split()) >= 2:
        nt = norm_ar(t)
        if nt.endswith(" " + on) and len(t.split()) - len(on.split()) >= 4:
            t = " ".join(t.split()[:-len(on.split())])
    if t == (title or "").strip():
        return t
    t = t.rstrip(" -–—|:،")
    while t.endswith("»") and t.count("»") > t.count("«"):
        t = t[:-1].rstrip(" -–—|:،")  # «»» يتيمة بقيت من الفاصل؛ «»» تغلق اقتباساً تبقى
    return t
