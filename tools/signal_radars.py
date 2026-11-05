"""رادارات الإشارات (مجانية، بلا نموذج لغوي) — خيط خلفي داخل المسار السريع لا يؤخر النشر:

1) الزلازل: USGS (كل 60 ث) + EMSC، دمج الحدث نفسه من المصدرين (فرق وقت ≤60 ث ومسافة <50 كم).
   يُنشر بالقناة «🔴 عاجل | هزة أرضية…» إذا كان المركز داخل العراق بقوة ≥3.5، أو خلال 300 كم من مدينة عراقية بقوة ≥5.0،
   وعمر الحدث ≤15 دقيقة (قاعدة القناة). «تحديث» رداً على المنشور إذا عُدّلت القوة بـ0.3 فأكثر. البصمة مشتركة (tv_sigs.json).
2) انقطاع الإنترنت (IODA، كل 5 د): هبوط ≥30% بمؤشري BGP والفحص النشط معاً مقارنة بوسيط الساعتين السابقتين ← رسالة خاصة للمحررين
   فقط (لا القناة)، مرة لكل حدث وتهدئة ساعتين.
3) قفزات الدولار: قنوات البورصة العامة (معاينة t.me/s، كل 90 ث) ← سعر بغداد/أربيل؛ تغير ≥1.5% خلال 30 دقيقة بالقناة نفسها ←
   مسودة عنوان جاهزة للمحررين بزر نشر (آلية بوابة المراسل). لا نشر تلقائي.
الحالة (أحداث شوهدت، قراءات، آخر تنبيه) في radars_state.json على إصدار fastlane.
"""
import json
import math
import re
import threading
import time
import urllib.request
from datetime import datetime, timezone, timedelta

USGS = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
EMSC = "https://www.seismicportal.eu/fdsnws/event/1/query?format=json&limit=20&minmag=3"
IODA = "https://api.ioda.inetintel.cc.gatech.edu/v2/signals/raw/country/IQ?from={f}&until={u}"
IODA_PAGE = "https://ioda.inetintel.cc.gatech.edu/country/IQ"
ASSET = "radars_state.json"
UA = {"User-Agent": "hobi-ajel-radars/1.0 (+https://t.me/hassawassal)"}
SRC_AR = {"usgs": "المركز الأمريكي للمسح الجيولوجي", "emsc": "المركز الأوروبي المتوسطي لرصد الزلازل"}

Q_EVERY, IODA_EVERY, USD_EVERY = 60, 300, 90
IRAQ_MIN, NEAR_MIN, NEAR_KM = 3.5, 5.0, 300
Q_FRESH_MIN = 15
Q_PER_HOUR = 3
REVISE = 0.3
IODA_DROP, IODA_COOLDOWN = 0.30, 2 * 3600
USD_JUMP, USD_WIN, USD_COOLDOWN = 0.015, 30 * 60, 45 * 60
USD_CH = ["dollarirq", "iqborsa", "borsa_erbil", "dollariraqi", "dollar_price"]
USD_NAMES = {"dollarirq": "بورصة الكفاح والحارثية", "iqborsa": "بيش الدولار اليوم", "borsa_erbil": "بورصة أربيل",
             "dollariraqi": "سعر الدولار في العراق لحظة بلحظة", "dollar_price": "سعر الدولار اليوم"}

# حدود العراق التقريبية (خط طول، خط عرض) — مضلع مبسط يكفي لتمييز الداخل عن دول الجوار بهامش بضعة كيلومترات
IRAQ = [(38.79, 33.38), (39.20, 32.16), (40.40, 31.95), (41.90, 31.20), (44.70, 29.18), (46.55, 29.10), (47.45, 29.35),
        (47.70, 30.10), (48.55, 29.95), (48.10, 30.45), (47.70, 31.00), (47.70, 31.40), (47.00, 32.00), (46.10, 32.90),
        (45.40, 33.97), (45.60, 34.60), (45.90, 35.00), (46.15, 35.10), (45.95, 35.80), (45.50, 36.00), (45.00, 36.80),
        (44.80, 37.15), (44.20, 37.30), (42.80, 37.40), (42.35, 37.10), (41.29, 36.36), (41.00, 34.40)]
