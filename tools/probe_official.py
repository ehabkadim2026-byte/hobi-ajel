"""فحص قنوات تلغرام مرشّحة لمسؤولين وجهات رسمية عراقية: هل القناة عامة؟ ما اسمها؟ متى آخر منشور؟ (قراءة المعاينة العامة فقط)."""
import html as H
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/126 Mobile Safari/537.36"}


def probe(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(f"https://t.me/s/{u}", headers=UA), timeout=20) as r:
            p = r.read(900_000).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return {"u": u, "ok": False, "err": type(e).__name__}
    title = re.search(r'<meta property="og:title" content="([^"]*)"', p)
    desc = re.search(r'<meta property="og:description" content="([^"]*)"', p)
    pt = re.search(r'class="tgme_page_title"[^>]*>\s*<span[^>]*>([^<]+)', p) or re.search(r'class="tgme_header_title"[^>]*>([^<]+)', p)
    times = re.findall(r'<time datetime="([^"]+)"', p)
    subs = re.search(r'<span class="counter_value">([^<]+)</span>\s*<span class="counter_type">subscribers', p)
    refs = re.findall(r'tgme_widget_message_forwarded_from_name"\s+href="https://t\.me/([A-Za-z0-9_]{5,})', p) + re.findall(r'href="https://t\.me/([A-Za-z][A-Za-z0-9_]{4,})(?:/\d+)?"', p)
    return {"u": u, "refs": refs, "page_title": H.unescape(pt.group(1)).strip() if pt else "", "ok": bool(times), "title": H.unescape(title.group(1)) if title else "", "desc": H.unescape(desc.group(1))[:160] if desc else "",
            "last": times[-1] if times else None, "n": len(times), "subs": subs.group(1) if subs else None}


if __name__ == "__main__":
    cands = [x.strip() for x in open(sys.argv[1], encoding="utf-8") if x.strip() and not x.startswith("#")]
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(probe, dict.fromkeys(cands)))
    if len(sys.argv) > 3:  # زحف: القنوات التي تحوّل منها القنوات الرسمية أو تذكرها، ثم فحصها
        from collections import Counter
        known = {r["u"].lower() for r in res}
        c = Counter(x for r in res for x in set(r.get("refs") or []) if x.lower() not in known and x.lower() not in ("share", "joinchat", "addlist", "s", "iv", "proxy"))
        more = [u for u, _ in c.most_common(150)]
        extra = list(ThreadPoolExecutor(8).map(probe, more))
        for e in extra:
            e["cited_by"] = c[e["u"]]
        res = res + extra
    for r in res:
        r.pop("refs", None)
    json.dump(res, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(sum(1 for r in res if r["ok"]), "/", len(res), "قناة عامة فعّالة")
