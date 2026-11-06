"""أرشيف صور مرخّصة حسب الموضوع — آخر خيار قبل خلفية الشعار (إيهاب 06/11: كل خبر بصورة مرتبة).

assets/archive/<موضوع>/*.jpg — صور ملك القناة أو ملكية عامة/CC0 فقط (لا تحتاج نسبة).
assets/archive/credits.json يحفظ مصدر كل صورة وترخيصها.
fetch: python -m tools.archive_photo fetch — يجلب صوراً بترخيص ملكية عامة/CC0 من ويكيميديا كومنز لكل موضوع.
"""
import hashlib
import json
import random
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCH = ROOT / "assets" / "archive"

# الموضوع ← كلمات العنوان (الأدق أولاً)
TOPICS = [
    ("rain", r"أمطار|امطار|سيول|فيضان|عاصفة|عواصف|الأنواء|الانواء|طقس|غبار|ثلوج"),
    ("oil", r"نفط|النفط|برميل|مصفى|مصافي|سومو|صادرات|الغاز|حقل"),
    ("electricity", r"كهرباء|الكهرباء|ميغاواط|محطة توليد|التيار"),
    ("parliament", r"مجلس النواب|البرلمان|النائب|نائب عن|جلسة|اللجنة النيابية|النيابية"),
    ("security", r"الأمن|القوات|الجيش|الشرطة|اعتقال|القبض|عبوة|انفجار|مسيرة|مسيّرة|صاروخ|الحشد|مكافحة|خلية الإعلام"),
    ("economy", r"الدولار|الدينار|البنك المركزي|الرواتب|الموازنة|المالية|الاقتصاد|الأسعار|البورصة"),
    ("education", r"التربية|التعليم|المدارس|الطلبة|الامتحانات|الجامعة|الدوام"),
    ("health", r"الصحة|مستشفى|المستشفى|طبي|وباء|إصابات بـ|لقاح"),
    ("sport", r"المنتخب|الدوري|مباراة|كأس|اللاعب|نادي|أسود الرافدين|الفيفا"),
    ("water", r"المياه|دجلة|الفرات|السدود|الجفاف|الري"),
    ("basra", r"البصرة"), ("erbil", r"أربيل|اربيل|الإقليم|كردستان"), ("mosul", r"الموصل|نينوى"),
    ("baghdad", r"بغداد|العراق|الحكومة|رئيس الوزراء|مجلس الوزراء"),
]
QUERIES = {  # بحث كومنز (إنكليزي)
    "rain": "rain Iraq", "oil": "oil refinery Iraq", "electricity": "power station Iraq", "parliament": "Council of Representatives of Iraq",
    "security": "Iraqi police", "economy": "Iraqi dinar", "education": "school Iraq", "health": "hospital Baghdad",
    "sport": "Iraq national football team", "water": "Tigris river", "basra": "Basra", "erbil": "Erbil citadel", "mosul": "Mosul",
    "baghdad": "Baghdad skyline",
}
OK_LIC = re.compile(r"public domain|^pd|cc0|cc-zero", re.I)


def topic(title):
    for name, rx in TOPICS:
        if re.search(rx, title or ""):
            return name
    return None


def pick(title):
    """صورة أرشيفية للموضوع أو None. ثابتة للعنوان نفسه (لا تتغير الصورة بين التعديلات)."""
    t = topic(title)
    if not t:
        return None
    files = sorted((ARCH / t).glob("*.jpg"))
    if not files:
        return None
    i = int(hashlib.md5((title or "").encode()).hexdigest(), 16) % len(files)
    return files[i].read_bytes()


def _get(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "AKA-archive/1.0 (news photo archive)"}), timeout=30).read())


def fetch(per_topic=6):
    """يجلب صوراً بترخيص ملكية عامة/CC0 فقط من ويكيميديا كومنز؛ يحفظ المصدر بالـcredits."""
    from PIL import Image
    import io
    credits = json.loads((ARCH / "credits.json").read_text(encoding="utf-8")) if (ARCH / "credits.json").exists() else {}
    for t, q in QUERIES.items():
        d = ARCH / t
        d.mkdir(parents=True, exist_ok=True)
        have = len(list(d.glob("*.jpg")))
        if have >= per_topic:
            continue
        api = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=search&gsrnamespace=6&gsrlimit=40&gsrsearch="
               + urllib.parse.quote(q + " filetype:bitmap") + "&prop=imageinfo&iiprop=url|extmetadata|size&iiurlwidth=1600")
        try:
            pages = (_get(api).get("query") or {}).get("pages", {}).values()
        except Exception as e:  # noqa: BLE001
            print(f"::warning title=archive::{t} {type(e).__name__}")
            continue
        n = have
        for pg in pages:
            if n >= per_topic:
                break
            ii = (pg.get("imageinfo") or [{}])[0]
            meta = ii.get("extmetadata") or {}
            lic = (meta.get("LicenseShortName") or {}).get("value", "")
            if not OK_LIC.search(lic) or (ii.get("width") or 0) < 1000:
                continue
            try:
                raw = urllib.request.urlopen(urllib.request.Request(ii.get("thumburl") or ii["url"], headers={"User-Agent": "AKA-archive/1.0"}), timeout=30).read()
                im = Image.open(io.BytesIO(raw)).convert("RGB")
                if im.width < im.height:
                    continue
                im.thumbnail((1600, 1600))
                b = io.BytesIO()
                im.save(b, "JPEG", quality=88)
            except Exception:  # noqa: BLE001
                continue
            name = f"{t}_{hashlib.md5(pg['title'].encode()).hexdigest()[:10]}.jpg"
            (d / name).write_bytes(b.getvalue())
            credits[f"{t}/{name}"] = {"file": pg["title"], "license": lic, "page": ii.get("descriptionurl")}
            n += 1
        print(f"::notice title=archive::{t}: {n} صورة")
    (ARCH / "credits.json").write_text(json.dumps(credits, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1:] == ["fetch"]:
        fetch()
    else:
        print(topic(" ".join(sys.argv[1:])))
