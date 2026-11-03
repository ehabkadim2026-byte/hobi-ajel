# مؤقت: اكتشاف مرشحين من فهارس عامة ومحركات بحث وصفحات القنوات (يُحذف بعد الاستخدام)
import re, sys, time, urllib.request, urllib.parse, collections, json
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36", "Accept-Language": "ar,en;q=0.8"}
def get(u):
    try:
        return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25).read().decode("utf-8", "replace")
    except Exception as e:
        return "ERR " + str(e)
BAD = {"s","joinchat","addstickers","share","proxy","iv","c","addlist","boost","contact","socks","setlanguage","telegram","durov","premium","channel","username"}
TME = re.compile(r"(?:t|telegram)\.me/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})")
cnt = collections.Counter(); log = []
def add(h, tag, pats):
    n = 0
    for p in pats:
        for m in p.findall(h):
            m = m.lower()
            if m in BAD or m.endswith("bot"): continue
            cnt[m] += 1; n += 1
    log.append((tag, len(h), n, h[:80] if h.startswith("ERR") else ""))
TELEM = re.compile(r"/channels/\d+-([A-Za-z][A-Za-z0-9_]{4,31})")
TGST = re.compile(r"/channel/@([A-Za-z][A-Za-z0-9_]{4,31})")
for p in range(1, 6):
    add(get(f"https://telemetr.io/en/catalog/iraq/news?page={p}"), f"telemetr news p{p}", [TELEM])
for cat in ["politics", "education", "economics", "other"]:
    add(get(f"https://telemetr.io/en/catalog/iraq/{cat}"), f"telemetr {cat}", [TELEM])
for u in ["https://tgstat.com/ar/news?country=iq", "https://tgstat.com/news?country=iq", "https://iq.tgstat.com/news", "https://tgstat.com/en/channels/rating?country=iq&category=news"]:
    add(get(u), u, [TGST, TME])
qs = [l.strip() for l in open(sys.argv[1]) if l.strip()]
for q in qs:
    h = get("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(q)); add(urllib.parse.unquote(h), "ddg " + q, [TME]); time.sleep(18)
    h = get("https://www.bing.com/search?q=" + urllib.parse.quote(q) + "&count=50"); add(urllib.parse.unquote(h).replace(" › ", "/"), "bing " + q, [TME]); time.sleep(2)
AT = re.compile(r"(?<![A-Za-z0-9_@])@([A-Za-z][A-Za-z0-9_]{4,31})")
for s in [l.strip() for l in open(sys.argv[2]) if l.strip()]:
    url = f"https://t.me/s/{s}"
    for page in range(5):
        h = get(url)
        add(h, "deep " + s, [TME, AT])
        ids = re.findall(r'data-post="[^/]+/(\d+)"', h)
        if not ids: break
        url = f"https://t.me/s/{s}?before={min(map(int, ids))}"
        time.sleep(0.4)
json.dump({"counts": cnt.most_common(), "log": log}, open(sys.argv[3], "w"), ensure_ascii=False)
print(len(cnt))
