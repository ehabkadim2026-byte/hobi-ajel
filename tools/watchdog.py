"""مراقب مستقل (Watchdog) لسلسلة الرصد — يعمل في سير عمل منفصل (watchdog.yml).

كل دقيقة لمدة ~5 دقائق: يفحص آخر جولة رصد.
- لا جولة جارية ولا منتظرة، وآخر جولة انتهت قبل > 4 دقائق ← يطلق جولة جديدة (توقف السلسلة).
- جولة عالقة > 12 دقيقة ← يلغيها ثم يطلق جولة جديدة.
- 3 جولات فاشلة متتالية ← يسجّل حادثاً (الإصلاح الآلي هنا قد يكرر العطل؛ يُترك للمراجعة مع تنبيه).
كل حادث يُسجّل بسببه ونتيجة معالجته في إصدار «ops» (ops-incidents.json) — مستقل عن كاش الرصد.
في النهاية يطلق نفسه من جديد، والرصد بدوره يطلقه إن غاب: سلسلتان تحيي إحداهما الأخرى، والجدولة الاحتياطية لـGitHub طبقة ثالثة.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = os.environ.get("GITHUB_REPOSITORY", "ehabkadim2026-byte/hobi-ajel")
MAIN = "hobi-ajel.yml"
STALE_MIN, STUCK_MIN, ROUNDS, EVERY_S = 4, 12, 5, 60


def gh(*a, check=True):
    r = subprocess.run(["gh", *a], capture_output=True, text=True)
    if check and r.returncode:
        raise RuntimeError(r.stderr.strip()[:200])
    return r.stdout


def now():
    return datetime.now(timezone.utc)


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def runs(wf, n=10):
    return json.loads(gh("api", f"repos/{REPO}/actions/workflows/{wf}/runs?per_page={n}"))["workflow_runs"]


def dispatch(wf):
    for _ in range(3):
        if subprocess.run(["gh", "api", "-X", "POST", f"repos/{REPO}/actions/workflows/{wf}/dispatches", "-f", "ref=main"],
                          capture_output=True).returncode == 0:
            return True
        time.sleep(5)
    return False


def log_incident(kind, cause, action, result):
    """يضيف الحادث إلى ops-incidents.json على إصدار ops (آخر 300)."""
    rec = {"at": now().strftime("%Y-%m-%dT%H:%M:%SZ"), "by": "watchdog", "kind": kind, "cause": cause, "action": action, "result": result}
    print(f"::warning title=incident::{json.dumps(rec, ensure_ascii=False)}")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ops-incidents.json"
        if subprocess.run(["gh", "release", "view", "ops"], capture_output=True).returncode:
            subprocess.run(["gh", "release", "create", "ops", "--title", "سجل العمليات", "--notes", "حوادث المراقب والإصلاح الذاتي", "--prerelease"], capture_output=True)
        subprocess.run(["gh", "release", "download", "ops", "-p", p.name, "-D", td, "--clobber"], capture_output=True)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = []
        data = (data + [rec])[-300:]
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        subprocess.run(["gh", "release", "upload", "ops", str(p), "--clobber"], capture_output=True)


def check():
    rs = runs(MAIN)
    active = [r for r in rs if r["status"] in ("queued", "pending", "waiting", "requested", "in_progress")]
    for r in active:
        if r["status"] == "in_progress" and (now() - ts(r["run_started_at"] or r["created_at"])).total_seconds() / 60 > STUCK_MIN:
            subprocess.run(["gh", "api", "-X", "POST", f"repos/{REPO}/actions/runs/{r['id']}/cancel"], capture_output=True)
            ok = dispatch(MAIN)
            log_incident("جولة عالقة", f"الجولة {r['id']} تعمل منذ أكثر من {STUCK_MIN} دقيقة", "إلغاؤها وإطلاق جولة جديدة",
                         "نجح" if ok else "فشل الإطلاق")
            return "stuck"
    if active:
        return "ok"
    done = [r for r in rs if r["status"] == "completed"]
    last = max((ts(r["updated_at"]) for r in done), default=None)
    gap = (now() - last).total_seconds() / 60 if last else 999
    fails = 0
    for r in sorted(done, key=lambda r: r["created_at"], reverse=True):
        if r["conclusion"] == "failure":
            fails += 1
        else:
            break
    if fails >= 3:
        print(f"::warning title=watchdog::{fails} جولات فاشلة متتالية")
    if gap > STALE_MIN:
        ok = dispatch(MAIN)
        log_incident("توقف السلسلة", f"لا جولة جارية، وآخر جولة انتهت قبل {gap:.1f} دقيقة" + (f"؛ {fails} جولات فاشلة متتالية" if fails else ""),
                     "إطلاق جولة رصد جديدة", "نجح" if ok else "فشل الإطلاق")
        return "restarted"
    return "ok"


def main():
    results = []
    for i in range(ROUNDS):
        try:
            results.append(check())
        except Exception as e:  # noqa: BLE001
            results.append(f"err:{type(e).__name__}")
        if i < ROUNDS - 1:
            time.sleep(EVERY_S)
    # أطلق نفسي من جديد إن لم تكن هناك نسخة منتظرة
    mine = [r for r in runs("watchdog.yml", 5) if r["status"] in ("queued", "pending", "waiting", "requested")]
    again = dispatch("watchdog.yml") if not mine else True
    print(f"::notice title=watchdog::{json.dumps({'checks': results, 'self_dispatch': again}, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
