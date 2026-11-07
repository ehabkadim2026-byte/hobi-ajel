"""المسار السريع «أول من يرصد»: يفحص القنوات الرسمية والأولية كل 30 ثانية لساعات متواصلة، وينشر الخبر المهم فوراً
(بطاقة تُرفع مباشرة لتلغرام بلا انتظار نشر الموقع). يتبادل بصمات المنشور مع الجولة الرئيسية عبر إصدار «fastlane»
حتى لا يتكرر الخبر بين المسارين.
"""
import html as H
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import tg_push as T  # noqa: E402
from tools.tv_source import important, PROMO  # noqa: E402
from tools import fastbreak as FB  # noqa: E402

CFG = json.loads((ROOT / "config" / "fastlane.json").read_text(encoding="utf-8"))
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/126 Mobile"}
STRICT = re.compile(r"(?<![\u0600-\u06FF])(?:و|ف|ب|ل|ال|وال|بال|لل|فال)?(عاجل|مقتل|قتلى|استشهاد|انفجار|قصف|استهداف|اشتباك|اغتيال|القبض|اعتقال|حريق|غرق|زلزال|هزة|سيول|تعطيل|عطلة|الدوام|"
                    r"رواتب|الرواتب|قرار|يقرر|تقرر|إقالة|استقالة|تعيين|إعفاء|حظر|منع|إغلاق|فتح|الموازنة|سعر الصرف|الدولار|انتخابات|المفوضية|حكم|يقضي|الإعدام|السجن)")
ME_RX = re.compile(r"(فلسطين|غزة|الضفة|لبنان|بيروت|سوريا|دمشق|إيران|طهران|تركيا|أنقرة|السعودية|الرياض|الخليج|اليمن|صنعاء|الأردن|مصر|القاهرة|إسرائيل|الاحتلال|الكويت|قطر|الإمارات|البحرين|هرمز|البحر الأحمر)")
FAR_RX = re.compile(r"(الانتخابات الأمريكية|الكونغرس|مجلس النواب الأمريكي|الديمقراطيون|الجمهوريون|أوكرانيا|روسيا|الصين|تايوان|كوريا|"
                    r"مجلس الشيوخ|ديمقراطيين|جمهوريين|الناخبين|صوتوا|الاستطلاعات|استطلاع|أسعار البنزين|فانس|شومر|هيغسيث|نيويورك)")  # سياسة أمريكية داخلية (فحص 4، تدقيق 22:11 04/11: 3072، 3075، 3078، 3101)


def regional_ok(ch, text, first, mine):
    """حدث إقليمي كبير (عربي/شرق أوسط) موسوم «عاجل» من العربية/الحدث/الجزيرة — طلب إيهاب 04/11، بسقف منفصل بالساعة."""
    if ch not in CFG.get("intl", []) or not FLAG.search(text[:40]) or FAR_RX.search(first) or not ME_RX.search(first):
        return False
    if not (T.SEC_RX.search(first) or T.EVENT_RX.search(first)) or MINOR_RX.search(first) or T.MINOR_RX.search(first):
        return False
    mil = bool(MIL_EVENT_RX.search(first))  # بيان عسكري عن الحدث نفسه («المتحدث باسم التحالف: اعتراض صاروخ كروز… باتجاه الرياض») ليس تصريحاً سياسياً (فاتنا 08:03–08:24 07/11)
    if SPEAKER_RX.search(first) and not mil:
        return False  # تصريح مسؤول أجنبي («رئيس الوزراء وزير الخارجية القطري: في لبنان… القصف مستمر») ليس الحدث نفسه (3801، فحص 4، تدقيق 04:11 07/11)
    if T.STATEMENT_RX.search(first) and not mil and not re.search(r"(قصف|غارة|غارات|ضربة|ضربات|انفجار|اغتيال|هجوم صاروخي|إطلاق صواريخ|اطلاق صواريخ)\s", first):
        return False  # تصريح سياسي عن الحرب («ترمب: الحرب رفعت البنزين») ليس حدثاً إقليمياً كبيراً — كما is_regional بالجولة الرئيسية (3101)
    return sum(1 for x in mine if x.get("ts", 0) >= time.time() - 3600 and x.get("reg")) < CFG.get("region_per_hour", 6)


MIL_EVENT_RX = re.compile(r"(?:اعتراض|اعترضت|تعترض|إسقاط|اسقاط|أسقطت|اسقطت|تدمير|دمرت)\s+(?:وتدمير\s+)?(?:\S+\s+){0,2}?(?:صاروخ|صواريخ|مسيرة|مسيّرة|مسيرات|مسيّرات|طائرة مسيرة|طائرات مسيرة)"
                          r"|(?:صاروخ|صواريخ)\s+(?:كروز|باليستي|بالستي|باليستية)|(?:هجوم|هجمات)\s+(?:بصواريخ|بالصواريخ|بمسيرات|بالمسيرات|بطائرات)")
SPEAKER_RX = re.compile(r"^\W*(?:عاجل\W*)?[^:]{0,20}(?:رئيس|وزير|وزيرة|المتحدث|الناطق|متحدث|سفير|مندوب|الأمين العام|الامين العام|مستشار|أمير|امير|ملك|ولي العهد)[^:]{0,45}:")
# حادث إقليمي محدود (شهيد واحد، استهداف دراجة نارية) ليس «حدثاً كبيراً» يستحق القناة العراقية (فحص 4، تدقيق 18:15 04/11: 3047 لبنان)
MINOR_RX = re.compile(r"(?:مصابون|مصابين|جرحى)\s+(?:في|ب|جراء)\s*(?:غارة|قصف|استهداف)|(?:شهيد|قتيل|مصاب|جريح)\s+(?:و(?:مصاب|جريح|مصابان)|واحد)|(?:شهيد|قتيل)ان?\s+في\s+غارة|استهدفت?\s+(?:دراجة|سيارة|مركبة)|(?:إصابة|اصابة)\s+(?:شخص|مواطن)\s")
FLAG = re.compile(r"^\W{0,6}(عاجل|عــاجل|عاااجل|⚡|🔴|🚨)")
# وضع السكوت لا يقبل: إسناد مجهول («مسؤول دبلوماسي:»، «مصدر:»)، رأياً أو تقييماً، أو خبراً خفيفاً — هذه تنتظر حكم النموذج أو الجولة الرئيسية
QUIET_BAD = re.compile(r"^\W*(?:مصدر|مصادر|مسؤول|مسؤولون|مسؤولة)\b[^:]{0,30}:|(?:يمثل|تمثل|يعد|تعد|يعتبر|تعتبر|يرى|ترى|يعتقد)\s|"
                       r"(?:يتألق|تتألق|يحصد|تحصد)\s|جدل\s+(?:حول|بشأن)|مطالبات\s|(?:الطقس|الأنواء|الانواء)\b")
