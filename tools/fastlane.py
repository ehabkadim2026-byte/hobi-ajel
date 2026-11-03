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
STRICT = re.compile(r"(عاجل|مقتل|قتلى|استشهاد|انفجار|قصف|استهداف|اشتباك|اغتيال|القبض|اعتقال|حريق|غرق|زلزال|هزة|سيول|تعطيل|عطلة|الدوام|"
                    r"رواتب|الرواتب|قرار|يقرر|تقرر|إقالة|استقالة|تعيين|إعفاء|حظر|منع|إغلاق|فتح|الموازنة|سعر الصرف|الدولار|انتخابات|المفوضية|حكم|يقضي|الإعدام|السجن)")
FLAG = re.compile(r"^\W{0,6}(عاجل|عــاجل|عاااجل|⚡|🔴|🚨)")
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


LAST_FULL = [0.0]


GEM_CALLS = []
GEM_PER_HOUR = 90  # حماية حصة Gemini المجانية: حكم الأهمية لأخبار القنوات السريعة والوكالات غير الموسومة


def gem_ok():
    now = time.time()
    GEM_CALLS[:] = [t for t in GEM_CALLS if t >= now - 3600]
    if len(GEM_CALLS) >= GEM_PER_HOUR:
        return False
    GEM_CALLS.append(now)
    return True


