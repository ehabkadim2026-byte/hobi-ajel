"""مراقب القطوعات (إيهاب 07/11: «ممنوع أي قطع» — مراقب يبلّغ بأي قطع ولا يعبر وقت بلا إشعار).

يعمل مع كل جولة رئيسية (كل ~5 دقائق):
- جلسة المسار السريع تعمل منذ ≥6 دقائق والمستمع ليس «listening»، أو نبض الحالة متوقف ≥8 دقائق ⇒ قطع.
- الإجراء: إلغاء الجلسة العالقة (خطوة relaunch تطلق جديدة فوراً) — بشرط مرور 10 دقائق على آخر تشغيل.
- الإشعار: رسالة خاصة للمحررين (مشرفي القناة) عند كل قطع وعند التعافي، مرة واحدة لكل حادثة.
لا يطبع أسراراً. يكتب ::warning بالسجل دائماً.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
REPO = os.environ.get("GITHUB_REPOSITORY", "ehabkadim2026-byte/hobi-ajel")
STATE = ROOT / "data" / "watchdog.json"


def gh(*args):
    r = subprocess.run(["gh", "api", *args], capture_output=True, text=True, timeout=30)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def notify(text):
    token, chat = os.environ.get("MARSAD_TG_BOT_TOKEN"), (os.environ.get("MARSAD_TG_CHAT_ID") or "@akamedia_iq")
    if not token or not chat:
        return
    try:
        from tools.manual_pub import editors
        from tools.tg_push import api
        for uid in editors(token, chat):
            api(token, "sendMessage", chat_id=uid, text=text, disable_web_page_preview="true")
    except Exception as e:  # noqa: BLE001
        print(f"::warning title=watchdog::notify {type(e).__name__}")


def main():
    now = time.time()
    STATE.parent.mkdir(exist_ok=True)
    subprocess.run(["gh", "release", "download", "fastlane", "-p", "watchdog.json", "-D", str(STATE.parent), "--clobber"], capture_output=True, timeout=30)
    try:
        st = json.loads(STATE.read_text())
    except Exception:  # noqa: BLE001
        st = {}
    runs = (gh(f"repos/{REPO}/actions/workflows/fastlane.yml/runs?per_page=3") or {}).get("workflow_runs", [])
    live = next((r for r in runs if r["status"] == "in_progress"), None)
    rel = gh(f"repos/{REPO}/releases/tags/fastlane") or {}
    asset = next((a for a in rel.get("assets", []) if a["name"] == "fast_status.json"), None)
    listener, beat = None, None
    if asset:
        beat = ts(asset["updated_at"])
        r = subprocess.run(["gh", "api", "-H", "Accept: application/octet-stream", f"repos/{REPO}/releases/assets/{asset['id']}"],
                           capture_output=True, text=True, timeout=30)
        try:
            listener = (json.loads(r.stdout).get("listener") or {}).get("state")
        except Exception:  # noqa: BLE001
            pass
    problem = None
    if live:
        age = now - ts(live["run_started_at"] or live["created_at"])
        if age >= 360 and beat and now - beat >= 480:
            problem = f"نبض المسار السريع متوقف منذ {int((now - beat) / 60)} دقيقة"
        elif age >= 360 and beat and beat > ts(live["created_at"]) and listener and listener != "listening":
            problem = f"حساب الرصد غير متصل (الحالة: {listener})"
    inc = st.get("incident")
    if problem:
        print(f"::warning title=watchdog::{problem}")
        if live and now - ts(live["created_at"]) >= 600:
            subprocess.run(["gh", "api", "-X", "POST", f"repos/{REPO}/actions/runs/{live['id']}/cancel"], capture_output=True, timeout=30)
            action = "أعدت تشغيله تلقائياً"
        else:
            action = "ينتظر 10 دقائق من آخر تشغيل قبل الإعادة"
        if not inc:
            st["incident"] = {"t": now, "why": problem}
            notify(f"⚠️ مراقب أكا: قطع بالرصد — {problem}. {action}.")
    elif inc and live and listener == "listening":
        mins = int((now - inc["t"]) / 60)
        notify(f"✅ مراقب أكا: رجع الرصد يشتغل طبيعي (مدة الانقطاع ~{mins} دقيقة).")
        st.pop("incident", None)
    st["last_check"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    st["listener"] = listener
    STATE.write_text(json.dumps(st, ensure_ascii=False))
    subprocess.run(["gh", "release", "upload", "fastlane", str(STATE), "--clobber"], capture_output=True, timeout=30)  # حالة الحادثة بين الجولات (إشعار واحد لكل حادثة)
    print(f"::notice title=watchdog::listener={listener} beat_age={int(now - beat) if beat else '?'}s live={bool(live)}")


if __name__ == "__main__":
    main()
