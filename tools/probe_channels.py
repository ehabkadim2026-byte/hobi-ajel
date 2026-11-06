"""فحص قنوات تلغرام عامة قبل إضافتها: الاسم، المشتركون، الوصف، آخر منشورين (قراءة فقط)."""
import html as H, re, sys, urllib.request
for h in sys.argv[1:]:
    try:
        pg = urllib.request.urlopen(urllib.request.Request(f"https://t.me/s/{h}", headers={"User-Agent": "Mozilla/5.0"}), timeout=15).read().decode("utf-8", "ignore")
        ttl = re.search(r'<meta property="og:title" content="([^"]*)"', pg)
        ds = re.search(r'<meta property="og:description" content="([^"]*)"', pg)
        sub = re.search(r'<span class="counter_value">([^<]+)</span>\s*<span class="counter_type">subscribers', pg)
        last = re.findall(r'<div class="tgme_widget_message_text[^>]*>(.*?)</div>', pg, re.S)[-3:]
        times = re.findall(r'datetime="([^"]+)"', pg)[-1:]
        last = " ؛ ".join(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", H.unescape(x))).strip()[:90] for x in last)
        print(f"::notice title={h}::{H.unescape(ttl.group(1)) if ttl else ''} | {sub.group(1) if sub else '?'} | {(H.unescape(ds.group(1))[:70] if ds else '')} | آخر {times[0][:16] if times else '?'} | {last}")
    except Exception as e:
        print(f"::notice title={h}::{type(e).__name__}")
