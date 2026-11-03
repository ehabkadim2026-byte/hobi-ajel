# مؤقت: اكتشاف وفحص قنوات تلغرام عامة (يُحذف بعد الاستخدام)
import json, re, sys, time, urllib.request, collections, html
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
BAD = {"s","joinchat","addstickers","share","proxy","iv","c","addlist","boost","contact","socks","setlanguage","telegram","durov","premium"}
LINK = re.compile(r"https?://(?:t|telegram)\.me/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})(?=[/\"'?<\s]|$)")
AT = re.compile(r"(?<![A-Za-z0-9_@])@([A-Za-z][A-Za-z0-9_]{4,31})")
def get(u):
    for i in range(3):
        try:
            return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20).read().decode("utf-8", "replace")
        except Exception as e:
            err = str(e); time.sleep(2 + 3 * i)
    return ""
def txt(h):
    return html.unescape(re.sub(r"<[^>]+>", " ", h)).strip()
def probe(u):
    h = get(f"https://t.me/s/{u}")
    r = {"u": u}
    m = re.search(r'<div class="tgme_channel_info_header_title"[^>]*>(.*?)</div>', h, re.S)
    r["title"] = txt(m.group(1)) if m else None
    m = re.search(r'<div class="tgme_channel_info_description"[^>]*>(.*?)</div>', h, re.S)
    r["desc"] = txt(m.group(1))[:200] if m else None
    m = re.search(r'<span class="counter_value">([^<]+)</span>\s*<span class="counter_type">subscribers', h)
    r["subs"] = m.group(1) if m else None
    times = re.findall(r'<time datetime="([^"]+)"', h)
    r["n"] = len(times); r["last"] = times[-1] if times else None; r["first"] = times[0] if times else None
    texts = [txt(t) for t in re.findall(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', h, re.S)]
    alltext = " ".join(texts)
    r["ar"] = len(re.findall(r"[ء-ي]", alltext)); r["kurd"] = len(re.findall(r"[ڕڵێۆەڤ]", alltext))
    r["sample"] = [t[:160] for t in texts[-3:]]
    return r, h
def mentions(h, own):
    out = set(x.lower() for x in LINK.findall(h)) | set(x.lower() for x in AT.findall(txt(h)))
    return {x for x in out if x not in BAD and x != own.lower() and not x.endswith("bot")}
seeds = [l.strip() for l in open(sys.argv[1]) if l.strip() and not l.startswith("#")]
guesses = [l.strip() for l in open(sys.argv[2]) if l.strip() and not l.startswith("#")]
known = {x.lower() for x in seeds} | {l.strip().lower() for l in open(sys.argv[3]) if l.strip()}
cnt = collections.Counter(); via = collections.defaultdict(set)
for s in seeds:
    h = get(f"https://t.me/s/{s}")
    for m in mentions(h, s):
        cnt[m] += 1; via[m].add(s)
    time.sleep(0.25)
cands = [g for g in dict.fromkeys(guesses) if g.lower() not in known]
snow = [m for m, c in cnt.most_common() if m not in known and m not in {g.lower() for g in cands}][:int(sys.argv[5])]
res = []
for u in cands + snow:
    try:
        r, _ = probe(u)
    except Exception as e:
        r = {"u": u, "err": str(e)}
    r["src"] = "guess" if u in cands else "snow"; r["refs"] = cnt.get(u.lower(), 0); r["via"] = sorted(via.get(u.lower(), []))[:5]
    res.append(r); time.sleep(0.25)
json.dump(res, open(sys.argv[4], "w"), ensure_ascii=False, indent=0)
print(len(res), sum(1 for r in res if r.get("n")))
