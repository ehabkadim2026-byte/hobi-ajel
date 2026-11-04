"""موثوقية المصادر (مرة يومياً داخل الجولة الرئيسية، بلا نموذج لغوي): لكل مصدر نشر 15 خبراً عراقياً فأكثر خلال 14 يوماً نقيس
من أرشيف الرصد نفسه (العناقيد = الحدث نفسه لدى جهات متعددة، والجهات الرسمية = تعريف tools/confirm.py):

- confirmed_rate: من ادعاءاته «الأصلية» (التي سبق بها أي جهة رسمية في العنقود) نسبة ما نشرت جهة رسمية لاحقاً (≤24 ساعة) خبراً متسقاً
  معه (الخبر نفسه بالبصمة، الأرقام المشتركة متفقة، وليس نفياً).
- denied_rate: نسبة ما نشرت عنه جهة رسمية لاحقاً نفياً (لا صحة/عار عن الصحة/غير صحيح/تنفي…) للخبر نفسه.
- first_rate: من العناقيد التي نشرتها جهتان فأكثر، نسبة ما كان فيه أول من نشر (أصالة لا نقل).
- number_mismatch_rate: حين توجد جهة رسمية للخبر نفسه ولكليهما أرقام (حصيلة، مبلغ، موعد): نسبة تعارض الأرقام.
- relay_rate: نسبة ما نشره بعد جهة رسمية (نقل بيان)، لا تدخل في التأكيد/النفي.
- volume، median_lead_min (فارقه عن أول ناشر للعنقود بالدقائق، وسيط).

الدرجة 0–100 (الأوزان W أدناه، والنِّسب مُنعَّمة نحو المتوسط العام بوزن PRIOR_K عيّنة حتى لا تتطرف العينات الصغيرة):
  40 + 30×min(1, تأكيد/0.08) + 20×min(1, سبق/0.50) + 10×(1 − min(2, تأخر وسيط/60د)) − 450×نفي − 60×تعارض أرقام
مقطوعة بين 0 و100. الطبقات: موثوقة (≥75 ونفي ≤2% وn≥30 و3 تأكيدات رسمية فعلية على الأقل)، ضعيفة (نفي ≥8% أو درجة <40)، عادية، «غير كافٍ» (عينات أقل من الحد).
الجهات الرسمية تُدرج منفصلة (مصدر أولي لا «موثوق»)، والجهات المستبعدة بقرار ثابت لا تُقيَّم.

الناتج: source_trust.json على إصدار fastlane + pwa/source_trust.json للتطبيق. يُعاد الحساب إذا مضى على آخر حساب 20 ساعة فأكثر،
وإلا تُنسخ النسخة المنشورة إلى pwa/ فقط (رخيص). تشغيل: python3 -m tools.reliability [--db PATH] [--force] [--no-upload]
"""
import json
import re
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ASSET = "source_trust.json"
LOCAL = ROOT / "pwa" / ASSET
DAYS = 14
MIN_ITEMS = 15        # حد الإدراج: خبر عراقي خلال 14 يوماً
MIN_ORIG = 10         # ادعاءات أصلية (قبل أي جهة رسمية) لازمة لحساب الدرجة
MIN_MULTI = 8         # عناقيد متعددة المصادر لازمة لحساب السبق
TRUST_N = 30          # «موثوقة» تحتاج 30 ادعاءً أصلياً على الأقل
MIN_CONF = 3          # و3 تأكيدات رسمية فعلية على الأقل (السبق والسرعة وحدهما لا يكفيان للثقة)
PRIOR_K = 20          # وزن التنعيم نحو المتوسط العام (عدد عيّنات افتراضي)
CONFIRM_H = 24
REFRESH_H = 20
# التأكيد الرسمي نادر (الجهات الرسمية لا تنشر أغلب الأخبار؛ المتوسط ~2%) فالحد الكامل 8% (≈4 أضعاف المتوسط)، والنفي وتعارض الأرقام
# يخصمان بشدة: نفي واحد من كل 50 ادعاءً = −9، وتعارض أرقام في ثلث المقارنات = −20.
W = {"base": 40, "confirmed": 30, "confirmed_full": 0.08, "first": 20, "first_full": 0.50, "speed": 10, "speed_full_min": 60,
     "denied": 450, "mismatch": 60}
