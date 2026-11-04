"""فحص مؤقت لمرشحي مصادر جديدة (تلغرام معاينة عامة + RSS). يُحذف بعد الفحص."""
import html as H, json, re, sys, time, urllib.request, email.utils, datetime as dt
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/126 Mobile Safari/537.36"}
NOW = dt.datetime.now(dt.timezone.utc)
IQ = re.compile(r'العراق|عراقي|بغداد|البصرة|نينوى|الموصل|كركوك|الأنبار|الانبار|النجف|كربلاء|ديالى|صلاح الدين|ذي قار|الناصرية|بابل|الحلة|واسط|الكوت|ميسان|العمارة|المثنى|السماوة|الديوانية|أربيل|اربيل|دهوك|السليمانية|كردستان|Iraq|Baghdad|Kurdistan|Erbil', re.I)
AR = re.compile(r'[؀-ۿ]')
def get(url, n=1_500_000):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
        return r.read(n).decode("utf-8", "replace")
def strip(s): return H.unescape(re.sub(r'<[^>]+>', ' ', s or '')).strip()
def tg(u):
    try: p = get(f"https://t.me/s/{u}")
    except Exception as e: return {"u": u, "ok": False, "err": type(e).__name__}
    title = re.search(r'<meta property="og:title" content="([^"]*)"', p)
    desc = re.search(r'<meta property="og:description" content="([^"]*)"', p)
    subs = re.search(r'<span class="counter_value">([^<]+)</span>\s*<span class="counter_type">subscribers', p)
    blocks = p.split('class="tgme_widget_message_wrap')[1:]
    posts = []; refs = []
    for b in blocks:
        t = re.search(r'<time datetime="([^"]+)"', b)
        tx = re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', b, re.S)
        fw = re.search(r'tgme_widget_message_forwarded_from_name"\s+href="https://t\.me/([A-Za-z0-9_]{5,})', b)
        if fw: refs.append(fw.group(1))
        refs += re.findall(r'href="https://t\.me/([A-Za-z][A-Za-z0-9_]{4,})(?:/\d+)?"', b)
        posts.append({"t": t.group(1) if t else None, "x": strip(tx.group(1))[:220] if tx else "", "fw": fw.group(1) if fw else None})
    rec = [q for q in posts if q["t"] and (NOW - dt.datetime.fromisoformat(q["t"])).total_seconds() < 3 * 86400]
    txt = [q for q in rec if len(q["x"]) > 25]
    return {"u": u, "ok": bool(posts), "title": H.unescape(title.group(1)) if title else "", "desc": H.unescape(desc.group(1))[:200] if desc else "",
            "subs": subs.group(1) if subs else None, "n": len(posts), "n3d": len(rec), "txt3d": len(txt),
            "ar": sum(1 for q in txt if AR.search(q["x"])), "iq": sum(1 for q in txt if IQ.search(q["x"])),
            "fw_share": round(sum(1 for q in rec if q["fw"]) / max(1, len(rec)), 2),
            "last": posts[-1]["t"] if posts else None, "sample": [q["x"][:160] for q in txt[-5:]], "refs": refs}
def pdate(s):
    s = (s or "").strip()
    try: d = email.utils.parsedate_to_datetime(s)
    except Exception:
        try: d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception: return None
    if d.tzinfo is None: d = d.replace(tzinfo=dt.timezone.utc)
    return d