CITIES = [("بغداد", 33.31, 44.36), ("البصرة", 30.51, 47.78), ("الموصل", 36.34, 43.13), ("أربيل", 36.19, 44.01), ("كركوك", 35.47, 44.39),
          ("السليمانية", 35.56, 45.43), ("دهوك", 36.87, 42.99), ("النجف", 32.00, 44.33), ("كربلاء", 32.60, 44.02), ("الحلة", 32.48, 44.42),
          ("الناصرية", 31.04, 46.26), ("العمارة", 31.84, 47.14), ("الكوت", 32.51, 45.82), ("الديوانية", 31.99, 44.92), ("السماوة", 31.32, 45.28),
          ("الرمادي", 33.42, 43.30), ("الفلوجة", 33.35, 43.78), ("بعقوبة", 33.75, 44.64), ("تكريت", 34.60, 43.68), ("سامراء", 34.20, 43.87),
          ("حلبجة", 35.18, 45.98), ("زاخو", 37.14, 42.68), ("خانقين", 34.35, 45.38), ("مندلي", 33.75, 45.55), ("بدرة", 33.11, 45.94),
          ("القائم", 34.37, 41.09), ("الرطبة", 33.04, 40.28), ("سنجار", 36.32, 41.87), ("علي الغربي", 32.46, 46.69), ("بنجوين", 35.62, 45.95),
          ("رانية", 36.25, 44.88), ("سوران", 36.65, 44.54), ("دربندخان", 35.11, 45.69), ("كلار", 34.63, 45.32), ("طوزخورماتو", 34.88, 44.63),
          ("الفاو", 29.98, 48.47), ("عانة", 34.47, 41.95), ("هيت", 33.64, 42.83), ("قلعة دزة", 36.18, 45.13), ("جمجمال", 35.53, 44.83)]
COUNTRY_AR = {"iran": "إيران", "turkey": "تركيا", "turkiye": "تركيا", "türkiye": "تركيا", "syria": "سوريا", "iraq": "العراق", "kuwait": "الكويت",
              "saudi arabia": "السعودية", "jordan": "الأردن", "armenia": "أرمينيا", "azerbaijan": "أذربيجان", "georgia": "جورجيا"}
REGION_AR = {"IRAN-IRAQ BORDER REGION": ("المنطقة الحدودية العراقية الإيرانية", "إيران/العراق"), "WESTERN IRAN": ("غرب إيران", "إيران"),
             "NORTHWESTERN IRAN": ("شمال غرب إيران", "إيران"), "SOUTHERN IRAN": ("جنوب إيران", "إيران"), "CENTRAL IRAN": ("وسط إيران", "إيران"),
             "NORTHERN IRAN": ("شمال إيران", "إيران"), "EASTERN TURKEY": ("شرق تركيا", "تركيا"), "TURKEY-IRAN BORDER REGION": ("المنطقة الحدودية التركية الإيرانية", "تركيا/إيران"),
             "TURKEY-SYRIA BORDER REGION": ("المنطقة الحدودية التركية السورية", "تركيا/سوريا"), "CENTRAL TURKEY": ("وسط تركيا", "تركيا"),
             "SOUTHERN TURKEY": ("جنوب تركيا", "تركيا"), "SYRIA": ("سوريا", "سوريا"), "NORTHERN IRAQ": ("شمال العراق", "العراق"),
             "IRAQ": ("العراق", "العراق"), "SOUTHERN IRAQ": ("جنوب العراق", "العراق"), "IRAQ-SYRIA BORDER REGION": ("المنطقة الحدودية العراقية السورية", "العراق/سوريا"),
             "KUWAIT": ("الكويت", "الكويت"), "PERSIAN GULF": ("الخليج", "الخليج"), "JORDAN": ("الأردن", "الأردن"), "NORTHERN AND CENTRAL IRAQ": ("شمال ووسط العراق", "العراق")}
