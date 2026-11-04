"""تفريغ للتدقيق: آخر منشورات القناة (نص كامل + وقت + مشاهدات) وملفات الحالة. للقراءة فقط.
سير audit.yml ينسخ معه من إصدار fastlane إلى probe: fast_status.json وfast_decisions.json (قرارات المسار السريع وأسبابها) وposted_fast/main.json."""
import html as H, json, re, urllib.request
from datetime import datetime, timedelta, timezone
UA = {"User-Agent": "Mozilla/5.0"}
ch = "hassawassal"
posts, before = [], ""
for _ in range(12):
    page = urllib.request.urlopen(urllib.request.Request(f"https://t.me/s/{ch}{before}", headers=UA), timeout=20).read().decode("utf-8", "replace")
    blocks = page.split('class="tgme_widget_message_wrap')[1:]
    if not blocks:
        break
    got = []
    for b in blocks:
        pid = re.search(rf'data-post="{ch}/(\d+)"', b)
        t = re.search(r'<time[^>]+datetime="([^"]+)"', b)
        tx = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', b, re.S)
        v = re.search(r'tgme_widget_message_views">([^<]+)<', b)
        kind = "video" if "tgme_widget_message_video" in b else "photo" if "tgme_widget_message_photo" in b else "preview" if "link_preview" in b else "text"
        if not (pid and t):
            continue
        text = H.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<br\s*/?>", "\n", tx.group(1)))) if tx else ""
        got.append({"id": int(pid.group(1)), "t": t.group(1), "views": v.group(1) if v else "", "kind": kind, "text": text[:900]})
    posts += got
    if not got or min(p["t"] for p in got) < (datetime.now(timezone.utc) - timedelta(hours=14)).isoformat():
        break
    before = f"?before={min(p['id'] for p in got)}"
posts.sort(key=lambda p: p["id"])
json.dump(posts, open("audit_posts.json", "w"), ensure_ascii=False, indent=0)
print(len(posts), "posts")
