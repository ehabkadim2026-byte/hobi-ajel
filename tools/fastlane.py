"""المسار السريع «أول من يرصد»: يفحص القنوات الرسمية والأولية كل 30 ثانية لساعات متواصلة، وينشر الخبر المهم فوراً
(بطاقة تُرفع مباشرة لتلغرام بلا انتظار نشر الموقع). يتبادل بصمات المنشور مع الجولة الرئيسية عبر إصدار «fastlane»
حتى لا يتكرر الخبر بين المسارين.
"""
import html as H
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import tg_push as T  # noqa: E402
from tools.tv_source import important, PROMO  # noqa: E402

CFG = json.loads((ROOT / "config" / "fastlane.json").read_text(encoding="utf-8"))
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) Chrome/126 Mobile"}
ROUTINE = re.compile(r"(يهنئ|تهنئة|يعزي|تعزية|ينعى|نعى|بمناسبة|ذكرى|عيد|يستذكر|صباح الخير|جمعة مباركة|رحم الله|إنا لله|تابعونا|رابط القناة)")
STATE = ROOT / "data" / "fastlane_state.json"


def gh_get(asset):
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run(["gh", "release", "download", "fastlane", "-p", asset, "-D", td, "--clobber"], capture_output=True, timeout=30)
        if r.returncode:
            return []
        try:
            return json.loads((Path(td) / asset).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return []


def gh_put(asset, data):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / asset
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        if subprocess.run(["gh", "release", "view", "fastlane"], capture_output=True, timeout=30).returncode:
            subprocess.run(["gh", "release", "create", "fastlane", "--title", "المسار السريع", "--notes", "بصمات المنشور بين المسارين", "--prerelease"],
                           capture_output=True, timeout=30)
        subprocess.run(["gh", "release", "upload", "fastlane", str(p), "--clobber"], capture_output=True, timeout=30)


def latest_posts(ch):
    page = urllib.request.urlopen(urllib.request.Request(f"https://t.me/s/{ch}", headers=UA), timeout=12).read().decode("utf-8", "replace")
    out = []
    for b in page.split('class="tgme_widget_message_wrap')[1:]:
        pid = re.search(rf'data-post="{re.escape(ch)}/(\d+)"', b, re.I)
        tx = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', b, re.S)
        tm = re.search(r'<time[^>]+datetime="([^"]+)"', b)
        img = re.search(r"tgme_widget_message_photo_wrap[^>]+background-image:url\('([^']+)'\)", b)
        if not (pid and tx and tm):
            continue
        text = H.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<br\s*/?>", "\n", tx.group(1)))).strip()
        out.append({"id": int(pid.group(1)), "text": text, "t": datetime.fromisoformat(tm.group(1)), "img": img.group(1) if img else None})
    name = re.search(r'<meta property="og:title" content="([^"]*)"', page)
    return out, H.unescape(name.group(1)) if name else ch


def main():
    token = os.environ.get("MARSAD_TG_BOT_TOKEN", "").strip()
    if not token:
        return
    chat_id = os.environ.get("MARSAD_TG_CHAT_ID", "").strip() or "@hassawassal"
    run_until = time.time() + float(os.environ.get("FAST_MINUTES", "330")) * 60
    try:
        st = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        st = {}
    last = st.get("last", {})
    mine = gh_get("fast_sigs.json")
    stats = {"loops": 0, "posted": 0, "skipped": {}, "errors": 0}
    from tools.editorial import edit_headline
    from tools import tg_card
    while time.time() < run_until:
        t0 = time.time()
        stats["loops"] += 1
        main_sigs = gh_get("main_sigs.json") if stats["loops"] % 4 == 1 else main_sigs if stats["loops"] > 1 else []
        now = datetime.now(timezone.utc)
        mine = [x for x in mine if x.get("ts", 0) >= time.time() - 12 * 3600]
        T.build_idf([x.get("title", "") for x in mine] + [x.get("title", "") for x in main_sigs][-400:]) if stats["loops"] % 20 == 1 else None
        for ch in CFG["channels"]:
            try:
                posts, cname = latest_posts(ch)
            except Exception:  # noqa: BLE001
                stats["errors"] += 1
                continue
            seen = last.get(ch, 0)
            new = [p for p in posts if p["id"] > seen]
            if posts:
                last[ch] = max(p["id"] for p in posts)
            if not seen:
                continue  # أول مرة: نسجل خط الأساس فقط
            for p in new:
                def skip(why):
                    stats["skipped"][why] = stats["skipped"].get(why, 0) + 1
                age = (now - p["t"]).total_seconds() / 60
                first = next((ln.strip() for ln in p["text"].split("\n") if len(ln.strip().split()) >= 6), "")
                if age > CFG["max_age_min"]:
                    skip("قديم"); continue
                if not first or PROMO.search(first) or ROUTINE.search(first):
                    skip("روتيني"); continue
                if sum(1 for x in mine if x.get("ts", 0) >= time.time() - 3600) >= CFG["per_hour"]:
                    skip("سقف"); continue
                sig = T.title_sig(first)
                if any(T.same_story(sig, x) for x in mine + main_sigs):
                    skip("مكرر"); continue
                ok, by = important(p["text"][:600])
                if not ok:
                    skip("غير مهم"); continue
                head = edit_headline(first, context=p["text"][:500])
                photo = None
                if p["img"]:
                    try:
                        photo = tg_card.fetch_jpeg(p["img"])
                    except Exception:  # noqa: BLE001
                        pass
                loud = ch in CFG["loud"] or "عاجل" in p["text"][:60]
                card = tg_card.card_lux(photo, head, loud, p["t"].strftime("%Y-%m-%dT%H:%M:%SZ"))
                tags = T.province_tags(first)
                cap = f"<b>{'🔴 عاجل | ' if loud else ''}{H.escape(head)}</b>\n\n📌 المصدر: {H.escape(re.sub(r' — .*$', '', cname))}" + \
                      (("\n" + " ".join(tags)) if tags else "") + f"\n\nزورونا على الرابط للأخبار العاجلة 👇\n{T.CHANNEL}"
                kb = json.dumps({"inline_keyboard": [[{"text": "📖 المصدر", "url": f"https://t.me/{ch}/{p['id']}"},
                                                      {"text": "↗️ شارك القناة", "url": "https://t.me/share/url?url=https%3A%2F%2Ft.me%2Fhassawassal"}]]})
                try:
                    r = T.api(token, "sendPhoto", files={"photo": ("card.jpg", card)}, chat_id=chat_id, caption=cap[:1024], parse_mode="HTML",
                              reply_markup=kb, disable_notification="false" if loud else "true")
                except Exception as e:  # noqa: BLE001
                    r = {"ok": False}
                    print("::warning title=fastlane send::", type(e).__name__)
                if r.get("ok"):
                    stats["posted"] += 1
                    mine.append({"w": sorted(sig[0]), "d": sorted(sig[1]), "ts": time.time(), "title": first[:200], "id": f"fast:{ch}/{p['id']}",
                                 "lag_min": round(age, 1)})
                    gh_put("fast_sigs.json", mine)
                    print(f"::notice title=fastlane posted::{ch}/{p['id']} بعد {age:.1f} د من نشر المصدر — {head[:80]}")
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps({"last": last}, ensure_ascii=False), encoding="utf-8")
        time.sleep(max(3, CFG["every_sec"] - (time.time() - t0)))
    print(f"::notice title=fastlane::{json.dumps(stats, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
