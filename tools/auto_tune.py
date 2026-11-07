"""الضبط الذاتي لمصادر المسار السريع (مرة يومياً داخل الجولة الرئيسية بعد موثوقية المصادر، بلا نموذج لغوي وبلا كلفة).

يقرأ: أرشيف الرصد (آخر 5 أيام)، source_trust.json (pwa/ أو إصدار fastlane)، fast_decisions.json وfastlane_auto.json السابق (إصدار fastlane).
يكتب: fastlane_auto.json على إصدار fastlane = {updated_utc, promote, demote, why, candidates, today, ...}. config/fastlane.json لا يتغير:
fastlane.py يدمج القائمتين في الذاكرة عند البدء وكل ~300 دورة (merge أدناه).

- ترقية (قناة تلغرام ليست في أي طبقة): طبقة «موثوقة»، أو «عادية» بسبق ≥20% وn≥30 ووسيط تأخر ≤5 د؛ وأول ناشر لـ3 أحداث فأكثر
  (5 جهات فأكثر) خلال 5 أيام؛ لا جهة مستبعدة؛ سقف 10 يومياً و60 إجمالاً. الترقيات السابقة تبقى ما لم تنطبق عليها قاعدة تنزيل.
- تنزيل (يوقف الفحص السريع فقط، الجمع العادي مستمر): قناة سريعة غير رسمية وغير منافسة بطبقة «ضعيفة»، أو بلا أي منشور نصي مجموع
  خلال 72 ساعة (مع جمع ناجح للمصدر خلال 24 ساعة)، أو ≥90% من قراراتها السريعة خلال 3 أيام not_iraq/dup/low_value (20 قراراً فأكثر؛
  القنوات العربية/الدولية «intl» معفاة من هذه القاعدة لأن «ليس عراقياً» طبيعي فيها). سقف 10 يومياً، والتنزيل يبقى 7 أيام ثم يُعاد التقييم.
- مرشحون للاكتشاف: أكثر 15 قناة/موقعاً غير مرصود يستشهد بها المرصودون (روابط t.me و@معرّف وروابط المواقع، آخر 3 أيام، مصدران مستشهدان
  على الأقل). لا تُضاف آلياً: وكيل التطوير الأسبوعي يتحقق منها.

تشغيل: python3 -m tools.auto_tune [--db PATH] [--trust F] [--decisions F] [--prev F] [--force] [--no-upload] [--out F]
"""
import json
import re
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ASSET = "fastlane_auto.json"
TIER_KEYS = ("breaking", "hot", "agency", "intl", "loud")  # طبقات غير رسمية؛ «channels» = الجهات الرسمية لا تُمس
DAYS_FIRST, MIN_SRC, MIN_FIRST = 5, 5, 3
PRO_FIRST_RATE, PRO_N, PRO_LAG = 0.20, 30, 5.0
CAP_DAY, CAP_TOTAL = 10, 60
SILENT_H, DEC_DAYS, DEC_MIN, DEC_BAD = 72, 3, 20, 0.90
BAD_REASONS = {"not_iraq", "dup", "low_value"}
DEMOTE_DAYS = 7
CAND_DAYS, CAND_TOP, CAND_MIN_SRC = 3, 15, 2
REFRESH_H = 20
FOREIGN_RX = re.compile(r"(إيران|ايران|طهران|خامنئي|لبنان|بيروت|سوريا|دمشق|إسرائيل|اسرائيل|الاحتلال|غزة|فلسطين|اليمن|صنعاء|السعودية|"
                        r"أمريك|امريك|واشنطن|ترامب|ترمب|روسيا|أوكرانيا|الصين|تركيا|مصر|الأردن|الخليج|الكويت|قطر|الإمارات)")
FOREIGN_STATE = re.compile(r"(khamenei|presstv|irna|mehrnews|isna_|tasnim|farsna|sputnik|rtarabic)", re.I)  # حسابات دول/قادة أجانب ليست مصادر أخبار عراقية
KURDISH = re.compile(r"[ەێۆڵڕڤ]")
HANDLE = re.compile(r"[A-Za-z][A-Za-z0-9_]{3,31}")
OWN = {"hassawassal", "akamedia_iq"}
SOCIAL = re.compile(r"(^|\.)(t\.me|telegram\.me|telegram\.org|youtube\.com|youtu\.be|facebook\.com|fb\.com|fb\.watch|instagram\.com|twitter\.com|x\.com|"
                    r"tiktok\.com|whatsapp\.com|wa\.me|threads\.net|snapchat\.com|linkedin\.com|google\.[a-z.]+|goo\.gl|bit\.ly|tinyurl\.com|linktr\.ee|"
                    r"apple\.com|play\.google\.com|wikipedia\.org|cutt\.ly|shorturl\.at|rb\.gy|t\.co|ow\.ly|is\.gd)$", re.I)


