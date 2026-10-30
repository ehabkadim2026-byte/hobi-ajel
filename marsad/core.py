"""المسار: جمع ← استخراج ← توحيد ← إزالة تكرار ← تصنيف ← تجميع ← تحقق ← تنبيه ← أرشفة."""
import hashlib
import json
import math
import re
import sqlite3
from collections import Counter
from datetime import timedelta
from pathlib import Path

from .textnorm import (canonical_url, fingerprint, iso, norm_ar, now_utc,
                       parse_time, tokens)

ROOT = Path(__file__).resolve().parent.parent
import os
DB_PATH = Path(os.environ.get("MARSAD_DB", ROOT / "data" / "marsad.db"))
CONFIG = ROOT / "config"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(
  id TEXT PRIMARY KEY, name TEXT, url TEXT, platform TEXT, category TEXT, region TEXT,
  lang TEXT, method TEXT, frequency TEXT, official INTEGER DEFAULT 0, status TEXT,
  verified TEXT, evidence TEXT, added_by TEXT, last_success_utc TEXT, last_error TEXT,
  last_error_utc TEXT, consecutive_failures INTEGER DEFAULT 0, notes TEXT);
CREATE TABLE IF NOT EXISTS fetch_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT, batch_id TEXT, at_utc TEXT,
  ok INTEGER, n_items INTEGER, n_new INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS items(
  id TEXT PRIMARY KEY, platform TEXT, source_id TEXT, source_name TEXT, url TEXT,
  canon_url TEXT UNIQUE, published_utc TEXT, time_precision TEXT, date_confirmed INTEGER,
  collected_utc TEXT, updated_utc TEXT, title TEXT, text TEXT, norm TEXT, fp TEXT,
  views TEXT, kind TEXT, entities TEXT, watchlists TEXT, cluster_id TEXT, batch_id TEXT,
  stale INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS ix_items_pub ON items(published_utc);
CREATE INDEX IF NOT EXISTS ix_items_fp ON items(fp);
CREATE INDEX IF NOT EXISTS ix_items_cluster ON items(cluster_id);
CREATE INDEX IF NOT EXISTS ix_items_source ON items(source_id);
CREATE TABLE IF NOT EXISTS item_versions(
  item_id TEXT, seen_utc TEXT, title TEXT, text TEXT, views TEXT);
CREATE TABLE IF NOT EXISTS clusters(
  id TEXT PRIMARY KEY, label TEXT, first_utc TEXT, last_utc TEXT, n_items INTEGER,
  n_sources INTEGER, origin_item_id TEXT, storyline TEXT, verification TEXT, watchlists TEXT);
CREATE INDEX IF NOT EXISTS ix_clusters_last ON clusters(last_utc);
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, cluster_id TEXT, level TEXT, score INTEGER,
  created_utc TEXT, signature TEXT, is_update INTEGER, what_new TEXT, body TEXT,
  delivery TEXT DEFAULT 'outbox');
CREATE TABLE IF NOT EXISTS feedback(
  id INTEGER PRIMARY KEY AUTOINCREMENT, item_id TEXT, label TEXT, note TEXT, at_utc TEXT);
CREATE TABLE IF NOT EXISTS changelog(
  id INTEGER PRIMARY KEY AUTOINCREMENT, at_utc TEXT, kind TEXT, detail TEXT);
