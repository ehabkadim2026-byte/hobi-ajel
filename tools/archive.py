"""حماية الأرشيف: نسخ احتياطية مستقلة عن كاش GitHub Actions + استعادة تلقائية + اختبار استعادة.

سبب الفقدان السابق: القاعدة كانت تعيش فقط في actions/cache. تغيير مفتاح الكاش (أو انتهاء صلاحيته بعد 7 أيام
بلا استخدام، أو تجاوز حد 10GB للمستودع) يعطي قاعدة فارغة بصمت. الحل هنا طبقتان مستقلتان على GitHub Releases:
  1) db-backup/marsad.db.gz — لقطة كاملة للقاعدة كل ~30 دقيقة (تُستبدل). تُستعاد تلقائياً إذا غاب الكاش.
  2) archive-YYYY-MM/items-YYYY-MM-DD.jsonl.gz — أرشيف يومي دائم للنصوص والروابط والتوقيتات والتصنيفات
     (يوم بغداد السابق). لا يُحذف بالتنظيف، ولا ينزّل فيديو أو صور.
تنبيه: المستودع عام، فالنسخ عامة أيضاً — وهي أخبار منشورة أصلاً، بلا أسرار أو معرّفات قنوات.

الاستخدام (داخل Actions مع GH_TOKEN):
  python3 -m tools.archive restore     # إن غابت القاعدة
  python3 -m tools.archive snapshot    # لقطة القاعدة (كل 20 جولة تقريباً)
  python3 -m tools.archive daily       # أرشيف اليوم السابق مرة واحدة يومياً + اختبار استعادة
  python3 -m tools.archive stats       # أرقام السعة -> pwa/storage.json
"""
import gzip
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "marsad.db"
PWA = ROOT / "pwa"
TMP = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "marsad-archive"
STATE = ROOT / "data" / "archive_state.json"


def gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {r.stderr.strip()[:200]}")
    return r


def ensure_release(tag, title, notes):
    if gh("release", "view", tag, check=False).returncode != 0:
        gh("release", "create", tag, "--title", title, "--notes", notes, "--prerelease")


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_state(s):
    STATE.write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")


def counts(path):
    con = sqlite3.connect(str(path))
    ok = con.execute("PRAGMA integrity_check").fetchone()[0]
    n = con.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    c = con.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
    rng = con.execute("SELECT MIN(collected_utc), MAX(collected_utc) FROM items").fetchone()
    con.close()
    return {"integrity": ok, "items": n, "clusters": c, "oldest": rng[0], "newest": rng[1]}