TIERS = ("موثوقة", "عادية", "ضعيفة", "غير كافٍ")
METHOD = ("من أرشيف الرصد (آخر 14 يوماً): العنقود = الحدث نفسه؛ الجهة الرسمية = تعريف confirm.py. التأكيد = جهة رسمية نشرت لاحقاً (≤24س) "
          "خبراً متسقاً (البصمة نفسها، الأرقام متفقة، ليس نفياً)؛ النفي = جهة رسمية نفت الخبر نفسه. الدرجة 40 + 30×min(1,تأكيد/8%) + 20×min(1,سبق/50%) + 10×سرعة "
          "− 450×نفي − 60×تعارض أرقام (نسب مُنعّمة). موثوقة ≥75 ونفي ≤2% وn≥30 و≥3 تأكيدات رسمية؛ ضعيفة نفي ≥8% أو <40. "
          "حدود: التغطية الرسمية جزئية (أغلب الأخبار لا تنشرها جهة رسمية)، والعناقيد آلية قد تخلط خبرين.")

# كلمات لا تميّز الشبكة الإعلامية (قناة الجهة وموقعها وتلفزيونها شبكة واحدة)
NET_STOP = {"قناه", "وكاله", "شبكه", "فضاييه", "الفضاييه", "نيوز", "news", "tv", "عاجل", "الاخباريه", "اخباريه", "موقع", "اخبار", "الاخبار",
            "telegram", "rss", "يوتيوب", "youtube", "تلفزيون", "اذاعه", "راديو", "صحيفه", "جريده", "مجله", "منصه", "بث", "مباشر", "the", "al",
            "official", "الرسميه", "رسمي", "عبر", "google", "عربي", "عربيه", "العربيه", "العراقيه", "العراق", "iraq", "iraqi", "|", "-", "—"}
NET_ALIAS = {"964": "964", "media964": "964", "الشرقيه": "الشرقيه", "alsharqiya": "الشرقيه", "السومريه": "السومريه", "alsumaria": "السومريه",
             "alsumariatviraq": "السومريه", "شفق": "شفق", "shafaq": "شفق", "shafaaqnews": "شفق", "دجله": "دجله", "dijlah": "دجله",
             "dijlahtvchannel": "دجله", "رووداو": "رووداو", "روداو": "رووداو", "rudaw": "رووداو", "الحدث": "العربيه-الحدث", "alhadath": "العربيه-الحدث",
             "alhadath_brk": "العربيه-الحدث", "alarabiya": "العربيه-الحدث", "alarabiyabr": "العربيه-الحدث", "الجزيره": "الجزيره", "ajanews": "الجزيره",
             "aljazeera": "الجزيره", "بغداد اليوم": "بغداد اليوم", "baghdadtoday": "بغداد اليوم"}
# شبكة الإعلام العراقي (الحكومية) تملك واع والعراقية وجريدة الصباح: شبكة واحدة لا مصادر مستقلة
NET_ALIAS.update({k: "شبكه الاعلام العراقي" for k in ("واع", "inainaiq", "ina", "iraqimedianetwork", "iraqiagtv", "iraqianews", "alsbaahiq",
                                                      "الصباح", "الاعلام العراقي", "imn")})


def _norm(s):
    from marsad.textnorm import norm_ar
    return norm_ar(s or "")


