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
print("selftest ok")
