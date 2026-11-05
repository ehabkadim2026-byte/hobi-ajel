"""نموذج بطاقات للمراجعة: يرسم آخر أخبار حقيقية بالقالب الحالي والجديد ويحفظها في preview/ (لا ينشر شيئاً)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import tg_card  # noqa: E402
from tools.tg_push import src, is_breaking  # noqa: E402
from tools.editorial import clean_headline as headline0  # noqa: E402
headline = lambda n: headline0(n["title"])  # noqa: E731

out = ROOT / "preview"
out.mkdir(exist_ok=True)
news = json.loads((ROOT / "pwa" / "news.json").read_text(encoding="utf-8"))
items = news if isinstance(news, list) else news.get("items", news.get("news", []))
items = [n for n in items if n.get("about_iraq") and n.get("level") in ("عاجل", "مهم")][:60]
done = 0
for n in items:
    _, url = src(n)
    img = tg_card.find_image(url)
    if not img:
        continue
    try:
        ph = tg_card.fetch_jpeg(img)
    except Exception:  # noqa: BLE001
        continue
    h = headline(n)
    name, _ = src(n)
    for st in "ABC":
        (out / f"v5_{done}_{st}.jpg").write_bytes(tg_card.card_news4(ph, h, is_breaking(n) or done == 0, n.get("first_utc"), source=name, style=st))
    print(done, n["title"][:80], "=>", h)
    done += 1
    if done >= 4:
        break
for st in "ABC":
    (out / f"v5_op_{st}.jpg").write_bytes(tg_card.card_news4(None, "تثبيت سقف الإنتاج يمنح الاستقرار المالي ويدعم التخطيط الاقتصادي للعراق", False, items[0].get("first_utc"), tag="رأي", style=st))