def net_key(sid, name="", url=""):
    """مفتاح الشبكة/المالك: قناة تلغرام وموقع وتلفزيون الجهة نفسها = شبكة واحدة (لا تُعد مصادر مستقلة)."""
    base = re.sub(r"\s*[—|-]\s*(telegram|RSS|rss|يوتيوب|YouTube)\s*$", "", name or "")
    base = re.sub(r"\(.*?\)", " ", base)
    if re.fullmatch(r"\s*(?:t\.me|telegram|[A-Za-z0-9_.-]+\.(?:iq|com|net|org|tv|news))\s*", base or ""):
        base = ""  # اسم المصدر رابط لا اسم جهة: المعرّف (القناة/النطاق) هو الشبكة
    m = re.match(r"telegram:t\.me/([A-Za-z0-9_]+)", sid or "")
    handle = (m.group(1).lower() if m else "")
    host = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", (url or "").lower()))
    root = host.split(".")[-2] if host.count(".") >= 1 and host not in ("t.me", "news.google.com") else ""
    for k in (handle, root):
        if k and k in NET_ALIAS:
            return NET_ALIAS[k]
    n = _norm(base)
    if n in NET_ALIAS:
        return NET_ALIAS[n]
    toks = [t for t in n.split() if t not in NET_STOP and len(t) >= 2]
    for t in toks:
        if t in NET_ALIAS:
            return NET_ALIAS[t]
    if toks:
        return " ".join(toks[:2])
    return handle or root or (sid or "").lower()


def official_of(sid, url):
    from tools import confirm as CF
    m = re.match(r"telegram:t\.me/([A-Za-z0-9_]+)", sid or "")
    return CF.official_name(m.group(1)) if m else CF.official_name(url or "")


def excluded(sid, name, url):
    from marsad.cli import EXCLUDED_SRC
    return bool(EXCLUDED_SRC.search(f"{sid} {name} {url}"))


def _ts(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _nums(d):
    return {x for x in d if not re.fullmatch(r"(19|20)\d\d", x)}


AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
# النفي بحدود كلمة (DENY_RX القديم كان يطابق «نفتح» و«تنفيذ»)
DENIAL_RX = re.compile(r"(?<![\u0600-\u06FF])(?:[وف]?(?:لا صحة|لاصحة|عار[يٍ]? عن الصحة|غير صحيح[ةه]?|ينفي|تنفي|ننفي|نفى|نفت|نفي|تكذيب|يكذب|تكذب))"
                       r"(?![\u0600-\u06FF])")
# المصدر نفسه ينقل نفياً أو تحذيراً من صفحات/استمارات مزيفة: ليس ادعاءً يُنفى (تحذير الوزارة اللاحق من «استمارات مزيفة» ليس نفياً له)
REPORTS_DENIAL_RX = re.compile(r"(?<![\u0600-\u06FF])[وف]?(?:تحذر|يحذر|تحذّر|يحذّر|تحذير|مزيف[ةه]?|مزيّف[ةه]?|وهمي[ةه]?|شائع[ةه]|شائعات|احتيال)(?![\u0600-\u06FF])")
UNIT_RX = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:بـ\s*)?(%|[\u0600-\u06FFA-Za-z]{2,})")


def sig(title):
    from tools import tg_push as T
    return T.title_sig((title or "").translate(AR_DIGITS))


def _unit(u):
    """جذر تقريبي للوحدة: منتسباً=منتسبين، متهماً=متهمين، درجة=درجات، مليار=ملياراً (مليون≠مليار)."""
    w = re.sub(r"[ً-ْٰـ]", "", u).translate(str.maketrans("أإآة", "اااه"))
    w = re.sub(r"^(?:وال|بال|لل|ال|و|ب)(?=\S{3,})", "", w)
    w = re.sub(r"(?:ات|ين|ون|ان)$", "", w) if len(w) > 4 else w
    w = re.sub(r"[اه]$", "", w) if len(w) > 3 else w
    return w[:4]