def rss(url):
    try: p = get(url, 4_000_000)
    except Exception as e: return {"url": url, "ok": False, "err": f"{type(e).__name__}:{str(e)[:80]}"}
    its = re.findall(r'<(item|entry)[\s>](.*?)</\1>', p, re.S)
    out = []
    for _, b in its:
        ti = re.search(r'<title[^>]*>(.*?)</title>', b, re.S)
        d = re.search(r'<(pubDate|published|updated|dc:date)[^>]*>(.*?)</\1>', b, re.S)
        ti = strip(re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', ti.group(1), flags=re.S)) if ti else ""
        out.append((ti, pdate(d.group(2)) if d else None))
    rec = [x for x in out if x[1] and (NOW - x[1]).total_seconds() < 2 * 86400]
    return {"url": url, "ok": bool(rec), "n": len(out), "n2d": len(rec), "iq2d": sum(1 for t, _ in rec if IQ.search(t)),
            "newest": max((x[1] for x in out if x[1]), default=None).isoformat() if any(x[1] for x in out) else None,
            "sample": [t[:140] for t, _ in rec[:5]], "head": p[:120] if not out else ""}
def links(url):
    try: p = get(url, 2_000_000)
    except Exception as e: return url, [], type(e).__name__
    us = re.findall(r'(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})', p)
    return url, us, None
def disc(existing, ex):
    sites = [x.strip() for x in open(".github/probe_sites.txt", encoding="utf-8") if x.strip() and not x.startswith("#")]
    found = defaultdict(set); log = []
    for url, us, err in ex.map(links, sites):
        log.append({"url": url, "n": len(set(us)), "err": err})
        for x in set(us):
            if x.lower() not in existing and x.lower() not in ("share", "joinchat", "addlist", "iv", "proxy", "s", "socialmedia") and not x.lower().endswith("bot"):
                found[x].add(url)
    return found, log
if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "disc":
    src = json.load(open("config/sources.json", encoding="utf-8"))["sources"]
    fl = json.load(open("config/fastlane.json", encoding="utf-8"))
    existing = {s["id"].split("t.me/")[-1].lower() for s in src if s["id"].startswith("telegram:")}
    existing |= {x.lower() for k in ("hot", "channels", "breaking", "agency", "intl", "loud") for x in fl.get(k, [])}
    ex = ThreadPoolExecutor(10)
    found, log = disc(existing, ex)
    extra = [x.strip() for x in open(".github/probe_tg.txt", encoding="utf-8") if x.strip() and not x.startswith("#")]
    todo = list(dict.fromkeys(list(found) + extra))
    res = list(ex.map(tg, todo))
    for r in res:
        r["from"] = sorted(found.get(r["u"], []))[:4]; r.pop("refs", None)
    json.dump(res, open("probe_tg.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0, default=str)
    json.dump(log, open("probe_health.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    feeds = [x.strip() for x in open(".github/probe_rss.txt", encoding="utf-8") if x.strip() and not x.startswith("#")]
    rr = list(ex.map(rss, list(dict.fromkeys(feeds))))
    json.dump(rr, open("probe_rss.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0, default=str)
    print(len(res), "tg;", sum(r["ok"] for r in res), "ok")
    sys.exit(0)
if __name__ == "__main__":
    src = json.load(open("config/sources.json", encoding="utf-8"))["sources"]
    fl = json.load(open("config/fastlane.json", encoding="utf-8"))
    existing = {s["id"].split("t.me/")[-1].lower() for s in src if s["id"].startswith("telegram:")}
    existing |= {x.lower() for k in ("hot", "channels", "breaking", "agency", "intl", "loud") for x in fl.get(k, [])}
    cands = [x.strip() for x in open(".github/probe_tg.txt", encoding="utf-8") if x.strip() and not x.startswith("#")]
    feeds = [x.strip() for x in open(".github/probe_rss.txt", encoding="utf-8") if x.strip() and not x.startswith("#")]
    ex = ThreadPoolExecutor(10)
    # 1) زحف: ما تحوّل منه القنوات الحالية أو تذكره
    crawl = list(ex.map(tg, sorted({s["id"].split("t.me/")[-1] for s in src if s["id"].startswith("telegram:") and s.get("status") != "مستبعد"})))
    cited = defaultdict(set)
    for r in crawl:
        for x in set(r.get("refs") or []):
            if x.lower() not in existing and x.lower() not in ("share", "joinchat", "addlist", "iv", "proxy", "s") and not x.lower().endswith("bot"):
                cited[x].add(r["u"])
    top = sorted(cited, key=lambda k: -len(cited[k]))[:260]
    health = [{k: r.get(k) for k in ("u", "ok", "n3d", "txt3d", "last", "err")} for r in crawl]
    todo = [u for u in dict.fromkeys(cands + top) if u.lower() not in existing]
    res = list(ex.map(tg, todo))
    for r in res:
        r["cited_by"] = sorted(cited.get(r["u"], []))[:8]; r["n_cited"] = len(cited.get(r["u"], []))
        r.pop("refs", None)
    json.dump(res, open("probe_tg.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0, default=str)
    json.dump(health, open("probe_health.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    rr = list(ex.map(rss, list(dict.fromkeys(feeds))))
    json.dump(rr, open("probe_rss.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0, default=str)
    print(len(res), "tg;", sum(r["ok"] for r in res), "ok;", len(rr), "rss;", sum(r["ok"] for r in rr), "ok")
