"""فحص سريع قبل كل commit: يشغّل مسارات التحرير والنشر الحساسة بنموذج لغوي وهمي، حتى لا يمر خطأ مثل دالة محذوفة."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tools.editorial as E  # noqa: E402

E.gemini = lambda prompt, **k: "أعلنت وزارة الداخلية القبض على عصابة تضم 5 متهمين في بغداد"
E._EXHAUSTED.clear()
import os  # noqa: E402
os.environ.setdefault("GEMINI_API_KEY", "selftest")
out = E.edit_headline("عاجل | شاهد.. الداخلية تعلن القبض على عصابة تضم 5 متهمين ببغداد!!", context="نص الخبر")
assert out and "5" in out, out
assert E._safe("نرفض التدخل في شؤون العراق", "رفض التدخل في شؤون العراق")
assert E.pick_best(["#عاجل", "الداخلية تعلن القبض على عصابة تضم 5 متهمين في بغداد"])
from tools import tg_push as T  # noqa: E402
T.build_idf(["البنك المركزي العراقي شحنة دولار", "وزير النفط يبحث"])
assert T.same_story(T.title_sig("البنك المركزي العراقي: شحنة جديدة من الدولار"),
                    {"w": sorted(T.title_sig("المركزي العراقي: شحنات دولار في الطريق")[0]), "d": []}) in (True, False)
assert T.iraq_title("البنك المركزي العراقي") and not T.iraq_title("روسيا توسع ضرباتها على أوكرانيا")
T.fmt({"title": "وزارة الداخلية تعلن القبض على عصابة", "level": "مهم", "sources": [{"name": "x", "url": "https://ina.iq/1"}]})
from tools import tg_card as C  # noqa: E402
assert len(C.card_a(None, "البنك المركزي العراقي: شحنة جديدة من الدولار", True, "2026-11-01T10:00:00Z")) > 10000
from tools import test_confirm  # noqa: E402
test_confirm.run()  # «✅ أكدته» وسجل قرارات المسار السريع بواجهة تلغرام وهمية
from tools import test_auto_tune  # noqa: E402
test_auto_tune.run()  # الضبط الذاتي اليومي للمسار السريع (ترقية/تنزيل/مرشحون) ودمجه بالذاكرة
# تدقيق 14:11 04/11: عنوان «منصب + فعل غير مدرج» ليس مبتوراً، وتحليل/رسالة مفتوحة ليست خبراً، والناشر المستبعد عبر Google News يُحذف، وخبر دولة بعيدة ليس «عن العراق»
assert not T.incomplete("وزير التربية يرفض مقترحاً نيابياً لفتح التقديم بصفة محاضر مجاني") and T.incomplete("رئيس هيئة النزاهة الاتحادية")
assert T.low_value("العراق لا يواجه تداعيات اقتصادية محتملة فحسب، بل يواجه مخاطر أمنية") and T.low_value("إلى السيد وهب: بما أنك الآن في الخطوط الجوية")
assert not T.verify_line({"status": "مؤكد", "sources": [{"name": "1News - وان نيوز — telegram"}]}).startswith("✅")
from marsad.collect import _google_news, _gn_outlet  # noqa: E402
assert [i["source_name"] for i in _google_news([{"title": "خبر عن بغداد - المعلومة"}, {"title": "خبر آخر - شفق نيوز"}])] == ["شفق نيوز (عبر Google News)"]
assert _gn_outlet("درەو") == "موقع إخباري" and _gn_outlet("PUKmedia یەکێتیی نیشتمانیی") == "PUKmedia"
from tools.export_pwa import about_iraq_title  # noqa: E402
assert not about_iraq_title("ترامب: تهانينا للديمقراطيين", True) and about_iraq_title("محافظ البصرة يفتتح مشروعاً", True)
from tools import fastlane as FL  # noqa: E402
from datetime import datetime as _dt, timezone as _tz  # noqa: E402
_now = _dt.now(_tz.utc)
_st = [{"w": sorted(T.title_sig("تأجيل محاكمة 7 متهمين فرنسيين من داعش في بغداد")[0]), "d": ["7"], "ts": _now.timestamp() - 3600}]
assert FL.story_old(T.title_sig("تأجيل محاكمة 7 متهمين فرنسيين من داعش في بغداد… تفاصيل"), _st, _now)
assert not FL.story_old(T.title_sig("هجوم مسلح أمام مبنى مديرية بلديات أربيل"), _st, _now)
# تدقيق 18:15 04/11: تكرار بصياغة أخرى، وليس خبراً، وعاجل بلا مضمون عاجل، واسم مصدر «t.me»
_p = [{"title": "مصدر: النزاهة تدقق عقود وزارة النقل والمطارات وتكشف تلاعباً يُشتبه بارتباطه بتمويل جهات مسلحة خارجة عن القانون", "ts": _now.timestamp() - 600}]
assert T.sec_dup("رصد تلاعب في عقود وزارة النقل والمطارات لصالح جهة مسلحة خارجة عن القانون", _p, _now.timestamp())
assert not T.sec_dup("وزير النقل يؤكد مواصلة العمل على استيفاء متطلبات رفع الحظر الأوروبي", _p, _now.timestamp())
assert T.low_value("توضيح إلى متابعين قناة واحد العراق: إدارة القناة توضح أنها لا تمتلك صفحة على تطبيق الـ Tiktok")
assert T.low_value("يحتمل تعطيل الدوام ليوم غد الخميس في بابل بعد المناشدات")
assert not T.low_value("وزير الداخلية يصادق على ترقية أكثر من 1100 موظف مدني ضمن جدول عام 2026")
assert not (T.SEC_RX.search("العراق يواجه لبنان وإيران في بطولة البصرة الرباعية") or T.EVENT_RX.search("العراق يواجه لبنان وإيران في بطولة البصرة الرباعية")
            or T.URGENT_RX.search("العراق يواجه لبنان وإيران في بطولة البصرة الرباعية"))
assert FL.MINOR_RX.search("وزارة الصحة اللبنانية: شهيد ومصاب في غارة إسرائيلية استهدفت دراجة نارية")
from marsad.cli import clean_source_name as _csn  # noqa: E402
assert _csn({"name": "t.me — telegram", "url": "https://t.me/najafmc", "id": "telegram:t.me/najafmc"}) == "@najafmc — telegram"
assert _csn({"name": "رئيس مجلس الوزراء علي فالح الزيدي (القناة الرسمية) — telegram", "url": "https://t.me/x", "id": "x"}) == "رئيس مجلس الوزراء علي فالح الزيدي — telegram"
from tools import test_reliability  # noqa: E402
test_reliability.run()  # موثوقية المصادر، «☑️ تطابق لدى مصدر موثوق»، بوابة «ضعيفة»، بوابة الإساءة
print("selftest ok")
