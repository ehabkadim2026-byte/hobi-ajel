import html as H, json, re, sys, time, urllib.request, ssl
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
UA={"User-Agent":"Mozilla/5.0 (Linux; Android 14) Chrome/126 Mobile Safari/537.36","Accept-Language":"ar,en;q=0.8"}
CTX=ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
BAD={"share","joinchat","addlist","s","iv","proxy","addstickers","socks","setlanguage","boost","c","contact","login"}
def get(url,n=900000,t=20):
    try:
        with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=t,context=CTX) as r: return r.read(n).decode("utf-8","replace")
    except Exception as e: return ""
TME=re.compile(r'(?:https?:)?//(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})',re.I)
def site(u):
    p=get(u,1500000,25)
    return u,[x for x in TME.findall(p) if x.lower() not in BAD], len(p)
def page(u,before=None):
    return get(f"https://t.me/s/{u}"+(f"?before={before}" if before else ""))
def crawl(u,pages=3):
    refs=[]; before=None
    for i in range(pages):
        p=page(u,before)
        if not p: break
        refs+=re.findall(r'tgme_widget_message_forwarded_from_name"\s+href="https://t\.me/([A-Za-z0-9_]{5,})',p)
        refs+=[x for x in TME.findall(p)]
        ids=[int(x) for x in re.findall(r'data-post="[^/"]+/(\d+)"',p)]
        if not ids: break
        before=min(ids)
        time.sleep(0.5)
    return u,[r for r in set(refs) if r.lower() not in BAD and r.lower()!=u.lower()]
AR=re.compile(r'[؀-ۿ]'); KU=re.compile(r'[ڕڵۆێەڤ]')
def probe(u):
    p=page(u)
    g=lambda rx:(m.group(1) if (m:=re.search(rx,p)) else None)
    title=g(r'<meta property="og:title" content="([^"]*)"'); desc=g(r'<meta property="og:description" content="([^"]*)"')
    subs=g(r'<span class="counter_value">([^<]+)</span>\s*<span class="counter_type">subscribers')
    times=re.findall(r'<time datetime="([^"]+)"',p)
    texts=[H.unescape(re.sub(r'<[^>]+>',' ',t)).strip() for t in re.findall(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',p,re.S)]
    texts=[re.sub(r'\s+',' ',t) for t in texts if t]
    j=' '.join(texts)
    return {"u":u,"title":H.unescape(title or ""),"desc":H.unescape(desc or "")[:200],"subs":subs,"n":len(texts),"last":times[-1] if times else None,
            "ar":len(AR.findall(j)),"kurd":len(KU.findall(j)),"sample":texts[-1][:160] if texts else "","verified":'verified-icon' in p or 'tgme_header_title' in p and 'verified' in p}
if __name__=="__main__":
    sites=[x.strip() for x in open("sites.txt") if x.strip() and not x.startswith("#")]
    seeds=[x.strip() for x in open("seeds.txt") if x.strip()]
    cands=[x.strip() for x in open("cands.txt") if x.strip() and not x.startswith("#")]
    skip={x.strip().lower() for x in open("skip.txt") if x.strip()}
    via=defaultdict(set)
    with ThreadPoolExecutor(12) as ex:
        sres=list(ex.map(site,sites))
    sitelog=[]
    for u,l,n in sres:
        sitelog.append(f"{u} bytes={n} tg={sorted(set(l))}")
        for x in set(l): via[x].add("site:"+u)
    with ThreadPoolExecutor(5) as ex:
        for u,refs in ex.map(crawl,seeds):
            for r in refs: via[r].add("tg:"+u)
    for c in cands: via[c].add("guess")
    allc={}
    for k,v in via.items():
        if k.lower() in skip: continue
        allc.setdefault(k.lower(),(k,set()))[1].update(v)
    # rank: site links and guesses all; tg refs by count, top 400
    sel=[k for k,(o,v) in allc.items() if any(not x.startswith("tg:") for x in v)]
    rest=sorted([k for k in allc if k not in sel],key=lambda k:-len(allc[k][1]))[:400]
    order=sel+rest
    with ThreadPoolExecutor(6) as ex:
        res=list(ex.map(lambda k:probe(allc[k][0]),order))
    for r in res: r["via"]=sorted(allc[r["u"].lower()][1])[:6]; r["cited"]=len(allc[r["u"].lower()][1])
    json.dump(res,open("probe-src.json","w"),ensure_ascii=False,indent=0)
    with open("probe-src.txt","w") as f:
        f.write("\n".join(sitelog)+"\n\n")
        for r in res:
            if r["n"] or r["title"] and not r["title"].startswith("Telegram: Contact"):
                f.write(f'{r["u"]} | {r["title"]} | {r["subs"]} | {r["n"]} | {r["last"]} | ar={r["ar"]} ku={r["kurd"]} | {r["sample"][:100]} | via={",".join(r["via"][:3])}\n')
    print(len(res),"probed")