def num_units(title):
    """{وحدة: {أرقام}}: «25 متهماً» → {متهم: {25}}. الرقم بلا وحدة (أو سنة) لا يُقارن."""
    out = {}
    for n, u in UNIT_RX.findall((title or "").translate(AR_DIGITS)):
        if re.fullmatch(r"(19|20)\d\d", n):
            continue
        k = "%" if u == "%" else _unit(u)
        out.setdefault(k, set()).add(n.replace(",", "."))
    return out


def numbers_conflict(ta, tb):
    """تعارض أرقام حقيقي: الوحدة نفسها («متهم»، «قتيل»، «مليار») بأرقام مختلفة لا يجمعها أي رقم مشترك."""
    a, b = num_units(ta), num_units(tb)
    shared = set(a) & set(b)
    return bool(shared) and all(not (a[k] & b[k]) for k in shared)


def numbers_checkable(ta, tb):
    return bool(set(num_units(ta)) & set(num_units(tb)))


def similar(a, b):
    """الخبر نفسه داخل العنقود (العنقود الآلي قد يجمع خبرين): مطابقة confirm.py بلا شرط الأرقام = البصمة + 3 كلمات مشتركة."""
    from tools import tg_push as T
    return len(a[0] & b[0]) >= 3 and T.same_story(a, {"w": sorted(b[0]), "d": sorted(b[1])})


def consistent(a, b):
    """تأكيد = مطابقة confirm.matches (تشمل اتفاق الأرقام المشتركة)."""
    from tools import confirm as CF
    return CF.matches(a, {"sig": {"w": sorted(b[0]), "d": sorted(b[1])}})


def compute(con, now=None, days=DAYS):
    from tools import tg_push as T
    from tools import confirm as CF
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    srcs = {r[0]: {"name": r[1] or r[0], "url": r[2] or "", "category": r[3]} for r in con.execute("SELECT id, name, url, category FROM sources")}
    off_cache, iq_cache = {}, {}
    rows = con.execute("SELECT source_id, published_utc, collected_utc, time_precision, title, cluster_id FROM items "
                       "WHERE COALESCE(published_utc, collected_utc) >= ? AND cluster_id IS NOT NULL", (since,)).fetchall()
    T.build_idf([r[4] or "" for r in rows[-6000:]])
    clusters = {}
    vol = {}
    for sid, pub, col, prec, title, cid in rows:
        tp, tc = (_ts(pub) if pub and prec != "approx" else None), _ts(col)
        # وقت النشر موثوق إذا جُمع بعده بأقل من 3 ساعات (خلاصات بساعة 12 بدل 24 ظهرت أقدم بـ12 ساعة: كلمة RSS)؛ وإلا وقت الجمع
        # للتأكيد/النقل، ولا يدخل في السبق والتأخر
        good = bool(tp and tc and -300 <= tc - tp <= 3 * 3600)
        t = tp if good else (tc or tp)
        if not t or not title:
            continue
        if sid not in off_cache:
            s = srcs.get(sid) or {}
            off_cache[sid] = official_of(sid, s.get("url"))
        key = title[:160]
        if key not in iq_cache:
            iq_cache[key] = bool(T.iraq_strict(title) or T.iraq_domestic(title))
        iq = iq_cache[key]
        if iq:
            vol[sid] = vol.get(sid, 0) + 1
        clusters.setdefault(cid, []).append((t, sid, title, iq, good))
    st = {}
    for cid, its in clusters.items():
        its.sort()
        first_t = min((x[0] for x in its if x[4]), default=None)
        nsrc = len({x[1] for x in its})
        offs = [(t, sid, title, sig(title), bool(DENIAL_RX.search(title))) for t, sid, title, iq, _g in its if off_cache.get(sid)]
        seen = set()
        for t, sid, title, iq, good in its:
            if sid in seen or off_cache.get(sid):
                continue
            seen.add(sid)
            s = st.setdefault(sid, {"n": 0, "orig": 0, "relay": 0, "conf": 0, "den": 0, "num_n": 0, "mism": 0, "multi": 0, "first": 0,
                                    "lead": [], "rep_denial": 0, "off_cov": 0, "ex": {}})
            if nsrc >= 2 and good and first_t is not None:
                s["multi"] += 1
                s["first"] += t <= first_t + 1
                s["lead"].append((t - first_t) / 60)
            if not iq:
                continue
            s["n"] += 1
            if DENIAL_RX.search(title) or REPORTS_DENIAL_RX.search(title):
                s["rep_denial"] += 1  # المصدر نفسه ينقل نفياً: ليس ادعاءً يُؤكَّد أو يُنفى
                continue
            g = sig(title)
            win = [o for o in offs if o[0] <= t + CONFIRM_H * 3600 and o[0] >= t - CONFIRM_H * 3600 and similar(g, o[3])]
            if not win:
                s["orig"] += 1
                continue
            rel = [o for o in win if o[0] <= t + 60]
            later = [o for o in win if o[0] > t + 60]
            numeric = [o for o in win if not o[4] and numbers_checkable(title, o[2])]
            if numeric:
                s["num_n"] += 1
                if all(numbers_conflict(title, o[2]) for o in numeric):
                    s["mism"] += 1
                    s["ex"].setdefault("mism", (title[:120], numeric[0][2][:120]))
            if rel and not any(o[4] for o in rel):
                s["relay"] += 1
                continue
            s["orig"] += 1
            s["off_cov"] += 1
            if any(o[4] for o in later + rel):
                s["den"] += 1
                s["ex"].setdefault("den", (title[:120], next(o[2] for o in later + rel if o[4])[:120]))
            elif any(consistent(g, o[3]) for o in later):
                s["conf"] += 1
                s["ex"].setdefault("conf", (title[:120], next(o[2] for o in later if consistent(g, o[3]))[:120]))
    return st, vol, srcs, off_cache