def _excluded(s):
    from marsad.cli import EXCLUDED_SRC
    return bool(EXCLUDED_SRC.search(s or ""))


def _ts(s):
    try:
        return datetime.fromisoformat((s or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _handle(sid):
    m = re.match(r"telegram:t\.me/([A-Za-z0-9_]+)$", sid or "")
    return m.group(1) if m else None


def valid_handle(u):
    return isinstance(u, str) and bool(HANDLE.fullmatch(u)) and not _excluded(u) and u.lower() not in OWN


# ---------------------------------------------------------------- الدمج (يستعمله fastlane.py)
def merge(base, auto):
    """base = طبقات config/fastlane.json الأصلية. يعيد قواميس الطبقات بعد الدمج (في الذاكرة فقط):
    «demote» تُحذف من الطبقات غير الرسمية (لا تُحذف قناة رسمية أبداً)، و«promote» تُضاف إلى «breaking» إذا لم تكن بأي طبقة."""
    out = {k: list(base.get(k) or []) for k in ("channels",) + TIER_KEYS}
    if not isinstance(auto, dict):
        return out
    off = {c.lower() for c in out["channels"]}
    # 07/11: وكالات/قنوات كبرى (Sky، CNN، BBC، الشرق الأوسط، K24…) نُزّلت لأن الجامع النصي لا يقرأها رغم أن المستمع يستقبلها —
    # الطبقتان الدولية والوكالات وقائمة never_demote لا تُنزَّل أبداً
    off |= {c.lower() for k in ("intl", "agency") for c in out.get(k, [])} | {c.lower() for c in base.get("never_demote") or []}
    known = {c.lower() for k in out for c in out[k]}
    dem = {u.lower() for u in auto.get("demote") or [] if isinstance(u, str)} - off
    for k in TIER_KEYS:
        out[k] = [c for c in out[k] if c.lower() not in dem]
    seen = set()
    for u in auto.get("promote") or []:
        if valid_handle(u) and u.lower() not in known | dem | seen and len(seen) < CAP_TOTAL:
            seen.add(u.lower())
            out["breaking"].append(u)
    return out


# ---------------------------------------------------------------- الحساب
def is_iraqi(title):
    from tools import tg_push as T
    return bool(T.iraq_strict(title or "") or T.iraq_domestic(title or ""))


def first_counts(con, now, days=DAYS_FIRST, min_src=MIN_SRC):
    """sid ← عدد الأحداث العراقية (min_src جهة فأكثر، آخر days يوم) التي كان فيها أول ناشر (وقت نشر موثوق كما في reliability).
    وأيضاً sid ← (عدد العناوين، عدد الكردية) لاستبعاد القنوات غير العربية (المسار السريع عربي)."""
    since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cl, lang = {}, {}
    for sid, pub, col, prec, cid, title in con.execute(
            "SELECT source_id, published_utc, collected_utc, time_precision, cluster_id, title FROM items "
            "WHERE COALESCE(published_utc, collected_utc) >= ? AND cluster_id IS NOT NULL", (since,)):
        tp, tc = (_ts(pub) if pub and prec != "approx" else None), _ts(col)
        good = bool(tp and tc and -300 <= tc - tp <= 3 * 3600)
        cl.setdefault(cid, []).append((tp if good else 9e18, sid, title or "", good))
        lg = lang.setdefault(sid, [0, 0])
        lg[0] += 1
        lg[1] += bool(KURDISH.search(title or ""))
    out = {}
    for its in cl.values():
        if len({x[1] for x in its}) < min_src:
            continue
        good = sorted(x for x in its if x[3])
        if not good or not is_iraqi(good[0][2]):
            continue  # الحدث غير عراقي (سانا أول ناشر لأخبار سوريا لا يفيد قناة أخبار العراق)
        t0 = good[0][0]
        for s in {x[1] for x in good if x[0] <= t0 + 1}:
            out[s] = out.get(s, 0) + 1
    return out, lang


def tally_decisions(decisions, prev_tally, now):
    """{يوم: {قناة: [سيئ، الكل]}} لآخر 3 أيام. fast_decisions.json يحمل آخر ~400 قرار فقط، فنحتفظ بعدّاد يومي في الملف نفسه
    ونأخذ الأكبر لكل (يوم، قناة) حتى لا يُعدّ القرار مرتين."""
    items = (decisions or {}).get("items") if isinstance(decisions, dict) else decisions
    cur = {}
    for x in items or []:
        if not isinstance(x, dict) or not x.get("ch") or x.get("decision") not in ("skip", "post", "fail"):
            continue
        day = (x.get("t") or "")[:10]
        c = cur.setdefault(day, {}).setdefault(x["ch"], [0, 0])
        c[0] += x.get("reason") in BAD_REASONS
        c[1] += 1
    lo = (now - timedelta(days=DEC_DAYS)).strftime("%Y-%m-%d")
    out = {}
    for day in set(cur) | set(prev_tally or {}):
        if day < lo:
            continue
        a, b = (prev_tally or {}).get(day) or {}, cur.get(day) or {}
        out[day] = {ch: max(a.get(ch, [0, 0]), b.get(ch, [0, 0]), key=lambda v: v[1]) for ch in set(a) | set(b)}
    return out


def silent_channels(con, now, handles):
    """قنوات (من handles) جُمع مصدرها بنجاح خلال 24 ساعة ولم يُجمع لها أي منشور نصي خلال 72 ساعة."""
    lo72 = (now - timedelta(hours=SILENT_H)).strftime("%Y-%m-%dT%H:%M:%SZ")
    lo24 = (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    by_low = {}
    for (sid,) in con.execute("SELECT id FROM sources WHERE id LIKE 'telegram:t.me/%'"):
        h = _handle(sid)
        if h:
            by_low[h.lower()] = sid
    out = []
    for h in handles:
        sid = by_low.get(h.lower())
        if not sid:
            continue  # ليس بالجمع العادي: لا نعرف نشاطه
        ok = con.execute("SELECT 1 FROM fetch_log WHERE source_id=? AND ok=1 AND at_utc >= ? LIMIT 1", (sid, lo24)).fetchone()
        if not ok:
            continue  # تعطل الجمع لا يعني سكوت القناة
        n = con.execute("SELECT COUNT(*) FROM items WHERE source_id=? AND collected_utc >= ? AND LENGTH(TRIM(COALESCE(text, title, ''))) >= 20",
                        (sid, lo72)).fetchone()[0]
        if n == 0:
            out.append(h)
    return out


URL_RX = re.compile(r"https?://([A-Za-z0-9.-]+\.[A-Za-z]{2,})(?=[/?#:\s\"'<>)]|$)(/[^\s\"'<>)]*)?", re.I)  # «https://www.kurd…» المبتور لا يُعد
TME_RX = re.compile(r"(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})\b", re.I)
AT_RX = re.compile(r"(?<![\w.@/])@([A-Za-z][A-Za-z0-9_]{4,31})\b")


def _root(host):
    h = host.lower().lstrip(".")
    h = h[4:] if h.startswith("www.") else h
    parts = h.split(".")
    if len(parts) >= 3 and parts[-2] in ("com", "net", "org", "gov", "edu", "co", "news") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def candidates(con, now, monitored_tg, monitored_hosts, top=CAND_TOP):
    """أكثر القنوات/المواقع غير المرصودة استشهاداً لدى المصادر المرصودة (عدد المصادر المستشهدة، ثم عدد الإشارات)."""
    from tools.discover import NOT_NEWS
    since = (now - timedelta(days=CAND_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mon_tg = {h.lower() for h in monitored_tg}
    mon_roots = {_root(h) for h in monitored_hosts if h}
    tg, site = {}, {}
    names = {}
    iq_src = {sid for sid, reg in con.execute("SELECT id, region FROM sources") if reg and not re.search(r"(أجنبي|إقليمي|عربي|دولي|إيران)", reg)}
    for sid, sname, title, text, url in con.execute("SELECT source_id, source_name, title, text, url FROM items WHERE collected_utc >= ?", (since,)):
        blob = text or ""
        if not (is_iraqi(title) or (sid in iq_src and not FOREIGN_RX.search(title or ""))):
            continue  # الاستشهاد في خبر عراقي أو لدى مصدر عراقي بخبر غير أجنبي (قناة خامنئي يستشهد بها الإعلام الإيراني في أخبار إيران)
        own = (_handle(sid) or "").lower()
        names.setdefault(sid, re.sub(r"\s*—\s*(telegram|RSS|rss)$", "", sname or sid))
        for u in set(TME_RX.findall(blob)) | set(AT_RX.findall(blob)):
            lu = u.lower()
            if lu == own or lu in mon_tg or lu in OWN or NOT_NEWS.search(u) or lu.endswith("bot") or _excluded(u) or FOREIGN_STATE.search(u):
                continue
            tg.setdefault(lu, {"u": u, "src": set(), "n": 0})
            tg[lu]["src"].add(sid)
            tg[lu]["n"] += 1
        for host, _p in URL_RX.findall(blob):
            r = _root(host)
            if SOCIAL.search(host.lower()) or SOCIAL.search(r) or r in mon_roots or _excluded(host) or "." not in r or \
                    (len(r.split(".")[0]) <= 4 and not r.endswith(".iq")):  # مختصِر روابط (f24.my، n9.cl، edgs.co)
                continue
            if (url or "") and _root(re.sub(r"^https?://([^/]+).*$", r"\1", url)) == r:
                continue  # المصدر يستشهد بموقعه هو
            site.setdefault(r, {"u": r, "src": set(), "n": 0})
            site[r]["src"].add(sid)
            site[r]["n"] += 1
    rows = [{"kind": "telegram", "ref": f"t.me/{v['u']}", "cited_by": len(v["src"]), "mentions": v["n"],
             "examples": sorted(names.get(s, s) for s in v["src"])[:3]} for v in tg.values()]
    rows += [{"kind": "site", "ref": v["u"], "cited_by": len(v["src"]), "mentions": v["n"],
              "examples": sorted(names.get(s, s) for s in v["src"])[:3]} for v in site.values()]
    rows = [r for r in rows if r["cited_by"] >= CAND_MIN_SRC]
    rows.sort(key=lambda r: (-r["cited_by"], -r["mentions"], r["ref"]))
    return rows[:top]


def _competitor_handles():
    try:
        g = json.loads((ROOT / "config" / "competitors.json").read_text(encoding="utf-8"))["groups"]
    except Exception:  # noqa: BLE001
        return set()
    return {_handle(s).lower() for ids in g.values() for s in ids if _handle(s)}


def _monitored(con):
    """قنوات ومواقع بالجمع العادي (القاعدة + sources.json + discovered.json)."""
    tg, hosts = set(), set()
    rows = [(r[0], r[1]) for r in con.execute("SELECT id, url FROM sources")]
    for f in ("sources.json", "discovered.json"):
        try:
            rows += [(s.get("id"), s.get("url")) for s in json.loads((ROOT / "config" / f).read_text(encoding="utf-8"))["sources"]]
        except Exception:  # noqa: BLE001
            pass
    for sid, url in rows:
        h = _handle(sid or "")
        m = re.search(r"t\.me/(?:s/)?([A-Za-z0-9_]+)", url or "")
        if h or m:
            tg.add((h or m.group(1)).lower())
        else:
            host = re.sub(r"^https?://([^/]+).*$", r"\1", (url or "").lower())
            for d in re.findall(r"site:([\w.\-]+)", url or "") + ([host] if "google" not in host and "." in host else []):
                hosts.add(d)
    return tg, hosts


def compute(con, trust, decisions, prev, cfg, now=None):
    now = now or datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    prev = prev if isinstance(prev, dict) else {}
    srcs = (trust or {}).get("sources") or {}
    base = {k: list(cfg.get(k) or []) for k in ("channels",) + TIER_KEYS}
    official = {c.lower() for c in base["channels"]}
    in_tier = {c.lower() for k in base for c in base[k]}
    comp = _competitor_handles()
    never = {str(c).lower() for c in cfg.get("auto_never") or []}  # قرار تحريري: قنوات لا تُرقّى آلياً أبداً (مفتاح اختياري في config/fastlane.json)
    intl = {c.lower() for c in base["intl"]}
    why = {}
    firsts, lang = first_counts(con, now)

    # ---- التنزيل: القنوات السريعة الحالية غير الرسمية وغير المنافسة (طبقات الإعداد + الترقيات السابقة)
    prev_dem = {u: d for u, d in (prev.get("demoted_at") or {}).items() if isinstance(u, str)}
    keep_dem = {u: d for u, d in prev_dem.items() if (_ts(d + "T00:00:00Z") or 0) >= (now - timedelta(days=DEMOTE_DAYS)).timestamp()
                and u.lower() not in official}
    prev_pro = [u for u in prev.get("promote") or [] if valid_handle(u) and u.lower() not in in_tier and u.lower() not in never]
    fast = list(dict.fromkeys([c for k in TIER_KEYS for c in base[k]] + prev_pro))
    fast = [c for c in fast if c.lower() not in official and c.lower() not in comp and not c.startswith("rss:")]
    kept_low = {u.lower() for u in keep_dem}
    tally = tally_decisions(decisions, prev.get("decision_tally"), now)
    dec = {}
    for day in tally.values():
        for ch, (b, n) in day.items():
            d = dec.setdefault(ch.lower(), [0, 0])
            d[0] += b
            d[1] += n
    silent = {h.lower() for h in silent_channels(con, now, fast)}
    new_dem = []
    for c in fast:
        lc = c.lower()
        if lc in kept_low:
            continue
        t = (srcs.get(f"telegram:t.me/{c}") or {})
        if not t:
            t = next((r for s, r in srcs.items() if (_handle(s) or "").lower() == lc), {})
        b, n = dec.get(lc, [0, 0])
        reason = None
        if t.get("tier") == "ضعيفة":
            reason = f"طبقة «ضعيفة» (درجة {t.get('score')}، نفي {round(100 * (t.get('denied_rate') or 0), 1)}%)"
        elif lc in silent:
            reason = "لا منشور نصي مجموع خلال 72 ساعة رغم نجاح الجمع"
        elif lc not in intl and n >= DEC_MIN and b / n >= DEC_BAD:
            reason = f"{b}/{n} من قراراتها السريعة خلال 3 أيام ليس عراقياً/مكرر/قيمة منخفضة"
        if reason:
            new_dem.append((0 if t.get("tier") == "ضعيفة" else 1 if lc in silent else 2, -n, c, reason))
    new_dem.sort()
    new_dem = new_dem[:CAP_DAY]
    demoted_at = dict(keep_dem)
    for *_x, c, reason in new_dem:
        demoted_at[c] = today
        why[c] = "تنزيل: " + reason
    for u in keep_dem:
        why.setdefault(u, (prev.get("why") or {}).get(u) or "تنزيل سابق")
    dem_low = {u.lower() for u in demoted_at}

    # ---- الترقية
    pro_kept = [u for u in prev_pro if u.lower() not in dem_low]
    for u in pro_kept:
        why[u] = (prev.get("why") or {}).get(u) or "ترقية سابقة"
    pro_at = {u: d for u, d in (prev.get("promoted_at") or {}).items() if u in pro_kept}
    cands = []
    for sid, r in srcs.items():
        h = _handle(sid)
        if not h or h.lower() in in_tier or h.lower() in never or h.lower() in dem_low or h.lower() in {u.lower() for u in pro_kept}:
            continue
        if not valid_handle(h) or _excluded(f"{sid} {r.get('name')} {r.get('url')}"):
            continue
        tier, fr, n, lag = r.get("tier"), r.get("first_rate") or 0, r.get("n") or 0, r.get("median_lead_min")
        ok_tier = tier == "موثوقة" or (tier == "عادية" and fr >= PRO_FIRST_RATE and n >= PRO_N and lag is not None and lag <= PRO_LAG)
        fc = firsts.get(sid, 0)
        nt, nk = lang.get(sid, [0, 0])
        if nt and nk / nt > 0.3:
            continue  # قناة كردية: المسار السريع ينشر بالعربية
        if ok_tier and fc >= MIN_FIRST:
            cands.append((-fc, -fr, h, tier, fr, n, lag, fc, r.get("name"), sid))
    cands.sort()
    dbname = {r[0]: re.sub(r"\s*—\s*telegram$", "", r[1] or "") for r in con.execute("SELECT id, name FROM sources WHERE id LIKE 'telegram:%'")}
    room = max(0, CAP_TOTAL - len(pro_kept))
    new_pro = cands[:min(CAP_DAY, room)]
    for _a, _b, h, tier, fr, n, lag, fc, name, sid in new_pro:
        pro_at[h] = today
        why[h] = (f"ترقية: {dbname.get(sid) or re.sub(r' — .*$', '', name or h)} (@{h}) — طبقة «{tier}»، أول ناشر لـ{fc} حدثاً (5 جهات فأكثر) خلال 5 أيام، "
                  f"سبق {round(100 * fr)}%، n={n}، وسيط التأخر {lag} د")
    promote = pro_kept + [x[2] for x in new_pro]

    mon_tg, mon_hosts = _monitored(con)
    cand = candidates(con, now, mon_tg | in_tier | {u.lower() for u in promote}, mon_hosts)
    return {"updated_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "promote": promote, "demote": sorted(demoted_at), "why": why,
            "candidates": cand, "today": {"promoted": [x[2] for x in new_pro], "demoted": [x[2] for x in new_dem]},
            "promoted_at": pro_at, "demoted_at": demoted_at, "decision_tally": tally,
            "rules": {"promote": f"موثوقة، أو عادية بسبق ≥{int(PRO_FIRST_RATE * 100)}% وn≥{PRO_N} ووسيط تأخر ≤{PRO_LAG:g} د؛ وأول ناشر ≥{MIN_FIRST} أحداث "
                                 f"(≥{MIN_SRC} جهات) خلال {DAYS_FIRST} أيام؛ سقف {CAP_DAY}/يوم و{CAP_TOTAL} إجمالاً",
                      "demote": f"غير رسمية وغير منافسة: ضعيفة، أو صامتة {SILENT_H} ساعة، أو ≥{int(DEC_BAD * 100)}% قرارات not_iraq/dup/low_value "
                                f"(≥{DEC_MIN} قراراً، {DEC_DAYS} أيام، intl معفاة)؛ سقف {CAP_DAY}/يوم، يبقى {DEMOTE_DAYS} أيام",
                      "candidates": "للمراجعة الأسبوعية فقط، لا تُضاف آلياً"}}


def summary_line(d):
    """سطر تقرير 11 مساءً: «🤖 ضبط ذاتي: +N للمسار السريع، −M، مرشحون K» (من ضبط اليوم)."""
    if not isinstance(d, dict) or not d.get("updated_utc"):
        return ""
    t = d.get("today") or {}
    return (f"🤖 ضبط ذاتي: +{len(t.get('promoted') or [])} للمسار السريع، −{len(t.get('demoted') or [])}، مرشحون {len(d.get('candidates') or [])}"
            f" (المجموع: {len(d.get('promote') or [])} مُرقّاة، {len(d.get('demote') or [])} مُنزّلة)")


# ---------------------------------------------------------------- التشغيل
def gh_get(asset):
    try:
        with tempfile.TemporaryDirectory() as td:
            r = subprocess.run(["gh", "release", "download", "fastlane", "-p", asset, "-D", td, "--clobber"], capture_output=True, timeout=30)
            return json.loads((Path(td) / asset).read_text(encoding="utf-8")) if r.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def _load(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    arg = lambda k: argv[argv.index(k) + 1] if k in argv else None  # noqa: E731
    upload, force = "--no-upload" not in argv, "--force" in argv
    now = datetime.now(timezone.utc)
    prev = _load(arg("--prev")) if arg("--prev") else (gh_get(ASSET) if upload else None)
    if not force and isinstance(prev, dict) and now.timestamp() - (_ts(prev.get("updated_utc")) or 0) < REFRESH_H * 3600:
        print(f"::notice title=auto_tune::ضبط اليوم موجود ({prev.get('updated_utc')})")
        return prev
    trust = _load(arg("--trust") or ROOT / "pwa" / "source_trust.json") or gh_get("source_trust.json") or {}
    decisions = _load(arg("--decisions")) if arg("--decisions") else gh_get("fast_decisions.json")
    cfg = json.loads((ROOT / "config" / "fastlane.json").read_text(encoding="utf-8"))
    from marsad import core
    con = core.connect(arg("--db")) if arg("--db") else core.connect()
    res = compute(con, trust, decisions, prev, cfg, now)
    out = Path(arg("--out") or ROOT / "data" / ASSET)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    if upload:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / ASSET
            p.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
            try:
                subprocess.run(["gh", "release", "upload", "fastlane", str(p), "--clobber"], capture_output=True, timeout=40)
            except Exception:  # noqa: BLE001
                pass
    print(f"::notice title=auto_tune::{summary_line(res)} | +{res['today']['promoted']} −{res['today']['demoted']}")
    return res


if __name__ == "__main__":
    main()
