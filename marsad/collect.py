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
        if not getters:  # Atom (يوتيوب، Blogger)
            A = "{http://www.w3.org/2005/Atom}"
            def atom(tag, e):
                if tag == "link":
                    l = e.find(A + "link")
                    return (l.get("href") if l is not None else "") or ""
                if tag == "pubDate":
                    return (e.findtext(A + "published") or e.findtext(A + "updated") or "").strip()
                if tag == "description":
                    return (e.findtext(A + "summary") or e.findtext("{http://search.yahoo.com/mrss/}group/{http://search.yahoo.com/mrss/}description") or "").strip()
                return (e.findtext(A + tag) or "").strip()
            getters = [(lambda tag, e=e: atom(tag, e)) for e in root.iter(A + "entry")]
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


IRAQ_RX = re.compile(r"\b(Iraq|Iraqi|Iraqis|Baghdad|Kurdistan|Erbil|Irbil|Basra|Basrah|Mosul|Kirkuk|Najaf|Karbala|Sulaymaniyah|Anbar|Fallujah|Sinjar|Duhok|Sudani|Zaidi"
                     r"|Irak\w*|Bağdat|Kerkük|Musul|Süleymaniye|Haşdi)\b|عراق|بغداد|اربیل|اربيل|کرکوک|كركوك|موصل|بصره|سلیمانیه|حشد الشعبی|حشدالشعبی", re.I)


def _google_news(items):
    """عناوين Google News بصيغة «العنوان - الناشر»: نفصل اسم الناشر ونضعه مصدراً للمادة."""
    for it in items:
        t = it["title"] or ""
        if " - " in t:
            head, outlet = t.rsplit(" - ", 1)
            if 1 < len(outlet) <= 60:
                it["title"], it["source_name"] = head.strip(), outlet.strip() + " (عبر Google News)"
        it["text"] = ""
    return items


IRAQI_OUTLETS = re.compile(r"(السومرية|شفق|بغداد اليوم|المدى|الصباح|واع|الأنباء العراقية|964|رووداو|روداو|كوردستان|كردستان ?24|الفرات|المعلومة|المسلة|العالم الجديد|"
                           r"ألترا عراق|الترا عراق|الغد برس|دجلة|الرابعة|الشرقية|يس عراق|الزمان|صوت العراق|كتابات|موازين|العراق اليوم|نون|براثا|الاقتصاد نيوز|المربد|"
                           r"السومرية نيوز|عراق|العراقية|NRT|INA|Shafaq|Rudaw|Kurdistan24|Baghdad|Iraqi)", re.I)


def collect_source(source, state):
    if source["method"] == "rss":
        items = parse_rss(http_get(source["url"]), source)
        if "news.google.com" in source["url"]:
            items = _google_news(items)
            if source.get("category") == "تحليل أجنبي":
                items = [i for i in items if IRAQ_RX.search(i["title"] or "")]
            if (source.get("region") or "").startswith("إقليمي"):  # الإعلام العربي غير العراقي فقط؛ العراقي مرصود مباشرة
                items = [i for i in items if not IRAQI_OUTLETS.search(i.get("source_name") or "")]
            return items
        if source.get("category") == "صحافة أجنبية" and "/iraq" not in source["url"].lower() and "iraq" not in source["url"].lower():
            items = [i for i in items if IRAQ_RX.search((i["title"] or "") + " " + (i["text"] or ""))]
        return items
    if source["method"] == "telegram_preview":
        return collect_telegram(source, state.get(source["id"]))
    raise ValueError("طريقة غير مدعومة آلياً: " + source["method"])