TOWNS_AR = {"sarpol-e zahab": "سربل ذهاب", "qasr-e shirin": "قصر شيرين", "kermanshah": "كرمانشاه", "ilam": "إيلام", "mehran": "مهران",
            "dehloran": "دهلران", "javanrud": "جوانرود", "paveh": "باوه", "marivan": "مريوان", "baneh": "بانه", "sardasht": "سردشت",
            "piranshahr": "بيرانشهر", "ahvaz": "الأهواز", "khorramshahr": "المحمرة", "abadan": "عبادان", "hakkari": "هكاري", "yuksekova": "يوكسكوفا",
            "van": "وان", "sirnak": "شرناخ", "cizre": "جزيرة ابن عمر", "silopi": "سلوبي", "mardin": "ماردين", "diyarbakir": "ديار بكر",
            "malatya": "ملاطية", "kahramanmaras": "كهرمان مرعش", "gaziantep": "غازي عنتاب", "sanliurfa": "شانلي أورفا", "adiyaman": "أديامان",
            "batman": "بطمان", "siirt": "سعرد", "tabriz": "تبريز", "urmia": "أرومية", "khoy": "خوي", "salmas": "سلماس", "qamishli": "القامشلي",
            "al hasakah": "الحسكة", "deir ez-zor": "دير الزور", "halabjah": "حلبجة", "halabja": "حلبجة", "khanaqin": "خانقين"}

STATUS = {"quake": {"ok": None, "err": 0, "seen": 0, "posted": 0, "updates": 0, "last": None},
          "ioda": {"ok": None, "err": 0, "alerts": 0, "drop": None, "last": None},
          "usd": {"ok": None, "err": 0, "readings": 0, "alerts": 0, "last": None}}
STATE = {"quakes": {}, "ioda": {"last_alert": 0, "active": False}, "usd": {"read": {}, "last_alert": {}}, "posts": []}
_LOCK = threading.RLock()


def _now():
    return time.time()


def _get(url, timeout=15):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read(3_000_000).decode("utf-8", "replace"))


def km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(min(1, a)))


def in_iraq(lat, lon):
    inside, n = False, len(IRAQ)
    for i in range(n):
        x1, y1 = IRAQ[i]
        x2, y2 = IRAQ[(i + 1) % n]
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def nearest_city(lat, lon):
    return min(((km(lat, lon, c[1], c[2]), c[0]) for c in CITIES))


# ───────── الزلازل ─────────
def parse_usgs(d):
    out = []
    for f in (d or {}).get("features", []):
        p, g = f.get("properties") or {}, (f.get("geometry") or {}).get("coordinates") or []
        if p.get("type") not in (None, "earthquake") or p.get("mag") is None or len(g) < 2:
            continue
        out.append({"src": "usgs", "id": f"usgs:{f.get('id')}", "t": p["time"] / 1000, "lat": g[1], "lon": g[0], "depth": g[2] if len(g) > 2 else None,
                    "mag": round(float(p["mag"]), 1), "place": p.get("place") or "", "url": p.get("url")})
    return out


def parse_emsc(d):
    out = []
    for f in (d or {}).get("features", []):
        p = f.get("properties") or {}
        if p.get("mag") is None or p.get("lat") is None:
            continue
        try:
            t = datetime.fromisoformat(p["time"].replace("Z", "+00:00")).timestamp()
        except Exception:  # noqa: BLE001
            continue
        out.append({"src": "emsc", "id": f"emsc:{p.get('unid') or f.get('id')}", "t": t, "lat": float(p["lat"]), "lon": float(p["lon"]),
                    "depth": abs(float(p["depth"])) if p.get("depth") is not None else None, "mag": round(float(p["mag"]), 1),
                    "place": p.get("flynn_region") or "", "url": f"https://www.seismicportal.eu/eventdetails.html?unid={p.get('unid')}"})
    return out


