"""اختبارات موثوقية المصادر و«☑️ تطابق لدى مصدر موثوق» وبوابة «ضعيفة» وبوابة الإساءة (بلا شبكة: قاعدة SQLite مؤقتة وواجهة تلغرام وهمية).
تشغيل: python3 -m tools.test_reliability
"""
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import confirm as CF  # noqa: E402
from tools import reliability as R  # noqa: E402
from tools import tg_push as T  # noqa: E402
from tools.test_confirm import Store, Api, KB  # noqa: E402

# قاعدة المالك: لا ننقل ما يسيء للعراق أو العراقيين أو أي مكوّن عراقي
OFFENSIVE = [
    "الروافض يحتفلون في كربلاء وسط إجراءات أمنية",
    "النواصب يهاجمون مقرات الحشد في الأنبار",
    "العراقيين حرامية بالفطرة ولا أمل في الإصلاح",
    "الأكراد خونة ويبيعون النفط لإسرائيل",
    "صفويون يسيطرون على مفاصل الدولة في بغداد",
    "العراق مزبلة لا تصلح للعيش بحسب ناشط",
    "إعلامي خليجي يسخر من العراقيين بعد خسارة المنتخب",
    "دعوات على مواقع التواصل: اذبحوا الشيعة أينما وجدتموهم",
    "فضيحة مدوية للنائب محمد الفلاني في صفقة الأراضي",
    "تورط الوزير خالد العبيدي بسرقة أموال المحافظة",
    "المسيحيون كفار ويجب طردهم من سهل نينوى",
    "مهزلة البرلمان العراقي تتواصل بجلسة جديدة",
    "شروكية الجنوب يغلقون الطرق في الناصرية",
    "عبدة الشيطان يعودون إلى سنجار بعد سنوات",
]
FACTUAL_NEGATIVE = [
    "مقتل 5 أشخاص بانفجار عبوة ناسفة في ديالى",
    "هيئة النزاهة تضبط متهمين بالاختلاس في دائرة عقارات الدولة ببغداد",
    "النزاهة: الحبس الشديد لمدير عام سابق بتهمة الإضرار بالمال العام",
    "القبض على 3 دواعش في كركوك بعملية استخبارية",
    "الأمم المتحدة تطالب بمحاسبة مرتكبي الإبادة الجماعية بحق الإيزيديين",
    "حملة لمكافحة الكلاب السائبة في البصرة بعد تسجيل إصابات",
    "أزمة كهرباء خانقة في بغداد مع انقطاع التيار لساعات طويلة",
    "محكمة جنايات الكرخ تحكم بالسجن على نائب سابق بتهمة الرشوة",
    "هجوم بطائرة مسيرة يستهدف حقل كورمور الغازي في السليمانية",
    "تظاهرات في الناصرية احتجاجاً على تردي الخدمات وقطع طرق رئيسية",
    "خلية الإعلام الأمني: مقتل إرهابيين اثنين بضربة جوية في وادي حوران",
    "اعتقال موظف في مصرف حكومي بتهمة اختلاس 3 مليارات دينار",
    "البرلمان يستجوب وزير الكهرباء بشأن انقطاع التيار في المحافظات",
    "فضيحة فساد في وزارة الصحة: هيئة النزاهة تحيل مسؤولين إلى القضاء",
]

TRUST = {"updated_utc": "2026-11-04T00:00:00Z", "sources": {
    "telegram:t.me/dijlahtvchannel": {"name": "دجلة الفضائية — telegram", "url": "https://t.me/dijlahtvchannel", "net": "دجله", "tier": "موثوقة"},
    "rss:dijlah.tv/rss": {"name": "دجلة الفضائية — RSS", "url": "https://dijlah.tv/rss", "net": "دجله", "tier": "موثوقة"},
    "telegram:t.me/alsumariatviraq": {"name": "السومرية نيوز — telegram", "url": "https://t.me/alsumariatviraq", "net": "السومريه", "tier": "عادية"},
    "telegram:t.me/weak1": {"name": "قناة ضعيفة 1", "url": "https://t.me/weak1", "net": "ضعيفه1", "tier": "ضعيفة"},
    "telegram:t.me/weak2": {"name": "قناة ضعيفة 2", "url": "https://t.me/weak2", "net": "ضعيفه2", "tier": "ضعيفة"}}}
