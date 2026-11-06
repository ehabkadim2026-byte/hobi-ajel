"""آخر منشورات القناة العامة كما يراها المتابع (قراءة فقط)."""
import html as H, re, urllib.request
pg = urllib.request.urlopen(urllib.request.Request("https://t.me/s/akamedia_iq", headers={"User-Agent": "Mozilla/5.0"}), timeout=20).read().decode("utf-8", "ignore")
for m in re.finditer(r'data-post="akamedia_iq/(\d+)".*?<div class="tgme_widget_message_text[^>]*>(.*?)</div>.*?datetime="([^"]+)"', pg, re.S):
    t = re.sub(r"<br\s*/?>", " ⏎ ", m.group(2)); t = H.unescape(re.sub(r"<[^>]+>", "", t))
    print(f"::notice title={m.group(1)} {m.group(3)[11:16]}::{t[:400]}")