def iraq_strong(t):
    from marsad.textnorm import norm_ar
    iq, _ = T._markers()
    x = " " + norm_ar(t) + " "
    return any(w and w in x for w in iq)


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
    from tools import manual_pub as MP
    seen_manual = MP.done_ids()
    while time.time() < run_until:
        t0 = time.time()
        try:  # أوامر المحررين /نشر و/عاجل: تُنشر خلال ثوانٍ
            stats["manual"] = stats.get("manual", 0) + MP.poll(token, chat_id, seen_manual)
        except Exception as e:  # noqa: BLE001
            print("::warning title=manual_pub::", type(e).__name__)
        stats["loops"] += 1
        main_sigs = (gh_get("main_sigs.json") + gh_get("tv_sigs.json")) if stats["loops"] % 4 == 1 else main_sigs if stats["loops"] > 1 else []
        now = datetime.now(timezone.utc)
        mine = [x for x in mine if x.get("ts", 0) >= time.time() - T.DEDUP_H * 3600]
        T.build_idf([x.get("title", "") for x in mine] + [x.get("title", "") for x in main_sigs][-400:]) if stats["loops"] % 20 == 1 else None
        from concurrent.futures import ThreadPoolExecutor
        allc = [(c, "official") for c in CFG["channels"]] + [(c, "breaking") for c in CFG.get("breaking", []) if c not in CFG["channels"]]
        hot = set(CFG.get("hot", []))
        full = time.time() - LAST_FULL[0] >= CFG["every_sec"] or stats["loops"] == 1
        chans = allc if full else [x for x in allc if x[0] in hot]  # الأكثر سبقاً كل 8 ثوانٍ، الكل كل 25
        if full:
            LAST_FULL[0] = time.time()

        def fetch(c):
            try:
                return c, latest_posts(c[0])
            except Exception:  # noqa: BLE001
                return c, None
        with ThreadPoolExecutor(10) as ex:
            results = list(ex.map(fetch, chans))
        for (ch, tier), res in results:
            if res is None:
                stats["errors"] += 1
                continue
            posts, cname = res
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
                from tools.editorial import complete_line
                first = complete_line(p["text"])
                first = first if len(first.split()) >= 6 and not T.PROMO_RX.search(first) else ""
                if age > CFG["max_age_min"]:
                    skip("قديم"); continue
                if not first or PROMO.search(first) or ROUTINE.search(first):
                    skip("روتيني"); continue
                if sum(1 for x in mine if x.get("ts", 0) >= time.time() - 3600) >= CFG["per_hour"]:
                    skip("سقف"); continue
                sig = T.title_sig(first)
                if any(T.same_story(sig, x) for x in mine + main_sigs) or T.sec_dup(first, mine + main_sigs, time.time()):
                    skip("مكرر"); continue
                lk = T.lead_key(first)
                if ch not in CFG["loud"] and sum(1 for x in mine + main_sigs if x.get("ts", 0) >= time.time() - 3600 and T.lead_key(x.get("title") or "") == lk) >= 2:
                    skip("نفس الجهة خلال ساعة"); continue
                if T.low_value(first) or T.incomplete(first) or T.PRESS_RX.search(first):
                    skip("عنوان غير صالح"); continue
                if ch in CFG.get("agency", []):
                    # وكالة موثوقة: عاجلها (أو حدث مهم بكلمات صريحة) عن العراق يُنشر فوراً منسوباً لها، بلا انتظار مصدر ثانٍ
                    if not T.iraq_strict(first):
                        skip("وكالة: ليس عراقياً"); continue
                    if FLAG.search(p["text"][:40]) or STRICT.search(first):
                        ok = True
                    else:  # خبر وكالة غير موسوم: يحكم النموذج على أهميته (واع سبقتنا 12 مرة بأخبار عادية مهمة كنا ننتظرها للجولة الرئيسية)
                        ok, by = important(p["text"][:600]) if gem_ok() else (False, "سقف")
                        ok = ok and by == "Gemini" and not T.ROUTINE_RX.search(first)
                elif tier == "breaking":
                    # قنوات الأخبار السريعة: فقط ما وسمته «عاجل» ويذكر العراق صراحة
                    if not T.iraq_strict(first):
                        skip("ليس عراقياً"); continue
                    if FLAG.search(p["text"][:40]) or T.SEC_RX.search(first):
                        ok = True  # عاجل عراقي، أو خبر أمني عراقي حتى بلا وسم «عاجل» (الأمني لا ينتظر)
                    elif gem_ok():
                        # خبر عراقي غير موسوم من قناة سريعة (دجلة، السومرية، 964…): المسار السريع هو الناشر الأساسي الآن،
                        # والجولة الرئيسية تتأخر 5–10 دقائق بطبيعتها — يحكم النموذج على أهميته (تحليل السبق 2026-11-03)
                        ok, by = important(p["text"][:600])
                        ok = ok and by == "Gemini" and not T.ROUTINE_RX.search(first)
                    else:
                        skip("سقف النموذج بالساعة"); continue
                else:
                    ok, by = important(p["text"][:600])
                    if by != "Gemini":
                        ok = bool(STRICT.search(p["text"][:400]))  # بلا نموذج لغوي: كلمات الحدث المهم فقط (لا «يلتقي/يستقبل»)
                if not ok:
                    skip("غير مهم"); continue
                head = edit_headline(first, context=p["text"][:500])
                photo = None
                if p["img"]:
                    try:
                        photo = tg_card.fetch_jpeg(p["img"])
                    except Exception:  # noqa: BLE001
                        pass
                # «عاجل» (شارة حمراء + وميض) فقط لما وسمته المصادر عاجلاً أو حدث أمني عراقي — لا لكل منشورات الجهات الرسمية
                loud = (bool(FLAG.search(p["text"][:40])) or bool(T.SEC_RX.search(first) and T.iraq_strict(first))) and not T.NOT_URGENT_RX.search(head)  # سعر الدولار/السلف/التقديم بلا «عاجل» (تدقيق 2835)
                card = tg_card.card_news4(photo, head, loud, p["t"].strftime("%Y-%m-%dT%H:%M:%SZ"), source=re.sub(r" — .*$", "", cname), style="A")
                tags = T.province_tags(first)
                cap = f"<b>{'🔴 عاجل | ' if loud else ''}{H.escape(head)}</b>\n\n📌 المصدر: {H.escape(re.sub(r' — .*$', '', cname))}" + \
                      (("\n" + " ".join(tags)) if tags else "") + f"\n\nزورونا على الرابط للأخبار العاجلة 👇\n{T.CHANNEL}"
                kb = json.dumps({"inline_keyboard": [[{"text": "📖 المصدر", "url": f"https://t.me/{ch}/{p['id']}"},
                                                      {"text": "↗️ شارك القناة", "url": "https://t.me/share/url?url=https%3A%2F%2Ft.me%2Fhassawassal"}]]})
                r = {"ok": False}
                if loud:  # العاجل يومض: بطاقة متحركة (تُحفظ فيديو من تلغرام)، والصورة احتياط
                    try:
                        anim = tg_card.breaking_anim(photo, head, p["t"].strftime("%Y-%m-%dT%H:%M:%SZ"), style="news4A", source=re.sub(r" — .*$", "", cname))
                        r = T.api(token, "sendAnimation", files={"animation": ("breaking.mp4", anim, "video/mp4")}, chat_id=chat_id, caption=cap[:1024],
                                  parse_mode="HTML", reply_markup=kb, width="1080", height="1350", disable_notification="false")
                    except Exception as e:  # noqa: BLE001
                        print("::warning title=fastlane anim::", type(e).__name__)
                try:
                    if not r.get("ok"):
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
        if stats["loops"] % 10 == 0:
            gh_put("fast_status.json", {**stats, "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps({"last": last}, ensure_ascii=False), encoding="utf-8")
        # تهدئة تلقائية إذا كثرت أخطاء الجلب (حماية من حدود الطلبات)
        err_rate = sum(1 for _, r in results if r is None) / max(1, len(results))
        step = CFG.get("hot_every_sec", 8) * (3 if err_rate > 0.3 else 1)
        time.sleep(max(2, step - (time.time() - t0)))
    print(f"::notice title=fastlane::{json.dumps(stats, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
