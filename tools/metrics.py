"""لوحة قياس الأداء الحقيقي → pwa/metrics.json

- المصادر: المُسجّلة، العاملة، المتوقفة وأسباب التعطل، الصامتة (تعمل بلا مواد 24 ساعة)، المكررة (نفس الرابط أو نفس المنفذ بمسارين).
- زمن الوصول حسب نوع المصدر (من meta.json).
- التكرار والأخطاء: نسبة النسخ داخل الأحداث، ونسبة محاولات الجلب الفاشلة 24 ساعة.
- عينة مرجعية يومية: 20 خبراً من «أبرز أخبار العراق» في Google News (خلاصة ليست ضمن مصادرنا)،
  ونفحص هل التقطناها من مصادرنا غير Google ومتى. هي عينة مرجعية محددة، لا «نسبة تغطية للإنترنت».
- التخزين وحدود الخدمات المجانية (من storage.json).
"""
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from marsad import core  # noqa: E402
from marsad.textnorm import tokens, iso, now_utc, parse_time  # noqa: E402

PWA = ROOT / "pwa"
STATE = ROOT / "data" / "archive_state.json"
REF_URL = "https://news.google.com/rss/headlines/section/geo/Iraq?hl=ar&gl=IQ&ceid=IQ:ar"
REF_URL2 = "https://news.google.com/rss/search?q=%D8%A7%D9%84%D8%B9%D8%B1%D8%A7%D9%82+when:1d&hl=ar&gl=IQ&ceid=IQ:ar"


