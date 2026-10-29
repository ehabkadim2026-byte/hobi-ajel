"""جامعات الخادم (RSS + معاينة تلغرام). تعمل فقط في بيئة شبكة مفتوحة (GitHub Actions أو خادم).
في بيئة Claude السحابية الصدفة لا تصل للمواقع؛ الجمع هناك يتم عبر أداة الجلب ثم `cli ingest`.

دروس مسجلة:
- صفحة t.me/s/<قناة> قد تُعاد من كاش قديم عبر الوسطاء؛ الجامع يتقدم بـ ?after=N حتى «No posts».
- وقت المعاينة UTC؛ التاريخ يؤخذ من سمة datetime في الوسم <time>.
"""
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape

UA = "MarsadHobi/0.3 (+media monitoring; respectful polling)"


def _safe_url(url):
    """يرمّز الأحرف غير اللاتينية في الرابط (روابط عربية مثل خلاصات شفق)."""
    from urllib.parse import quote, urlsplit, urlunsplit
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc.encode("idna").decode() if p.netloc else p.netloc,
                       quote(p.path, safe="/%:@"), quote(p.query, safe="=&%:/?+,;@"), p.fragment))


def http_get(url, timeout=20, retries=2, backoff=4):
    last = None
    url = _safe_url(url)
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 — نسجّل أي فشل كنقطة عمى
            last = e
            if "429" in str(e):
                time.sleep(backoff * 4 * (attempt + 1))
            else:
                time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"{type(last).__name__}: {last}")


def _rss_items_loose(xml_text):
    """بديل متسامح عندما تكون الخلاصة XML غير سليم: يقرأ <item> بالتعابير النمطية."""
    for blk in re.findall(r"<item[\s>].*?</item>", xml_text, re.S | re.I):
        def g(tag, blk=blk):
            m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", blk, re.S | re.I)
            v = m.group(1) if m else ""
            return re.sub(r"^<!\[CDATA\[(.*)\]\]>$", r"\1", v.strip(), flags=re.S).strip()
        yield g


def parse_rss(xml_text, source):
    try:
        root = ET.fromstring(xml_text)
        getters = [(lambda tag, it=it: (it.findtext(tag) or "").strip()) for it in root.iter("item")]
    except ET.ParseError:
        getters = list(_rss_items_loose(xml_text))
    out = []
    for g in getters:
        out.append({"platform": "web", "source_id": source["id"], "source_name": source["name"],
                    "url": g("link"), "title": unescape(g("title")), "text": unescape(re.sub("<[^>]+>", " ", g("description")))[:300],
                    "published_utc": g("pubDate") or None, "date_confirmed": bool(g("pubDate"))})
    return out


def parse_tme(html, source):
    """يقسم الصفحة على data-post ويستخرج من كل جزء: النص، المشاهدات، وقت datetime (UTC)."""
    out = []
    for chunk in html.split('data-post="')[1:]:
        m = re.match(r"([^\"/]+)/(\d+)\"", chunk)
        if not m:
            continue
        user, num = m.groups()
        body = re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', chunk, re.S)
        views = re.search(r'class="tgme_widget_message_views">([^<]*)<', chunk)
        dt = re.search(r'<time[^>]*datetime="([^"]+)"', chunk)
        text = ""
        if body:
            text = re.sub(r"<br\s*/?>", "\n", body.group(1))
            text = unescape(re.sub(r"<[^>]+>", "", text)).strip()
        if not text:
            continue
        out.append({"platform": "telegram", "source_id": source["id"], "source_name": source["name"],
                    "url": f"https://t.me/{user}/{num}", "post_no": int(num), "title": (text.split("\n")[0] if len(text.split("\n")[0].strip(" 🔻🔴📌⭕️:")) >= 25 else " ".join(text.split()))[:200],
                    "text": text[:500], "views": views.group(1) if views else None,
                    "published_utc": dt.group(1) if dt else None, "date_confirmed": bool(dt)})
    return out


def collect_telegram(source, last_seen=None, max_pages=3):
    user = source["url"].rstrip("/").split("/")[-1]
    after = last_seen
    items = []
    for _ in range(max_pages):
        url = f"https://t.me/s/{user}" + (f"?after={after}" if after else "")
        page = parse_tme(http_get(url), source)
        if not page:
            break
        items += page
        after = max(p["post_no"] for p in page)
        if len(page) < 20 or last_seen is None:
            break
        time.sleep(2)
    return items


def collect_source(source, state):
    if source["method"] == "rss":
        return parse_rss(http_get(source["url"]), source)
    if source["method"] == "telegram_preview":
        return collect_telegram(source, state.get(source["id"]))
    raise ValueError("طريقة غير مدعومة آلياً: " + source["method"])
