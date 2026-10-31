"""محرك اكتشاف المصادر (Source Discovery Engine) — كل 6 ساعات.

مسارا الاكتشاف (مشروعان، بلا تجاوز حمايات):
  1) قنوات تلغرام عامة تُذكر روابطها في الأخبار التي جمعناها آخر 24 ساعة (t.me/<اسم>).
  2) مواقع تظهر كناشرين في نتائج Google News عن العراق (<source url>) — نبحث لها عن خلاصة RSS معلنة.
التقييم قبل أي إضافة (درجة 0–100):
  النشاط (منشورات 24 ساعة) 25 · الصلة بالعراق 30 · الأصالة (ليست نسخاً لما عندنا) 25 · السرعة (سبقت مصادرنا) 10 · العربية 10
القبول التلقائي: ≥ 65 + صلة ≥ 50% + نشاط ≥ 10/يوم + أصالة ≥ 50% + غير مستبعد + غير مكرر. 35–59 ← قائمة مراجعة بشرية. أقل ← رفض.
المستبعد دائماً: إعلام الجهات المصنّفة إرهابية أمريكياً (قرار ثابت)، والمحتوى الكردي فقط، والحسابات الشخصية غير الإعلامية.
الإضافات تُكتب في config/discovered.json (لا يُلمس السجل الأصلي) وتُرفع للمستودع، ويمكن التراجع بحذف السطر.
المراجعة: المحرر يرسل للبوت «/مصدر قبول <المفتاح>» أو «/مصدر رفض <المفتاح>».
"""
import json
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from marsad import core  # noqa: E402
from marsad.collect import http_get, parse_tme, parse_rss  # noqa: E402
from marsad.textnorm import norm_ar, tokens, parse_time  # noqa: E402

STATE = ROOT / "data" / "discovery_state.json"
DISC = ROOT / "config" / "discovered.json"
PWA = ROOT / "pwa"
EVERY_H = 6
EXCLUDE = re.compile(r"(نجباء|النجباء|كتائب حزب الله|عصائب|العصائب|قناة العهد|alahad|حركة حقوق|المنار|almanar|الأقصى|aqsa|تسنيم|tasnim|وكالة فارس|farsnews|nujaba|kataib|asaib|rojnews|pkk|بي كي كي)", re.I)
NON_NEWS_TOPIC = re.compile(r"(وظائف|توظيف|تسويق|تدريب|افلام|أفلام|مسلسل|اغاني|أغاني|متجر|عروض|اعلانات|إعلانات|تعليم|كورسات|رياضة|بث مباشر للمباريات|crypto|كريبتو|تداول|shop|store|movies)", re.I)
NOT_NEWS = re.compile(r"(bot$|^joinchat$|^addlist$|^share$|^iv$|^proxy$|^s$|^c$|^\+)", re.I)
IRAQ_WORDS = [norm_ar(w) for w in ["العراق", "عراقي", "بغداد", "البصرة", "الموصل", "اربيل", "كركوك", "النجف", "كربلاء", "الانبار", "ديالى", "نينوى",
                                    "ذي قار", "ميسان", "واسط", "بابل", "صلاح الدين", "السليمانية", "دهوك", "الحشد", "مجلس النواب", "الزيدي", "الدينار"]]
KURDISH = re.compile(r"[ەێۆڵڕڤ]")
UA = "Mozilla/5.0 (HobiAjel source discovery)"


def load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def known(con):
    urls = {r[0].lower().rstrip("/") for r in con.execute("SELECT url FROM sources WHERE url IS NOT NULL")}
    tg = {u.split("/")[-1] for u in urls if "t.me/" in u}
    doms = set()
    for u in urls:
        doms |= set(re.findall(r"site:([\w.\-]+)", u))
        h = urlsplit(u).netloc
        if h and "google" not in h and "t.me" not in h:
            doms.add(h[4:] if h.startswith("www.") else h)
    return tg, doms


def iraq_ratio(texts):
    if not texts:
        return 0.0
    return sum(1 for t in texts if any(w in norm_ar(t) for w in IRAQ_WORDS)) / len(texts)