ROUTINE = re.compile(r"(يهنئ|تهنئ|هنأ|هنّأ|هنأت|(?:يستقبل|تستقبل|استقبل)\s+(?:لجنة|وفد|وفداً|وفدا|مدير|عدد|كادر)|تبارك|يبارك|تهنئة|يعزي|تعزية|ينعى|نعى|بمناسبة|ذكرى|عيد|يستذكر|صباح الخير|جمعة مباركة|رحم الله|إنا لله|تابعونا|رابط القناة)")
STATE = ROOT / "data" / "fastlane_state.json"

# قنوات تسم كل منشوراتها «عاجل» (fm98_1 نشرت تدريب سباحة لطلبة الشرطة بوميض عاجل 05/11): نتتبع نسبة الوسم لكل قناة،
# وإذا تجاوزت 60% من آخر 20 منشوراً (بعد 8 منشورات على الأقل) أو كانت القناة في flag_ignore يُهمل وسمها والحكم للمضمون فقط
_FLAG_HIST = {}


def flagged(ch, text):
    f = bool(FLAG.search((text or "")[:40]))
    h = _FLAG_HIST.setdefault(ch, [])
    h.append(f)
    del h[:-20]
    if ch in CFG.get("flag_ignore", []) or (len(h) >= 8 and sum(h) / len(h) > 0.6):
        return False
    return f


def story_old(sig, stories, now, fresh_min=None, title=None):
    """هل الخبر متداول لدى الجهات المرصودة (3+) منذ أكثر من FRESH_MIN دقيقة؟ رسالة القناة الجديدة لا تجعل الخبر جديداً."""
    lim = now.timestamp() - 60 * (fresh_min or T.FRESH_MIN)
    old = [s for s in stories or [] if s.get("ts", 1e18) < lim and s.get("ts", 0) >= now.timestamp() - T.STORY_H * 3600]
    return any(T.same_story(sig, s) for s in old) or bool(title and T.near_dup(title, old, now.timestamp(), hours=T.STORY_H))