def snapshot(force=False):
    st0 = load_state()
    last = st0.get("last_snapshot_utc")
    if not force and last and datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00")) < timedelta(minutes=30):
        print("snapshot fresh, skip")
        return
    TMP.mkdir(parents=True, exist_ok=True)
    raw = TMP / "marsad.db"
    src = sqlite3.connect(str(DB))
    dst = sqlite3.connect(str(raw))
    src.backup(dst)  # نسخة متسقة حتى لو كانت القاعدة مفتوحة
    dst.close(); src.close()
    gz = TMP / "marsad.db.gz"
    with open(raw, "rb") as f, gzip.open(gz, "wb", compresslevel=6) as g:
        shutil.copyfileobj(f, g)
    ensure_release("db-backup", "نسخة احتياطية لقاعدة الرصد",
                   "لقطة متجددة لقاعدة «هوبي عاجل» تُستبدل كل ~30 دقيقة. تُستعاد تلقائياً إذا فُقد كاش Actions.")
    gh("release", "upload", "db-backup", str(gz), "--clobber")
    st = load_state()
    st["last_snapshot_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    st["snapshot_gz_bytes"] = gz.stat().st_size
    save_state(st)
    print("snapshot", gz.stat().st_size, "bytes")


def restore():
    """تُستدعى إذا لم يُرجع الكاش قاعدة: ننزّل آخر لقطة. فشلها لا يوقف الجولة (تبدأ قاعدة جديدة)."""
    if DB.exists() and DB.stat().st_size > 100_000:
        print("db present, no restore")
        return
    TMP.mkdir(parents=True, exist_ok=True)
    r = gh("release", "download", "db-backup", "-p", "marsad.db.gz", "-D", str(TMP), "--clobber", check=False)
    if r.returncode != 0:
        print("::warning title=archive::لا توجد لقطة للاستعادة:", r.stderr.strip()[:150])
        return
    DB.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(TMP / "marsad.db.gz", "rb") as g, open(DB, "wb") as f:
        shutil.copyfileobj(g, f)
    c = counts(DB)
    print(f"::warning title=archive restored::استُعيدت القاعدة من النسخة الاحتياطية {json.dumps(c, ensure_ascii=False)}")
    st = load_state()
    st["last_restore_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    st["last_restore"] = c
    save_state(st)


def daily(force_day=None):
    """أرشيف يوم بغداد السابق (مرة واحدة) + اختبار استعادة فعلي من النسختين."""
    now = datetime.now(timezone.utc)
    bgd = now + timedelta(hours=3)
    day = force_day or (bgd - timedelta(days=1)).strftime("%Y-%m-%d")
    st = load_state()
    if not force_day and not st.get("last_restore_test"):
        force_day = day = bgd.strftime("%Y-%m-%d")  # أول تشغيل: اختبار استعادة فوري على اليوم الجاري (جزئي)
    if not force_day and bgd.hour < 3:
        return
    if st.get("last_daily") == day and not force_day:
        print("daily already done", day)
        return
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc) - timedelta(hours=3)
    end = start + timedelta(days=1)
    s, e = start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    TMP.mkdir(parents=True, exist_ok=True)
    out = TMP / (f"items-{day}.jsonl.gz" if not force_day else f"items-{day}-partial.jsonl.gz")
    n = 0
    q = ("SELECT i.id, i.platform, i.source_id, i.source_name, i.url, i.published_utc, i.collected_utc, i.title, "
         "substr(i.text,1,1200) AS text, i.kind, i.entities, i.watchlists, i.cluster_id, c.label AS cluster_label, "
         "c.verification AS cluster_verification, c.n_sources AS cluster_sources, s.category, s.region, s.lang "
         "FROM items i LEFT JOIN clusters c ON c.id=i.cluster_id LEFT JOIN sources s ON s.id=i.source_id "
         "WHERE i.collected_utc >= ? AND i.collected_utc < ? ORDER BY i.collected_utc")
    with gzip.open(out, "wt", encoding="utf-8") as g:
        for r in con.execute(q, (s, e)):
            g.write(json.dumps(dict(r), ensure_ascii=False) + "\n")
            n += 1
    con.close()
    if n == 0:
        print("::warning title=archive::لا مواد لليوم", day)
        if not force_day:
            st["last_daily"] = day
        save_state(st)
        return
    tag = "archive-" + day[:7]
    ensure_release(tag, f"أرشيف الرصد {day[:7]}", "أرشيف يومي دائم: نصوص وروابط وتوقيتات وتصنيفات (JSONL مضغوط، سطر لكل مادة). لا فيديو ولا صور.")
    gh("release", "upload", tag, str(out), "--clobber")
    # اختبار الاستعادة: ننزّل ما رفعناه للتو ونقارن
    chk = TMP / "check"
    shutil.rmtree(chk, ignore_errors=True); chk.mkdir()
    gh("release", "download", tag, "-p", out.name, "-D", str(chk))
    with gzip.open(chk / out.name, "rt", encoding="utf-8") as g:
        back = sum(1 for _ in g)
    gh("release", "download", "db-backup", "-p", "marsad.db.gz", "-D", str(chk))
    with gzip.open(chk / "marsad.db.gz", "rb") as g, open(chk / "r.db", "wb") as f:
        shutil.copyfileobj(g, f)
    dbc = counts(chk / "r.db")
    test = {"day": day, "archived_items": n, "restored_items": back, "archive_ok": back == n,
            "db_backup": dbc, "db_ok": dbc["integrity"] == "ok" and dbc["items"] > 0,
            "gz_bytes": out.stat().st_size, "at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    if not force_day:
        st["last_daily"] = day
    else:
        test["partial_day"] = True
    st["last_restore_test"] = test
    st.setdefault("daily_bytes", {})[day] = out.stat().st_size
    st["daily_bytes"] = dict(sorted(st["daily_bytes"].items())[-60:])
    save_state(st)
    print(f"::notice title=restore_test::{json.dumps(test, ensure_ascii=False)}")


def stats():
    st = load_state()
    db_bytes = DB.stat().st_size if DB.exists() else 0
    c = counts(DB) if DB.exists() else {}
    per_day = None
    if DB.exists():
        con = sqlite3.connect(str(DB))
        per_day = con.execute("SELECT COUNT(*) FROM items WHERE collected_utc >= datetime('now','-1 day')").fetchone()[0]
        con.close()
    days = list(st.get("daily_bytes", {}).values())
    avg = int(sum(days) / len(days)) if days else None
    out = {"updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "db_bytes": db_bytes,
           "db": c, "items_last_24h": per_day, "retention_days_db": int(os.environ.get("MARSAD_RETENTION_DAYS", "8")),
           "snapshot_gz_bytes": st.get("snapshot_gz_bytes"), "last_snapshot_utc": st.get("last_snapshot_utc"),
           "archive_avg_day_gz_bytes": avg,
           "archive_year_estimate_mb": round(avg * 365 / 1e6, 1) if avg else None,
           "last_restore_test": st.get("last_restore_test"), "last_restore_utc": st.get("last_restore_utc"),
           "limits": {"actions_cache_repo": "10 GB (تُحذف الأقدم تلقائياً، وتنتهي بعد 7 أيام بلا استخدام)",
                      "release_asset": "حتى 2 GB للملف الواحد", "pages_site": "1 GB",
                      "actions_minutes": "غير محدودة للمستودعات العامة على المشغلات العادية"}}
    PWA.mkdir(exist_ok=True)
    (PWA / "storage.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"::notice title=storage::{json.dumps({k: out[k] for k in ('db_bytes', 'items_last_24h', 'snapshot_gz_bytes', 'archive_avg_day_gz_bytes')}, ensure_ascii=False)} {json.dumps(c, ensure_ascii=False)}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    try:
        {"restore": restore, "snapshot": lambda: snapshot(len(sys.argv) > 2), "daily": lambda: daily(sys.argv[2] if len(sys.argv) > 2 else None), "stats": stats}[cmd]()
    except Exception as e:  # noqa: BLE001
        print(f"::warning title=archive {cmd} failed::{type(e).__name__}: {str(e)[:200]}")