CAP = ("<b>مقتل 5 أشخاص بانفجار عبوة ناسفة في قضاء الطارمية شمالي بغداد</b>\n\n📌 المصدر: السومرية نيوز\n"
       "⏳ التحقق: غير مؤكد بعد — مصدر واحد\n\nزورونا على الرابط للأخبار العاجلة 👇\nhttps://t.me/akamedia_iq")
X = "مقتل 5 أشخاص بانفجار عبوة ناسفة في قضاء الطارمية شمالي بغداد"
Y = "انفجار عبوة ناسفة يقتل 5 أشخاص في الطارمية شمال العاصمة بغداد"


def _offensive():
    for t in OFFENSIVE:
        assert T.offensive(t) and T.low_value(t), t
    for t in FACTUAL_NEGATIVE:
        assert not T.offensive(t), ("حُجب خبر واقعي", t)
        assert not T.low_value(t), ("low_value حجب خبراً واقعياً", t)
    from tools import fastlane as F
    assert F.bad_title_reason(OFFENSIVE[0]) == "offensive"
    return len(OFFENSIVE), len(FACTUAL_NEGATIVE)


def _ledger(store=None):
    store = store or Store()
    return store, CF.Ledger("main", store.get, store.put)


def _trusted():
    R.load(data=TRUST)
    now = time.time()
    T.build_idf([X, Y, "وزير النفط يبحث مع شركة بريطانية", "مجلس الوزراء يعقد جلسته"])
    assert R.tier_of("dijlahtvchannel") == "موثوقة" and R.tier_of("https://t.me/dijlahtvchannel/55") == "موثوقة"
    assert R.net_of("https://dijlah.tv/news/1") == R.net_of("dijlahtvchannel") == "دجله"
    # 1) مصدر موثوق مستقل بأرقام متسقة ← سطر واحد بعد سطر التحقق، والأزرار تبقى
    st, led = _ledger()
    led.add_post(201, T.title_sig(X), CAP, "photo", False, title=X, kb=KB, src="alsumariatviraq", ts=now - 900, src_ts=now - 1000)
    api = Api()
    assert CF.check_trusted(led, api, "T", "@c", "دجلة الفضائية", Y, now - 600, "dijlahtvchannel", now=now) == 1
    cap = api.calls[0][1]["caption"]
    lines = cap.split("\n")
    i = next(k for k, x in enumerate(lines) if x.startswith("⏳ التحقق"))
    assert lines[i + 1] == "☑️ تطابق لدى مصدر موثوق: دجلة الفضائية" and api.calls[0][1]["reply_markup"] == KB and CF.html_ok(cap)
    # 2) مرة واحدة لكل منشور (حتى بعد إعادة التحميل)
    led2 = CF.Ledger("main", st.get, st.put)
    assert CF.check_trusted(led2, api, "T", "@c", "دجلة الفضائية", Y, now - 500, "dijlah.tv", now=now) == 0 and len(api.calls) == 1
    # 3) «✅ أكدته» بعده ما زال ممكناً، ويُبنى على التعليق الأحدث (لا يمحو سطر التطابق)
    api2 = Api()
    assert CF.check(led2, api2, "T", "@c", "خلية الإعلام الأمني", "خلية الإعلام الأمني: مقتل 5 أشخاص بانفجار عبوة ناسفة في قضاء الطارمية", now - 100, now=now) == 1
    c2 = api2.calls[0][1]["caption"]
    assert "✅ أكدته: خلية الإعلام الأمني" in c2 and c2.count("☑️ تطابق") == 1, c2
    # 4) رفض: الشبكة نفسها / نسخ نص مصدرنا / نفي / رقم مختلف / مصدر غير موثوق / منشور أكدته جهة رسمية أولاً
    cases = [("دجلة الفضائية", Y, now - 600, "dijlahtvchannel", "dijlah.tv/rss"),                 # موقع دجلة وقناتها = شبكة واحدة
             ("دجلة الفضائية", X + " .", now - 900, "dijlahtvchannel", "alsumariatviraq"),          # نص شبه متطابق بعد مصدرنا
             ("دجلة الفضائية", "الداخلية تنفي مقتل 5 أشخاص بانفجار عبوة ناسفة في الطارمية", now - 600, "dijlahtvchannel", "alsumariatviraq"),
             ("دجلة الفضائية", "انفجار عبوة ناسفة يقتل 7 أشخاص في الطارمية شمال العاصمة بغداد", now - 600, "dijlahtvchannel", "alsumariatviraq"),
             ("السومرية", Y, now - 600, "alsumariatviraq", "weak1")]
    for name, title, ts, ref, xsrc in cases:
        st, led = _ledger()
        led.add_post(202, T.title_sig(X), CAP, "photo", False, title=X, kb=KB, src=xsrc, ts=now - 900, src_ts=now - 1000)
        api = Api()
        assert CF.check_trusted(led, api, "T", "@c", name, title, ts, ref, now=now) == 0 and not api.calls, (name, title, ref, xsrc)
    st, led = _ledger()
    led.add_post(203, T.title_sig(X), CAP, "photo", False, title=X, src="alsumariatviraq", ts=now - 900)
    assert CF.check(led, Api(), "T", "@c", "خلية الإعلام الأمني", "خلية الإعلام الأمني: مقتل 5 أشخاص بانفجار عبوة ناسفة في قضاء الطارمية", now - 300, now=now) == 1
    api = Api()
    assert CF.check_trusted(led, api, "T", "@c", "دجلة الفضائية", Y, now - 200, "dijlahtvchannel", now=now) == 0 and not api.calls
    # 5) الجولة الرئيسية: confirm_round يقرأ عنوان المصدر الموثوق من الخط الزمني (t + sid)
    st, led = _ledger()
    led.add_post(204, T.title_sig(X), CAP, "photo", False, title=X, nid="c_x", src="https://t.me/alsumariatviraq/9", ts=now - 900)
    iso = datetime.fromtimestamp(now - 300, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    news = [{"id": "c_x", "title": X, "timeline": [{"source": "السومرية نيوز — telegram", "url": "https://t.me/alsumariatviraq/9", "pub": iso, "t": X},
                                                   {"source": "دجلة الفضائية — telegram", "url": "https://t.me/dijlahtvchannel/77", "pub": iso,
                                                    "sid": "telegram:t.me/dijlahtvchannel", "t": Y}]}]
    old = T.PWA
    try:
        T.PWA = Path("/nonexistent-trust")  # confirm_round يحمّل الملف؛ هنا نُبقي الجدول الاختباري
        R.load(data=TRUST)
        R._TRUST["_key"] = str(T.PWA / "source_trust.json")
        api = Api()
        assert T.confirm_round("T", "@c", news, datetime.fromtimestamp(now, timezone.utc), api_fn=api, ledger=led) == 1
        assert "☑️ تطابق لدى مصدر موثوق: دجلة الفضائية" in api.calls[0][1]["caption"]
    finally:
        T.PWA = old
    R.load(data=TRUST)
    # 6) بوابة «ضعيفة»: كل المصادر ضعيفة = لا نشر؛ مصدر غير ضعيف أو جهة رسمية = معزَّز
    assert R.weak_only([("telegram:t.me/weak1", "قناة ضعيفة 1", "https://t.me/weak1/1"), (None, "قناة ضعيفة 2", "https://t.me/weak2/3")])
    assert not R.weak_only([("telegram:t.me/weak1", "", "https://t.me/weak1/1"), ("telegram:t.me/alsumariatviraq", "", "https://t.me/alsumariatviraq/2")])
    assert not R.weak_only([("telegram:t.me/weak1", "", "https://t.me/weak1/1"), (None, "وزارة الخارجية", "https://t.me/iqmofa/5")])
    assert not R.weak_only([("telegram:t.me/unknown", "", "https://t.me/unknown/1")]) and not R.weak_only([])
    R.load(data={})


def _compute():
    """قاعدة مصغرة: مصدر A يسبق ثم تؤكده الوزارة؛ B ينقل بعد الوزارة؛ C يُنفى؛ D رقم مختلف؛ «نفتح/تنفيذ» ليسا نفياً."""
    con = sqlite3.connect(":memory:")
    con.executescript("CREATE TABLE sources(id TEXT PRIMARY KEY, name TEXT, url TEXT, category TEXT);"
                      "CREATE TABLE items(source_id TEXT, published_utc TEXT, collected_utc TEXT, time_precision TEXT, title TEXT, cluster_id TEXT);")
    con.executemany("INSERT INTO sources VALUES(?,?,?,?)", [
        ("telegram:t.me/srcA", "مصدر أ", "https://t.me/srcA", "قنوات تلغرام"), ("telegram:t.me/srcB", "مصدر ب", "https://t.me/srcB", "قنوات تلغرام"),
        ("telegram:t.me/moiiraqi", "وزارة الداخلية العراقية — telegram", "https://t.me/moiiraqi", "مصادر رسمية وأولية")])
    now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
    iso = lambda m: (now - timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    rows = [
        ("telegram:t.me/srcA", iso(300), iso(299), "exact", "القبض على 4 متهمين بسرقة مصرف في البصرة", "k1"),
        ("telegram:t.me/moiiraqi", iso(280), iso(279), "exact", "الداخلية: القبض على 4 متهمين بسرقة مصرف في محافظة البصرة", "k1"),
        ("telegram:t.me/srcB", iso(270), iso(269), "exact", "الداخلية العراقية تعلن القبض على 4 متهمين بسرقة مصرف في البصرة", "k1"),
        ("telegram:t.me/srcB", iso(200), iso(199), "exact", "اغتيال ضابط كبير في الشرطة بهجوم مسلح وسط بغداد", "k2"),
        ("telegram:t.me/moiiraqi", iso(150), iso(149), "exact", "الداخلية تنفي اغتيال ضابط كبير في الشرطة بهجوم مسلح وسط بغداد", "k2"),
        ("telegram:t.me/srcA", iso(100), iso(99), "exact", "إصابة 12 منتسباً بانقلاب عجلة عسكرية في طريق الموصل", "k3"),
        ("telegram:t.me/moiiraqi", iso(90), iso(89), "exact", "إصابة 3 منتسبين بانقلاب عجلة عسكرية في طريق الموصل", "k3"),
        ("telegram:t.me/srcA", iso(60), iso(59), "exact", "وزير الداخلية يوجه بتنفيذ خطة أمنية جديدة في بغداد", "k4"),
        ("telegram:t.me/moiiraqi", iso(50), iso(49), "exact", "بعد ساعة.. نفتح باب تنفيذ الخطة الأمنية الجديدة في بغداد بتوجيه وزير الداخلية", "k4"),
        ("telegram:t.me/srcB", iso(800), iso(40), "exact", "وزير الداخلية يوجه بتنفيذ خطة أمنية جديدة في بغداد", "k4"),  # وقت نشر غير موثوق (12 ساعة)
    ]
    con.executemany("INSERT INTO items VALUES(?,?,?,?,?,?)", rows)
    assert not R.DENIAL_RX.search("بعد ساعة.. نفتح باب التقديم") and not R.DENIAL_RX.search("تنفيذاً لتوجيهات")
    assert not CF.DENY_RX.search("بعد ساعة… نفتح التقديم على الوجبة الثالثة") and CF.DENY_RX.search("الداخلية تنفي اغتيال ضابط")
    assert R.numbers_conflict("إصابة 12 منتسباً", "إصابة 3 منتسبين") and not R.numbers_conflict("القبض على 25 متهماً", "٢٥ متهماً في قبضة الأمن")
    assert not R.numbers_conflict("14 مليون دولار", "21 ملياراً") and R.numbers_conflict("هزة بقوة 3.4 درجات", "بقوة 3.8 درجة")
    st, vol, srcs, offc = R.compute(con, now)
    assert offc["telegram:t.me/moiiraqi"] and not offc["telegram:t.me/srcA"]
    a, b = st["telegram:t.me/srcA"], st["telegram:t.me/srcB"]
    assert a["conf"] == 2 and a["orig"] == 3 and a["den"] == 0 and a["mism"] == 1 and a["num_n"] == 2, a
    assert b["relay"] == 2 and b["den"] == 1 and b["orig"] == 1, b  # k1 نقل بعد الوزارة؛ k4 بوقت الجمع بعد الوزارة = نقل
    assert b["multi"] == 2, b  # بند k4 (وقت غير موثوق) خارج السبق
    assert R.net_key("telegram:t.me/x", "t.me — telegram", "https://t.me/x") == "x"
    assert R.net_key("rss:alsumaria.tv", "السومرية نيوز — RSS", "https://www.alsumaria.tv/Rss") == R.net_key("telegram:t.me/alsumariatviraq", "السومرية", "")


def run():
    n_off, n_ok = _offensive()
    _trusted()
    _compute()
    print(f"test_reliability ok (إساءة {n_off} مرفوضة، {n_ok} خبراً سلبياً واقعياً يمر)")


if __name__ == "__main__":
    run()
