"""يكتب pwa/news.json و pwa/meta.json من الأرشيف (آخر 72 ساعة) لنسخة الهاتف المستقلة من «هوبي عاجل»."""
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from marsad import core  # noqa: E402
from marsad.report import cluster_dossier  # noqa: E402
from marsad.textnorm import iso, now_utc  # noqa: E402
from tools.export_app import status_of  # noqa: E402
from tools import verify as V, watch as W, analysis as A  # noqa: E402
try:
    IRAQ_ONLY = {x["id"] for x in json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))["sources"] if x.get("iraq_only")}
except Exception:  # noqa: BLE001
    IRAQ_ONLY = set()
WNAMES = {f["id"]: f.get("name", f["id"]) for f in W.load()}
WKIND = {f["id"]: f.get("kind") for f in W.load()}
from marsad.collect import IRAQ_RX as IRAQ_MULTI  # noqa: E402


import re  # noqa: E402

URL_RX = re.compile(r"https?://\S+|t\.me/\S+|www\.\S+")
SIG_RX = re.compile(r"(الدائرة الاعلامية|المكتب الاعلامي|المكتب الإعلامي|الدائرة الإعلامية|تابعونا|للاشتراك|رابط القناة)")
FLAG_RX = re.compile(r"(^|\s|[🔴🚨⭕️🔻])عاجل")
FLAG_SPAM = set()


from tools.editorial import complete_line  # noqa: E402


def clean_title(label, texts):
    """عنوان مقروء: يتجاهل الروابط وتواقيع القنوات، ويأخذ أول سطر له معنى (مع ضم سطر المتحدث للكلام)."""
    def ok(line):
        line = URL_RX.sub("", line).strip(" -–|:🔻🔴📌⭕️🚨•")
        return line if len(line) >= 20 and not (SIG_RX.search(line) and len(line) < 45) else ""
    for t in texts:
        c = complete_line(t)
        if ok(c) and len(c.split()) >= 6:
            if ok(label or "") and len((label or "").split()) >= 7 and not (label or "").strip().startswith("•"):
                return ok(label)
            return ok(c)[:220]
    if ok(label or ""):
        return ok(label)
    joined = URL_RX.sub("", " ".join((texts[0] if texts else label or "").split())).strip()
    return (joined or label or "")[:200]


from marsad.textnorm import norm_ar  # noqa: E402

IRAQ_AR = [norm_ar(w) for w in ["العراق", "عراقي", "عراقية", "العراقيين", "بغداد", "البصرة", "الموصل", "أربيل", "اربيل", "كركوك", "النجف", "كربلاء",
           "السليمانية", "الأنبار", "الفلوجة", "سنجار", "دهوك", "نينوى", "ديالى", "صلاح الدين", "ذي قار", "الناصرية", "ميسان", "واسط", "بابل",
           "إقليم كردستان", "اقليم كوردستان", "السوداني", "الزيدي", "الحشد الشعبي", "الكاظمي",
           "مجلس النواب", "مجلس الوزراء", "الإطار التنسيقي", "مجلس القضاء الأعلى", "الدينار", "الزوراء", "القوة الجوية", "الطلبة", "الشرطة الاتحادية"]]
FOREIGN_AR = [norm_ar(w) for w in ["إسرائيل", "الإسرائيلي", "فلسطين", "الفلسطيني", "غزة", "الضفة", "لبنان", "اللبناني", "حزب الله", "سوريا", "السوري", "دمشق",
              "إيران", "الإيراني", "طهران", "تركيا", "التركي", "أنقرة", "السعودية", "الرياض", "الإمارات", "قطر", "الكويت", "الأردن", "مصر", "اليمن", "الحوثي",
              "واشنطن", "ترامب", "روسيا", "أوكرانيا", "الصين", "أوروبا", "فرنسا", "بريطانيا", "هرمز", "الخليج",
              # دول وجنسيات بعيدة: خبرها مو «عن العراق» حتى لو نقلته قناة عراقية (وزير النقل الإسباني 04/11)
              "إسبانيا", "الإسباني", "الإسبانية", "أمريكا", "الأمريكي", "الأميركي", "الأمريكية", "الولايات المتحدة", "الكونغرس", "البيت الأبيض",
              "الديمقراطيون", "الجمهوريون", "ألمانيا", "الألماني", "الفرنسي", "البريطاني", "لندن", "باريس", "برلين",
              "موسكو", "الروسي", "الأوكراني", "كييف", "بكين", "الصيني", "الهندي", "باكستان", "أفغانستان", "اليابان", "الياباني", "كوريا",
              "إيطاليا", "الإيطالي", "هولندا", "السويد", "كندا", "أستراليا", "البرازيل", "المكسيك", "الأرجنتين", "تايوان", "فنزويلا", "كوبا",
              "المغرب", "الجزائر", "تونس", "ليبيا", "السودان", "البحرين", "عُمان", "الدوحة", "أبوظبي", "القاهرة", "عمّان", "بيروت", "الجولاني", "طرطوس"]]
