"""قنوات الأقسام (إيهاب 07/11: «نقسم قنوات تلغرام: سياسي، اقتصادي، ثقافي، رياضي — كل قناة وأخبارها»).

القناة الرئيسية تبقى تنشر كل شيء. كل منشور ناجح يُنسخ (copyMessage) لقناة قسمه بعد اكتمال إثرائه
(تأخير ~75 ث حتى تنتقل الصورة والعنوان المصحح)، فالقسم يأخذ النسخة النهائية لا المسودة.

التفعيل: config/topic_channels.json ← {"politics": "@aka_politics", ...}. معرّف فارغ = القسم معطل.
شرط تلغرام: البوت مشرف بصلاحية النشر في قناة القسم. لا ينسخ شيئاً بلا تفعيل صريح.
"""
import json
import re
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG_PATH = ROOT / "config" / "topic_channels.json"

# القسم ← أنواع aka_card + كلمات إضافية
ROUTES = {
    "sport": r"المنتخب|الدوري|مباراة|كأس|اللاعب|نادي|أسود الرافدين|الفيفا|الاتحاد العراقي لكرة|بطولة|هدف|ملعب|الأولمبية",
    "economy": r"الدولار|الدينار|البنك المركزي|الرواتب|رواتب|الموازنة|وزارة المالية|النفط|برميل|سومو|الأسعار|سعر|البورصة|الذهب|التجارة|المصرف|مصرف|سلف|الاستثمار|الكمارك|الضرائب|الكهرباء",
    "culture": r"ثقاف|مهرجان|معرض الكتاب|فنان|الفنان|مسرح|فيلم|سينما|رواية|شاعر|الشعر|متحف|آثار|الآثار|تراث|اليونسكو|موسيقى|أغنية|دراما|مسلسل",
    "politics": r"مجلس النواب|البرلمان|النائب|رئيس الوزراء|مجلس الوزراء|الحكومة|السوداني|الوزير|وزير|الكتل|الإطار التنسيقي|الانتخابات|المفوضية|رئيس الجمهورية|الخارجية|السفير|حزب|تحالف|ائتلاف|المحافظ|مجلس المحافظة|قرار|استجواب|تصويت",
}
ORDER = ["sport", "economy", "culture", "politics"]  # الأدق أولاً: «وزير الشباب يحضر مباراة» رياضة لا سياسة


def load():
    try:
        return {k: v for k, v in json.loads(CFG_PATH.read_text(encoding="utf-8")).items() if not k.startswith("_") and v}
    except Exception:  # noqa: BLE001
        return {}


def route(title):
    """قسم الخبر أو None (الأمني والعام يبقيان بالرئيسية فقط)."""
    t = title or ""
    for k in ORDER:
        if re.search(ROUTES[k], t):
            return k
    return None


def mirror(api, token, from_chat, mid, title, delay=75):
    """ينسخ المنشور لقناة قسمه بعد delay ثانية (بخيط خلفي — لا يؤخر النشر الرئيسي). يرجع القسم أو None."""
    chans = load()
    sec = route(title)
    if not chans or not sec or sec not in chans or not mid:
        return None

    def go():
        try:
            api(token, "copyMessage", chat_id=chans[sec], from_chat_id=from_chat, message_id=str(mid), disable_notification="true")
        except Exception as e:  # noqa: BLE001
            print(f"::warning title=topic_channels::{sec} {type(e).__name__}")

    t = threading.Timer(delay, go)
    t.daemon = True
    t.start()
    return sec
