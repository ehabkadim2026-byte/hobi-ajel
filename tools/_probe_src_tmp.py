import html as H, json, re, sys, urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
UA={"User-Agent":"Mozilla/5.0"}
def get(u,t=15):
    return urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=t).read().decode("utf-8","ignore")
cfg=json.load(open("config/sources.json"))["sources"]
have={s["url"].rstrip("/").split("/")[-1].lower() for s in cfg if s.get("method")=="telegram_preview"}
sites=["moh.gov.iq","moi.gov.iq","karbala.gov.iq","basra.gov.iq","najaf.gov.iq","dhiqar.gov.iq","babil.gov.iq","anbar.gov.iq","ninevehgov.iq","salahaddin.gov.iq","wasit.gov.iq","maysan.gov.iq","muthanna.gov.iq","diwaniya.gov.iq","kirkuk.gov.iq","diyala.gov.iq","amanatbaghdad.gov.iq","moelc.gov.iq","motc.gov.iq","mowr.gov.iq","mot.gov.iq","moedu.gov.iq","mohesr.gov.iq","mofa.gov.iq","mod.mil.iq","cabinet.iq","pmo.iq","parliament.iq","sjc.iq","ina.iq","cbi.iq","nazaha.iq","iraqinews.gov.iq","moc.gov.iq","mop.gov.iq","ihec.iq","cmc.iq","mocom.gov.iq","molsa.gov.iq","moj.gov.iq","moa.gov.iq","moi.gov.iq/cd","ncci.gov.iq","baghdadairport.gov.iq","ica.gov.iq"]
src={}
def site(s):
    try: return s, re.findall(r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{5,32})", get("https://"+s+"/"))
    except Exception as e: return s, []
with ThreadPoolExecutor(10) as ex:
    for s,hs in ex.map(site,sites):
        for h in hs: src.setdefault(h.lower(),set()).add("site:"+s)
# forwarded / mentioned in our Iraqi telegram channels
iraq=[s["url"].rstrip("/").split("/")[-1] for s in cfg if s.get("method")=="telegram_preview" and "العراق" in (s.get("region") or "")]
def ch(h):
    try: return h, re.findall(r'href="https://t\.me/([A-Za-z0-9_]{5,32})(?:/\d+)?"', get("https://t.me/s/"+h))
    except Exception: return h, []
cnt=Counter()
with ThreadPoolExecutor(8) as ex:
    for h,hs in ex.map(ch,iraq):
        for x in set(hs):
            if x.lower()!=h.lower(): cnt[x.lower()]+=1; src.setdefault(x.lower(),set()).add("ch:"+h)
extra=sys.argv[1:]
for e in extra: src.setdefault(e.lower(),set()).add("manual")
bad=("share","joinchat","addstickers","iv","proxy","contact","addlist","boost")
cands=[h for h in sorted(src,key=lambda h:-len(src[h])) if h not in have and h not in bad][:160]
print("sites with links:",sorted({v for x in src.values() for v in x if v.startswith("site:")}))
print("ch citations:",cnt.most_common(40))
def probe(h):
    try:
        pg=get("https://t.me/s/"+h)
        ttl=re.search(r'<meta property="og:title" content="([^"]*)"',pg); ds=re.search(r'<meta property="og:description" content="([^"]*)"',pg)
        sub=re.search(r'<span class="counter_value">([^<]+)</span>\s*<span class="counter_type">subscribers',pg)
        txt=[re.sub(r"\s+"," ",re.sub(r"<[^>]+>"," ",H.unescape(x))).strip() for x in re.findall(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>',pg,re.S)]
        times=re.findall(r'<time datetime="([^"]+)"',pg)
        ar=sum(1 for t in txt if re.search(r"[؀-ۿ]{3}",t))
        return {"h":h,"via":sorted(src[h])[:6],"title":H.unescape(ttl.group(1)) if ttl else "","desc":H.unescape(ds.group(1))[:160] if ds else "","subs":sub.group(1) if sub else None,"last":times[-1] if times else None,"n":len(times),"ar":ar,"sample":[t[:110] for t in txt[-4:]]}
    except Exception as e:
        return {"h":h,"via":sorted(src[h])[:6],"err":type(e).__name__}
with ThreadPoolExecutor(8) as ex: out=list(ex.map(probe,cands))
json.dump(out,open("probe_src.json","w"),ensure_ascii=False,indent=0)
print(len(cands),"candidates")