# العنوان يحكم «عن العراق» قبل نصوص المواد: نصوص القنوات العراقية تحمل توقيعها («…العراق»، «نينوى الغد») فكانت أخبار الانتخابات
# الأمريكية وتصريحات قاليباف تُعدّ عراقية (160 عنقوداً بنافذة تدقيق 14:11 04/11 رغم إصلاح 030a709 — فحص 6).
_IQ_GENERIC_T = {norm_ar(w) for w in ["مجلس النواب", "مجلس الوزراء", "الطلبة", "الدينار", "القوة الجوية", "الشرطة الاتحادية"]}
IRAQ_STRONG_T = [w for w in IRAQ_AR if w not in _IQ_GENERIC_T] + [norm_ar(w) for w in ["كردستان", "كوردستان", "برلمان الإقليم", "العراقي", "العراقيين", "الرافدين",
                                                                      "القرنة", "الرميلة", "حقل مجنون", "الإطار", "ميناء الفاو", "الفاو"]]
FAR_T = [norm_ar(w) for w in ["إسبانيا", "الإسباني", "الإسبانية", "أمريكا", "الأمريكي", "الأميركي", "الأمريكية", "الأميركية", "الأمريكيين", "الأميركيين",
         "الولايات المتحدة", "الكونغرس", "البيت الأبيض", "الديمقراطيون", "الديمقراطيين", "الجمهوريون", "الجمهوريين", "مجلس الشيوخ",
         "التجديد النصفي", "الانتخابات النصفية", "ترامب", "ترمب", "أوباما", "واشنطن", "ألمانيا", "فرنسا", "بريطانيا", "إيطاليا", "روسيا", "أوكرانيا",
         "الصين", "اليابان", "كوريا", "الهند", "باكستان", "ليبيا", "السودان", "المغرب", "الجزائر", "تونس", "بتكوين", "فلوريدا", "تكساس", "ميشيغان", "كاليفورنيا"]]
REG_T = [norm_ar(w) for w in ["إيران", "الإيراني", "الإيرانية", "طهران", "قاليباف", "خامنئي", "الحرس الثوري", "بروجردي", "إسرائيل", "الإسرائيلي", "غزة",
         "لبنان", "سوريا", "السوري", "دمشق", "تركيا", "التركي", "السعودية", "الإمارات", "قطر", "الكويت", "الأردن", "مصر", "اليمن", "الحوثي", "هرمز"]]
LOCAL_ROLE_T = re.compile(r"^\W*(?:وزير|وزيرة|وزارة|رئيس الوزراء|رئيس مجلس الوزراء|محافظ|النائب|النائبة|السفير العراقي|سفير العراق|مستشار الأمن القومي|"
                          r"الخارجية|رئيس الجمهورية|رئيس البرلمان|رئيس مجلس النواب|هيئة|خلية الإعلام|قيادة العمليات|جهاز)")


def about_iraq_title(label, about):
    """يصحح «عن العراق» من العنوان: دولة بعيدة بلا كلمة عراقية صريحة ← لا؛ دولة إقليمية بلا كلمة عراقية ولا جهة محلية بأوله ← لا."""
    lab = norm_ar(label or "")
    if not about or any(w in lab for w in IRAQ_STRONG_T) or IRAQ_EN.search(label or ""):
        return about
    if any(w in lab for w in FAR_T):
        return False
    if any(w in lab for w in REG_T) and not LOCAL_ROLE_T.search(label or ""):
        return False
    return about


IRAQ_FOREIGN_EN = re.compile(r"\b(Spain|Spanish|Trump|Democrats|Republicans|Congress|Ukraine|Russia|China|India|Pakistan)\b", re.I)
IRAQ_EN = re.compile(r"\b(Iraq|Iraqi|Iraqis|Baghdad|Kurdistan|Erbil|Basra|Mosul|Kirkuk|Najaf|Karbala|Sulaymaniyah|Anbar|Sinjar|Duhok)\b", re.I)
TOPICS = [
    ("أمن", "أمن أمني قصف انفجار اغتيال اعتقال القبض إرهاب داعش اشتباك الحشد الجيش الشرطة صاروخ مسيرة هجوم قتلى جرحى ضربة عملية عسكرية مسلحين عبوة",
     r"attack|killed|strike|militia|drone|rocket|security|army|troops|bomb|ISIS|Daesh|militant|explosion|arrest"),
    ("سياسة", "البرلمان مجلس النواب الحكومة رئيس الوزراء وزير انتخابات الكتلة تحالف رئاسة قانون سفير دبلوماسي زيارة اجتماع الإطار التنسيقي حزب نائب جلسة",
     r"parliament|minister|government|election|president|diplomat|envoy|talks|lawmaker|coalition|party|policy|sanction"),
    ("اقتصاد", "الدولار النفط الموازنة رواتب مصرف البنك المركزي أسعار تجارة استثمار صادرات الذهب الدينار الضرائب الكمارك برميل",
     r"oil|dollar|budget|bank|trade|economy|investment|exports|salaries|crude|market|price|dinar"),
    ("خدمات", "الكهرباء الماء المياه مجاري طرق مشاريع مشروع سد بلدية إعمار الإسكان النقل المطار جسر ماء الشرب انقطاع",
     r"electricity|water|infrastructure|housing|airport|project|power outage"),
    ("صحة", "صحة مستشفى وباء مرض طبي دواء كوليرا لقاح إصابات الأطباء علاج",
     r"health|hospital|disease|medical|cholera|vaccine|outbreak|patients"),
    ("تعليم", "التربية امتحانات جامعة طلاب مدارس الدوام التعليم العالي الطلبة نتائج القبول",
     r"school|university|students|education|exam"),
    ("ثقافة", "ثقافة مهرجان فن فنان كتاب معرض تراث آثار مسرح سينما شعر رواية متحف",
     r"culture|festival|art|artist|heritage|museum|film|book|archaeolog"),
    ("رياضة", "منتخب كرة الدوري مباراة نادي لاعب بطولة الاتحاد العراقي لكرة القدم أولمبي",
     r"football|soccer|match|league|team|player|sport|olympic|cup"),
    ("مجتمع", "عشائر عشيرة نزاع مناشدة حادث مروري غرق حريق زواج طلاق متظاهرين تظاهرة احتجاج مواطنين المرأة الأطفال",
     r"protest|tribe|women|children|refugees|displaced|society|rights"),
    ("طقس", "طقس أمطار درجات الحرارة الأنواء عاصفة غبار سيول", r"weather|rain|storm|flood|heat"),
]
TOPICS = [(n, [norm_ar(w) for w in ar.split()], re.compile(r"\b(" + en + r")", re.I)) for n, ar, en in TOPICS]


