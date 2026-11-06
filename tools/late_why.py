"""لماذا تأخرنا/تعادلنا؟ لكل صف «تأخرنا» و«متقارب» في لوحة السبق: أقدم ناشر في الحدث (من كل ما نجمعه)، فارقه عن منشورنا، وهل هو في المسار السريع."""
import json, re, sqlite3, sys, urllib.request
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.first_sources import handles  # noqa: E402
fast, fast_rss, _ = handles()
o = json.loads(urllib.request.urlopen("https://ehabkadim2026-byte.github.io/hobi-ajel/scoop.json", timeout=20).read().decode())
db = sqlite3.connect(ROOT / "data" / "marsad.db"); db.row_factory = sqlite3.Row
def dt(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))
agg = {}
for r in o["rows"]:
    if r.get("status") not in ("تأخرنا", "متقارب") or not r.get("id"):
        continue
    it = db.execute("SELECT source_id, source_name, platform, url, MIN(COALESCE(published_utc, collected_utc)) t, collected_utc c FROM items WHERE cluster_id=?", (r["id"],)).fetchone()
    if not it or not it["t"]:
        continue
    sid = it["source_id"] or ""
    key = re.sub(r"^(?:https?://)?(?:t\.me/(?:s/)?)?", "", sid.split(":", 1)[1] if ":" in sid else sid).strip("/").lower()
    dom = re.sub(r"^https?://(www\.)?", "", it["url"] or "").split("/")[0].lower()
    inf = key in fast or (it["platform"] == "rss" and dom in fast_rss)
    lag = (dt(r["our"]) - dt(it["t"])).total_seconds() / 60
    det = (dt(it["c"]) - dt(it["t"])).total_seconds() / 60 if it["c"] else None
    print(f"::notice title={r['status']}::{lag:+.0f}د بعد {it['source_name']} [{ 'سريع' if inf else 'خارج السريع'} | {it['platform']}] رُصد بعد {det if det is None else round(det)}د | منافس {r.get('comp')} {r.get('delta_min')}د | {r['title'][:70]}")
    a = agg.setdefault(f"{it['source_name']} ({'سريع' if inf else 'خارج'}/{it['platform']})", [0, 0])
    a[0] += 1; a[1] += lag
for k, (n, s) in sorted(agg.items(), key=lambda kv: -kv[1][0])[:15]:
    print(f"::notice title=origin::{n} مرة، متوسط تأخرنا {s/n:.0f}د — {k}")