def relevant(e):
    """(يُنشر؟, داخل العراق؟, (المسافة، أقرب مدينة))"""
    d, city = nearest_city(e["lat"], e["lon"])
    inside = in_iraq(e["lat"], e["lon"])
    return (inside and e["mag"] >= IRAQ_MIN) or (d <= NEAR_KM and e["mag"] >= NEAR_MIN), inside, (d, city)


def where(e, inside, near):
    d, city = near
    if inside:
        return (f"{city} (العراق)" if d <= 15 else f"منطقة قرب {city} (العراق)")
    place = e.get("place") or ""
    reg = REGION_AR.get(place.upper().strip())
    m = re.search(r"of\s+(.+?),\s*([A-Za-züÜ ]+)$", place) or re.search(r"^(.+?),\s*([A-Za-züÜ ]+)$", place)
    if m:
        town, country = m.group(1).strip().lower(), COUNTRY_AR.get(m.group(2).strip().lower())
        if country:
            t_ar = TOWNS_AR.get(town)
            return f"{('منطقة قرب ' + t_ar + ' (' + country + ')') if t_ar else 'منطقة في ' + country} على بعد {int(round(d, -1)) or int(d)} كم من {city}"
    if reg:
        return f"{reg[0]} ({reg[1]}) على بعد {int(round(d, -1)) or int(d)} كم من {city}"
    return f"منطقة على بعد {int(round(d, -1)) or int(d)} كم من {city}"


def merge(events, known):
    """يدمج الأحداث الجديدة مع المعروفة: الحدث نفسه من مصدرين = فرق ≤60 ث ومسافة <50 كم."""
    for e in sorted(events, key=lambda x: x["t"]):
        hit = None
        for k, q in known.items():
            if e["id"] in q["ids"] or (abs(q["t"] - e["t"]) <= 60 and km(q["lat"], q["lon"], e["lat"], e["lon"]) < 50):
                hit = k
                break
        if hit is None:
            known[e["id"]] = {"ids": [e["id"]], "t": e["t"], "lat": e["lat"], "lon": e["lon"], "depth": e["depth"], "mag": e["mag"],
                              "mags": {e["src"]: e["mag"]}, "srcs": [e["src"]], "place": e["place"], "url": e["url"], "seen": _now(),
                              "posted_mag": None, "msg": None, "upd": 0}
        else:
            q = known[hit]
            if e["id"] not in q["ids"]:
                q["ids"].append(e["id"])
            q["mags"][e["src"]] = e["mag"]
            if e["src"] not in q["srcs"]:
                q["srcs"].append(e["src"])
            if e["src"] == "usgs" or not q.get("place"):  # USGS: اسم بلدة أدق، وقيمته المرجع عند التعارض
                q["place"] = e["place"] or q["place"]
                q["mag"], q["depth"], q["lat"], q["lon"] = e["mag"], e["depth"] if e["depth"] is not None else q["depth"], e["lat"], e["lon"]
            elif "usgs" not in q["mags"]:
                q["mag"] = e["mag"]
    return known


def quake_head(q, inside, near):
    return f"هزة أرضية بقوة {q['mag']:.1f} درجات تضرب {where(q, inside, near)}"