"""

LEVELS = ["عاجل", "مهم", "متابعة", "ملخص دوري"]
STATE_MEDIA = {"telegram:t.me/inainaiq", "telegram:t.me/IraqiMediaNetwork", "telegram:t.me/IraqiaGTV",
               "telegram:t.me/iraqianews", "rss:ina.iq"}
FRESH_HOURS = 48  # مادة أقدم من هذا لا تولّد تنبيهاً (درس الكاش القديم لتلغرام)


def connect(path=None):
    con = sqlite3.connect(str(path or DB_PATH))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def log_change(con, kind, detail):
    con.execute("INSERT INTO changelog(at_utc,kind,detail) VALUES(?,?,?)", (iso(now_utc()), kind, detail))


def load_json(name, default=None):
    p = CONFIG / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


# ---------------------------------------------------------------- السجل
def import_sources(con, path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    n = 0
    cols = ["id", "name", "url", "platform", "category", "region", "lang", "method", "frequency",
            "official", "status", "verified", "evidence", "added_by", "notes"]
    for s in data["sources"]:
        row = {c: s.get(c) for c in cols}
        row["official"] = 1 if s.get("official") else 0
        con.execute(
            f"INSERT INTO sources({','.join(cols)}) VALUES({','.join('?' * len(cols))}) "
            "ON CONFLICT(id) DO UPDATE SET " + ",".join(f"{c}=excluded.{c}" for c in cols[1:]),
            [row[c] for c in cols])
        n += 1
    con.commit()
    return n


# ---------------------------------------------------------------- التصنيف
def tag_watchlists(norm_text, watchlists):
    hits = []
    for w in watchlists:
        exc = [norm_ar(x) for x in w.get("exclude", [])]
        if any(x and x in norm_text for x in exc):
            continue
        terms = [norm_ar(t) for t in w["terms"]]
        if any(t and re.search(r"(^|\s)(و|ب|ل|ال)?" + re.escape(t), norm_text) for t in terms):
            hits.append(w["id"])
    return hits


KIND_RULES = [
    ("نفي/تصحيح", r"(^|\s)(ينفي|تنفي|نفى|نفت|ينفي|تكذيب|تصحيح|غير صحيح|لا صحه)"),
    ("ادعاء من مصدر غير مسمى", r"(^|\s)(مصدر|مصادر) (امني|مطلع|سياسي|حكومي|خاص|مطلعه|امنيه|سعودي|امريكي|ايراني)"),
    ("نقل عن إعلام أجنبي", r"(صحيفه|مجله|هيئه البث|وكاله|موقع|جيروسليم|يديعوت|ايران انترناشونال|نيويورك تايمز|رويترز)[^:]{0,40}:"),
    ("رأي/تحليل", r"(^|\s)(برايك|راي|تحليل|قراءه في|ما الذي يمكن)|\?|؟"),
    ("قرار/إجراء رسمي", r"(^|\s)(يقرر|قرر|تقرر|يوجه|وجه|توجه|يوافق|وافق|يصدر|اصدر|تعلن|يعلن|اعلن|يصادق|صادق)"),
    ("تصريح منسوب", r"^[^:]{2,60}:"),
]


def classify_kind(norm_text, official):
    for kind, rx in KIND_RULES:
        if re.search(rx, norm_text):
            if kind == "تصريح منسوب" and official:
                return "بيان رسمي"
            return kind
    return "بيان رسمي" if official else "خبر مُبلّغ عنه"


ENTITY_RX = re.compile(r"(وزير [^\s]+|وزاره [^\s]+|مجلس [^\s]+|هيئه [^\s]+|محافظ [^\s]+|"
                       r"محافظه [^\s]+|مكتب [^\s]+ [^\s]+|جهاز [^\s]+ [^\s]+|البنك المركزي|مجلس النواب|"
                       r"بغداد|البصره|اربيل|كركوك|نينوى|الموصل|النجف|كربلاء|ديالى|الانبار|ذي قار|"
                       r"ميسان|واسط|بابل|الديوانيه|المثنى|صلاح الدين|السليمانيه|دهوك|سنجار|حلبجه)")


def extract_entities(norm_text):
    return sorted(set(m.group(0) for m in ENTITY_RX.finditer(norm_text)))[:12]


# ---------------------------------------------------------------- الإدخال
def norm_source_id(s):
    """يوحّد صيغ المعرّف المختصرة (tg:user) مع صيغة السجل (telegram:t.me/user)."""
    if s and s.startswith("tg:"):
        return "telegram:t.me/" + s[3:]
    return s


def item_id(canon):
    return hashlib.sha1(canon.encode()).hexdigest()[:16]


def ingest_batch(con, batch, now=None):
    """يدخل دفعة جمع (JSON). يرجع إحصاءً: جديد/مكرر/معدّل/مرفوض."""
    now = now or now_utc()
    watchlists = load_json("watchlists.json", {"watchlists": []})["watchlists"]
    official = {r["id"]: r["official"] for r in con.execute("SELECT id, official FROM sources")}
    stats = Counter()
    bid = batch.get("batch_id") or now.strftime("b%Y%m%d%H%M%S")
    per_source = Counter()
    per_source_new = Counter()
    for raw in batch.get("items", []):
        url = raw.get("url")
        title = (raw.get("title") or raw.get("text") or "").strip()
        if not url or not title:
            stats["rejected"] += 1
            continue
        canon = canonical_url(url)
        iid = item_id(canon)
        pub, prec = parse_time(raw.get("published_utc") or raw.get("pubdate"))
        text = (raw.get("text") or title).strip()
        norm = norm_ar(title + " " + text)
        fp = fingerprint(title)
        src = norm_source_id(raw.get("source_id"))
        per_source[src] += 1
        existing = con.execute("SELECT * FROM items WHERE canon_url=?", (canon,)).fetchone()
        if existing:
            if norm_ar(existing["title"]) != norm_ar(title) or norm_ar(existing["text"] or "") != norm_ar(text):
                con.execute("INSERT INTO item_versions VALUES(?,?,?,?,?)",
                            (iid, existing["updated_utc"], existing["title"], existing["text"], existing["views"]))
                con.execute("UPDATE items SET title=?, text=?, norm=?, fp=?, updated_utc=?, views=? WHERE id=?",
                            (title, text, norm, fp, iso(now), raw.get("views"), iid))
                stats["edited"] += 1
            else:
                con.execute("UPDATE items SET views=COALESCE(?, views) WHERE id=?", (raw.get("views"), iid))
                stats["duplicate"] += 1
            continue
        stale = 1 if (pub and now - pub > timedelta(hours=FRESH_HOURS)) else 0
        is_off = official.get(src, 1 if raw.get("official") else 0)
        con.execute(
            "INSERT INTO items(id,platform,source_id,source_name,url,canon_url,published_utc,time_precision,"
            "date_confirmed,collected_utc,updated_utc,title,text,norm,fp,views,kind,entities,watchlists,batch_id,stale)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (iid, raw.get("platform"), src, raw.get("source_name"), url, canon, iso(pub), prec,
             1 if raw.get("date_confirmed", prec == "exact") else 0, iso(now), iso(now), title, text, norm,
             fp, raw.get("views"), classify_kind(norm_ar(title), is_off),
             json.dumps(extract_entities(norm), ensure_ascii=False),
             json.dumps(tag_watchlists(norm, watchlists), ensure_ascii=False), bid, stale))
        stats["new"] += 1
        per_source_new[src] += 1
    for src, n in per_source.items():
        con.execute("INSERT INTO fetch_log(source_id,batch_id,at_utc,ok,n_items,n_new,error) VALUES(?,?,?,?,?,?,?)",
                    (src, bid, iso(now), 1, n, per_source_new[src], None))
        con.execute("UPDATE sources SET last_success_utc=?, consecutive_failures=0, status='يعمل' WHERE id=?",
                    (iso(now), src))
    for src in batch.get("ok", []):  # جلب ناجح بلا مواد جديدة: يُسجَّل نجاحاً حتى لا يبدو المصدر متوقفاً
        src = norm_source_id(src)
        if src in per_source:
            continue
        con.execute("INSERT INTO fetch_log(source_id,batch_id,at_utc,ok,n_items,n_new,error) VALUES(?,?,?,?,?,?,?)",
                    (src, bid, iso(now), 1, 0, 0, None))
        con.execute("UPDATE sources SET last_success_utc=?, consecutive_failures=0, status='يعمل' WHERE id=?", (iso(now), src))
    for f in batch.get("failed", []):
        f = dict(f, source_id=norm_source_id(f["source_id"]))
        con.execute("INSERT INTO fetch_log(source_id,batch_id,at_utc,ok,n_items,n_new,error) VALUES(?,?,?,?,?,?,?)",
                    (f["source_id"], bid, iso(now), 0, 0, 0, f.get("reason")))
        con.execute("UPDATE sources SET last_error=?, last_error_utc=?, consecutive_failures=consecutive_failures+1,"
                    " status=CASE WHEN consecutive_failures+1>=3 THEN 'متوقف' ELSE 'فشل مؤقت' END WHERE id=?",
                    (f.get("reason"), iso(now), f["source_id"]))
        stats["failed_sources"] += 1
    log_change(con, "ingest", f"{bid}: {dict(stats)}")
    con.commit()
    return dict(stats)


# ---------------------------------------------------------------- التجميع
def _idf(con):
    rows = con.execute("SELECT norm FROM items").fetchall()
    df = Counter()
    for r in rows:
        df.update(set(tokens(r["norm"])))
    n = max(len(rows), 1)
    return {t: math.log(1 + n / c) for t, c in df.items()}, n


def similarity(a, b, idf):
    sa, sb = set(a), set(b)
    inter = sa & sb
    if not inter:
        return 0.0, 0
    w = lambda s: sum(idf.get(t, 1.0) for t in s)
    return w(inter) / w(sa | sb), len(inter)


def cluster_items(con, window_hours=72):
    """يجمع المواد المتشابهة في خبر واحد. بين جهتين ≥0.35 وثلاث كلمات مشتركة؛ داخل الجهة ≥0.70."""
    idf, _ = _idf(con)
    from datetime import timedelta
    cutoff = iso(now_utc() - timedelta(hours=window_hours))
    # نافذة زمنية فقط (لا تحميل كل الأرشيف كل جولة) + فهرس كلمات لتقليل المقارنات: يحافظ على السرعة مع تضاعف المصادر
    items = con.execute("SELECT id, source_id, title, published_utc, collected_utc, cluster_id FROM items "
                        "WHERE cluster_id IS NULL OR COALESCE(published_utc, collected_utc) >= ? "
                        "ORDER BY COALESCE(published_utc, collected_utc)", (cutoff,)).fetchall()
    toks = {r["id"]: tokens(r["title"]) for r in items}
    inv = {}
    for r in items:
        for t in set(toks[r["id"]]):
            inv.setdefault(t, set()).add(r["id"])
    assigned = {r["id"]: r["cluster_id"] for r in items if r["cluster_id"]}
    members = {}
    for iid, cid in assigned.items():
        members.setdefault(cid, []).append(iid)
    meta = {r["id"]: r for r in items}
    for r in items:
        if r["id"] in assigned:
            continue
        t_r = r["published_utc"] or r["collected_utc"]
        best, best_s = None, 0.0
        cand = set()
        for t in set(toks[r["id"]]):
            ids_t = inv.get(t, ())
            if len(ids_t) <= 400:  # الكلمات الشائعة جداً لا تصلح للترشيح
                cand |= ids_t
        cand_clusters = {assigned[o] for o in cand if o in assigned}
        for cid in cand_clusters:
            ids = members.get(cid, [])
            for oid in ids:
                o = meta[oid]
                t_o = o["published_utc"] or o["collected_utc"]
                if abs((_dt(t_r) - _dt(t_o)).total_seconds()) > window_hours * 3600:
                    continue
                s, shared = similarity(toks[r["id"]], toks[oid], idf)
                same = o["source_id"] == r["source_id"]
                close = abs((_dt(t_r) - _dt(t_o)).total_seconds()) <= 6 * 3600
                shared_num = any(t.isdigit() and len(t) >= 2 and not re.fullmatch(r"20\d\d", t)
                                 for t in set(toks[r["id"]]) & set(toks[oid]))
                if ((same and (s >= 0.70 or (close and s >= 0.55)))
                        or (not same and s >= 0.35 and shared >= 3)
                        or (not same and shared_num and shared >= 4 and s >= 0.18)):
                    if s > best_s:
                        best, best_s = cid, s
        cid = best or ("c_" + r["id"][:10])
        members.setdefault(cid, []).append(r["id"])
        assigned[r["id"]] = cid
        con.execute("UPDATE items SET cluster_id=? WHERE id=?", (cid, r["id"]))
    members = _merge_storylines(con, members)
    _refresh_clusters(con, members)
    con.commit()
    return len(members)


def prune(con, days=8):
    """سياسة الاحتفاظ لنسخة الهاتف: حذف المواد الأقدم من N أيام حتى تبقى القاعدة صغيرة وسريعة."""
    from datetime import timedelta
    cutoff = iso(now_utc() - timedelta(days=days))
    old = [r[0] for r in con.execute("SELECT id FROM items WHERE COALESCE(published_utc, collected_utc) < ?", (cutoff,))]
    for i in range(0, len(old), 500):
        chunk = old[i:i + 500]
        q = ",".join("?" * len(chunk))
        con.execute(f"DELETE FROM item_versions WHERE item_id IN ({q})", chunk)
        con.execute(f"DELETE FROM items WHERE id IN ({q})", chunk)
    con.execute("DELETE FROM clusters WHERE id NOT IN (SELECT DISTINCT cluster_id FROM items WHERE cluster_id IS NOT NULL)")
    con.execute("DELETE FROM fetch_log WHERE at_utc < ?", (iso(now_utc() - timedelta(days=2)),))
    con.commit()
    return len(old)


def _merge_storylines(con, members):
    """الخطوط القصصية المعلّمة merge=true تجمع صياغات مختلفة للحدث نفسه في حدث واحد.
    الخطوط العامة (merge=false) تبقى وسماً فقط حتى لا تبتلع أخباراً مختلفة."""
    storylines = [s for s in load_json("storylines.json", {"storylines": []})["storylines"] if s.get("merge")]
    if not storylines:
        return members
    norms = {r["id"]: r["norm"] for r in con.execute("SELECT id, norm FROM items")}
    for s in storylines:
        terms = [norm_ar(t) for t in s["terms"]]
        hit = [cid for cid, ids in members.items()
               if sum(1 for t in terms if t in " ".join(norms[i] for i in ids)) >= s.get("min_hits", 2)]
        if len(hit) < 2 and not any(c == "s_" + s["id"] for c in hit):
            continue
        target = "s_" + s["id"]
        merged = []
        for cid in hit:
            merged += members.pop(cid)
            if cid != target:
                con.execute("DELETE FROM clusters WHERE id=?", (cid,))
        members[target] = merged
        con.execute(f"UPDATE items SET cluster_id=? WHERE id IN ({','.join('?' * len(merged))})", [target] + merged)
    return members


def _dt(s):
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def outlet_key(name):
    n = re.sub(r"\s*\((عبر )?Google News\)\s*$", "", name or "")
    n = re.sub(r"\s*[—-]\s*(telegram|تلغرام|RSS|rss|عاجل|أمن|اقتصاد|سياسة|/ar/rss.*)$", "", n)
    n = re.sub(r"\s*[—-]\s*(telegram|تلغرام|RSS)$", "", n)
    return norm_ar(n).replace(" ", "")[:30]


def _refresh_clusters(con, members):
    storylines = load_json("storylines.json", {"storylines": []})["storylines"]
    off = {r["id"]: r["official"] for r in con.execute("SELECT id, official FROM sources")}
    for cid, ids in members.items():
        rows = con.execute(f"SELECT * FROM items WHERE id IN ({','.join('?' * len(ids))}) "
                           "ORDER BY COALESCE(published_utc, collected_utc)", ids).fetchall()
        # الجهة = اسم الوسيلة الموحّد (نفس الوسيلة عبر Google News وقناتها/موقعها تُحسب جهة واحدة)
        srcs = sorted(set(outlet_key(r["source_name"] or r["source_id"]) for r in rows))
        times = [r["published_utc"] for r in rows if r["published_utc"]]
        origin = rows[0]
        # «مصدر رسمي أولي» فقط لجهة مُصدِرة تتكلم عن نفسها؛ الوكالة الرسمية التي تنقل عن صحيفة أجنبية أو مصدر
        # مجهول ليست مصدراً أولياً لذلك الادعاء، والإعلام الحكومي (واع، الشبكة) ناقل رسمي لا جهة مُصدِرة.
        relayed = {"نقل عن إعلام أجنبي", "ادعاء من مصدر غير مسمى", "رأي/تحليل"}
        issuers = {r["source_id"] for r in rows if off.get(r["source_id"]) and r["source_id"] not in STATE_MEDIA
                   and r["kind"] not in relayed}
        state_media = {r["source_id"] for r in rows if r["source_id"] in STATE_MEDIA and r["kind"] not in relayed}
        if issuers:
            rest = len(srcs) - len(issuers)
            ver = "مصدر رسمي أولي" + (f" + {rest} جهة ناقلة" if rest else "")
        elif state_media:
            ver = "وكالة/إعلام رسمي (ناقل، ليس الجهة المُصدِرة)" + (f" + {len(srcs) - len(state_media)} جهة" if len(srcs) > len(state_media) else "")
        elif len(srcs) >= 2:
            ver = f"منشور لدى {len(srcs)} جهات (قد تنقل عن بعضها؛ ليست تأكيدات مستقلة بالضرورة)"
        else:
            ver = "جهة واحدة"
        wl = sorted(set(w for r in rows for w in json.loads(r["watchlists"] or "[]")))
        norm_all = " ".join(r["norm"] for r in rows)
        story = next((s["id"] for s in storylines
                      if sum(1 for t in s["terms"] if norm_ar(t) in norm_all) >= s.get("min_hits", 2)), None)
        con.execute("INSERT INTO clusters(id,label,first_utc,last_utc,n_items,n_sources,origin_item_id,storyline,"
                    "verification,watchlists) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                    "label=excluded.label, first_utc=excluded.first_utc, last_utc=excluded.last_utc, "
                    "n_items=excluded.n_items, n_sources=excluded.n_sources, origin_item_id=excluded.origin_item_id,"
                    "storyline=excluded.storyline, verification=excluded.verification, watchlists=excluded.watchlists",
                    (cid, (next((s["title"] for s in storylines if "s_" + s["id"] == cid), None) or origin["title"])[:200], min(times) if times else None, max(times) if times else None,
                     len(rows), len(srcs), origin["id"], story, ver, json.dumps(wl, ensure_ascii=False)))


# ---------------------------------------------------------------- التنبيه
SEVERE = [r"(^|\s)(انفجار|اغتيال|قتلى|مقتل|استشهاد|اختطاف|اقتحام)", r"(هجوم|قصف|ضربه) (علي|على|صاروخي|بطائره|بمسيره|جوي)",
          r"(اسقاط|اعتراض) (طائره|طائرتي|مسيره|مسيرات|صاروخ)", r"اغلاق (معبر|منفذ|مطار|الحدود|مضيق)",
          r"حظر (التجوال|تجوال)", r"(عقوبات) (على|علي) ", r"(دوي) انفجار"]
DECISION = [r"(^|\s)(يقرر|قرر|تقرر|يصادق|صادق|يوافق|وافق|اقال|اقاله|يقيل|تعيين|تكليف|حكم|احكام|السجن|الاعدام)",
            r"\d[\d,.]*\s*(مليار|مليون|الف|٪|%)"]


def score_cluster(con, c):
    wls = {w["id"]: w for w in load_json("watchlists.json", {"watchlists": []})["watchlists"]}
    rows = con.execute("SELECT * FROM items WHERE cluster_id=?", (c["id"],)).fetchall()
    text = " ".join(r["norm"] for r in rows)
    pr = max([wls[w].get("priority", 1) for w in json.loads(c["watchlists"] or "[]") if w in wls] or [0])
    s, why = pr, []
    if pr:
        why.append(f"ملف رصد (أولوية {pr})")
    if any(re.search(rx, text) for rx in SEVERE):
        s += 2
        why.append("حدث خطورة محددة بسياقها")
    elif any(re.search(rx, text) for rx in DECISION):
        s += 1
        why.append("قرار/حكم/رقم كبير")
    if c["n_sources"] >= 2:
        s += 1
        why.append(f"لدى {c['n_sources']} جهات")
    if c["verification"].startswith("مصدر رسمي"):
        s += 1
        why.append("مصدر رسمي أولي")
    if c["n_items"] >= 5:
        s += 1
        why.append("5 مواد فأكثر")
    two = c["n_sources"] >= 2 or c["verification"].startswith("مصدر رسمي")
    # عتبات مرنة (طلب Ehab 29/10): العاجل لا يشترط حدثاً خطيراً بالضرورة
    if (s >= 5 and two) or s >= 6:
        lvl = "عاجل"
    elif s >= 3:
        lvl = "مهم"
    elif s >= 2:
        lvl = "متابعة"
    else:
        lvl = "ملخص دوري"
    return lvl, s, why, rows


def _numbers(text):
    return sorted(set(re.findall(r"\d[\d,.]*", text)))


def generate_alerts(con, now=None):
    """تنبيه جديد للحدث الجديد، وتحديث فقط عند تغير جوهري (مستوى أعلى، جهة جديدة، رقم جديد)."""
    now = now or now_utc()
    out = []
    for c in con.execute("SELECT * FROM clusters").fetchall():
        lvl, s, why, rows = score_cluster(con, c)
        fresh = [r for r in rows if not r["stale"] and r["published_utc"]
                 and now - _dt(r["published_utc"]) <= timedelta(hours=FRESH_HOURS)]
        if not fresh or lvl == "ملخص دوري":
            continue
        srcs = sorted(set(r["source_name"] or r["source_id"] for r in rows))
        nums = _numbers(" ".join(r["title"] for r in rows))
        sig = json.dumps({"lvl": lvl, "srcs": srcs, "nums": nums}, ensure_ascii=False)
        prev = con.execute("SELECT * FROM alerts WHERE cluster_id=? ORDER BY id DESC LIMIT 1", (c["id"],)).fetchone()
        what_new = "حدث جديد"
        if prev:
            if prev["signature"] == sig:
                continue
            p = json.loads(prev["signature"])
            changes = []
            if LEVELS.index(lvl) < LEVELS.index(p["lvl"]):
                changes.append(f"ارتفع المستوى من {p['lvl']} إلى {lvl}")
            new_src = [x for x in srcs if x not in p["srcs"]]
            if new_src:
                changes.append("جهات جديدة: " + "، ".join(new_src))
            new_nums = [x for x in nums if x not in p["nums"]]
            if new_nums:
                changes.append("أرقام جديدة: " + "، ".join(new_nums))
            if not changes:
                continue
            what_new = "؛ ".join(changes)
        origin = min(rows, key=lambda r: r["published_utc"] or "9")
        body = {
            "ماذا حدث": c["label"],
            "متى": origin["published_utc"],
            "لماذا يستحق الانتباه": "، ".join(why) or "—",
            "المصدر": origin["source_name"], "الرابط": origin["url"],
            "كل الروابط": [r["url"] for r in rows],
            "درجة التحقق": c["verification"] + ("" if origin["date_confirmed"] else " — تاريخ المصدر مُستنتج لا مؤكد"),
            "الجديد": what_new,
            "الإجراء البحثي المقترح": suggest_action(c, rows),
        }
        con.execute("INSERT INTO alerts(cluster_id,level,score,created_utc,signature,is_update,what_new,body) "
                    "VALUES(?,?,?,?,?,?,?,?)", (c["id"], lvl, s, iso(now), sig, 1 if prev else 0, what_new,
                                                json.dumps(body, ensure_ascii=False)))
        out.append((lvl, c["label"], what_new))
    con.commit()
    return out


def suggest_action(c, rows):
    kinds = {r["kind"] for r in rows}
    if "ادعاء من مصدر غير مسمى" in kinds:
        return "البحث عن بيان رسمي يؤكد أو ينفي؛ لا يُعامل كواقعة قبل ذلك"
    if "نقل عن إعلام أجنبي" in kinds:
        return "فتح المادة الأجنبية الأصلية والتحقق من النص والسياق"
    if c["verification"].startswith("مصدر رسمي"):
        return "فتح البيان الأصلي ومطابقة الأرقام والأسماء، ومتابعة التنفيذ"
    if c["n_sources"] == 1:
        return "البحث عن مصدر مستقل ثانٍ أو الأصل الرسمي"
    return "تحديد المصدر الأول المؤكد ومتابعة التحديثات"


# ---------------------------------------------------------------- البحث
def search(con, q="", platform=None, source=None, watchlist=None, since=None, until=None, verification=None, limit=200):
    sql = ("SELECT i.*, c.verification AS cver, c.n_sources FROM items i LEFT JOIN clusters c ON c.id=i.cluster_id "
           "WHERE 1=1")
    args = []
    for term in norm_ar(q).split():
        sql += " AND i.norm LIKE ?"
        args.append(f"%{term}%")
    if platform:
        sql += " AND i.platform=?"; args.append(platform)
    if source:
        sql += " AND i.source_id=?"; args.append(source)
    if watchlist:
        sql += " AND i.watchlists LIKE ?"; args.append(f'%"{watchlist}"%')
    if since:
        sql += " AND i.published_utc>=?"; args.append(since)
    if until:
        sql += " AND i.published_utc<=?"; args.append(until)
    if verification:
        sql += " AND c.verification LIKE ?"; args.append(f"%{verification}%")
    sql += " ORDER BY i.published_utc DESC LIMIT ?"
    args.append(limit)
    return con.execute(sql, args).fetchall()


# ---------------------------------------------------------------- الصحة
def health(con, now=None):
    now = now or now_utc()
    rows = []
    for s in con.execute("SELECT * FROM sources ORDER BY platform, name"):
        last = s["last_success_utc"]
        age = (now - _dt(last)).total_seconds() / 3600 if last else None
        if s["status"] in ("غير مقروء", "يحتاج ربطاً", "بانتظار قرار", "مستبعد"):
            state = s["status"]
        elif s["consecutive_failures"] >= 3:
            state = "متوقف"
        elif s["consecutive_failures"] > 0:
            state = "فشل مؤقت"
        elif last is None:
            state = "لم يُجمع بعد"
        elif age is not None and age > 48:
            state = "قديم (>48 ساعة)"
        else:
            state = "يعمل"
        rows.append({"id": s["id"], "name": s["name"], "platform": s["platform"], "state": state,
                     "last_success": last, "last_error": s["last_error"], "failures": s["consecutive_failures"]})
    return rows
