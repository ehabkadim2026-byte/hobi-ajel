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