KURDISH = re.compile(r"[ەێۆڵڕڤ]")
ARABIC_CH = re.compile(r"[\u0600-\u06FF]")
INTERVIEW_RX = re.compile(r"\b(interview|Q&A|speaks to|in conversation|podcast)\b", re.I)
OPINION_RX = re.compile(r"\b(opinion|op-ed|column|commentary|editorial|view)\b", re.I)
ANALYSIS_RX = re.compile(r"\b(analysis|explainer|explained|why|how|what .* means|inside|the future of|strategy|lessons)\b", re.I)


AGENCY_RX = re.compile(r"\b(Reuters|Associated Press|AP News|AFP|Agence France|Bloomberg|Anadolu|Xinhua|dpa|TASS|UPI|EFE|Kyodo|ANSA|Agenzia Nova|NHK)\b", re.I)


def views_num(v):
    m = re.match(r"([\d.]+)\s*([KMk]?)", str(v or ""))
    if not m:
        return 0
    return int(float(m.group(1)) * {"K": 1e3, "k": 1e3, "M": 1e6}.get(m.group(2), 1))


PMF_STRONG = [norm_ar(w) for w in ["الحشد الشعبي", "هيئة الحشد", "قوات الحشد", "فصائل الحشد", "ألوية الحشد", "قانون الحشد", "رئيس هيئة الحشد",
              "مديرية إعلام الحشد", "الفياض", "أبو فدك", "قيادة الحشد", "الحشد العشائري", "حشد العتبات"]]
PMF_WEAK = norm_ar("الحشد")
PMF_CTX = [norm_ar(w) for w in ["اللواء", "قوات", "قطعات", "عمليات", "الفصائل", "قانون", "هيئة", "مقاتلي", "الأمنية", "قيادة", "تشكيلات"]]
PMF_EN = re.compile(r"\b(Popular Mobili[sz]ation (Forces|Units|Committee|Authority)|PMF|PMU|Hashd|al-Hashd|Hashed al-Shaabi|Falih al-Fayyadh)\b", re.I)
DECISION_RX = re.compile(r"(قرر|قرار|أمر ديواني|امر ديواني|يوجه|وجّه|وجه ب|أصدر|اصدر|يقرر|تقرر|أقر|اقر|يعمم|عمّم)")
STATEMENT_RX = re.compile(r"(قال|صرّح|صرح|أكد|اكد|أعلن|اعلن|أوضح|اوضح|said|says|told|announced|stated)")
CLAIM_RX = re.compile(r"(اتهم|يتهم|اتهامات|زعم|يزعم|مزاعم|ادعى|يدعي|نسب|مصادر لم تكشف|مصدر مطلع|accus|alleg|claim|reportedly)", re.I)


def is_pmf(ntext, raw):
    if any(w in ntext for w in PMF_STRONG) or PMF_EN.search(raw):
        return True
    if PMF_WEAK in ntext:  # «الحشد» وحدها ملتبسة (حشد جماهيري): تُقبل فقط مع كلمة سياق أمنية/مؤسسية
        return sum(1 for w in PMF_CTX if w in ntext) >= 2
    return False


def topic_of(norm_text, en_text):
    best, score = "عام", 0
    for name, words, rx in TOPICS:
        sc = sum(1 for w in words if w and w in norm_text) + len(rx.findall(en_text or ""))
        if sc > score:
            best, score = name, sc
    return best


