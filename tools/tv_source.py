"""قناة الرصد التلفزيوني الخاصة بإيهاب → نشر تلقائي مُنتقى في «هسة وصل».

البوت مشرف على قناة إيهاب، فيستلم كل منشور فيديو فيها (channel_post) بأي حجم. ننشر منها فقط:
- فيديو مدته ≤ 120 ثانية (config/tv_source.json: max_sec).
- خبر مهم: يحكم عليه Gemini (نعم/لا) إن وُجد المفتاح، وإلا كلمات الأهمية (عاجل، أمني، حكومي، كوارث…).
- غير ترويجي، وغير مكرر لما نُشر خلال 12 ساعة، وليس من جهة مستبعدة.
النشر بنسخ الرسالة داخل تلغرام (copyMessage) بعنوان محرَّر — بلا تحميل ولا حد حجم.
"""
import html as H
import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config" / "tv_source.json"

IMPORTANT = re.compile(r"(عاجل|مقتل|قتلى|شهداء|استشهاد|إصابة|جرحى|انفجار|اشتباك|اغتيال|اعتقال|القبض|قصف|غارة|هجوم|حريق|غرق|سيول|زلزال|هزة|"
                       r"رئيس الوزراء|رئيس الجمهورية|البرلمان|مجلس النواب|مجلس الوزراء|الحكومة|وزير|وزارة|محافظ|القضاء|المحكمة|المفوضية|"
                       r"الحشد|الجيش|الداخلية|الدفاع|المخابرات|الأمن الوطني|الموازنة|الرواتب|النفط|الدولار|البنك المركزي|الكهرباء|"
                       r"قرار|إعلان|يعلن|تعلن|بيان|عطلة|تعطيل|انتخابات|احتجاج|تظاهر)")
PROMO = re.compile(r"(ترقبوا|ترقّبوا|يعرض|تعرض|الليلة|موعدكم|حلقة|الحلقة|برنامج|تابعونا|انتظرونا|قريباً|قريبا|إعلان تجاري|رعاية|مسلسل)")
GATE_PROMPT = ("أنت محرر أخبار عراقي. هل هذا المقطع التلفزيوني خبر مهم يستحق النشر في قناة أخبار عاجلة عراقية؟ "
               "مهم = حدث أمني، قرار حكومي أو برلماني، تصريح لمسؤول بارز، كارثة أو حادث كبير، شأن اقتصادي يمس الناس. "
               "غير مهم = ترويج برنامج، منوعات، رياضة عادية، طرائف، تحية، أدعية، طقس عادي. أجب بكلمة واحدة: نعم أو لا.\n\nوصف المقطع: ")


def cfg():
    try:
        return json.loads(CFG.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def is_source(chat):
    c = cfg()
    want = str(c.get("channel") or "").lstrip("@").lower()
    return bool(want) and (str(chat.get("username") or "").lower() == want or str(chat.get("id")) == want)


def important(cap):
    try:
        from tools.editorial import gemini
        ans = gemini(GATE_PROMPT + cap[:600], max_tokens=5, temperature=0)
        if ans is not None:
            return "نعم" in ans, "Gemini"
    except Exception:  # noqa: BLE001
        pass
    return bool(IMPORTANT.search(cap)), "كلمات"


def handle(token, chat_id, post, sent, editors_chats):
    """post = channel_post من قناة إيهاب. يرجع سبب القرار (يُسجل في الإحصاءات)."""
    from tools.tg_push import api, title_sig, same_story, CHANNEL
    from tools.tg_video import excluded
    from tools.editorial import edit_headline
    c = cfg()
    v = post.get("video") or post.get("animation") or ((post.get("document") or {}) if (post.get("document") or {}).get("mime_type", "").startswith("video") else None)
    if not v:
        return "ليس فيديو"
    if time.time() - post.get("date", 0) > 24 * 3600:
        return "أقدم من 24 ساعة"  # نبدأ دائماً بالجديد؛ لا ننشر القديم
    dur = v.get("duration") or 0
    cap = (post.get("caption") or "").strip()
    st = sent.setdefault("_tvsrc", {"sigs": [], "day": "", "n": 0})
    today = time.strftime("%Y-%m-%d")
    if st.get("day") != today:
        st["day"], st["n"] = today, 0
    if dur and dur > int(c.get("max_sec", 120)):
        return f"أطول من {c.get('max_sec', 120)} ث"
    if len(cap.split()) < 4 or PROMO.search(cap):
        return "بلا وصف خبري أو ترويجي"
    if excluded(cap):
        return "جهة مستبعدة"
    if st["n"] >= int(c.get("daily_max", 40)):
        return "سقف يومي"
    sig = title_sig(cap)
    now = time.time()
    from tools.tg_push import fastlane_sigs, iraq_strict, build_idf, IDF, DEDUP_H, publish_main_sigs
    st["sigs"] = [x for x in st["sigs"] if x.get("ts", 0) >= now - DEDUP_H * 3600]
    tv_shared = fastlane_sigs("tv_sigs.json")  # نسخة مشتركة على الإصدار: الحالة المحلية قد تضيع بين جولتين متوازيتين (مقطع السومرية نُشر مرتين)
    others = [x for x in fastlane_sigs() + fastlane_sigs("main_sigs.json") + tv_shared if x.get("ts", 0) >= now - DEDUP_H * 3600]
    if not IDF:
        build_idf([x.get("title") or "" for x in others])
    if any(same_story(sig, x) for x in st["sigs"]) or any(same_story(sig, x) for x in sent.get("_titles", []) + others):
        return "مكرر"
    from tools.tg_push import low_value
    if low_value((cap.split("\n") or [""])[0]):
        return "ليس خبراً أو عامية"
    if not iraq_strict(cap[:300]):
        return "ليس عراقياً"  # القناة لأخبار العراق: مقاطع الشأن الأجنبي لا تُنشر
    ok, by = important(cap)
    if not ok:
        return f"غير مهم ({by})"
    lines = [ln.strip() for ln in cap.split("\n") if len(ln.strip()) >= 8]
    head = edit_headline(lines[0] if lines else cap[:200])
    src = c.get("credit") or ""
    caption = f"<b>{H.escape(head)}</b>\n\n" + (f"🎥 {H.escape(src)}\n\n" if src else "") + f"زورونا على الرابط للأخبار العاجلة 👇\n{CHANNEL}"
    try:
        r = api(token, "copyMessage", chat_id=chat_id, from_chat_id=post["chat"]["id"], message_id=post["message_id"],
                caption=caption[:1024], parse_mode="HTML")
    except Exception as e:  # noqa: BLE001
        return f"فشل النشر: {type(e).__name__}"
    if not r.get("ok"):
        return "فشل النشر: " + str(r.get("description"))[:80]
    st["n"] += 1
    st["sigs"].append({"w": sorted(sig[0]), "d": sorted(sig[1]), "ts": now})
    publish_main_sigs(tv_shared + [{"w": sorted(sig[0]), "d": sorted(sig[1]), "ts": now, "id": f"tv:{post.get('message_id')}", "title": head[:200]}], "tv_sigs.json")
    sent.setdefault("_titles", []).append({"w": sorted(sig[0]), "d": sorted(sig[1]), "ts": now})
    return f"نُشر ({by})"