def _smooth(k, n, prior):
    return (k + PRIOR_K * prior) / (n + PRIOR_K)


def score_all(st, vol, srcs, off_cache, now=None):
    now = now or datetime.now(timezone.utc)
    cand = {sid: s for sid, s in st.items() if vol.get(sid, 0) >= MIN_ITEMS}
    tot = lambda f: sum(s[f] for s in cand.values())  # noqa: E731
    pr = {"conf": tot("conf") / max(1, tot("orig")), "den": tot("den") / max(1, tot("orig")), "first": tot("first") / max(1, tot("multi")),
          "mism": tot("mism") / max(1, tot("num_n"))}
    out, excl, aggr = {}, [], []
    for sid, s in cand.items():
        info = dict(srcs.get(sid) or {"name": sid, "url": ""})
        hm = re.match(r"telegram:t\.me/([A-Za-z0-9_]+)", sid)
        if hm and re.match(r"^\s*t\.me\b", info["name"] or ""):
            info["name"] = f"{hm.group(1)} — telegram"  # اسم المصدر رابط: نعرض المعرّف
        if excluded(sid, info["name"], info["url"]):
            excl.append(sid)
            continue
        if "news.google" in sid or "news.google" in (info["url"] or ""):
            aggr.append(sid)  # مجمّع Google News (عدة وسائل في خلاصة واحدة) ليس مصدراً واحداً يُقيَّم
            continue
        cr = s["conf"] / s["orig"] if s["orig"] else 0.0
        dr = s["den"] / s["orig"] if s["orig"] else 0.0
        fr = s["first"] / s["multi"] if s["multi"] else 0.0
        mr = s["mism"] / s["num_n"] if s["num_n"] else 0.0
        lead = statistics.median(s["lead"]) if s["lead"] else None
        rec = {"name": info["name"], "url": info["url"], "net": net_key(sid, info["name"], info["url"]), "volume": vol.get(sid, 0), "n": s["orig"],
               "claims": s["n"], "relay": s["relay"], "official_covered": s["off_cov"], "confirmed": s["conf"], "denied": s["den"],
               "multi": s["multi"], "first": s["first"], "num_checked": s["num_n"], "num_mismatch": s["mism"],
               "confirmed_rate": round(cr, 4), "denied_rate": round(dr, 4), "first_rate": round(fr, 4), "number_mismatch_rate": round(mr, 4),
               "relay_rate": round(s["relay"] / s["n"], 4) if s["n"] else 0.0, "median_lead_min": round(lead, 1) if lead is not None else None,
               "examples": s["ex"]}
        if s["orig"] < MIN_ORIG or s["multi"] < MIN_MULTI:
            rec.update(score=None, tier="غير كافٍ")
        else:
            c = _smooth(s["conf"], s["orig"], pr["conf"])
            d = _smooth(s["den"], s["orig"], pr["den"])
            f = _smooth(s["first"], s["multi"], pr["first"])
            m = _smooth(s["mism"], s["num_n"], pr["mism"])
            sp = 1 - min(2.0, max(0.0, lead or 0.0) / W["speed_full_min"])  # فوري +10، ساعة 0، ساعتان فأكثر −10 (إعادة نشر القديم)
            sc = (W["base"] + W["confirmed"] * min(1.0, c / W["confirmed_full"]) + W["first"] * min(1.0, f / W["first_full"]) + W["speed"] * sp
                  - W["denied"] * d - W["mismatch"] * m)
            sc = round(max(0.0, min(100.0, sc)), 1)
            if dr >= 0.08 or sc < 40:
                tier = "ضعيفة"
            elif sc >= 75 and dr <= 0.02 and s["orig"] >= TRUST_N and s["conf"] >= MIN_CONF:
                tier = "موثوقة"
            else:
                tier = "عادية"
            rec.update(score=sc, tier=tier)
        out[sid] = rec
    offl = sorted(({"id": sid, "name": (srcs.get(sid) or {}).get("name") or sid, "body": nm, "volume": vol.get(sid, 0)}
                   for sid, nm in off_cache.items() if nm), key=lambda x: -x["volume"])
    counts = {t: sum(1 for r in out.values() if r["tier"] == t) for t in TIERS}
    return {"updated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "window_days": DAYS, "method": METHOD, "weights": W,
            "thresholds": {"min_items": MIN_ITEMS, "min_orig": MIN_ORIG, "min_multi": MIN_MULTI, "trusted_n": TRUST_N, "trusted_min_confirmed": MIN_CONF, "prior_k": PRIOR_K},
            "priors": {k: round(v, 4) for k, v in pr.items()}, "counts": counts, "sources": out, "official": offl,
            "excluded": sorted(excl), "aggregators": len(aggr)}