def quake_tick(ctx, fetch=_get):
    evs, ok = [], False
    for url, parse in ((USGS, parse_usgs), (EMSC, parse_emsc)):
        try:
            evs += parse(fetch(url))
            ok = True
        except Exception:  # noqa: BLE001
            STATUS["quake"]["err"] += 1
    if not ok:
        STATUS["quake"]["ok"] = False
        return 0
    STATUS["quake"].update(ok=True, last=_iso())
    now = _now()
    with _LOCK:
        known = STATE["quakes"]
        for k in [k for k, q in known.items() if now - q["t"] > 48 * 3600]:
            known.pop(k)
        merge([e for e in evs if now - e["t"] <= 6 * 3600], known)
        STATUS["quake"]["seen"] = len(known)
        items = list(known.items())
    posted = 0
    for k, q in items:
        go, inside, near = relevant(q)
        if not go:
            continue
        if q["msg"] is None and q.get("posted_mag") is None:
            if now - q["t"] > Q_FRESH_MIN * 60:
                q["posted_mag"] = -1  # قديم: لا نشر (لا خبر عمره أكثر من 15 دقيقة)
                continue
            STATE["posts"] = [t for t in STATE["posts"] if t >= now - 3600]
            if len(STATE["posts"]) >= Q_PER_HOUR:
                continue
            head = quake_head(q, inside, near)
            when = (datetime.fromtimestamp(q["t"], timezone.utc) + timedelta(hours=3)).strftime("%H:%M")
            extra = f"العمق: {int(round(q['depth'] or 0))} كم — الوقت: {when} بتوقيت بغداد" + ("" if inside else f"\nأقرب مدينة عراقية: {near[1]} ({int(near[0])} كم)")
            src = " / ".join(SRC_AR[s] for s in q["srcs"])
            q["posted_mag"] = q["mag"]  # قبل الإرسال: لا محاولة ثانية إذا فشل (يمنع التكرار)
            ok_, _msg, mid = ctx["send"](head, True, src, extra, f"radar:quake:{k}")
            if ok_:
                q["msg"] = mid
                STATE["posts"].append(now)
                STATUS["quake"]["posted"] += 1
                posted += 1
        elif q["msg"] and q["posted_mag"] and q["posted_mag"] > 0 and abs(q["mag"] - q["posted_mag"]) >= REVISE and q["upd"] < 2:
            src = SRC_AR["usgs" if "usgs" in q["mags"] else q["srcs"][-1]]
            txt = f"🔄 تحديث | عدّل {src} قوة الهزة إلى {q['mag']:.1f} درجات (كانت {q['posted_mag']:.1f})"
            q["posted_mag"], q["upd"] = q["mag"], q["upd"] + 1
            if ctx["reply"](q["msg"], txt):
                STATUS["quake"]["updates"] += 1
    return posted


# ───────── IODA ─────────
def _series(d, name):
    for s in ((d or {}).get("data") or [[]])[0]:
        if s.get("datasource") == name and isinstance(s.get("values"), list):
            return s["from"], s["step"], s["values"]
    return None