def delay_stats(con, now):
    """تأخر الاكتشاف = وقت رصد التطبيق − وقت النشر المعلن، لمواد آخر 3 ساعات ذات وقت نشر دقيق.
    تُستبعد مواد «الجلب الأول» لمصدر جديد (نُشرت قبل رصدها بأكثر من 6 ساعات) لأنها ليست تأخراً حقيقياً."""
    rows = con.execute("SELECT i.published_utc, i.collected_utc, i.url, s.method FROM items i LEFT JOIN sources s ON s.id=i.source_id "
                       "WHERE i.collected_utc >= ? AND i.time_precision='exact' AND i.published_utc IS NOT NULL", (iso(now - timedelta(hours=3)),)).fetchall()
    groups = {"تلغرام": [], "RSS": [], "Google News": []}
    for r in rows:
        try:
            m = (datetime.fromisoformat(r["collected_utc"].replace("Z", "+00:00")) - datetime.fromisoformat(r["published_utc"].replace("Z", "+00:00"))).total_seconds() / 60
        except (ValueError, AttributeError):
            continue
        if m < -5 or m > 360:
            continue
        g = "تلغرام" if r["method"] == "telegram_preview" else "Google News" if "news.google.com" in (r["url"] or "") else "RSS"
        groups[g].append(max(m, 0))
    def st(xs):
        xs = sorted(xs)
        return {"median_min": round(xs[len(xs) // 2], 1), "p90_min": round(xs[int(len(xs) * 0.9)], 1), "n": len(xs)} if xs else None
    allx = [x for v in groups.values() for x in v]
    res = st(allx) or {}
    if res:
        res["by_type"] = {k: st(v) for k, v in groups.items() if v}
    return res or None



def readings(analysis):
    """وكيل التحليل الخبري: قراءة سياسية محايدة لأكبر الأحداث (20+ جهة)، تُكتب مرة لكل حدث وتُحدَّث إذا زاد انتشاره كثيراً. حتى 2 بالجولة."""
    p = ROOT / "data" / "tg_sent.json"
    try:
        sent = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        sent = {}
    cache = sent.get("_ana") or {}
    from tools.editorial import os_key
    calls = 0
    for a in sorted(analysis, key=lambda x: -x["n_sources"]):
        hit = cache.get(a["id"])
        if hit and a["n_sources"] < hit.get("n", 0) * 1.6:
            a["reading"] = hit.get("r")
            continue
        if calls >= 1 or a["n_sources"] < 30 or not os_key():  # حصة Gemini محجوزة أولاً لمقالتي التحليل اليوميتين
            continue
        calls += 1
        r = A.write_reading(a)
        if r:
            cache[a["id"]] = {"r": r, "n": a["n_sources"], "t": a.get("last_time"), "title": a["title"]}
            a["reading"] = r
    sent["_ana"] = dict(sorted(cache.items(), key=lambda kv: kv[1].get("t") or "", reverse=True)[:200])
    p.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")
    print(f"::notice title=analysis agent::{json.dumps({'calls': calls, 'readings': sum(1 for a in analysis if a.get('reading'))}, ensure_ascii=False)}")


LLM_PER_RUN = 0  # التطبيق: قواعد + أنظف صياغة فقط؛ حصة Gemini محجوزة لوكيل القناة والتحليل والمسار السريع


def edit_titles(out):
    """تحرير العناوين للتطبيق: القواعد المجانية لكل الأخبار، وإعادة الصياغة الرصينة (Gemini) لعاجل ومهم العراق.
    كل حدث يُصاغ مرة واحدة ويُحفظ في data/tg_sent.json تحت «_hl» (نفس الملف المحفوظ بين الجولات) ويستعمله التلغرام أيضاً."""
    from tools import editorial as E
    p = ROOT / "data" / "tg_sent.json"
    try:
        sent = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        sent = {}
    cache = sent.get("_hl") or {}
    calls = 0
    for n in out:
        raw = n["title"]
        if n.get("title_orig"):  # مترجم آلياً: نكتفي بالقواعد
            n.pop("alts", None); n.pop("lead", None)
            n["title"] = E.formal_rules(E.clean_headline(raw, max_len=200)) or raw
            continue
        alts = n.pop("alts", None) or []
        lead = n.get("lead") or ""
        if not lead:
            n.pop("lead", None)
        if alts:
            raw = E.pick_best([raw] + alts)  # أنظف صياغة بين المصادر (بلا تمويه أو هاشتاغ أو فقرة طويلة)
        hit = cache.get(n["id"])
        if hit and hit.get("src") == raw:
            new = hit["t"]
        else:
            important = (n.get("about_iraq") or n.get("pmf")) and (n.get("source_flag") or n.get("level") in ("عاجل", "مهم"))
            if important and calls < LLM_PER_RUN and E.os_key() and E.LLM_STATS["error"] < 2:
                import time as _tm
                if calls:
                    _tm.sleep(1.5)
                calls += 1
                err0 = E.LLM_STATS["error"]
                new = E.edit_headline(raw, max_len=200, context=lead)
                if E.LLM_STATS["error"] == err0:  # لا نخزن نتيجة خطأ مؤقت (حد الطلبات): يُعاد المحاولة بالجولة الجاية
                    cache[n["id"]] = {"src": raw, "t": new, "at": n.get("latest_utc")}
            else:
                new = E.formal_rules(E.clean_headline(raw, max_len=200)) or raw
        if new and new != raw:
            n["title_src"] = raw
            n["title"] = new
        n["edited_title"] = True
    keep = sorted(cache.items(), key=lambda kv: kv[1].get("at") or "", reverse=True)[:3000]
    sent["_hl"] = dict(keep)
    p.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")
    print(f"::notice title=editorial::{json.dumps({'llm_calls': calls, **E.LLM_STATS, 'cache': len(keep)}, ensure_ascii=False)}")
    for r in E.REJECTS:
        print(f"::notice title=editorial_reject::{json.dumps(r, ensure_ascii=False)}")

def main(hours=24):
    con = core.connect()
    now = now_utc()
    out = []
    analysis = []
    spreads = []
    global FLAG_SPAM
    # قنوات تضع «عاجل» على أغلب منشوراتها (حتى المنوعات): وسمها لا يُعتمد (أكثر من 40% من منشوراتها خلال 24 ساعة)
    rates = con.execute("SELECT source_id, COUNT(*), SUM(CASE WHEN substr(COALESCE(title,''),1,12) LIKE '%عاجل%' THEN 1 ELSE 0 END) FROM items "
                        "WHERE collected_utc >= ? GROUP BY source_id", (iso(now - timedelta(hours=24)),)).fetchall()
    FLAG_SPAM = {r[0] for r in rates if r[1] >= 10 and (r[2] or 0) / r[1] > 0.4}
    print(f"::notice title=flag_spam::{len(FLAG_SPAM)} مصدر وسم «عاجل» لديه لا يُعتمد")
    matcher = W.Matcher()
    try:
        verdicts = json.loads((ROOT / "data" / "tg_sent.json").read_text(encoding="utf-8")).get("_verdicts", {})
    except Exception:  # noqa: BLE001
        verdicts = {}
    try:
        tr = json.loads((ROOT / "data" / "translations.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        tr = {}
    # أخبار اليوم فقط (منتصف ليل بغداد)، حتى لا يظهر خبر قديم
    bg = now + timedelta(hours=3)
    day_start = iso(bg.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=3))
    recent = con.execute("SELECT * FROM clusters WHERE last_utc >= ?", (iso(now - timedelta(hours=26)),)).fetchall()
    older_analysis = con.execute("SELECT DISTINCT c.* FROM clusters c JOIN items i ON i.cluster_id=c.id JOIN sources s ON s.id=i.source_id "
                                 "WHERE c.last_utc >= ? AND c.last_utc < ? AND s.region LIKE 'أجنبي — تحليل%'",
                                 (iso(now - timedelta(days=7)), iso(now - timedelta(hours=26)))).fetchall()
    for c in list(recent) + list(older_analysis):
        d = cluster_dossier(con, c)
        st, basis = status_of(d)
        ev = sorted(d["evidence"], key=lambda e: e["time"] or "")
        texts = [r[0] or "" for r in con.execute("SELECT COALESCE(text, title) FROM items WHERE cluster_id=? ORDER BY published_utc", (c["id"],))]
        level = d["level"]
        if level != "عاجل" and any(FLAG_RX.search(t[:80]) for t in texts):
            # المصدر نفسه وسمه «عاجل»: يصير عاجلاً، إلا إذا كانت القناة مجمّعاً يسمي كل شي عاجل (اسمها فيه «عاجل»)
            names = [e["source"] or "" for e in ev]
            level = "مهم" if all("عاجل" in n for n in names) else "عاجل"
        rl = con.execute("SELECT s.region, s.lang FROM items i JOIN sources s ON s.id=i.source_id WHERE i.cluster_id=?", (c["id"],)).fetchall()
        regs = {r[0] or "" for r in rl}
        langs = {r[1] or "" for r in rl}
        origins = {"أجنبي" if r.startswith("أجنبي") else "عربي" if r.startswith("إقليمي") else "عراقي" for r in regs} or {"عراقي"}
        origin = "عراقي" if "عراقي" in origins else "عربي" if "عربي" in origins else "أجنبي"
        alltext = " ".join(texts) + " " + (d["label"] or "")
        ntext = norm_ar(alltext)
        iraq_kw = any(w in ntext for w in IRAQ_AR) or bool(IRAQ_EN.search(alltext)) or bool(IRAQ_MULTI.search(alltext))
        foreign_kw = any(w in ntext for w in FOREIGN_AR)
        # «عن العراق» = كلمة عراقية صريحة، أو مصدر عراقي بخبر محلي ما يذكر دولة أخرى
        about_iraq = iraq_kw or (origin == "عراقي" and not foreign_kw and not IRAQ_FOREIGN_EN.search(alltext))
        about_iraq = about_iraq_title(d["label"], about_iraq)
        if origin == "أجنبي" and not iraq_kw:
            continue  # الإعلام الأجنبي: ما يخص العراق فقط
        if not iraq_kw and IRAQ_ONLY and all(r[0] in IRAQ_ONLY for r in con.execute("SELECT DISTINCT source_id FROM items WHERE cluster_id=?", (c["id"],))):
            continue  # مصادر «العراق فقط» (مجمّعات إقليمية/منحازة أضافها إيهاب): نأخذ منها ما يخص العراق فقط
        scope = ("أجنبي" if regs and all(r.startswith("أجنبي") for r in regs)
                 else "إقليمي" if regs and all(r.startswith("إقليمي") or r.startswith("أجنبي") for r in regs) else "العراق")
        latest = max((e["time"] for e in ev if e["time"]), default=None)
        is_analysis_src = any(r.startswith("أجنبي — تحليل") for r in regs)
        if not latest or latest < iso(now - timedelta(days=7 if is_analysis_src else 1)):
            continue
        if len(KURDISH.findall(alltext)) >= 3:
            continue  # المحتوى الكردي لا يُعرض (لا توجد ترجمة كردي→عربي مجانية موثوقة حالياً)
        title = clean_title(d["label"], texts)
        title_ar = tr.get(title) or tr.get((d["label"] or "").strip())
        if not ARABIC_CH.search(title_ar or title):
            continue  # لا نعرض عنواناً غير مترجم للعربية
        if not title_ar and langs and langs <= {"fa", "tr"}:
            continue  # فارسي/تركي غير مترجم بعد (الفارسي بحروف عربية لكنه ليس عربياً)
        en = title if title_ar else ""
        kind = None
        if origin == "أجنبي":
            kind = ("مقابلة" if INTERVIEW_RX.search(en) else "رأي" if OPINION_RX.search(en)
                    else "تحليل" if (is_analysis_src or ANALYSIS_RX.search(en)) else None)
        if is_analysis_src and not kind:
            kind = "تحليل"
        if latest < iso(now - timedelta(days=1)) and not kind:
            continue
        collected = con.execute("SELECT MIN(collected_utc) FROM items WHERE cluster_id=?", (c["id"],)).fetchone()[0]
        # لا وقت بالمستقبل أبداً: الخبر ما ينشر بعد ما رصدناه
        first_t = min(x for x in (d["first"], collected) if x) if (d["first"] or collected) else None
        latest = min(latest, iso(now))
        agency = origin == "أجنبي" and (any(r.startswith("أجنبي — وكالة") for r in regs) or any(AGENCY_RX.search(e["source"] or "") for e in ev))
        views = max([views_num(r[0]) for r in con.execute("SELECT views FROM items WHERE cluster_id=?", (c["id"],))] or [0])
        first_ev = next((e for e in ev if e["time"]), ev[0] if ev else None)
        irows = con.execute("SELECT i.source_name, i.url, i.published_utc, i.collected_utc, i.updated_utc, i.kind, i.title, i.text, i.platform, i.source_id, s.official, s.category "
                            "FROM items i LEFT JOIN sources s ON s.id=i.source_id WHERE i.cluster_id=? ORDER BY COALESCE(i.published_utc, i.collected_utc)",
                            (c["id"],)).fetchall()
        edited = con.execute("SELECT COUNT(*) FROM item_versions v JOIN items i ON i.id=v.item_id WHERE i.cluster_id=?", (c["id"],)).fetchone()[0]
        flag_names = [r["source_name"] or "" for r in irows if FLAG_RX.search((r["title"] or "")[:80]) and r["source_id"] not in FLAG_SPAM
                      and (r["category"] or "") != "مدونون وصنّاع محتوى"]  # وسم «عاجل» عند المدوّنين لا يجعل الخبر عاجلاً
        source_flag = any("عاجل" not in n for n in flag_names)
        official_any = any(r["official"] for r in irows)
        if any(k == "رأي/تحليل" for k in (r["kind"] for r in irows)) or kind:
            ctype = "تحليل/رأي"
        elif official_any and not CLAIM_RX.search(alltext[:400]):
            ctype = "بيان رسمي"
        elif CLAIM_RX.search(alltext[:400]):
            ctype = "ادعاء منسوب"
        elif STATEMENT_RX.search(alltext[:300]):
            ctype = "تصريح"
        else:
            ctype = "خبر"
        pmf = is_pmf(ntext, alltext)
        pmf_kind = None
        if pmf:
            pmf_kind = ("بيان رسمي" if any(r["category"] == "الحشد الشعبي" and r["official"] for r in irows) or (official_any and ctype == "بيان رسمي")
                        else "تحليل" if ctype == "تحليل/رأي" else "دولي" if origin in ("أجنبي", "عربي") else "عراقي")
        delays = []
        for r in irows:
            if r["published_utc"] and r["collected_utc"]:
                try:
                    delays.append((datetime.fromisoformat(r["collected_utc"].replace("Z", "+00:00")) - datetime.fromisoformat(r["published_utc"].replace("Z", "+00:00"))).total_seconds() / 60)
                except ValueError:
                    pass
        pmf_class = None
        if pmf:
            pmf_class = ("قرار" if DECISION_RX.search((title_ar or title)[:160]) else "بيان رسمي" if pmf_kind == "بيان رسمي"
                         else "تصريح" if ctype == "تصريح" else "تحليل" if ctype == "تحليل/رأي" else "خبر")
        watch_hits = matcher.match(ntext + " " + norm_ar(title_ar or ""), alltext + " " + title, irows) if (about_iraq or pmf) else []
        va = V.assess([dict(r) for r in irows], verdicts.get(c["id"]))
        if A.eligible(d["n_sources"], about_iraq, level):
            try:
                analysis.append(A.build(c["id"], title_ar or title, irows, va, level,
                                        [WNAMES.get(w["id"], w["id"]) for w in watch_hits if WKIND.get(w["id"]) != "topic"]))
            except Exception as e:  # noqa: BLE001
                print("::warning title=analysis::", type(e).__name__, str(e)[:100])
        if about_iraq and A.spread_eligible(d["n_sources"], va, official_any):
            try:
                from tools.tg_push import iraq_title, far_title
                from tools.editorial import clean_headline
                st = clean_headline(title_ar or title)
                sp = A.spread(c["id"], st, irows, va) if iraq_title(st) and not far_title(st) else None
                if sp:
                    spreads.append(sp)
            except Exception as e:  # noqa: BLE001
                print("::warning title=spread::", type(e).__name__, str(e)[:100])
        recent_n = sum(1 for r in irows if r["collected_utc"] and r["collected_utc"] >= iso(now - timedelta(minutes=60)))
        # سرعة الانتشار (مثل Dataminr): عدد الجهات المختلفة التي نشرته خلال آخر 20 دقيقة — قفزة مفاجئة = خبر يتصاعد الآن
        surge_n = len({r["source_name"] for r in irows if r["collected_utc"] and r["collected_utc"] >= iso(now - timedelta(minutes=20))})
        alts, lead = None, None
        if not title_ar and (about_iraq or pmf) and (level in ("عاجل", "مهم", "متابعة") or source_flag):
            seen_a = set()
            alts = []
            for r in irows:
                ln = complete_line(r["text"] or r["title"] or "")[:220]
                k = ln[:40]
                if ln and k not in seen_a:
                    seen_a.add(k)
                    alts.append(ln)
                if len(alts) >= 6:
                    break
            lead = next((URL_RX.sub("", r["text"] or "").strip()[:400] for r in irows if len((r["text"] or "")) > 80), None)
        out.append({"id": c["id"], "alts": alts, "lead": lead, "title": title_ar or title, "title_orig": title if title_ar else None, "status": st, "basis": basis, "level": level, "scope": scope, "origin": origin, "about_iraq": about_iraq, "kind": kind, "agency": agency,
                    "n_items": c["n_items"], "views": views or None,
                    "first_src": ({"name": first_ev["source"], "time": first_ev["time"]} if first_ev else None),
                    "topic": topic_of(ntext + " " + norm_ar(title_ar or ""), alltext),
                    "collected_utc": collected, "first_utc": first_t, "latest_utc": latest,
                    "date_confirmed": all(e["date_confirmed"] for e in ev), "n_sources": d["n_sources"],
                    "sources": [{"name": e["source"], "url": e["url"], "time": e["time"]} for e in ev][:6],
                    "why": d.get("why") or [], "source_flag": source_flag, "ctype": ctype, "pmf": pmf, "pmf_kind": pmf_kind,
                    "edited": bool(edited), "detect_delay_min": round(delays[0], 1) if delays and delays[0] >= -5 else None,
                    "escalating": recent_n >= 3 and (c["n_items"] or 0) >= 4, "surge_n": surge_n,
                    "trending_unconfirmed": (d["n_sources"] or 0) >= 3 and st != "مؤكد",
                    "pmf_class": pmf_class, "watch": watch_hits, "vstatus": va["vstatus"], "vwhy": va["vwhy"], "cited": va["cited"],
                    "origin_rec": va["origin"], "independent": va["independent"], "manual": any(r["platform"] == "manual" for r in irows),
                    "timeline": [{"source": r["source_name"], "url": r["url"], "pub": r["published_utc"], "seen": r["collected_utc"],
                                  "cited": V.cited_source((r["title"] or "") + " " + (r["text"] or "")), "manual": r["platform"] == "manual"} for r in irows][:12]})
    V.cross_disputes(out)
    try:
        edit_titles(out)  # التحرير تحسين، لا يجوز أن يوقف نشر الأخبار أبداً
    except Exception as e:  # noqa: BLE001
        print(f"::error title=editorial failed (الأخبار تُنشر بعناوينها الأصلية)::{type(e).__name__}: {str(e)[:150]}")
        for n in out:
            n.pop("alts", None)
            n.pop("lead", None)
    analysis.sort(key=lambda x: (x["last_time"] or ""), reverse=True)
    try:
        pass  # قراءات تحليل الانتشار أُلغيت (طلب إيهاب 2026-11-02): حصة Gemini كلها لـ«قراءة هسة وصل»
    except Exception as e:  # noqa: BLE001
        print(f"::warning title=analysis agent::{type(e).__name__}: {str(e)[:120]}")
    (ROOT / "pwa" / "analysis.json").write_text(json.dumps({"updated_utc": iso(now), "min_sources": A.MIN_SOURCES, "items": analysis[:40]},
                                                           ensure_ascii=False), encoding="utf-8")
    print(f"::notice title=analysis::{len(analysis)} حدث كبير (20+ جهة)")
    spreads.sort(key=lambda x: (x["last_time"] or ""), reverse=True)
    (ROOT / "pwa" / "spread.json").write_text(json.dumps({"updated_utc": iso(now), "min_sources": A.SPREAD_MIN, "items": spreads[:40]},
                                                         ensure_ascii=False), encoding="utf-8")
    print(f"::notice title=spread::{len(spreads)} خبر متداول غير مؤكد")
    out.sort(key=lambda x: x["latest_utc"] or "", reverse=True)
    pwa = ROOT / "pwa"
    (pwa / "news.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    hl = core.health(con, now)
    ok = [h["name"] for h in hl if h["state"] == "يعمل"]
    cnt = dict(con.execute("SELECT source_id, COUNT(*) FROM items WHERE published_utc >= ? GROUP BY source_id", (iso(now - timedelta(hours=24)),)).fetchall())
    act = {r[0] for r in con.execute("SELECT id FROM sources WHERE method IN ('rss','telegram_preview')")}
    from marsad.cli import source_priorities
    pr = source_priorities()
    srows = {r["id"]: r for r in con.execute("SELECT * FROM sources")}
    attempt = dict(con.execute("SELECT source_id, MAX(at_utc) FROM fetch_log GROUP BY source_id").fetchall())
    hrows = []
    for h in hl:
        if h["id"] not in act:
            continue
        r = srows[h["id"]]
        url = r["url"] or ""
        typ = ("تلغرام" if r["method"] == "telegram_preview" else "Google News" if "news.google.com" in url
               else "يوتيوب" if "youtube.com" in url else "RSS")
        disabled = h["id"] in pr["_disabled"] or r["status"] == "مستبعد"
        hrows.append({"id": h["id"], "name": h["name"], "type": typ, "category": r["category"], "region": r["region"] or "",
                      "lang": r["lang"] or "", "url": url, "method": r["method"], "priority": pr.get(h["id"], 2),
                      "enabled": not disabled, "state": "معطّل" if disabled else h["state"], "items_24h": cnt.get(h["id"], 0),
                      "last_success": h["last_success"], "last_attempt": attempt.get(h["id"]), "error": h["last_error"],
                      "failures": h["failures"]})
    (pwa / "health.json").write_text(json.dumps(hrows, ensure_ascii=False), encoding="utf-8")
    # قوائم المتابعة: ملف لكل شخصية/جهة/قضية + كيف نرصد حساباتها فعلاً
    from urllib.parse import unquote
    hby = {h["url"].lower().rstrip("/"): h for h in hrows}
    gn = [unquote(h["url"]).lower() for h in hrows if "news.google.com" in h["url"]]
    wl = []
    for f in matcher.follow:
        mine = [o for o in out if any(w["id"] == f["id"] for w in o.get("watch") or [])]
        provs = {}
        for o in mine:
            for w in o["watch"]:
                if w["id"] == f["id"] and w["prov"]:
                    provs[w["prov"]] = provs.get(w["prov"], 0) + 1
        wl.append({"id": f["id"], "kind": f.get("kind"), "name": f["name"], "role": f.get("role"), "n": len(mine), "prov": provs,
                   "urgent": sum(1 for o in mine if o["level"] == "عاجل" or o.get("source_flag")),
                   "latest": max((o["latest_utc"] for o in mine if o["latest_utc"]), default=None),
                   "accounts": W.accounts_status(f, hby, gn) if f.get("kind") != "topic" else [],
                   "verification": f.get("verification"), "confidence": f.get("confidence"),
                   "terms": (f.get("terms_ar") or [])[:8]})
    (pwa / "watch.json").write_text(json.dumps({"updated_utc": iso(now), "lists": wl}, ensure_ascii=False), encoding="utf-8")
    # أرشيف «تتبّع أصل الخبر»: كل مواد آخر 72 ساعة (لا الأخبار المجمّعة فقط)، مضغوطة؛ يُحمَّل عند فتح أداة التتبع فقط
    arch = []
    for r in con.execute("SELECT i.title, i.text, i.source_name, i.url, i.published_utc, i.collected_utc, i.kind, i.time_precision, s.official, s.region "
                         "FROM items i LEFT JOIN sources s ON s.id=i.source_id WHERE COALESCE(i.published_utc, i.collected_utc) >= ? "
                         "ORDER BY COALESCE(i.published_utc, i.collected_utc)", (iso(now - timedelta(hours=72)),)):
        t = (r["title"] or "").strip()
        if len(KURDISH.findall(t)) >= 3:
            continue
        txt = (r["text"] or "").strip()
        arch.append({"t": tr.get(t) or t, "o": t if tr.get(t) else None, "x": txt[:180] if txt and txt[:60] != t[:60] else "",
                     "s": r["source_name"], "u": r["url"], "p": r["published_utc"], "c": r["collected_utc"],
                     "q": r["time_precision"], "k": r["kind"], "f": 1 if r["official"] else 0})
    (pwa / "archive.json").write_text(json.dumps({"from": iso(now - timedelta(hours=72)), "to": iso(now), "n": len(arch),
                                                  "sources_checked": sum(1 for h in hrows if h["enabled"] and h["state"] == "يعمل"),
                                                  "sources_failed": [h["name"] for h in hrows if h["enabled"] and h["state"] in ("متوقف", "فشل مؤقت")][:60],
                                                  "items": arch}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (pwa / "meta.json").write_text(json.dumps({"updated_utc": iso(now), "stories": len(out), "sources_ok": len(ok), "sources_total": len(hrows),
                                               "detect_delay": delay_stats(con, now),
                                               "sections": {"iraq": sum(1 for o in out if o["about_iraq"]),
                                                            "region": sum(1 for o in out if not o["about_iraq"] and o["origin"] != "أجنبي"),
                                                            "arab_on_iraq": sum(1 for o in out if o["about_iraq"] and o["origin"] == "عربي"),
                                                            "foreign_on_iraq": sum(1 for o in out if o["origin"] == "أجنبي"),
                                                            "translated": sum(1 for o in out if o.get("title_orig")), "analysis": sum(1 for o in out if o.get("kind")), "agencies": sum(1 for o in out if o.get("agency")), "pmf": sum(1 for o in out if o.get("pmf")),
                                                            "escalating": sum(1 for o in out if o.get("escalating")), "source_flag": sum(1 for o in out if o.get("source_flag")),
                                                            "repeated": sum(1 for o in out if (o["n_sources"] or 0) >= 3),
                                                            "urgent": sum(1 for o in out if o["level"] == "عاجل"), "important": sum(1 for o in out if o["level"] == "مهم")}},
                                              ensure_ascii=False), encoding="utf-8")
    print(len(out), "خبراً في pwa/news.json")


if __name__ == "__main__":
    main()
