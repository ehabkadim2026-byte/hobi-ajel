"""اشتراكات المتابعين بالبوت: أخبار محافظة أو موضوع محدد تصل بالخاص.

المتابع يفتح البوت (زر «🔔 أخبار محافظتك» تحت منشورات القناة) ويختار من لوحة أزرار: محافظة أو موضوع، والضغط مرة ثانية يلغي.
نحفظ فقط معرّف المحادثة واختياراته (لا اسم ولا رقم). من يحظر البوت يُحذف اشتراكه تلقائياً. حد أعلى 15 رسالة للمتابع يومياً.
"""
import json
import re
from datetime import datetime, timedelta, timezone

PROV = ["بغداد", "البصرة", "نينوى", "أربيل", "كركوك", "النجف", "كربلاء", "السليمانية", "الأنبار", "ديالى", "صلاح الدين",
        "ذي قار", "بابل", "ميسان", "واسط", "دهوك", "المثنى", "الديوانية"]
ALIAS = {"الموصل": "نينوى", "الفلوجة": "الأنبار", "الرمادي": "الأنبار", "الحلة": "بابل", "الكوت": "واسط", "الناصرية": "ذي قار",
         "العمارة": "ميسان", "السماوة": "المثنى", "القادسية": "الديوانية", "بعقوبة": "ديالى", "تكريت": "صلاح الدين", "سامراء": "صلاح الدين",
         "سنجار": "نينوى", "تلعفر": "نينوى", "الزبير": "البصرة", "حلبجة": "السليمانية", "الكاظمية": "بغداد", "الأعظمية": "بغداد", "الكرادة": "بغداد"}
TOPICS = {
    "الرواتب": r"(رواتب|الرواتب|راتب|تمويل الرواتب|السلف|المتقاعدين|التقاعد|الرعاية الاجتماعية|منحة)",
    "التعليم والدوام": r"(التربية|التعليم|امتحانات|الامتحانات|الدور الثالث|الطلبة|القبول|الدوام|عطلة|العطلة|تعطيل)",
    "الكهرباء والخدمات": r"(الكهرباء|ساعات التجهيز|المولدات|الماء|المجاري|البلدية|الأمانة)",
    "الدولار والأسعار": r"(الدولار|سعر صرف|أسعار|الذهب|البنك المركزي)",
    "الأمن": r"(اعتقال|القبض|انفجار|اشتباك|هجوم|قصف|خلية الإعلام الأمني|إرهاب|ارهاب)",
    "الطقس": r"(الأنواء|الانواء|طقس|أمطار|امطار|درجات الحرارة|غبار|عاصفة|سيول)",
}
TOPIC_RX = {k: re.compile(v) for k, v in TOPICS.items()}
MAX_SUBS, DAY_CAP, RUN_CAP = 6, 15, 300
MINE, CLEAR = "اشتراكاتي", "إلغاء الكل"
WELCOME = ("🔔 أهلاً بك في تنبيهات «أكا ميديا».\n\nاختر محافظتك أو موضوعاً يهمك من الأزرار، وتصلك أخباره هنا بالخاص فور نشرها.\n"
           "اضغط الزر مرة ثانية للإلغاء. يمكنك اختيار حتى 6 اشتراكات.\nلا نحفظ عنك غير اختياراتك.")


def keyboard():
    rows = [PROV[i:i + 3] for i in range(0, len(PROV), 3)]
    tops = list(TOPICS)
    rows += [tops[i:i + 2] for i in range(0, len(tops), 2)]
    rows.append([MINE, CLEAR])
    return json.dumps({"keyboard": [[{"text": t} for t in r] for r in rows], "resize_keyboard": True, "is_persistent": True}, ensure_ascii=False)


def is_command(text):
    t = (text or "").strip()
    return t in PROV or t in ALIAS or t in TOPICS or t in (MINE, CLEAR) or t.startswith("/start")