def drop_of(d, name, now):
    s = _series(d, name)
    if not s:
        return None
    f, step, vals = s
    pts = [(f + i * step, v) for i, v in enumerate(vals) if isinstance(v, (int, float))]
    cur = [v for t, v in pts if t >= now - 40 * 60][-2:]
    base = sorted(v for t, v in pts if now - 150 * 60 <= t < now - 30 * 60)
    if not cur or len(base) < 4:
        return None
    med = base[len(base) // 2]
    return None if med <= 0 else max(0.0, 1 - (sum(cur) / len(cur)) / med)


def ioda_tick(ctx, fetch=_get):
    now = _now()
    try:
        d = fetch(IODA.format(f=int(now - 3 * 3600), u=int(now)), timeout=25)
    except Exception:  # noqa: BLE001
        STATUS["ioda"].update(ok=False, err=STATUS["ioda"]["err"] + 1)
        return False
    bgp, ping = drop_of(d, "bgp", now), drop_of(d, "ping-slash24", now)
    STATUS["ioda"].update(ok=True, last=_iso(), drop={"bgp": None if bgp is None else round(bgp, 3), "ping": None if ping is None else round(ping, 3)})
    st = STATE["ioda"]
    hit = bgp is not None and ping is not None and bgp >= IODA_DROP and ping >= IODA_DROP
    if not hit:
        if bgp is not None and ping is not None and bgp < IODA_DROP / 2 and ping < IODA_DROP / 2:
            st["active"] = False  # عاد طبيعياً: الحدث انتهى
        return False
    if st.get("active") or now - st.get("last_alert", 0) < IODA_COOLDOWN:
        return False
    st.update(active=True, last_alert=now)
    txt = (f"⚠️ مؤشر انقطاع إنترنت في العراق: هبوط مسارات BGP بنسبة {bgp:.0%} والاستجابة للفحص النشط بنسبة {ping:.0%} "
           f"مقارنة بالساعتين السابقتين (IODA — معهد جورجيا للتقنية).\n{IODA_PAGE}\n\nهذا تنبيه للمحررين فقط، لا يُنشر بالقناة. "
           "تحقق (امتحانات وزارية؟ عطل؟ قرار رسمي؟) قبل أي نشر.")
    ctx["dm"](txt, None)
    STATUS["ioda"]["alerts"] += 1
    return True


# ───────── الدولار ─────────
CITY_RX = {"بغداد": re.compile(r"بغداد|الكفاح|الحارثية"), "أربيل": re.compile(r"أربيل|اربيل|هەولێر|هه‌ولێر|Erbil", re.I)}
NUM_RX = re.compile(r"(?<![\d.,،])(1\d{2})[.,،](\d{3})(?![\d.,،])|(?<![\d.,،])(1\d{5})(?![\d.,،])|(?<![\d.,،])(1[2-9]\d{2})(?![\d.,،])")
AR_DIG = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _rate(s):
    m = NUM_RX.search(s.translate(AR_DIG))
    if not m:
        return None
    v = int(m.group(1) + m.group(2)) if m.group(1) else int(m.group(3) or 0) or int(m.group(4)) * 100
    return v if 120_000 <= v <= 250_000 else None


def parse_rates(text):
    """{مدينة: سعر لكل 100 دولار} من منشور بورصة («بغداد / 168,100»، «سعر الدولار - بغداد\\n168.250»، «دۆلار هەولێر 168,150»)."""
    t = (text or "").translate(AR_DIG)
    if not re.search(r"دولار|دۆلار|\$|💵", t) or re.search(r"الذهب|ذهب|عيار", t[:40]):
        return {}
    lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
    out = {}
    for city, rx in CITY_RX.items():
        for i, ln in enumerate(lines):
            if not rx.search(ln) or re.search(r"الصيرفات|صيرفة|حوالات|حوالة", ln):
                continue
            seg = ln[rx.search(ln).end():]
            v = _rate(seg)
            j = i + 1
            while v is None and j < min(len(lines), i + 3):
                if any(r.search(lines[j]) for r in CITY_RX.values()):
                    break
                v = _rate(lines[j])
                j += 1
            if v:
                out[city] = v
                break
    return out


def usd_tick(ctx, posts_fn):
    now = _now()
    st = STATE["usd"]
    ok_any = False
    for ch in USD_CH:
        try:
            posts, _ = posts_fn(ch)
            ok_any = True
        except Exception:  # noqa: BLE001
            STATUS["usd"]["err"] += 1
            continue
        for p in posts:
            ts = p["t"].timestamp() if hasattr(p["t"], "timestamp") else float(p["t"])
            if now - ts > 3 * 3600:
                continue
            for city, v in parse_rates(p["text"]).items():
                key = f"{ch}|{city}"
                rs = st["read"].setdefault(key, [])
                if any(r[2] == p["id"] for r in rs):
                    continue
                rs.append([ts, v, p["id"]])
                rs.sort()
                del rs[:-40]
                STATUS["usd"]["readings"] += 1
                if now - ts > 20 * 60:
                    continue  # قراءة قديمة: خط أساس فقط
                prev = [r for r in rs if ts - USD_WIN <= r[0] < ts and r[2] != p["id"]]
                if not prev:
                    continue
                ref = max(prev, key=lambda r: abs(v - r[1]))
                ch_pct = (v - ref[1]) / ref[1]
                if abs(ch_pct) < USD_JUMP or abs(ch_pct) > 0.15:  # أكثر من 15% = خطأ قراءة على الأغلب
                    continue
                if now - st["last_alert"].get(city, 0) < USD_COOLDOWN:
                    continue
                st["last_alert"][city] = now
                up = ch_pct > 0
                mins = max(1, int((ts - ref[0]) / 60))
                head = f"{'ارتفاع' if up else 'انخفاض'} سعر صرف الدولار في بورصة {city} إلى {v:,} دينار لكل 100 دولار"
                det = f"بعد أن كان {ref[1]:,} دينار قبل {mins} دقيقة ({'+' if up else '−'}{abs(ch_pct):.1%})"
                ctx["draft"](head, [det], USD_NAMES.get(ch, ch), f"usd:{city}:{int(now)}")
                STATUS["usd"]["alerts"] += 1
    STATUS["usd"].update(ok=ok_any, last=_iso() if ok_any else STATUS["usd"]["last"])


# ───────── التشغيل ─────────
def _iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_ctx(token, chat_id, api=None):
    """دوال الإرسال الحقيقية: النشر بالقناة عبر manual_pub.send_card (تكرار/بصمة/تطبيق)، والرسائل الخاصة للمحررين."""
    from tools import manual_pub as MP
    from tools import tg_push as T
    api = api or T.api

    def send(head, hot, src, extra, ref):
        return MP.send_card(token, chat_id, head, hot, src, extra, None, ref, "رادار", api=api, two_stage=True)

    def reply(mid, txt):
        try:
            return bool(api(token, "sendMessage", chat_id=chat_id, reply_to_message_id=mid, text=txt, disable_notification="true").get("ok"))
        except Exception:  # noqa: BLE001
            return False

    def dm(txt, _):
        for uid in MP.editors(token, chat_id):
            try:
                api(token, "sendMessage", chat_id=uid, text=txt, disable_web_page_preview="true")
            except Exception:  # noqa: BLE001
                pass  # محرر لم يبدأ محادثة مع البوت

    def draft(head, details, src, group):
        for uid in MP.editors(token, chat_id):
            MP.new_draft(token, api, uid, uid, head, details, src, None, note="💵 رادار الدولار: تغير سريع بقناة البورصة. تحقق من قراءة ثانية قبل النشر.",
                         kind="usd", group=group)
    return {"send": send, "reply": reply, "dm": dm, "draft": draft}


def start(token, chat_id, until, posts_fn, load=None, save=None, api=None):
    """خيط خلفي (daemon): لا يرفع استثناء، ولا يؤخر حلقة النشر."""
    try:
        d = load() if load else None
        if isinstance(d, dict):
            for k in ("quakes", "ioda", "usd"):
                if isinstance(d.get(k), dict):
                    STATE[k] = d[k]
            STATE["usd"].setdefault("read", {})
            STATE["usd"].setdefault("last_alert", {})
    except Exception:  # noqa: BLE001
        pass
    ctx = make_ctx(token, chat_id, api)

    def run():
        nxt = {"q": 0, "i": 0, "u": 0, "s": _now() + 300}
        while _now() < until:
            for k, every, fn in (("q", Q_EVERY, lambda: quake_tick(ctx)), ("i", IODA_EVERY, lambda: ioda_tick(ctx)),
                                 ("u", USD_EVERY, lambda: usd_tick(ctx, posts_fn))):
                if _now() >= nxt[k]:
                    nxt[k] = _now() + every
                    try:
                        fn()
                    except Exception as e:  # noqa: BLE001
                        print("::warning title=radar::", k, type(e).__name__, str(e)[:80])
            if save and _now() >= nxt["s"]:
                nxt["s"] = _now() + 300
                try:
                    with _LOCK:
                        snap = json.loads(json.dumps({"quakes": STATE["quakes"], "ioda": STATE["ioda"], "usd": STATE["usd"], "at": _iso()}))
                    save(snap)
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(5)
    threading.Thread(target=run, daemon=True, name="radars").start()


def status():
    return json.loads(json.dumps(STATUS))
