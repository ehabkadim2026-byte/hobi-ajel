"""تقرير أسبوعي بالمصادر المتوقفة (آخر جمع ناجح > 48 ساعة أو لم يُجمع أبداً) من pwa/health.json — يقرأ فقط.
لا يحذف ولا يعطّل: الإيقاف المؤقت آلي بقاطع الدارة في marsad/cli.py (3 إخفاقات ← كل 10 جولات، 6 ← 40، 10 ← 160)،
والإيقاف اليدوي بإضافة الرابط لـ disabled في config/overrides.json. الاستخدام:
  python3 tools/stale_sources.py [health.json] > docs/stale_sources.md"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _dt(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _collectable():
    """ما يمر بفلتر gate_sources فقط: بالسجل وغير مستبعد (المعلومة/صابرين بالقاعدة لكنها لا تُجمع عمداً)."""
    sys.path.insert(0, str(ROOT))
    from marsad.cli import EXCLUDED_SRC
    cfg = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))["sources"]
    return {s["id"] for s in cfg if not EXCLUDED_SRC.search(f"{s.get('name') or ''} " + ("" if "news.google.com" in (s.get("url") or s["id"]) else f"{s['id']} {s.get('url') or ''}"))}


def stale(rows, now=None, hours=48):
    now = now or datetime.now(timezone.utc)
    cut = now - timedelta(hours=hours)
    ok = _collectable()
    out = []
    for r in rows:
        if not r.get("enabled", True) or r["id"] not in ok:
            continue
        d = _dt(r.get("last_success"))
        if d is None or d < cut:
            out.append(r)
    return out


def breaker(f):
    f = f or 0
    return "معزول (كل 160 جولة)" if f >= 10 else "معزول (كل 40 جولة)" if f >= 6 else "معزول (كل 10 جولات)" if f >= 3 else "—"


def report(rows, now=None):
    now = now or datetime.now(timezone.utc)
    st = stale(rows, now)
    bgd = (now + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
    never = [r for r in st if not r.get("last_success")]
    fail = [r for r in st if r.get("failures")]
    L = [f"# المصادر المتوقفة — {bgd} بغداد", "",
         f"من {len(rows)} مصدراً بلوحة الصحة: {len(st)} بلا جمع ناجح منذ 48 ساعة "
         f"({len(never)} لم يُجمع أبداً، {len(fail)} بإخفاقات متتالية). لا حذف: القاطع الآلي يعزلها مؤقتاً ويعيد تجربتها.", "",
         "| المصدر | النوع | آخر نجاح | آخر محاولة | إخفاقات | العزل | الخطأ |", "|---|---|---|---|---|---|---|"]
    for r in sorted(st, key=lambda r: (-(r.get("failures") or 0), r.get("type") or "", r.get("name") or "")):
        L.append(f"| [{(r.get('name') or r['id'])[:60]}]({r.get('url') or ''}) | {r.get('type') or ''} | {(r.get('last_success') or 'أبداً')[:16]} "
                 f"| {(r.get('last_attempt') or '—')[:16]} | {r.get('failures') or 0} | {breaker(r.get('failures'))} | {(r.get('error') or '')[:60]} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    p = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "pwa" / "health.json"
    sys.stdout.write(report(json.loads(p.read_text(encoding="utf-8"))))