def originality(con, posts):
    """نسبة المنشورات غير الموجودة مسبقاً لدى مصادرنا + سبقها الزمني (دقائق) حين تتطابق."""
    since = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = con.execute("SELECT title, published_utc, collected_utc FROM items WHERE collected_utc >= ?", (since,)).fetchall()
    idx = [(set(tokens(r[0] or "")), r) for r in rows]
    copies, leads = 0, []
    for p in posts:
        pt = set(tokens(p.get("title") or ""))
        if len(pt) < 4:
            continue
        best = None
        for tk, r in idx:
            if len(pt & tk) >= 4 and len(pt & tk) / len(pt | tk) >= 0.5:
                best = r
                break
        if best:
            pp = parse_time(p.get("published_utc"))[0] if p.get("published_utc") else None
            op = parse_time(best[1] or best[2])[0]
            if pp and op:
                lead = (op - pp).total_seconds() / 60
                leads.append(lead)
                if lead < 2:
                    copies += 1  # نشرها بعد مصادرنا أو معها: إعادة نشر
            else:
                copies += 1
    n = max(1, len([p for p in posts if len(set(tokens(p.get("title") or ""))) >= 4]))
    return 1 - copies / n, (sorted(leads)[len(leads) // 2] if leads else None)


def score(n24, rel, orig, lead, arabic):
    s = (25 if n24 >= 5 else 10 if n24 >= 1 else 0) + rel * 30 + orig * 25 + (10 if (lead or 0) > 2 else 0) + arabic * 10
    return round(s)


def eval_telegram(con, user):
    html = http_get(f"https://t.me/s/{user}", timeout=15, retries=1, backoff=2)
    title = re.search(r'tgme_channel_info_header_title[^>]*>\s*<span[^>]*>(.*?)</span>', html, re.S)
    desc = re.search(r'tgme_channel_info_description[^>]*>(.*?)</div>', html, re.S)
    title = re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else user
    desc = re.sub(r"<[^>]+>", " ", desc.group(1)).strip()[:200] if desc else ""
    posts = parse_tme(html, {"id": "cand", "name": title})
    now = datetime.now(timezone.utc)
    recent = [p for p in posts if p.get("published_utc") and parse_time(p["published_utc"])[0] and now - parse_time(p["published_utc"])[0] < timedelta(hours=24)]
    texts = [p["text"] for p in posts]
    kurd = sum(1 for t in texts if len(KURDISH.findall(t)) >= 3) / max(1, len(texts))
    arabic = sum(1 for t in texts if re.search(r"[؀-ۿ]", t)) / max(1, len(texts))
    rel = iraq_ratio(texts)
    orig, lead = originality(con, posts)
    reasons = []
    if EXCLUDE.search(title + " " + desc + " " + user):
        reasons.append("جهة مستبعدة (قرار ثابت)")
    if kurd > 0.5:
        reasons.append("محتوى كردي غالب")
    if not posts:
        reasons.append("لا معاينة عامة/لا منشورات")
    if NON_NEWS_TOPIC.search(title + " " + desc):
        reasons.append("ليس مصدراً إخبارياً (وظائف/تسويق/ترفيه)")
    if rel < 0.3:
        reasons.append(f"صلة ضعيفة بالعراق ({rel:.0%})")
    sc = score(len(recent), rel, orig, lead, arabic)
    return {"key": "tg:" + user, "type": "تلغرام", "url": f"https://t.me/{user}", "name": title, "desc": desc, "n24": len(recent),
            "iraq": round(rel, 2), "original": round(orig, 2), "lead_min": round(lead, 1) if lead is not None else None,
            "arabic": round(arabic, 2), "score": sc, "excluded": reasons}


FEED_PATHS = ["/feed", "/rss", "/feed/", "/rss.xml", "/feed.xml", "/?feed=rss2", "/index.xml", "/ar/rss", "/rss/ar"]


def find_feed(home):
    try:
        page = http_get(home, timeout=12, retries=0, backoff=1)
        m = re.search(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*href=["\']([^"\']+)', page, re.I) or \
            re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]*type=["\']application/(?:rss|atom)\+xml', page, re.I)
        if m:
            u = m.group(1)
            return u if u.startswith("http") else home.rstrip("/") + "/" + u.lstrip("/")
    except Exception:  # noqa: BLE001
        pass
    for p in FEED_PATHS:
        try:
            x = http_get(home.rstrip("/") + p, timeout=10, retries=0, backoff=1)
            if "<rss" in x[:600] or "<feed" in x[:600]:
                return home.rstrip("/") + p
        except Exception:  # noqa: BLE001
            continue
    return None


def eval_site(con, home, name):
    feed = find_feed(home)
    dom = urlsplit(home).netloc.replace("www.", "")
    base = {"key": "web:" + dom, "type": "موقع", "url": home, "name": name, "desc": "", "feed": feed}
    if not feed:
        return {**base, "n24": 0, "iraq": 0, "original": 0, "lead_min": None, "arabic": 0, "score": 0, "excluded": ["لا خلاصة RSS معلنة"]}
    items = parse_rss(http_get(feed, timeout=15, retries=1, backoff=2), {"id": "cand", "name": name})
    now = datetime.now(timezone.utc)
    recent = [i for i in items if i.get("published_utc") and parse_time(i["published_utc"])[0] and now - parse_time(i["published_utc"])[0] < timedelta(hours=24)]
    texts = [(i["title"] or "") + " " + (i["text"] or "") for i in items]
    arabic = sum(1 for t in texts if re.search(r"[؀-ۿ]", t)) / max(1, len(texts))
    rel = iraq_ratio(texts)
    orig, lead = originality(con, items)
    reasons = ["جهة مستبعدة (قرار ثابت)"] if EXCLUDE.search(name + " " + home) else []
    if rel < 0.3:
        reasons.append(f"صلة ضعيفة بالعراق ({rel:.0%})")
    return {**base, "n24": len(recent), "iraq": round(rel, 2), "original": round(orig, 2), "lead_min": round(lead, 1) if lead is not None else None,
            "arabic": round(arabic, 2), "score": score(len(recent), rel, orig, lead, arabic), "excluded": reasons}


def gn_publishers():
    """ناشرون من Google News عن العراق مع روابط مواقعهم (<source url>)."""
    out = {}
    for q in ["العراق", "بغداد", "البصرة OR الموصل OR أربيل", "الحشد الشعبي", "النجف OR كربلاء OR الأنبار"]:
        from urllib.parse import quote
        try:
            x = http_get(f"https://news.google.com/rss/search?hl=ar&gl=IQ&ceid=IQ:ar&q={quote(q + ' when:1d')}", timeout=15, retries=1)
        except Exception:  # noqa: BLE001
            continue
        for u, n in re.findall(r'<source url="([^"]+)">([^<]+)</source>', x):
            out[u.rstrip("/")] = n
    return out


def fast_outlets(con, st, disc, t0, budget=100):
    """مسار السرعة: جهات تصلنا أخبارها عن العراق فقط عبر Google News (متأخرة ~50 دقيقة).
    نبحث لها عن خلاصة RSS مباشرة (أسرع بكثير) ونضيفها بأولوية 1 إذا كانت فعّالة ومرتبطة بالعراق."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cnt = Counter()
    for (n,) in con.execute("SELECT source_name FROM items WHERE url LIKE '%news.google.com%' AND collected_utc >= ?", (since,)):
        cnt[re.sub(r"\s*\(عبر Google News\)$", "", n or "").strip()] += 1
    pubs = {v.strip(): u for u, v in gn_publishers().items()}
    # «معروف» هنا = مرصود مباشرة (RSS/تلغرام)، لا عبر استعلامات site: في Google News (تلك هي البطيئة)
    doms = set()
    for (u,) in con.execute("SELECT url FROM sources WHERE method IN ('rss','telegram_preview') AND url NOT LIKE '%news.google.com%'"):
        h = urlsplit(u or "").netloc
        if h:
            doms.add(h[4:] if h.startswith("www.") else h)
    added = []
    for name, c in cnt.most_common(40):
        if time.time() - t0 > budget:
            break
        home = pubs.get(name)
        if not home or c < 5 or len(name.split()) > 5:  # اسم بشكل عنوان خبر = بيانات ناشر خاطئة
            continue
        dom = urlsplit(home).netloc.replace("www.", "")
        key = "fast:" + dom
        if dom in doms or key in st["seen"] or EXCLUDE.search(name + " " + home):
            continue
        try:
            ev = eval_site(con, home, name)
        except Exception as e:  # noqa: BLE001
            st["seen"][key] = {"t": time.time(), "decision": "تعذر", "why": type(e).__name__}
            continue
        ok = ev.get("feed") and ev.get("n24", 0) >= 3 and ev.get("iraq", 0) >= 0.3 and not ev.get("excluded")
        st["seen"][key] = {"t": time.time(), "decision": "إضافة (سرعة)" if ok else "رفض", "score": ev.get("score"), "gn_items": c}
        if ok:
            src = to_source(ev)
            src["priority"] = 1
            src["category"] = "مسار السرعة (بديل Google News)"
            src["evidence"] += f" · كانت تصلنا عبر Google News ({c}/24س)"
            if all(x["id"] != src["id"] for x in disc["sources"]):
                disc["sources"].append(src)
                added.append(name)
    return added


def to_source(c):
    if c["type"] == "تلغرام":
        return {"id": "telegram:t.me/" + c["url"].split("/")[-1], "name": c["name"] + " — telegram", "url": c["url"], "platform": "telegram",
                "method": "telegram_preview", "status": "لم يُجمع بعد", "frequency": "ساعي", "category": "مكتشف تلقائياً", "region": "العراق",
                "lang": "ar", "official": False, "added_by": "محرك الاكتشاف", "evidence": f"درجة {c['score']} · صلة {c['iraq']} · أصالة {c['original']} · {c['n24']}/24س"}
    return {"id": "rss:" + c["feed"], "name": c["name"] + " — RSS", "url": c["feed"], "platform": "web", "method": "rss", "status": "لم يُجمع بعد",
            "frequency": "ساعي", "category": "مكتشف تلقائياً", "region": "العراق", "lang": "ar", "official": False, "added_by": "محرك الاكتشاف",
            "evidence": f"درجة {c['score']} · صلة {c['iraq']} · أصالة {c['original']} · {c['n24']}/24س · {c['url']}"}


def commit(added):
    if not added:
        return "لا جديد"
    cmds = [["git", "config", "user.name", "rasid-discovery"], ["git", "config", "user.email", "rasid@users.noreply.github.com"],
            ["git", "add", str(DISC)], ["git", "commit", "-m", f"اكتشاف مصادر: +{len(added)}"], ["git", "pull", "--rebase", "--autostash", "-q"], ["git", "push", "-q"]]
    for c in cmds:
        r = subprocess.run(c, capture_output=True, text=True, cwd=ROOT)
        if r.returncode and c[1] != "config":
            return f"فشل {c[1]}: {r.stderr.strip()[:120]}"
    return "رُفع للمستودع"


def apply_decisions(st, disc):
    """قرارات المحرر من البوت (/مصدر قبول|رفض <المفتاح>)."""
    sent = load(ROOT / "data" / "tg_sent.json", {})
    dec = sent.get("_src_decisions", {})
    added = []
    for key, d in dec.items():
        c = st["review"].pop(key, None)
        if not c:
            continue
        st["seen"][key] = {"t": time.time(), "decision": d}
        if d == "قبول" and (c.get("type") == "تلغرام" or c.get("feed")):
            s = to_source(c)
            s["added_by"] = "مراجعة المحرر"
            if all(x["id"] != s["id"] for x in disc["sources"]):
                disc["sources"].append(s)
                added.append(s["name"])
    return added


def main(force=False):
    st = load(STATE, {"last": 0, "seen": {}, "review": {}, "added": [], "runs": []})
    disc = load(DISC, {"_note": "مصادر أضافها محرك الاكتشاف أو المحرر من قائمة المراجعة. احذف أي سطر للتراجع.", "sources": []})
    added_now = apply_decisions(st, disc)
    for k, c in list(st["review"].items()):  # إعادة تطبيق معايير الرفض على قائمة المراجعة القائمة
        if NON_NEWS_TOPIC.search((c.get("name") or "") + " " + (c.get("desc") or "")) or (c.get("iraq") or 0) < 0.3:
            st["review"].pop(k)
            st["seen"][k] = {"t": time.time(), "decision": "رفض", "why": "إعادة تقييم: ليس إخبارياً أو صلة ضعيفة"}
    due = force or time.time() - st.get("last", 0) >= EVERY_H * 3600 or not st.get("fast_v2")
    report = {"ran": False}
    if due:
        t0 = time.time()
        con = core.connect()
        tg_known, doms = known(con)
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        mentions = Counter()
        tg_low = {k.lower() for k in tg_known}
        for (txt,) in con.execute("SELECT text FROM items WHERE platform='telegram' AND collected_utc >= ?", (since,)):
            for u in re.findall(r"t\.me/([A-Za-z][A-Za-z0-9_]{4,31})", txt or ""):
                if u.lower() not in tg_low and not NOT_NEWS.search(u):
                    mentions[u] += 1
        cutoff = time.time() - 7 * 86400
        fresh = lambda k: k not in st["seen"] or st["seen"][k]["t"] < cutoff  # noqa: E731
        cands = [u for u, _ in mentions.most_common(40) if fresh("tg:" + u) and "tg:" + u not in st["review"]][:12]
        evaluated = []
        for u in cands:
            if time.time() - t0 > 70:
                break
            try:
                evaluated.append(eval_telegram(con, u))
            except Exception as e:  # noqa: BLE001
                evaluated.append({"key": "tg:" + u, "type": "تلغرام", "url": f"https://t.me/{u}", "name": u, "score": 0, "excluded": [f"تعذر الفحص: {type(e).__name__}"]})
            time.sleep(1)
        pubs = gn_publishers()
        site_c = [(u, n) for u, n in pubs.items() if urlsplit(u).netloc.replace("www.", "") not in doms
                  and fresh("web:" + urlsplit(u).netloc.replace("www.", "")) and "web:" + urlsplit(u).netloc.replace("www.", "") not in st["review"]][:8]
        for u, n in site_c:
            if time.time() - t0 > 110:
                break
            try:
                evaluated.append(eval_site(con, u, n))
            except Exception as e:  # noqa: BLE001
                evaluated.append({"key": "web:" + urlsplit(u).netloc, "type": "موقع", "url": u, "name": n, "score": 0, "excluded": [f"تعذر الفحص: {type(e).__name__}"]})
        auto, review, rejected = [], [], []
        for c in evaluated:
            c["at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            ok_tech = c["type"] == "تلغرام" or c.get("feed")
            if not c.get("excluded") and ok_tech and c["score"] >= 65 and c.get("iraq", 0) >= 0.5 and c.get("n24", 0) >= 10 and c.get("original", 0) >= 0.5:
                s = to_source(c)
                if all(x["id"] != s["id"] for x in disc["sources"]):
                    disc["sources"].append(s)
                    auto.append(c)
                st["seen"][c["key"]] = {"t": time.time(), "decision": "إضافة تلقائية", "score": c["score"]}
            elif not c.get("excluded") and ok_tech and c["score"] >= 35:
                st["review"][c["key"]] = c
                review.append(c)
            else:
                st["seen"][c["key"]] = {"t": time.time(), "decision": "رفض", "score": c.get("score"), "why": (c.get("excluded") or ["درجة منخفضة"])[0]}
                rejected.append(c)
        try:
            fast = fast_outlets(con, st, disc, t0, budget=max(30, 200 - (time.time() - t0)))
        except Exception as e:  # noqa: BLE001
            fast = [f"خطأ: {type(e).__name__}"]
        st["fast_v2"] = True
        auto += [{"name": n, "url": "", "score": 0, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")} for n in fast if not n.startswith("خطأ")]
        st["last"] = time.time()
        st["added"] = (st.get("added", []) + [{"name": c["name"], "url": c["url"], "score": c["score"], "at": c["at"]} for c in auto])[-100:]
        report = {"ran": True, "fast_outlets": fast, "candidates_tg": len(cands), "candidates_web": len(site_c), "evaluated": len(evaluated),
                  "auto_added": [c["name"] for c in auto], "to_review": [c["name"] for c in review], "rejected": len(rejected),
                  "secs": round(time.time() - t0, 1)}
        st["runs"] = (st.get("runs", []) + [{**report, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}])[-30:]
        st["last_rejected"] = [{"name": c["name"], "url": c["url"], "score": c.get("score"), "why": (c.get("excluded") or ["درجة منخفضة"])[0]} for c in rejected][-30:]
    if due or added_now:
        DISC.write_text(json.dumps(disc, ensure_ascii=False, indent=1), encoding="utf-8")
        report["commit"] = commit(report.get("auto_added", []) + added_now) if (report.get("auto_added") or added_now) else "لا جديد"
    report["editor_added"] = added_now
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    PWA.mkdir(exist_ok=True)
    (PWA / "discovery.json").write_text(json.dumps({"last_run": datetime.fromtimestamp(st["last"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if st.get("last") else None,
                                                    "every_h": EVERY_H, "total_discovered": len(disc["sources"]), "added": st.get("added", [])[-30:],
                                                    "review": list(st["review"].values())[-40:], "rejected": st.get("last_rejected", []),
                                                    "runs": st.get("runs", [])[-10:]}, ensure_ascii=False), encoding="utf-8")
    print(f"::notice title=discovery::{json.dumps(report, ensure_ascii=False)}")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