def gh_get(asset):
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run(["gh", "release", "download", "fastlane", "-p", asset, "-D", td, "--clobber"], capture_output=True, timeout=30)
        if r.returncode:
            return []
        try:
            return json.loads((Path(td) / asset).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return []


def gh_put(asset, data):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / asset
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        if subprocess.run(["gh", "release", "view", "fastlane"], capture_output=True, timeout=30).returncode:
            subprocess.run(["gh", "release", "create", "fastlane", "--title", "المسار السريع", "--notes", "بصمات المنشور بين المسارين", "--prerelease"],
                           capture_output=True, timeout=30)
        subprocess.run(["gh", "release", "upload", "fastlane", str(p), "--clobber"], capture_output=True, timeout=30)


def latest_posts(ch):
    page = urllib.request.urlopen(urllib.request.Request(f"https://t.me/s/{ch}", headers=UA), timeout=12).read().decode("utf-8", "replace")
    out = []
    for b in page.split('class="tgme_widget_message_wrap')[1:]:
        pid = re.search(rf'data-post="{re.escape(ch)}/(\d+)"', b, re.I)
        tx = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', b, re.S)
        tm = re.search(r'<time[^>]+datetime="([^"]+)"', b)
        img = re.search(r"tgme_widget_message_photo_wrap[^>]+background-image:url\('([^']+)'\)", b)
        if not (pid and tm and (tx or img)):
            continue  # صورة بلا نص تبقى: قد تكون كتاباً رسمياً مصوّراً (قراءة الوثيقة، fastbreak.ocr_doc)
        text = H.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<br\s*/?>", "\n", tx.group(1)))).strip() if tx else ""
        out.append({"id": int(pid.group(1)), "text": text, "t": datetime.fromisoformat(tm.group(1)), "img": img.group(1) if img else None})
    name = re.search(r'<meta property="og:title" content="([^"]*)"', page)
    return out, H.unescape(name.group(1)) if name else ch


LAST_FULL = [0.0]
LAST_RSS = [0.0]
RSS = {r["key"]: r for r in CFG.get("rss", [])}
RSS_ROT = [0]


def latest_rss(key):
    """موقع المنافس مباشرة: السومرية تنشر على موقعها قبل قناتها بوسيط 19 دقيقة وشفق بـ28 (قاعدة الرصد 3–4/11)، والجولة الرئيسية
    تجمع الخلاصة بتأخر وسيط 5 دقائق ثم تنتظر دورتها. المعرّف = وقت النشر بالثواني (متزايد) ليعمل خط الأساس كمنشورات تلغرام."""
    from marsad.collect import http_get, parse_rss
    from marsad.core import parse_time, fix_future
    r = RSS[key]
    now = datetime.now(timezone.utc)
    out = []
    for it in parse_rss(http_get(r["url"], timeout=12, retries=0), {"id": key, "name": r["name"]}):
        pub, _ = parse_time(it.get("published_utc"))
        if not pub or not (it.get("title") or "").strip():
            continue
        pub, _ = fix_future(pub, None, now)
        out.append({"id": int(pub.timestamp()), "text": it["title"].strip() + "\n" + (it.get("text") or ""), "t": pub, "img": None, "url": it.get("url")})
    return out, r["name"]


GEM_CALLS = []
GEM_PER_HOUR = 90  # حماية حصة Gemini المجانية: حكم الأهمية لأخبار القنوات السريعة والوكالات غير الموسومة


UPD_RX = re.compile(r"(ارتفاع|ارتفعت|ترتفع|حصيلة|الحصيلة|محدث|تحديث|جديد|إضافية|اضافية|آخر|اخر|نفي|ينفي|تنفي|تؤكد|يؤكد|رسمياً|رسميا|بيان)")
_DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def _new_numbers(new, old):
    """أرقام بالخبر الجديد غير موجودة بما نشرناه (حصيلة 3 ← 5) — أو نفي رسمي جديد لم يكن بما نشرناه.
    «يؤكد/تؤكد» ليست تحديثاً (فعل إخباري عام: «الزيدي … ويؤكد رفض» نزل 3 ردود خلال 5 ث 3348–3350)، والنفي لا يُعاد
    إذا كان منشورنا نفسه نفياً («الداخلية تنفي…» 3326 ثم 3 ردود بالنفي نفسه 3327–3329) — فحص 4، تدقيق 22:11 05/11."""
    nn = {x for x in re.findall(r"\d+", new.translate(_DIG)) if not re.fullmatch(r"(19|20)\d\d", x)}
    oo = set(re.findall(r"\d+", old.translate(_DIG)))
    return bool(nn - oo) or (bool(UPD_DENY.search(new)) and not UPD_DENY.search(old))


UPD_DENY = re.compile(r"(نفي|ينفي|تنفي|نفى|نفت|لا صحة|تكذب|يكذب|تكذيب)")
UPD_GAP_S = 600  # 10 دقائق على الأقل بعد المنشور الأصلي وبين تحديثين عليه: جهات تنقل التحديث نفسه بثوانٍ (3301، 3303، 3305 خلال 4 د)


def gem_ok():
    now = time.time()
    GEM_CALLS[:] = [t for t in GEM_CALLS if t >= now - 3600]
    if len(GEM_CALLS) >= GEM_PER_HOUR:
        return False
    GEM_CALLS.append(now)
    return True


DECISIONS = []  # سجل دائري لقرارات المسار السريع (لماذا رُفض/نُشر كل منشور) يُرفع fast_decisions.json للمدقق
DEC_MAX = 3000  # ~6 ساعات: 400 قرار كانت تغطي 30 دقيقة فقط فلا يعرف المدقق سبب رفض خبر بفجوة الإيقاع (فحص 5، تدقيق 10:11 07/11)
REASON = {"قديم": "fresh", "روتيني": "routine", "سقف": "cap", "مكرر": "dup", "نفس الجهة خلال ساعة": "same_actor",
          "وكالة: ليس عراقياً": "not_iraq", "ليس عراقياً": "not_iraq", "سقف النموذج بالساعة": "gem_cap"}


def decide(ch, pid, head, decision, reason):
    DECISIONS.append({"t": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "ch": ch, "id": pid, "head": (head or "")[:80],
                      "decision": decision, "reason": reason})
    del DECISIONS[:-DEC_MAX]


def bad_title_reason(t):
    """سبب دقيق لرفض «عنوان غير صالح» (عامية، جهة مستبعدة، مبتور، عرض صحف، قيمة منخفضة)."""
    if T.offensive(t):
        return "offensive"
    if T.dialect(t):
        return "dialect"
    if T.EXCL_RX.search(t):
        return "excluded"
    if T.incomplete(t):
        return "incomplete"
    if T.PRESS_RX.search(t):
        return "press"
    return "low_value"


def official_ch(ch, tier):
    """قناة جهة رسمية مُصدِرة (قائمة channels + رسمية في sources.json، لا وكالة ولا إعلام حكومي ناقل)."""
    from tools import confirm as CF
    return CF.official_name(ch) if tier == "official" else None


def trust_tier(ch, tier):
    """طبقة موثوقية القناة/الموقع (source_trust.json): موثوقة/عادية/ضعيفة/غير كافٍ أو None."""
    from tools import reliability as R
    return R.tier_of(RSS[ch]["url"] if tier == "rss" and ch in RSS else ch)


def load_trust():
    from tools import reliability as R
    d = gh_get("source_trust.json")
    R.load(data=d if isinstance(d, dict) else {})
    return bool(isinstance(d, dict) and d.get("sources"))


AUTO_BASE = {k: list(CFG.get(k) or []) for k in ("channels", "breaking", "hot", "agency", "intl", "loud")}


def load_auto():
    """الضبط الذاتي اليومي (tools/auto_tune.py → fastlane_auto.json): «promote» إلى breaking و«demote» تُرفع من الطبقات غير الرسمية، في الذاكرة فقط."""
    from tools import auto_tune as AT
    d = gh_get(AT.ASSET)
    if isinstance(d, dict) and "promote" in d:  # فشل التنزيل لا يُلغي ضبطاً محمّلاً
        CFG.update(AT.merge(AUTO_BASE, d))
        return {"promote": len(d.get("promote") or []), "demote": len(d.get("demote") or []), "at": d.get("updated_utc")}
    return None


def iraq_strong(t):
    from marsad.textnorm import norm_ar
    iq, _ = T._markers()
    x = " " + norm_ar(t) + " "
    return any(w and w in x for w in iq)


def main():
    token = os.environ.get("MARSAD_TG_BOT_TOKEN", "").strip()
    if not token:
        return
    chat_id = os.environ.get("MARSAD_TG_CHAT_ID", "").strip() or "-1004327422297"
    run_until = time.time() + float(os.environ.get("FAST_MINUTES", "330")) * 60
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        st = {}
    last = st.get("last", {})
    mine = gh_get("fast_sigs.json")
    try:
        stats_auto = load_auto()  # قبل قائمة حساب الرصد: القنوات المُرقّاة تُشترك أيضاً
    except Exception as e:  # noqa: BLE001
        stats_auto = None
        print("::warning title=auto_tune::", type(e).__name__)
    stats = {"loops": 0, "posted": 0, "skipped": {}, "errors": 0, "auto": stats_auto}
    from tools.editorial import edit_headline
    from tools import tg_card
    from tools import manual_pub as MP
    from tools import tg_user_listener as UL
    seen_manual = MP.done_ids()
    _all0 = list(dict.fromkeys(CFG.get("hot", []) + CFG["channels"] + CFG.get("breaking", []) + CFG.get("intl", []) + CFG.get("agency", [])))  # الأسرع أولاً للاشتراك التدريجي
    def _views_save(rows):  # يدمج مع المخزون (7 أيام) ويرفع channel_views.json — مادة تقرير «ماذا يشاهد جمهورنا»
        old = gh_get("channel_views.json") or {}
        cur = {str(r["id"]): r for r in (old.get("posts") or [])} if isinstance(old, dict) else {}
        for r in rows:
            cur[str(r["id"])] = r
        cut = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 7 * 86400))
        gh_put("channel_views.json", {"updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                      "posts": sorted((r for r in cur.values() if r["t"] >= cut), key=lambda r: r["id"])})
    UL.start(token, _all0, run_until - 60, views_cb=_views_save)  # حساب الرصد: منشورات لحظية بدل انتظار الفحص الدوري
    try:  # تنبيهات الهاتف (Web Push): خيط خلفي يقرأ الاشتراكات ويرسل بعد كل منشور ناجح (live_feed.publish ← web_push.notify)
        from tools import web_push as WP
        WP.start(token, run_until - 30, load=lambda: gh_get(WP.ASSET), save=lambda d: gh_put(WP.ASSET, d))
    except Exception as e:  # noqa: BLE001
        print("::warning title=web_push::", type(e).__name__)
    try:  # رادارات الإشارات (زلازل USGS/EMSC، انقطاع الإنترنت IODA، قفزات الدولار): خيط خلفي بمؤقتاته الخاصة، لا يؤخر النشر
        from tools import signal_radars as SR
        SR.start(token, chat_id, run_until - 30, latest_posts, load=lambda: gh_get(SR.ASSET), save=lambda d: gh_put(SR.ASSET, d))
    except Exception as e:  # noqa: BLE001
        SR = None
        print("::warning title=radars::", type(e).__name__)
    LOWER = {c.lower(): c for c in _all0}
    NAMES = {}
    from tools import confirm as CF
    try:
        ledger = CF.Ledger("fast")
    except Exception as e:  # noqa: BLE001
        ledger = None
        print("::warning title=confirm ledger::", type(e).__name__)
    LAST_DEC = [time.time()]
    # العاجل على مرحلتين: إرسال فوري ثم إثراء المنشور نفسه (tools/fastbreak.py)؛ RECENT = منشورات آخر 30 دقيقة لكل القنوات (مصادر لاحقة)
    from concurrent.futures import ThreadPoolExecutor as _TPE
    photo_pool = _TPE(2, thread_name_prefix="photo")
    EN = FB.Enricher(after=CFG.get("enrich_after_sec", 45), edit_headline=edit_headline, anim=tg_card.breaking_anim,
                     card=tg_card.card_news4, fetch=tg_card.fetch_jpeg, wm=lambda b: FB.watermarked(b, gem_ok=gem_ok))
    RECENT = []
    try:
        stats["trust"] = load_trust()  # طبقات المصادر (تُحدَّث يومياً بالجولة الرئيسية)
    except Exception as e:  # noqa: BLE001
        print("::warning title=trust::", type(e).__name__)
    prev_dec = gh_get("fast_decisions.json")  # السجل الدائري يستمر عبر إعادة التشغيل
    DECISIONS[:] = (prev_dec.get("items") or [])[-DEC_MAX:] if isinstance(prev_dec, dict) else []
    while time.time() < run_until:
        t0 = time.time()
        try:  # أوامر المحررين /نشر و/عاجل تُنشر خلال ثوانٍ، وبوابة المراسل (صوت/صورة/ملاحظات ← مسودة بأزرار) وضغطات أزرارها
            stats["manual"] = stats.get("manual", 0) + MP.poll(token, chat_id, seen_manual)
        except Exception as e:  # noqa: BLE001
            print("::warning title=manual_pub::", type(e).__name__)
        stats["loops"] += 1
        main_sigs = (gh_get("main_sigs.json") + gh_get("tv_sigs.json")) if stats["loops"] % 4 == 1 else main_sigs if stats["loops"] > 1 else []
        stories = gh_get("story_first.json") if stats["loops"] % 4 == 1 else stories if stats["loops"] > 1 else []
        if stats["loops"] % 300 == 0:  # ~كل 30–40 دقيقة: نسخة اليوم من source_trust.json
            try:
                load_trust()
                stats["auto"] = load_auto() or stats.get("auto")
            except Exception:  # noqa: BLE001
                pass
        if ledger is not None and stats["loops"] % 4 == 1:
            try:
                ledger.refresh_other()  # منشورات الجولة الرئيسية المرشحة لـ«أكدته»
            except Exception:  # noqa: BLE001
                pass
        now = datetime.now(timezone.utc)
        mine = [x for x in mine if x.get("ts", 0) >= time.time() - T.DEDUP_H * 3600]
        T.build_idf([x.get("title", "") for x in mine] + [x.get("title", "") for x in main_sigs][-400:] + [x.get("title", "") for x in stories][-400:]) if stats["loops"] % 20 == 1 else None
        from concurrent.futures import ThreadPoolExecutor
        allc = [(c, "official") for c in CFG["channels"]] + [(c, "breaking") for c in CFG.get("breaking", []) if c not in CFG["channels"]]
        hot = set(CFG.get("hot", []))
        full = time.time() - LAST_FULL[0] >= CFG["every_sec"] or stats["loops"] == 1
        woke = UL.WAKE.is_set()
        chans = allc if full else ([] if woke else [x for x in allc if x[0] in hot])  # الأكثر سبقاً كل 8 ثوانٍ، الكل كل 25، ولا فحص إذا أيقظنا منشور لحظي
        if full:
            LAST_FULL[0] = time.time()
        if RSS and time.time() - LAST_RSS[0] >= CFG.get("rss_every_sec", 45):
            LAST_RSS[0] = time.time()
            core = [k for k, r in RSS.items() if not r.get("rot")]
            rot = [k for k, r in RSS.items() if r.get("rot")]
            n = CFG.get("rss_rot_per_tick", 8)
            if rot:  # المواقع الإضافية بالتناوب حتى لا تطول الدورة (لكل موقع مهلة 12 ث)
                i0 = RSS_ROT[0] % len(rot)
                core += (rot[i0:] + rot[:i0])[:n]
                RSS_ROT[0] = i0 + n
            chans = chans + [(k, "rss") for k in core]

        def fetch(c):
            try:
                r = latest_rss(c[0]) if c[1] == "rss" else latest_posts(c[0])
            except Exception:  # noqa: BLE001
                return c, None
            for x in r[0]:
                x.setdefault("rx", time.time())  # لحظة الرصد (لقياس «الرصد ← الإرسال»)
            return c, r
        with ThreadPoolExecutor(10) as ex:
            results = list(ex.map(fetch, chans)) if chans else []
        tiers = dict(allc) | {k: "rss" for k in RSS}
        for (c, _t), r in results:
            if r:
                NAMES[c] = r[1]
        for lc, ps in UL.drain().items():  # ما وصل لحظياً من حساب الرصد يُعالج بنفس المسار والفلاتر
            c = LOWER.get(lc)
            if c and c in tiers:
                results.append(((c, tiers[c]), (sorted(ps, key=lambda x: x["id"]), NAMES.get(c, c))))
                stats["live"] = stats.get("live", 0) + len(ps)
        stats["listener"] = dict(UL.STATUS)
        for (ch, tier), res in results:
            if res is None:
                stats["errors"] += 1
                continue
            posts, cname = res
            seen = last.get(ch, 0)
            new = [p for p in posts if p["id"] > seen]
            if posts:
                last[ch] = max(p["id"] for p in posts)
            if not seen:
                continue  # أول مرة: نسجل خط الأساس فقط
            for p in new:
                from tools.editorial import complete_line
                raw = first = complete_line(p["text"])
                t_det = p.get("rx") or time.time()

                def skip(why, code=None):
                    stats["skipped"][why] = stats["skipped"].get(why, 0) + 1
                    decide(ch, p["id"], raw, "skip", code or REASON.get(why, why))
                age = (now - p["t"]).total_seconds() / 60
                oname = official_ch(ch, tier)
                from_doc = False
                if tier == "official" and len(first.split()) < 6 and (p.get("img_bytes") or p.get("img")) and age <= CFG["max_age_min"] \
                        and CFG.get("ocr", True) and not ROUTINE.search(p["text"]) and not PROMO.search(p["text"]):
                    # صورة كتاب/بيان رسمي بلا نص: Gemini يقرأ الجهة والتاريخ والقرار (سقف 20/س منفصل + سقف النموذج)، ثم البوابات المعتادة كلها
                    try:
                        img = p.get("img_bytes") or tg_card.fetch_jpeg(p["img"])
                        p["img_bytes"] = img
                        doc, code = FB.ocr_doc(img, re.sub(r" — .*$", "", oname or NAMES.get(ch) or ch), gem_ok=gem_ok)
                    except Exception as e:  # noqa: BLE001
                        doc, code = None, "ocr_" + type(e).__name__
                    if not doc:
                        skip("وثيقة غير صالحة", code); continue
                    raw = first = doc["head"]
                    p["text"] = doc["text"]
                    from_doc = True
                if first:
                    RECENT.append({"ch": ch, "name": NAMES.get(ch) or (RSS.get(ch) or {}).get("name") or ch, "first": first, "text": p["text"][:1500],
                                   "ts": p["t"].timestamp(), "ref": RSS[ch]["url"] if tier == "rss" and ch in RSS else ch,
                                   "img_bytes": p.get("img_bytes"), "img": p.get("img"), "official": bool(oname)})
                    del RECENT[:-600]
                    for _r in RECENT[:-150]:  # صور آخر 150 منشوراً فقط بالذاكرة (06/11: صورة الحدث من مصدر آخر)
                        _r.pop("img_bytes", None)
                if oname and ledger is not None and first and age <= CF.WINDOW_H * 60:
                    try:  # جهة رسمية نشرت: هل نشرنا الخبر نفسه من مصدر غير رسمي؟ ← «✅ أكدته» على منشورنا (قبل فلاتر النشر: غالباً يُرفض هنا كمكرر)
                        c_n = CF.check(ledger, T.api, token, chat_id, oname, first, p["t"].timestamp())
                        if c_n:
                            stats["confirmed"] = stats.get("confirmed", 0) + c_n
                            decide(ch, p["id"], first, "confirm", f"edited:{c_n}")
                    except Exception as e:  # noqa: BLE001
                        print("::warning title=confirm::", type(e).__name__, str(e)[:80])
                ttier = None if oname else trust_tier(ch, tier)
                if ttier == "موثوقة" and ledger is not None and first and age <= CF.WINDOW_H * 60:
                    try:  # مصدر مستقل «موثوق» نقل الخبر نفسه ← «☑️ تطابق لدى مصدر موثوق» على منشورنا (شبكة مختلفة، ليس نسخاً، أرقام متسقة)
                        ref = RSS[ch]["url"] if tier == "rss" and ch in RSS else ch
                        t_n = CF.check_trusted(ledger, T.api, token, chat_id, re.sub(r" — .*$", "", NAMES.get(ch) or (RSS.get(ch) or {}).get("name") or ch),
                                               first, p["t"].timestamp(), ref)
                        if t_n:
                            stats["trusted"] = stats.get("trusted", 0) + t_n
                            decide(ch, p["id"], first, "confirm", f"trusted:{t_n}")
                    except Exception as e:  # noqa: BLE001
                        print("::warning title=trusted::", type(e).__name__, str(e)[:80])
                first = first if len(first.split()) >= 6 and not T.PROMO_RX.search(first) else ""
                if age > CFG["max_age_min"]:
                    skip("قديم"); continue
                if not first or PROMO.search(first) or ROUTINE.search(first):
                    skip("روتيني", "routine" if first else "short"); continue
                if sum(1 for x in mine if x.get("ts", 0) >= time.time() - 3600) >= CFG["per_hour"]:
                    skip("سقف"); continue
                regional = False
                sig = T.title_sig(first)
                if any(T.same_story(sig, x) for x in mine + main_sigs) or T.sec_dup(first, mine + main_sigs, time.time()):
                    # تحديث على خبر نشرناه (حصيلة/رقم جديد/نفي/تأكيد رسمي): يُرسل ردّاً على منشورنا الأصلي بدل خبر مكرر (مقترح 4، 05/11)
                    base = next((x for x in reversed(mine) if x.get("mid") and T.same_story(sig, x) and time.time() - x.get("ts", 0) <= 3 * 3600), None)
                    if base and CFG.get("update_replies", True) and (oname or ttier != "ضعيفة") and base.get("upd", 0) < 3 and time.time() - max(base.get("upd_ts", 0), base.get("ts", 0)) >= UPD_GAP_S \
                            and UPD_RX.search(first) and _new_numbers(first, base.get("title", "")):
                        try:
                            uh = FB.fast_head(first)
                            rr = T.api(token, "sendMessage", chat_id=chat_id, reply_to_message_id=base["mid"], disable_notification="true",
                                       parse_mode="HTML", text=f"🔄 <b>تحديث:</b> {H.escape(uh)}" + (f"\n📌 المصدر: {H.escape(re.sub(r' — .*$', '', cname))}" if FB.SHOW_SOURCE else ""))
                            if rr.get("ok"):
                                base["upd"] = base.get("upd", 0) + 1
                                base["upd_ts"] = time.time()
                                base["title"] = (base.get("title", "") + " " + first)[:600]
                                gh_put("fast_sigs.json", mine)
                                decide(ch, p["id"], uh, "update", f"reply:{base['mid']}")
                                continue
                        except Exception as e:  # noqa: BLE001
                            print("::warning title=update_reply::", type(e).__name__)
                    skip("مكرر"); continue
                if story_old(sig, stories, now, title=first):
                    skip("قديم", "story_old"); continue  # الخبر نفسه متداول لدى 3 جهات منذ أكثر من 15 دقيقة (2980، 2985، 2990)
                lk = T.lead_key(first)
                if ch not in CFG["loud"] and sum(1 for x in mine + main_sigs if x.get("ts", 0) >= time.time() - 3600 and T.lead_key(x.get("title") or "") == lk) >= 2:
                    skip("نفس الجهة خلال ساعة"); continue
                if ch not in CFG["loud"] and not T.SEC_RX.search(first) and \
                        any(x.get("ts", 0) >= time.time() - 900 and T.lead_key(x.get("title") or "") == lk for x in mine + main_sigs):
                    skip("نفس الجهة خلال ساعة", "same_actor_15m"); continue  # تصريحات المتحدث نفسه بالدقيقة نفسها (الغدير: 3412، 3416، 3417 — تدقيق 04:11 06/11)
                if T.low_value(first) or T.incomplete(first) or T.PRESS_RX.search(first):
                    skip("عنوان غير صالح", bad_title_reason(first)); continue
                if ttier == "ضعيفة":
                    skip("مصدر ضعيف", "weak_src"); continue  # مصدر وحيد بطبقة «ضعيفة»: لا نشر سريع، والجولة الرئيسية تنشره إذا عززه مصدر آخر
                # قناة عراقية (لا عربية/دولية): خبر جهة رسمية بصيغة محلية بلا اسم العراق يكفي إذا خلا من أي علامة أجنبية («التقاعد: …»، «شرطة …»)
                pflag = flagged(ch, p["text"])
                # المصدر العربي/الدولي: العراق لازم يكون موضوع العنوان (أول 16 كلمة)، لا ذكراً عابراً بآخر فقرة طويلة
                # (النهار: «وزير سابق: حزب الله…» ذكر العراق بالكلمة 37 فنُشر 3453 — تدقيق 10:11 06/11)
                iraqi = T.iraq_strict(" ".join(first.split()[:16]) if ch in CFG.get("intl", []) else first) or \
                    (ch not in CFG.get("intl", []) and T.iraq_domestic(first))
                # رأي محلل/خبير عن العراق يُقبل بوسم «تحليل» بلا حكم الأهمية: لا ننتظر النموذج قبله (كان يُستدعى ثم يُتجاهل —
                # 3439 بعد 42.9 ث و3443 بعد 33.6 ث؛ فحص 7، تدقيق 04:11 06/11). السقف والشروط تُطبق أدناه كما هي.
                an_pre = bool(iraqi and T.analyst(first))
                if ch in CFG.get("agency", []) or tier == "rss" or (tier == "breaking" and ttier == "موثوقة"):
                    # وكالة موثوقة (أو موقعها مباشرة عبر RSS): عاجلها (أو حدث مهم بكلمات صريحة) عن العراق يُنشر فوراً منسوباً لها، بلا انتظار مصدر ثانٍ
                    if not iraqi and regional_ok(ch, p["text"], first, mine):
                        regional = True
                    elif not iraqi:
                        skip("وكالة: ليس عراقياً"); continue
                    why_no = "no_strict"
                    if regional or pflag or STRICT.search(first) or an_pre:
                        ok = True
                    else:  # خبر وكالة غير موسوم: يحكم النموذج على أهميته (واع سبقتنا 12 مرة بأخبار عادية مهمة كنا ننتظرها للجولة الرئيسية)
                        ok, by = important(p["text"][:600], news=True) if gem_ok() else (False, "سقف")
                        why_no = "gem_cap" if by == "سقف" else "gem_unavailable" if by not in ("Gemini", "قاعدة") else "gem_no" if not ok else "routine"
                        if by not in ("Gemini", "قاعدة"):
                            ok = bool(STRICT.search(first) or T.EVENT_RX.search(first))
                        ok = ok and (by == "قاعدة" or (by == "Gemini" and not T.ROUTINE_RX.search(first)))  # «قاعدة» = مهم بالتعريف (كان يُهمل هنا: رواتب كردستان 04/11)
                elif tier == "breaking":
                    # قنوات الأخبار السريعة: فقط ما وسمته «عاجل» ويذكر العراق صراحة
                    if not iraqi and regional_ok(ch, p["text"], first, mine):
                        regional = True
                    elif not iraqi:
                        skip("ليس عراقياً"); continue
                    why_no = "no_strict"
                    if regional or pflag or T.SEC_RX.search(first) or an_pre:
                        ok = True  # عاجل عراقي، أو خبر أمني عراقي حتى بلا وسم «عاجل» (الأمني لا ينتظر)، أو رأي محلل (يُوسم ويُسقف أدناه)
                    elif gem_ok():
                        # خبر عراقي غير موسوم من قناة سريعة (دجلة، السومرية، 964…): المسار السريع هو الناشر الأساسي الآن،
                        # والجولة الرئيسية تتأخر 5–10 دقائق بطبيعتها — يحكم النموذج على أهميته (تحليل السبق 2026-11-03)
                        ok, by = important(p["text"][:600], news=True)
                        why_no = "gem_unavailable" if by not in ("Gemini", "قاعدة") else "gem_no" if not ok else "routine"
                        if by not in ("Gemini", "قاعدة"):  # 07/11: النموذج غير متاح ليلاً فضاعت أخبار مهمة — الحدث العراقي الصريح يمر بالقاعدة
                            ok = bool(STRICT.search(first) or T.EVENT_RX.search(first))
                        ok = ok and (by == "قاعدة" or (by == "Gemini" and not T.ROUTINE_RX.search(first)))  # «قاعدة» = مهم بالتعريف (كان يُهمل هنا: رواتب كردستان 04/11)
                    else:
                        skip("سقف النموذج بالساعة"); continue
                elif an_pre:
                    ok, why_no = True, ""
                else:
                    if not oname and T.foreign_only(first):
                        skip("ليس عراقياً", "foreign_ch"); continue  # قناة عامة غير رسمية تنقل شأناً أجنبياً بلا ذكر العراق (3735 الحوثيون، 3753 الحرس الثوري — فحص 4، تدقيق 22:12 06/11)
                    ok, by = important(p["text"][:600], news=True)
                    why_no = "gem_no"
                    if by != "Gemini":
                        ok = bool(STRICT.search(p["text"][:400]) or (iraqi and T.EVENT_RX.search(first)))  # بلا نموذج لغوي: كلمات الحدث المهم فقط (لا «يلتقي/يستقبل»)
                        why_no = "gem_unavailable"  # والكلمات الصريحة لم تكفِ
                    if ok and T.ROUTINE_RX.search(first) and not STRICT.search(first):
                        ok, why_no = False, "routine"  # نشاط روتيني لجهة رسمية (حملة تشجير، يترأس جلسة، لقاءات أسبوعية: 2958، 2979، 2991) قبله النموذج
                # القناة ساكتة (لا منشور خلال quiet_min دقيقة): خبر عراقي من جهة غير ضعيفة رفضه النموذج كـ«غير مهم» يُنشر —
                # الإيقاع المطلوب خبر كل ~2 دقيقة، والصمت 20 دقيقة صباح 05/11 كان من صرامة النموذج لا من قلة الأخبار
                # (مجلس كردستان يعقد جلسته الأولى، خطة النفط لحقول الإقليم رُفضتا gem_no). الروتيني والضعيف والقصير يبقى مرفوضاً.
                quiet = False
                is_an = T.analyst(first)
                if is_an:  # رأي محلل/خبير عن العراق: يُقبل بوسم «تحليل» وبسقف analyst_per_hour (لا يمر عبر حكم الأهمية)
                    n_an = sum(1 for x in mine if x.get("an") and x.get("ts", 0) >= time.time() - 3600)
                    if not iraqi or ttier == "ضعيفة" or n_an >= CFG.get("analyst_per_hour", 3):
                        skip("سقف", "analyst_cap"); continue
                    ok = True
                # وضع السكوت للنهار فقط (8 ص – 12 ل بغداد كهدف الإيقاع)، ولقناة عراقية، ولعنوان خبري لا رأي/محلل/مصدر مجهول:
                # ليلاً وبالصباح الباكر كان يملأ القناة بغير الأخبار (3448 مقال، 3451 موعد الأذان، 3455) ونهاراً برأي (3464) — تدقيق 10:11 06/11
                bgh = (datetime.now(timezone.utc).hour + 3) % 24
                # ليلاً (إيهاب 07/11: «ممنوع أي قطع») يُسمح بعد 12 دقيقة سكوت للحدث/القرار العراقي الصريح فقط (لا مقالات ولا مواعيد)
                night_ok = bgh >= 8 or bool(T.SEC_RX.search(first) or T.EVENT_RX.search(first) or STRICT.search(first)
                                            or re.search(r"(?:ت|ي)?قرر|قرار|تعلن|أعلنت|إعلان|تعطيل|إغلاق|اغلاق|وفاة|مقتل|إصابة|حريق|انفجار|سيول|عاصفة", first))
                if not ok and why_no in ("gem_no", "gem_unavailable") and iraqi and not regional and ttier != "ضعيفة" and not T.ROUTINE_RX.search(first) \
                        and not ROUTINE.search(first) and len(first.split()) >= 7 and night_ok and ch not in CFG.get("intl", []) \
                        and not is_an and not QUIET_BAD.search(first):
                    qmin = CFG.get("quiet_min", 6) if bgh >= 8 else CFG.get("quiet_min_night", 12)
                    last_post = max([x.get("ts", 0) for x in mine + main_sigs if isinstance(x, dict)] or [0])
                    if time.time() - last_post >= qmin * 60:
                        ok, quiet = True, True
                if not ok:
                    skip("غير مهم", why_no); continue
                head0 = FB.fast_head(first)
                crit = CFG.get("two_stage", True) and not regional and (CFG.get("two_stage_all", False) or FB.critical(oname, pflag, first,
                                                                                   FB.loud_of(p["text"], first, head0, flag=pflag)))
                # الحرج: عنوان القواعد فوراً (الصياغة بالنموذج تأتي بالإثراء خلال 30–120 ث)، وغيره كما كان
                head = head0 if crit else edit_headline(first, context=p["text"][:500])
                if head != first:  # العنوان المحرر قد يطابق منشوراً سابقاً لم يطابقه النص الخام (الحكم بالمؤبد في كركوك 3264 ثم 3265 بعد دقيقتين — فحص 4، تدقيق 18:11 05/11)
                    hsig = T.title_sig(head)
                    if any(T.same_story(hsig, x) for x in mine + main_sigs) or T.sec_dup(head, mine + main_sigs, time.time()):
                        skip("مكرر", "edited_dup"); continue
                if T.low_value(head) or T.incomplete(head) or len(head.split()) < 5:
                    skip("عنوان غير صالح", "edited_" + (bad_title_reason(head) if len(head.split()) >= 5 else "short")); continue  # التحرير قد يبتر العنوان (حذف هاشتاغ/سطر): نفحص الناتج النهائي لا الخام (تدقيق 2883، 2884)
                photo = p.get("img_bytes")
                photo_fut = None
                if not photo and p["img"]:
                    if crit:  # مهلة قصيرة: الصورة المتأخرة تُضاف بالإثراء
                        photo, photo_fut = FB.photo_within(tg_card.fetch_jpeg, p["img"], CFG.get("fast_photo_sec", 1.5), photo_pool)
                    else:
                        try:
                            photo = tg_card.fetch_jpeg(p["img"])
                        except Exception:  # noqa: BLE001
                            pass
                # صور الجهات غير الرسمية قد تحمل شعار قناة أخرى (السابعة، وطن…): لا تُرسل فوراً، بل تُفحص بالإثراء وتُضاف إن كانت نظيفة (طلب إيهاب 05/11)
                hold = bool(CFG.get("wm_hold", True) and not oname and (photo or photo_fut))
                photo_hold = photo if hold else None
                if hold:
                    photo = None
                # «عاجل» (شارة حمراء + وميض) فقط لما وسمته المصادر عاجلاً أو حدث أمني عراقي — لا لكل منشورات الجهات الرسمية
                # وسم «عاجل» من المصدر وحده لا يكفي: بعض القنوات (ABC العربية) تسم كل منشور عاجلاً — يلزم حدث عاجل بالمضمون
                # (أمني/انفجار/كارثة/تعطيل دوام/استقالة) لا موعد مباراة ولا سعر أمبير ولا حالة جوية (فحص 4، تدقيق 18:15 04/11: 3025، 3038، 3044، 3049، 3060)
                loud = not is_an and (pflag or bool(T.SEC_RX.search(first) and T.iraq_strict(first))) and not T.NOT_URGENT_RX.search(head) \
                    and bool(T.SEC_RX.search(head) or T.EVENT_RX.search(head) or T.URGENT_RX.search(head)) \
                    and not (T.STATEMENT_RX.search(head) and not (T.SEC_RX.search(head) or T.EVENT_RX.search(head))) and T.iraq_strict(head)  # سعر الدولار/السلف/التقديم بلا «عاجل» (تدقيق 2835)
                src_name = re.sub(r" — .*$", "", cname) + (" (وثيقة رسمية)" if from_doc else "")
                card = tg_card.card_news4(photo, head, loud, p["t"].strftime("%Y-%m-%dT%H:%M:%SZ"), source=re.sub(r" — .*$", "", cname), style="A")
                tags = T.province_tags(first)
                tmark, tpin = T.topic_mark(head)  # إيهاب 06/11: «🎉 عطلة رسمية» (تُثبّت) و«💰 الرواتب»
                credit = FB.SHOW_SOURCE or ch.lower() in {x.lower() for x in CFG.get("credit_sources", [])}  # صفحة شخصية: يُذكر المصدر (إيهاب 06/11)
                cap = f"<b>{tmark or ('📊 تحليل | ' if is_an else '🔴 عاجل | ' if loud else '')}{H.escape(head)}</b>" + (f"\n\n📌 المصدر: {H.escape(src_name)}" if credit else "") + \
                      (("\n" + " ".join(tags)) if tags else "") + f"\n\nزورونا على الرابط للأخبار العاجلة 👇\n{T.CHANNEL}"
                kb = json.dumps({"inline_keyboard": [[{"text": "📖 التفاصيل", "url": p.get("url") or f"https://t.me/{ch}/{p['id']}"},
                                                      {"text": "↗️ شارك القناة", "url": "https://t.me/share/url?url=https%3A%2F%2Ft.me%2Fakamedia_iq"}]]})
                r = {"ok": False}
                kind = "photo"
                if loud and not crit:  # العاجل يومض: بطاقة متحركة (تُحفظ فيديو من تلغرام)، والصورة احتياط — الحرج يتحول للمتحرك بالإثراء
                    try:
                        anim = tg_card.breaking_anim(photo, head, p["t"].strftime("%Y-%m-%dT%H:%M:%SZ"), style="news4A", source=re.sub(r" — .*$", "", cname))
                        r = T.api(token, "sendAnimation", files={"animation": ("breaking.mp4", anim, "video/mp4")}, chat_id=chat_id, caption=cap[:1024],
                                  parse_mode="HTML", reply_markup=kb, width="1080", height="1350", disable_notification="false")
                        kind = "animation" if r.get("ok") else "photo"
                    except Exception as e:  # noqa: BLE001
                        print("::warning title=fastlane anim::", type(e).__name__)
                try:
                    if not r.get("ok"):
                        r = T.api(token, "sendPhoto", files={"photo": ("card.jpg", card)}, chat_id=chat_id, caption=cap[:1024], parse_mode="HTML",
                                  reply_markup=kb, disable_notification="false" if loud else "true")
                except Exception as e:  # noqa: BLE001
                    desc = ""
                    try:  # سبب رفض تلغرام (Bad Request: …) — كان يضيع فلا نعرف لماذا فشل الإرسال
                        desc = json.loads(e.read().decode()).get("description", "")[:80]
                    except Exception:  # noqa: BLE001
                        pass
                    r = {"ok": False, "description": desc}
                    print("::warning title=fastlane send::", type(e).__name__, desc)
                if not r.get("ok"):
                    decide(ch, p["id"], head, "fail", "send_failed:" + str(r.get("description") or r.get("error_code") or "")[:80])
                if r.get("ok"):
                    stats["posted"] += 1
                    if tpin:
                        try:
                            T.api(token, "pinChatMessage", chat_id=chat_id, message_id=(r.get("result") or {}).get("message_id"), disable_notification="true")
                        except Exception:  # noqa: BLE001
                            pass
                    FB.LAT.add("fast" if crit else "normal", time.time() - t_det)
                    FB.STATUS["fast_sent"] += int(bool(crit))
                    mine.append({"w": sorted(sig[0]), "d": sorted(sig[1]), "ts": time.time(), "title": first[:200], "id": f"fast:{ch}/{p['id']}",
                                 "mid": (r.get("result") or {}).get("message_id"), "an": bool(is_an),
                                 "lag_min": round(age, 1), "reg": regional})
                    gh_put("fast_sigs.json", mine)
                    decide(ch, p["id"], head, "post", "loud" if loud else "quiet" if quiet else tier)
                    DECISIONS[-1].update(lat_s=round(time.time() - t_det, 2), **({"stage": "fast"} if crit else {}), **({"doc": 1} if from_doc else {}))
                    try:  # تغذية لحظية للتطبيق (موقّعة) — يظهر بالتطبيق خلال ثوانٍ بدل انتظار الجولة
                        from tools import live_feed
                        live_feed.publish(token, {"id": f"{ch}/{p['id']}", "title": head, "t": p["t"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                  "urgent": bool(loud), "src": re.sub(r" — .*$", "", cname),
                                                  "url": p.get("url") or f"https://t.me/{ch}/{p['id']}", "msg": r["result"]["message_id"]})
                    except Exception:  # noqa: BLE001
                        pass
                    if ledger is not None:
                        try:  # سجل «أكدته الجهة الرسمية»: منشور من جهة غير رسمية قد تؤكده جهة رسمية لاحقاً
                            ledger.add_post(r["result"]["message_id"], sig, cap[:1024], kind, bool(official_ch(ch, tier)), title=first,
                                            kb=kb, src=RSS[ch]["url"] if tier == "rss" and ch in RSS else ch, src_ts=p["t"].timestamp())
                            ledger.save()
                        except Exception as e:  # noqa: BLE001
                            print("::warning title=confirm add::", type(e).__name__)
                    if crit:  # المرحلة 2: إثراء المنشور نفسه بعد ~45 ث (مرة واحدة)
                        EN.add({"mid": r["result"]["message_id"], "sent_at": time.time(), "src_ts": p["t"].timestamp(), "ch": ch, "first": first,
                                "text": p["text"], "head": head, "loud": bool(loud), "src": src_name, "credit": credit, "when": p["t"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "photo": photo, "photo_future": photo_fut, "img": p.get("img"), "kb": kb, "tags": tags, "hold": hold, "photo_hold": photo_hold,
                                "official": bool(oname), "ref": RSS[ch]["url"] if tier == "rss" and ch in RSS else ch})
                    print(f"::notice title=fastlane posted::{ch}/{p['id']} بعد {age:.1f} د من نشر المصدر — {head[:80]}")
        RECENT[:] = [x for x in RECENT if x["ts"] >= time.time() - 1800]
        try:
            stats["enriched"] = stats.get("enriched", 0) + EN.tick(RECENT, ledger, T.api, token, chat_id)
        except Exception as e:  # noqa: BLE001
            print("::warning title=enrich::", type(e).__name__, str(e)[:80])
        if stats["loops"] % 10 == 0:
            stats["lat"] = FB.LAT.summary()  # «الرصد ← الإرسال» بالثواني: fast (مرحلتان) وnormal وradar، وprep = الخطوات المؤجلة
            stats["fastbreak"] = dict(FB.STATUS, pending=len(EN.jobs))
            from tools import confirm as _CF
            try:
                from tools import web_push as _WP
                stats["push"] = _WP.status()
            except Exception:  # noqa: BLE001
                pass
            try:
                stats["radars"] = SR.status() if SR else None  # حالة الرادارات (منفصلة عن errors: أخطاء جلب القنوات فقط)
                stats["insider"] = dict(MP.STATUS)  # بوابة المراسل
            except Exception:  # noqa: BLE001
                pass
            gh_put("fast_status.json", {**stats, "confirm_log": _CF.LOG[-10:], "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
        if time.time() - LAST_DEC[0] >= 300 and DECISIONS:  # سجل القرارات كل ~5 دقائق
            LAST_DEC[0] = time.time()
            import threading as _th  # الرفع بالخلفية: لا يوقف حلقة الإرسال (السجل أكبر الآن)
            _snap = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "n": len(DECISIONS), "items": list(DECISIONS)}
            _th.Thread(target=gh_put, args=("fast_decisions.json", _snap), daemon=True).start()
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps({"last": last}, ensure_ascii=False), encoding="utf-8")
        # تهدئة تلقائية إذا كثرت أخطاء الجلب (حماية من حدود الطلبات)
        err_rate = sum(1 for _, r in results if r is None) / max(1, len(results))
        step = CFG.get("hot_every_sec", 8) * (3 if err_rate > 0.3 else 1)
        UL.WAKE.wait(max(2, step - (time.time() - t0)))  # يستيقظ فوراً إذا وصل منشور لحظي
    if DECISIONS:
        gh_put("fast_decisions.json", {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "n": len(DECISIONS), "items": DECISIONS})
    print(f"::notice title=fastlane::{json.dumps(stats, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