def load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def reference_check(con, now):
    """يجلب العينة المرجعية ويطابقها بأرشيف مصادرنا (مع استبعاد مصادر Google News نفسها)."""
    from marsad.collect import http_get, parse_rss, _google_news
    ref = []
    for u in (REF_URL, REF_URL2):
        try:
            xml = http_get(u, timeout=20)
            items = _google_news(parse_rss(xml, {"id": "ref", "name": "ref", "lang": "ar"}))
            ref += items
        except Exception as e:  # noqa: BLE001
            print("::warning title=metrics ref::", type(e).__name__, str(e)[:100])
        if len(ref) >= 20:
            break
    seen, sample = set(), []
    for r in ref:
        k = r["title"][:60]
        if k not in seen and r.get("title"):
            seen.add(k)
            sample.append(r)
    # عينة عادلة: أخبار نُشرت خلال آخر 24 ساعة وبعد بدء أرشيفنا الحالي (لا نحاسب على ما قبل وجود البيانات)
    oldest = con.execute("SELECT MIN(collected_utc) FROM items").fetchone()[0]
    floor = max(now - timedelta(hours=24), datetime.fromisoformat(oldest.replace("Z", "+00:00")) + timedelta(minutes=30)) if oldest else now - timedelta(hours=24)
    def pub_ok(x):
        p = parse_time(x.get("published_utc"))[0] if x.get("published_utc") else None
        return p is not None and floor <= p <= now
    excluded = sum(1 for x in sample if not pub_ok(x))
    sample = [x for x in sample if pub_ok(x)][:20]
    rows = con.execute("SELECT i.title, i.text, i.source_name, i.url, i.published_utc, i.collected_utc FROM items i "
                       "WHERE i.collected_utc >= ? AND i.url NOT LIKE '%news.google.com%'", (iso(now - timedelta(hours=36)),)).fetchall()
    idx = [(set(tokens((r["title"] or "") + " " + (r["text"] or "")[:200])), r) for r in rows]
    out = []
    for s in sample:
        st = set(tokens(s["title"]))
        best, bs = None, 0.0
        if len(st) >= 3:
            for tk, r in idx:
                inter = len(st & tk)
                if inter < 3:
                    continue
                sc = inter / len(st)
                if sc > bs or (sc == bs and best and (r["collected_utc"] or "") < (best["collected_utc"] or "")):
                    best, bs = r, sc
        hit = bs >= 0.5
        lag = None
        pub = parse_time(s.get("published_utc"))[0] if s.get("published_utc") else None
        if hit and pub and best["collected_utc"]:
            lag = round((datetime.fromisoformat(best["collected_utc"].replace("Z", "+00:00")) - pub).total_seconds() / 60, 1)
        out.append({"title": s["title"], "outlet": s.get("source_name"), "url": s.get("url"), "pub": iso(pub) if pub else None,
                    "captured": hit, "score": round(bs, 2), "our_source": best["source_name"] if hit else None,
                    "our_url": best["url"] if hit else None, "our_seen": best["collected_utc"] if hit else None, "lag_min": lag})
    n = len(out)
    lags = sorted(x["lag_min"] for x in out if x["lag_min"] is not None)
    return {"at_utc": iso(now), "reference": "أبرز أخبار العراق في Google News (عربي، العراق) — خلاصة ليست من مصادرنا",
            "n": n, "captured": sum(1 for x in out if x["captured"]), "excluded_old": excluded, "v": 2,
            "window_from": iso(floor),
            "median_lag_min": lags[len(lags) // 2] if lags else None,
            "note": "التطابق آلي بالكلمات (≥50% من كلمات العنوان). الفائت = لم نجد مادة مطابقة من مصادرنا خلال 36 ساعة. سالب = التقطناه قبل نشر المرجع.",
            "items": out}


def main():
    now = now_utc()
    con = core.connect()
    health = load(PWA / "health.json", [])
    meta = load(PWA / "meta.json", {})
    storage = load(PWA / "storage.json", {})
    cfg = load(ROOT / "config" / "sources.json", {"sources": []})["sources"] + load(ROOT / "config" / "discovered.json", {"sources": []})["sources"]
    enabled = [h for h in health if h["enabled"]]
    states = Counter(h["state"] for h in enabled)
    working = [h for h in enabled if h["state"] == "يعمل"]
    silent = [h for h in working if not h["items_24h"]]
    failing = [h for h in enabled if h["state"] in ("متوقف", "فشل مؤقت")]
    reasons = Counter()
    for h in failing:
        e = str(h.get("error") or "غير معروف")
        e = re.sub(r"https?://\S+", "", e)
        key = ("404 غير موجود" if "404" in e else "403 محجوب" if "403" in e else "مهلة/اتصال" if re.search(r"timed out|timeout|Connection|resolve|reset", e, re.I)
               else "تحليل الصفحة" if re.search(r"parse|XML|syntax|decode", e, re.I) else e[:40])
        reasons[key] += 1
    urls = Counter(s["url"].lower().rstrip("/") for s in cfg)
    dup_urls = [u for u, c in urls.items() if c > 1]
    outlets = Counter(core.outlet_key(s["name"]) for s in cfg if "news.google.com" not in s["url"])
    multi_route = sorted([o for o, c in outlets.items() if c > 1])[:40]
    day = iso(now - timedelta(hours=24))
    n_items = con.execute("SELECT COUNT(*) FROM items WHERE collected_utc >= ?", (day,)).fetchone()[0]
    n_clusters = con.execute("SELECT COUNT(DISTINCT cluster_id) FROM items WHERE collected_utc >= ?", (day,)).fetchone()[0]
    fl = con.execute("SELECT COUNT(*), SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END) FROM fetch_log WHERE at_utc >= ?", (day,)).fetchone()
    by_type = Counter(h["type"] for h in enabled)
    by_type_ok = Counter(h["type"] for h in working)
    st = load(STATE, {})
    ref = st.get("ref_check")
    bgd = now + timedelta(hours=3)
    if not ref or ref.get("v") != 2 or (bgd.hour >= 9 and ref.get("day") != bgd.strftime("%Y-%m-%d")):
        try:
            ref = reference_check(con, now)
            ref["day"] = bgd.strftime("%Y-%m-%d")
            hist = [h for h in st.get("ref_hist", []) if h["day"] != ref["day"]]
            hist.append({"day": ref["day"], "n": ref["n"], "captured": ref["captured"], "median_lag_min": ref["median_lag_min"]})
            st["ref_hist"] = hist[-30:]
            st["ref_check"] = ref
            STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
            print(f"::notice title=reference_check::{ref['captured']}/{ref['n']} median_lag={ref['median_lag_min']} | " +
                  " || ".join(f"{'✓' if x['captured'] else '✗'}{x['score']} {x['pub']} {x['title'][:70]}" for x in ref["items"]))
        except Exception as e:  # noqa: BLE001
            print("::warning title=metrics ref failed::", type(e).__name__, str(e)[:150])
    out = {"updated_utc": iso(now),
           "sources": {"registered": len(cfg), "monitored": len(health), "enabled": len(enabled), "working": len(working),
                       "silent_24h": len(silent), "failing": len(failing), "disabled": len(health) - len(enabled),
                       "states": dict(states), "fail_reasons": dict(reasons.most_common(8)),
                       "failing_list": [{"name": h["name"], "type": h["type"], "error": (h.get("error") or "")[:90], "last_success": h["last_success"]} for h in failing][:60],
                       "silent_list": [h["name"] for h in silent][:60],
                       "by_type": {t: {"enabled": by_type[t], "working": by_type_ok[t]} for t in by_type},
                       "duplicate_urls": dup_urls, "multi_route_outlets": multi_route},
           "latency": meta.get("detect_delay"),
           "dup": {"items_24h": n_items, "events_24h": n_clusters,
                   "copies_pct": round(100 * (1 - n_clusters / n_items), 1) if n_items else None},
           "errors": {"fetch_attempts_24h": fl[0] or 0, "failed_24h": fl[1] or 0,
                      "failed_pct": round(100 * (fl[1] or 0) / fl[0], 1) if fl[0] else None},
           "reference": ref, "reference_hist": st.get("ref_hist", []),
           "storage": storage}
    (PWA / "metrics.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    s = out["sources"]
    print(f"::notice title=metrics::registered={s['registered']} working={s['working']} silent={s['silent_24h']} failing={s['failing']} disabled={s['disabled']} dupurls={len(dup_urls)} copies%={out['dup']['copies_pct']} fail%={out['errors']['failed_pct']} reasons={json.dumps(s['fail_reasons'], ensure_ascii=False)}")


if __name__ == "__main__":
    main()
