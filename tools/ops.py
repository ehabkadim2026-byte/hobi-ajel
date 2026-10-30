"""مركز عمليات راصد → pwa/ops.json، ومراقبة تدفق الأخبار والإصلاح الذاتي الآمن.

كل جولة:
- تدفق الأخبار: مواد آخر 10/60 دقيقة. إذا كانت الجولات تنجح لكن لا مواد جديدة 20 دقيقة ← حادث «الخادم يعمل والجمع متوقف»،
  والإصلاح: الجولة التالية تجمع كل المصادر بصفحات استرجاع (تجاهل جدول الأولويات) مرة واحدة، ثم تُقيَّم النتيجة.
- توقف غير طبيعي لكل مصدر: الجلب ينجح لكن لا خبر جديد منذ مدة أطول بكثير من معدله المعتاد.
- Circuit Breaker: المصادر المعزولة (3+ إخفاقات) وفترة إعادة تجربتها.
كل 6 ساعات: فحص شامل (سلامة القاعدة، أعمار النسخ الاحتياطية والتقرير، المصادر المعزولة، الجولات الفاشلة).
الحوادث تُسجل بسببها ونتيجتها في إصدار «ops» (مشترك مع المراقب المستقل). لا إصلاح يكرر نفسه: كل إجراء له فترة تهدئة.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from marsad import core  # noqa: E402
from marsad.textnorm import iso, now_utc  # noqa: E402

PWA = ROOT / "pwa"
STATE = ROOT / "data" / "ops_state.json"
REPO = os.environ.get("GITHUB_REPOSITORY", "ehabkadim2026-byte/hobi-ajel")
COOLDOWN = {"flow_stall": 30 * 60, "full_check": 6 * 3600}


def load(p, d):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def gh_json(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else None


def incidents_get():
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run(["gh", "release", "download", "ops", "-p", "ops-incidents.json", "-D", td, "--clobber"], capture_output=True)
        if r.returncode:
            return []
        return load(Path(td) / "ops-incidents.json", [])


def incident(kind, cause, action, result):
    rec = {"at": iso(now_utc()), "by": "الجولة", "kind": kind, "cause": cause, "action": action, "result": result}
    print(f"::warning title=incident::{json.dumps(rec, ensure_ascii=False)}")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ops-incidents.json"
        if subprocess.run(["gh", "release", "view", "ops"], capture_output=True).returncode:
            subprocess.run(["gh", "release", "create", "ops", "--title", "سجل العمليات", "--notes", "حوادث المراقب والإصلاح الذاتي", "--prerelease"], capture_output=True)
        subprocess.run(["gh", "release", "download", "ops", "-p", p.name, "-D", td, "--clobber"], capture_output=True)
        data = load(p, [])
        data = (data + [rec])[-300:]
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        subprocess.run(["gh", "release", "upload", "ops", str(p), "--clobber"], capture_output=True)


def main():
    now = now_utc()
    st = load(STATE, {})
    con = core.connect()
    n10 = con.execute("SELECT COUNT(*) FROM items WHERE collected_utc >= ?", (iso(now - timedelta(minutes=10)),)).fetchone()[0]
    n60 = con.execute("SELECT COUNT(*) FROM items WHERE collected_utc >= ?", (iso(now - timedelta(minutes=60)),)).fetchone()[0]
    last_item = con.execute("SELECT MAX(collected_utc) FROM items").fetchone()[0]
    idle_min = (now - datetime.fromisoformat(last_item.replace("Z", "+00:00"))).total_seconds() / 60 if last_item else 999
    # 1) الخادم يعمل والجمع متوقف
    if st.get("force_full_pending") and n10 > 0:
        incident("تعافي التدفق", "عادت المواد بعد جولة الجمع الكامل", "—", f"{n10} مادة خلال 10 دقائق")
        st["force_full_pending"] = False
    if idle_min > 20 and time.time() - st.get("t_flow_stall", 0) > COOLDOWN["flow_stall"]:
        st["force_full"] = True
        st["force_full_pending"] = True
        st["t_flow_stall"] = time.time()
        incident("توقف تدفق الأخبار", f"الجولات تعمل لكن لا مادة جديدة منذ {idle_min:.0f} دقيقة", "جمع كامل لكل المصادر مع صفحات استرجاع بالجولة التالية", "مُجدول")
    # 2) توقف غير طبيعي لكل مصدر (الجلب ينجح، والمواد متوقفة)
    rows = con.execute("SELECT s.id, s.name, s.last_success_utc, s.consecutive_failures, "
                       "(SELECT MAX(collected_utc) FROM items i WHERE i.source_id=s.id) AS last_new, "
                       "(SELECT COUNT(*) FROM items i WHERE i.source_id=s.id AND i.collected_utc >= ?) AS n_day "
                       "FROM sources s WHERE s.method IN ('rss','telegram_preview') AND s.status NOT IN ('مستبعد')",
                       (iso(now - timedelta(hours=24)),)).fetchall()
    stalled, breaker = [], []
    for r in rows:
        f = r["consecutive_failures"] or 0
        if f >= 3:
            nxt = 160 if f >= 10 else 40 if f >= 6 else 10
            breaker.append({"name": r["name"], "failures": f, "retry_every_min": round(nxt * 1.5), "last_success": r["last_success_utc"]})
            continue
        if not r["last_new"] or not r["n_day"] or r["n_day"] < 6:
            continue
        gap_typ = 24 * 60 / r["n_day"]  # متوسط الفاصل بالدقائق
        since = (now - datetime.fromisoformat(r["last_new"].replace("Z", "+00:00"))).total_seconds() / 60
        ok_fetch = r["last_success_utc"] and (now - datetime.fromisoformat(r["last_success_utc"].replace("Z", "+00:00"))).total_seconds() < 3600
        if ok_fetch and since > max(6 * gap_typ, 180):
            stalled.append({"name": r["name"], "since_min": round(since), "typical_gap_min": round(gap_typ), "n_day": r["n_day"]})
    stalled.sort(key=lambda x: -x["since_min"] / max(1, x["typical_gap_min"]))
    # 3) فحص شامل كل 6 ساعات
    full = st.get("full_check") or {}
    if time.time() - st.get("t_full", 0) > COOLDOWN["full_check"]:
        res = {"at": iso(now)}
        try:
            res["db_integrity"] = con.execute("PRAGMA quick_check").fetchone()[0]
        except sqlite3.DatabaseError as e:
            res["db_integrity"] = f"خطأ: {e}"
        a = load(ROOT / "data" / "archive_state.json", {})
        res["last_snapshot"] = a.get("last_snapshot_utc")
        res["snapshot_age_min"] = round((now - datetime.fromisoformat(a["last_snapshot_utc"].replace("Z", "+00:00"))).total_seconds() / 60) if a.get("last_snapshot_utc") else None
        res["restore_test_ok"] = bool((a.get("last_restore_test") or {}).get("db_ok") and (a.get("last_restore_test") or {}).get("archive_ok"))
        res["isolated_sources"] = len(breaker)
        res["stalled_sources"] = len(stalled)
        rr = gh_json(f"repos/{REPO}/actions/workflows/hobi-ajel.yml/runs?per_page=100&created=>{(now - timedelta(hours=6)).strftime('%Y-%m-%dT%H:%M:%SZ')}")
        if rr:
            ws = rr["workflow_runs"]
            res["runs_6h"] = len(ws)
            res["failed_runs_6h"] = sum(1 for w in ws if w["conclusion"] == "failure")
        problems = []
        if res["db_integrity"] != "ok":
            problems.append("سلامة القاعدة")
        if res.get("snapshot_age_min") and res["snapshot_age_min"] > 90:
            problems.append("النسخة الاحتياطية قديمة")
        if res.get("failed_runs_6h", 0) > 5:
            problems.append(f"{res['failed_runs_6h']} جولة فاشلة")
        res["problems"] = problems
        res["ok"] = not problems
        if problems:
            incident("فحص شامل", "، ".join(problems), "تسجيل للمراجعة (لا إصلاح آلي قد يفاقم العطل)", "بانتظار المراجعة")
        st["t_full"] = time.time()
        st["full_check"] = full = res
    # 4) حالة السلسلة والمراقب
    chain = {}
    rr = gh_json(f"repos/{REPO}/actions/workflows/hobi-ajel.yml/runs?per_page=40")
    if rr:
        ws = [w for w in rr["workflow_runs"] if w["status"] == "completed"]
        hour = [w for w in ws if datetime.fromisoformat(w["created_at"].replace("Z", "+00:00")) >= now - timedelta(hours=1)]
        durs = [(datetime.fromisoformat(w["updated_at"].replace("Z", "+00:00")) - datetime.fromisoformat((w.get("run_started_at") or w["created_at"]).replace("Z", "+00:00"))).total_seconds() for w in hour]
        chain = {"runs_1h": len(hour), "failed_1h": sum(1 for w in hour if w["conclusion"] == "failure"),
                 "avg_run_s": round(sum(durs) / len(durs)) if durs else None}
    wd = gh_json(f"repos/{REPO}/actions/workflows/watchdog.yml/runs?per_page=3")
    if wd and wd["workflow_runs"]:
        w = wd["workflow_runs"][0]
        chain["watchdog"] = {"status": w["status"], "conclusion": w["conclusion"], "at": w["updated_at"]}
    incs = incidents_get()
    meta = load(PWA / "meta.json", {})
    metrics = load(PWA / "metrics.json", {})
    disc = load(PWA / "discovery.json", {})
    S = metrics.get("sources", {})
    out = {"updated_utc": iso(now), "live": idle_min <= 10, "idle_min": round(idle_min, 1),
           "items_10m": n10, "items_1h": n60, "detect_delay": meta.get("detect_delay"),
           "sources": {"registered": S.get("registered"), "working": S.get("working"), "failing": S.get("failing"),
                       "isolated": len(breaker), "stalled_abnormal": len(stalled), "silent_24h": S.get("silent_24h")},
           "breaker": breaker[:40], "stalled": stalled[:30], "chain": chain,
           "incidents": incs[-40:][::-1], "auto_healed": sum(1 for i in incs if i.get("result") in ("نجح", "مُجدول") or i.get("kind") == "تعافي التدفق"),
           "full_check": full, "discovery": {"last_run": disc.get("last_run"), "added": disc.get("added", [])[-10:],
                                             "review": disc.get("review", [])[:20], "total": disc.get("total_discovered")}}
    (PWA / "ops.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    print(f"::notice title=ops::{json.dumps({'live': out['live'], 'idle_min': out['idle_min'], 'items_1h': n60, 'isolated': len(breaker), 'stalled': len(stalled), 'chain': chain, 'incidents': len(incs)}, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