# ---------------------------------------------------------------- القراءة للنشر
_TRUST = {}


def load(path=None, data=None):
    """جدول الطبقات للنشر: sid ← سجل، وفهارس قناة تلغرام/نطاق/اسم. فارغ إذا لا يوجد ملف (لا يغيّر شيئاً حينها)."""
    key = "data" if data is not None else str(path or LOCAL)
    if data is None and _TRUST.get("_key") == key:
        return _TRUST
    if data is None:
        try:
            data = json.loads(Path(path or LOCAL).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = {}
    srcs = (data or {}).get("sources") or {} if isinstance(data, dict) else {}
    by_h, by_host, by_name = {}, {}, {}
    for sid, r in srcs.items():
        m = re.match(r"telegram:t\.me/([A-Za-z0-9_]+)", sid)
        if m:
            by_h[m.group(1).lower()] = sid
        else:
            host = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", (r.get("url") or "").lower()))
            if host and host not in by_host:
                by_host[host] = sid
        nm = re.sub(r"\s*—\s*(telegram|RSS|rss|يوتيوب)$", "", r.get("name") or "").strip()
        if nm:
            by_name.setdefault(nm, sid)
    _TRUST.clear()
    _TRUST.update({"_key": key, "src": srcs, "h": by_h, "host": by_host, "name": by_name,
                   "updated_utc": (data or {}).get("updated_utc") if isinstance(data, dict) else None})
    return _TRUST


def sid_of(ref=None, name=None):
    """sid من sid/قناة/رابط/اسم."""
    tr = _TRUST if _TRUST.get("_key") else load()
    if ref:
        r = ref.strip()
        if r in tr["src"]:
            return r
        m = re.match(r"^(?:telegram:)?(?:https?://)?t\.me/(?:s/)?([A-Za-z0-9_]+)", r)
        if m:
            return tr["h"].get(m.group(1).lower())
        if "/" not in r and "." not in r:
            return tr["h"].get(r.lower())
        host = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", r.lower()))
        if host in tr["host"]:
            return tr["host"][host]
    if name:
        nm = re.sub(r"\s*—\s*(telegram|RSS|rss|يوتيوب)$", "", name).strip()
        return tr["name"].get(nm)
    return None


def tier_of(ref=None, name=None):
    sid = sid_of(ref, name)
    return ((_TRUST.get("src") or {}).get(sid) or {}).get("tier") if sid else None


def weak_only(entries):
    """entries = [(sid أو رابط، الاسم، الرابط)] مصادر الخبر. True فقط إذا كانت كلها «ضعيفة» ولا جهة رسمية بينها
    (أي مصدر غير ضعيف أو بلا تقييم أو رسمي = الخبر معزَّز)."""
    from tools import confirm as CF
    if not entries:
        return False
    for ref, name, url in entries:
        if CF.official_name(url or "") or CF.official_name(re.sub(r"^telegram:", "", ref or "")) or tier_of(ref or url, name) != "ضعيفة":
            return False
    return True


def rec_of(ref=None, name=None):
    sid = sid_of(ref, name)
    return ((_TRUST.get("src") or {}).get(sid)) if sid else None


def net_of(ref=None, name=None):
    r = rec_of(ref, name)
    if r:
        return r.get("net")
    m = re.match(r"^(?:telegram:)?(?:https?://)?t\.me/(?:s/)?([A-Za-z0-9_]+)", (ref or "").strip())
    return net_key(f"telegram:t.me/{m.group(1)}" if m else "", name or "", "" if m else (ref or ""))


# ---------------------------------------------------------------- التشغيل
def gh_get():
    try:
        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run(["gh", "release", "download", "fastlane", "-p", ASSET, "-D", td, "--clobber"], capture_output=True, timeout=30)
            return json.loads((Path(td) / ASSET).read_text(encoding="utf-8")) if r.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def gh_put(path):
    try:
        subprocess.run(["gh", "release", "upload", "fastlane", str(path), "--clobber"], capture_output=True, timeout=40)
    except Exception:  # noqa: BLE001
        pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    db = argv[argv.index("--db") + 1] if "--db" in argv else None
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else LOCAL
    force, upload = "--force" in argv, "--no-upload" not in argv
    now = datetime.now(timezone.utc)
    if not force:
        prev = gh_get() if upload else None
        if prev and prev.get("updated_utc") and now.timestamp() - (_ts(prev["updated_utc"]) or 0) < REFRESH_H * 3600:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(prev, ensure_ascii=False), encoding="utf-8")
            print(f"::notice title=reliability::نسخة اليوم موجودة ({prev['updated_utc']}) — نُسخت إلى {out.name}")
            return prev
    from marsad import core
    t0 = time.time()
    con = core.connect(db) if db else core.connect()
    st, vol, srcs, offc = compute(con, now)
    res = score_all(st, vol, srcs, offc, now)
    res["took_sec"] = round(time.time() - t0, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    if upload:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ASSET
            p.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
            gh_put(p)
    print(f"::notice title=reliability::{json.dumps(res['counts'], ensure_ascii=False)} في {res['took_sec']}ث")
    return res


if __name__ == "__main__":
    main()