def handle(token, api, chat_id, text, sent):
    """يعالج رسالة متابع. يرجع True إذا كانت أمر اشتراك."""
    t = (text or "").strip()
    subs = sent.setdefault("_subs", {})
    me = subs.setdefault(str(chat_id), {"p": [], "t": [], "since": datetime.now(timezone.utc).strftime("%Y-%m-%d")})

    def say(msg):
        api(token, "sendMessage", chat_id=chat_id, text=msg, reply_markup=keyboard())

    if t.startswith("/start"):
        say(WELCOME)
        return True
    if t == MINE:
        cur = me["p"] + me["t"]
        say("اشتراكاتك: " + "، ".join(cur) if cur else "ما عندك اشتراكات بعد. اختر من الأزرار.")
        return True
    if t == CLEAR:
        me["p"], me["t"] = [], []
        say("أُلغيت كل اشتراكاتك. تقدر ترجع تختار بأي وقت.")
        return True
    key, kind = (ALIAS.get(t, t), "p") if (t in PROV or t in ALIAS) else (t, "t") if t in TOPICS else (None, None)
    if not key:
        return False
    if key in me[kind]:
        me[kind].remove(key)
        say(f"❎ أُلغي اشتراكك بـ «{key}».")
    elif len(me["p"]) + len(me["t"]) >= MAX_SUBS:
        say("وصلت الحد الأعلى (6 اشتراكات). ألغِ واحداً أولاً بالضغط عليه.")
    else:
        me[kind].append(key)
        say(f"✅ اشتركت بـ «{key}». تصلك أخباره هنا فور نشرها في القناة.")
    return True


def match(title):
    from marsad.textnorm import norm_ar
    t = " " + norm_ar(title or "") + " "
    prov = {p for p in PROV if norm_ar(p) in t} | {v for k, v in ALIAS.items() if norm_ar(k) in t}
    tops = {k for k, rx in TOPIC_RX.items() if rx.search(title or "")}
    return prov, tops


def dispatch(token, api, items, sent, msgs, app_url):
    """items = [{"id","title","text","card"}] ما نُشر للتو في القناة. يرسل نسخة لكل مشترك يطابق اختياره."""
    subs = sent.get("_subs") or {}
    if not subs or not items:
        return {"sent": 0}
    day = (datetime.now(timezone.utc) + timedelta(hours=3)).strftime("%Y-%m-%d")
    cnt = msgs.setdefault("_subs_n", {})
    if cnt.get("_day") != day:
        cnt.clear()
        cnt["_day"] = day
    dead = set(msgs.get("_subs_dead") or [])
    n = 0
    for it in items:
        prov, tops = match(it.get("title"))
        if not (prov or tops):
            continue
        for cid, s in subs.items():
            if cid in dead or n >= RUN_CAP or cnt.get(cid, 0) >= DAY_CAP:
                continue
            hit = sorted((prov & set(s.get("p", []))) | (tops & set(s.get("t", []))))
            if not hit:
                continue
            kw = {"parse_mode": "HTML"}
            if it.get("card"):
                kw["link_preview_options"] = json.dumps({"url": app_url + "cards/" + it["card"], "prefer_large_media": True, "show_above_text": True})
            else:
                kw["disable_web_page_preview"] = "true"
            try:
                r = api(token, "sendMessage", chat_id=cid, text=f"📍 من اشتراكك: {'، '.join(hit)}\n\n" + it["text"][:3900], **kw)
                if r.get("ok"):
                    n += 1
                    cnt[cid] = cnt.get(cid, 0) + 1
                elif r.get("error_code") == 403:
                    dead.add(cid)  # المتابع حظر البوت: نوقف الإرسال ونحذف اشتراكه في الجولة القادمة
            except Exception as e:  # noqa: BLE001
                if "403" in str(e):
                    dead.add(cid)
    msgs["_subs_dead"] = sorted(dead)[-500:]
    return {"sent": n, "subscribers": len(subs)}
