"""فحص مؤقت لسد فجوات التغطية (يُحذف بعد الاستخدام): زحف مراجع القنوات المرصودة + روابط تلغرام بالمواقع الرسمية + فحص مرشحين + RSS."""
import html as H
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/126 Mobile Safari/537.36"}
NOW = datetime.now(timezone.utc)
SKIP = {"share", "joinchat", "addlist", "s", "iv", "proxy", "boost", "contact", "c", "socks", "setlanguage", "login"}


def get(url, n=900_000, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
                return r.read(n).decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(6 * (i + 1))
                continue
            return None
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return None


def strip(t):
    t = re.sub(r"<br\s*/?>", "\n", t)
    return H.unescape(re.sub(r"<[^>]+>", "", t)).strip()


def refs_of(p):
    return re.findall(r'tgme_widget_message_forwarded_from_name"\s+href="https://t\.me/([A-Za-z0-9_]{5,})', p) + re.findall(
        r'href="https://t\.me/([A-Za-z][A-Za-z0-9_]{4,})(?:/\d+)?"', p)


def parse(u, p):
    title = re.search(r'<meta property="og:title" content="([^"]*)"', p)
    desc = re.search(r'<meta property="og:description" content="([^"]*)"', p)
    subs = re.search(r'<span class="counter_value">([^<]+)</span>\s*<span class="counter_type">subscribers', p)
    msgs = []
    for blk in p.split('class="tgme_widget_message_wrap')[1:]:
        tm = re.search(r'<time datetime="([^"]+)"', blk)
        tx = re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', blk, re.S)
        fw = "tgme_widget_message_forwarded_from" in blk
        msgs.append({"t": tm.group(1) if tm else None, "x": strip(tx.group(1)) if tx else "", "fw": fw})
    d3 = (NOW - timedelta(days=3)).isoformat()
    d7 = (NOW - timedelta(days=7)).isoformat()
    ar = lambda s: len(re.findall(r"[ء-ي]", s)) >= 15  # noqa: E731
    texts = [m for m in msgs if len(m["x"]) >= 25]
    times = [m["t"] for m in msgs if m["t"]]
    return {"u": u, "title": H.unescape(title.group(1)) if title else "", "desc": H.unescape(desc.group(1))[:220] if desc else "",
            "subs": subs.group(1) if subs else None, "n": len(msgs), "ntext": len(texts),
            "ar3d": sum(1 for m in texts if m["t"] and m["t"] >= d3 and ar(m["x"])),
            "ar7d": sum(1 for m in texts if m["t"] and m["t"] >= d7 and ar(m["x"])),
            "fw": sum(1 for m in msgs if m["fw"]),
            "last": max(times) if times else None, "first": min(times) if times else None,
            "last2": [m["x"][:260] for m in texts[-2:]]}


def probe(u):
    p = get(f"https://t.me/s/{u}")
    if p is None:
        return {"u": u, "ok": False, "err": "fetch"}
    r = parse(u, p)
    r["ok"] = bool(r["last"])
    return r


def seed_refs(item):
    u, deep = item
    p = get(f"https://t.me/s/{u}")
    if not p:
        return u, []
    refs = refs_of(p)
    if deep:
        ids = re.findall(r'data-post="[^/]+/(\d+)"', p)
        if ids:
            p2 = get(f"https://t.me/s/{u}?before={min(int(i) for i in ids)}")
            if p2:
                refs += refs_of(p2)
    return u, refs


def web_links(url):
    p = get(url, 1_500_000, tries=2)
    if not p:
        return url, None, [], []
    tg = sorted(set(m for m in re.findall(r'(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})', p) if m.lower() not in SKIP))
    rss = sorted(set(re.findall(r'<link[^>]+type="application/(?:rss|atom)\+xml"[^>]+href="([^"]+)"', p)))
    t = re.search(r"<title[^>]*>(.*?)</title>", p, re.S)
    return url, (strip(t.group(1))[:100] if t else ""), tg, rss


def rss_probe(url):
    p = get(url, 3_000_000, tries=2)
    if not p:
        return {"url": url, "ok": False}
    items = re.findall(r"<item[\s>]|<entry[\s>]", p)
    dates = re.findall(r"<(?:pubDate|published|updated|dc:date)>([^<]+)<", p)
    titles = [strip(x) for x in re.findall(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", p, re.S)][:4]
    return {"url": url, "ok": bool(items), "items": len(items), "newest": dates[:3], "titles": titles}


if __name__ == "__main__":
    cfg = json.load(open(sys.argv[1], encoding="utf-8"))
    src = json.load(open("config/sources.json", encoding="utf-8"))["sources"] + json.load(open("config/discovered.json", encoding="utf-8"))["sources"]
    fl = json.load(open("config/fastlane.json", encoding="utf-8"))
    known = {}
    for x in src:
        m = re.search(r"t\.me/(?:s/)?([A-Za-z0-9_]+)", x.get("url") or "")
        if m:
            known[m.group(1).lower()] = (x.get("region") or "") + " " + (x.get("category") or "")
    for k in ("channels", "breaking"):
        for u in fl[k]:
            known.setdefault(u.lower(), "fastlane")
    out = {"at": NOW.isoformat()}
    # 0: بحث عام (DuckDuckGo/Bing) عن روابط t.me
    def search(q):
        found = []
        for url in (f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(q)}", f"https://www.bing.com/search?q={urllib.parse.quote(q)}&count=50"):
            p = get(url, 1_500_000, tries=1) or ""
            found += [m for m in re.findall(r"t\.me(?:/|%2F)(?:s(?:/|%2F))?([A-Za-z][A-Za-z0-9_]{4,31})", p) if m.lower() not in SKIP]
        return q, sorted(set(found))
    with ThreadPoolExecutor(4) as ex:
        out["search"] = dict(ex.map(search, cfg.get("queries", [])))
    srch = [u for v in out["search"].values() for u in v]
    # A: المواقع الرسمية
    with ThreadPoolExecutor(8) as ex:
        web = list(ex.map(web_links, cfg["web"]))
    out["web"] = [{"url": a, "title": b, "tg": c, "rss": d} for a, b, c, d in web]
    webtg = [u for _, _, tg, _ in web for u in tg]
    # B: مراجع القنوات المرصودة
    deep_rx = re.compile(r"الأنبار|ديالى|صلاح|سامراء|بابل|الديوانية|القادسية|كرد|كورد|أربيل|دهوك|السليمانية|اتحادي|رسمي")
    seeds = [(u, bool(deep_rx.search(v))) for u, v in known.items() if v != "fastlane" and (not cfg.get("seed_deep_only") or deep_rx.search(v))]
    cnt, by = Counter(), defaultdict(set)
    with ThreadPoolExecutor(6) as ex:
        for u, refs in ex.map(seed_refs, seeds):
            for r in set(x.lower() for x in refs):
                if r not in known and r not in SKIP and r != u.lower():
                    cnt[r] += 1
                    by[r].add(u)
    out["refcount"] = {k: [v, sorted(by[k])[:6]] for k, v in cnt.most_common(400)}
    # C: المرشحون
    cands = list(dict.fromkeys([c for c in cfg["cands"]] + webtg + srch + [k for k, _ in cnt.most_common(cfg.get("top_refs", 220))]))
    cands = [c for c in cands if c.lower() not in known or c in cfg.get("force", [])]
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(probe, cands))
    for r in res:
        r["cited_by"] = cnt.get(r["u"].lower(), 0)
    out["cands"] = res
    # D: RSS
    rsss = list(dict.fromkeys(cfg["rss"] + [x for _, _, _, rs in web for x in rs if x.startswith("http")]))
    with ThreadPoolExecutor(8) as ex:
        out["rss"] = list(ex.map(rss_probe, rsss))
    json.dump(out, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(len(seeds), "seeds", len(cands), "cands", sum(1 for r in res if r.get("ok")), "ok")
