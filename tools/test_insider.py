"""اختبارات «بوابة المراسل» ورادارات الإشارات بواجهة تلغرام وهمية ونموذج وهمي (لا يُرسل شيء للقناة ولا يُلمس الإصدار ولا الشبكة).
تشغيل: python3 -m tools.test_insider
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import manual_pub as MP  # noqa: E402
from tools import signal_radars as SR  # noqa: E402
from tools import tg_push as T  # noqa: E402
from tools import tg_card  # noqa: E402

CH = "@hassawassal"
ED = "111"  # محرر (مشرف)
STRANGER = "999"


class Api:
    def __init__(self):
        self.calls, self.ups = [], []

    def __call__(self, token, method, files=None, **kw):
        self.calls.append((method, kw))
        if method == "getUpdates":
            return {"ok": True, "result": list(self.ups)}
        if method == "getFile":
            return {"ok": True, "result": {"file_path": "x"}}
        if method.startswith("send"):
            return {"ok": True, "result": {"message_id": 5000 + len(self.calls)}}
        return {"ok": True}

    def n(self, method, chat=None):
        return sum(1 for m, kw in self.calls if m == method and (chat is None or str(kw.get("chat_id")) == str(chat)))

    def last(self, method):
        return [kw for m, kw in self.calls if m == method][-1]


def _patch():
    saved = {"sigs": [], "files": 0}
    MP._ED.update(t=time.time(), ids={ED: "محرر"})
    T.fastlane_sigs = lambda name="fast_sigs.json": [x for x in saved["sigs"] if name == "tv_sigs.json"]
    T.publish_main_sigs = lambda titles, name="main_sigs.json": saved.__setitem__("sigs", list(titles))
    tg_card.card_news4 = lambda *a, **k: b"JPEG"
    tg_card.breaking_anim = lambda *a, **k: b"MP4"
    MP._file = lambda token, api, fid, limit=0: (saved.__setitem__("files", saved["files"] + 1), b"OGGDATA")[1]
    from tools import live_feed
    live_feed.publish = lambda token, item: saved.setdefault("feed", []).append(item)
    MP.INS_CALLS.clear()
    MP.DRAFTS.clear()
    return saved


def _msg(mid, uid=ED, **kw):
    m = {"message_id": mid, "date": int(time.time()), "chat": {"id": int(uid), "type": "private"}, "from": {"id": int(uid)}}
    m.update(kw)
    return {"update_id": mid, "message": m}


def _cb(cid, did, act, uid=ED):
    return {"update_id": 10_000 + int(cid), "callback_query": {"id": str(cid), "from": {"id": int(uid)}, "data": f"i:{act}:{did}",
                                                                "message": {"chat": {"id": int(uid)}, "message_id": 1}}}


def run_insider():
    saved = _patch()
    gem = {"n": 0, "parts": None}

    def fake_gem(prompt, parts=None):
        gem["n"] += 1
        gem["parts"] = parts
        if parts and parts[0]["inline_data"]["mime_type"] == "image/jpeg":
            return json.dumps({"transcript": "وزارة التربية — كتاب رقم 455 في 2026/11/05: تعطيل الدوام الرسمي في مدارس بغداد يوم الخميس",
                               "headline": "وزارة التربية تعلن تعطيل الدوام الرسمي في مدارس بغداد يوم الخميس", "details": ["بموجب الكتاب المرقم 455"],
                               "source": "وزارة التربية", "issuer": "وزارة التربية", "date": "2026/11/05", "official": "نعم", "ok": True}, ensure_ascii=False)
        return "```json\n" + json.dumps({"transcript": "صار حريق بسوق الشورجة والدفاع المدني وصل، ماكو اصابات", "ok": True,
                                         "headline": "اندلاع حريق في سوق الشورجة وسط بغداد وفرق الدفاع المدني تباشر إخماده دون إصابات",
                                         "details": [], "source": ""}, ensure_ascii=False) + "\n```"
    MP._gem = fake_gem
    seen = set()
    api = Api()
    marks = []
    poll = lambda: MP.poll("tok", CH, seen, api=api, bg=False, save=lambda s: marks.append(len(s)))  # noqa: E731

    # 1) بصمة صوتية ← مسودة بأزرار، بلا أي نشر
    api.ups = [_msg(1, voice={"file_id": "v1", "duration": 14, "mime_type": "audio/ogg"})]
    assert poll() == 0
    assert gem["n"] == 1 and gem["parts"][0]["inline_data"]["mime_type"] == "audio/ogg"
    assert api.n("sendPhoto") == 0 and api.n("sendAnimation") == 0, "لا نشر بلا زر"
    dm = api.last("sendMessage")
    assert "الشورجة" in dm["text"] and "i:h:" in dm["reply_markup"] and "التفريغ" in dm["text"], dm
    did = next(iter(MP.DRAFTS))
    # الرسالة نفسها مرة ثانية (لا offset) لا تُعالج مرتين
    poll()
    assert gem["n"] == 1 and len(MP.DRAFTS) == 1
    # 2) زر «انشر عاجل» ← نشر واحد بالقناة
    api.ups = [_cb(1, did, "h")]
    assert poll() == 1
    assert api.n("sendAnimation", CH) == 1 and api.n("sendPhoto", CH) == 0
    assert "🔴 عاجل" in api.last("sendAnimation")["caption"] and "الشورجة" in api.last("sendAnimation")["caption"]
    assert saved["sigs"] and saved["sigs"][-1]["id"] == f"insider:{did}" and saved["feed"][-1]["urgent"] is True
    # 3) الضغطة نفسها (callback مكرر) وضغطة ثانية جديدة: لا نشر ثانٍ
    poll()
    api.ups = [_cb(2, did, "n")]
    poll()
    assert api.n("sendAnimation", CH) + api.n("sendPhoto", CH) == 1, "نشر مرة واحدة فقط"
    assert "نُشر سابقاً" in api.last("answerCallbackQuery")["text"]

    # 4) صورة كتاب رسمي ← قراءة الجهة/التاريخ + مسودة؛ «انشر خبر» ← بطاقة بالصورة
    api.ups = [_msg(2, photo=[{"file_id": "p1", "file_size": 10}])]
    poll()
    assert gem["parts"][0]["inline_data"]["mime_type"] == "image/jpeg"
    dm = api.last("sendMessage")
    assert "الجهة: وزارة التربية" in dm["text"] and "تبدو وثيقة رسمية؟ نعم" in dm["text"], dm["text"]
    did2 = [k for k in MP.DRAFTS if k != did][0]
    assert MP.DRAFTS[did2]["photo"] == b"OGGDATA"
    api.ups = [_cb(3, did2, "n")]
    assert poll() == 1 and api.n("sendPhoto", CH) == 1
    assert "مدارس بغداد" in api.last("sendPhoto")["caption"] and "📌 المصدر: وزارة التربية" in api.last("sendPhoto")["caption"]
    assert MP.DRAFTS[did2]["photo"] is None  # الصورة تُحذف من الذاكرة بعد النشر

    # 5) غير المشرف: تجاهل تام (لا نموذج، لا رد، لا تعليم)
    n_gem, n_calls = gem["n"], len(api.calls)
    api.ups = [_msg(3, uid=STRANGER, voice={"file_id": "v9", "duration": 5}), _msg(4, uid=STRANGER, text="صار انفجار قرب ساحة التحرير هسه")]
    poll()
    assert gem["n"] == n_gem and api.n("sendMessage", STRANGER) == 0 and f"{STRANGER}:3" not in seen
    assert len(api.calls) == n_calls + 1  # getUpdates فقط
    # ضغطة زر من غير مشرف: لا نشر
    api.ups = [_cb(4, did2, "h", uid=STRANGER)]
    assert poll() == 0 and "للمحررين" in api.last("answerCallbackQuery")["text"]

    # 6) مسودة منتهية (أكثر من 30 دقيقة) ← لا نشر
    api.ups = [_msg(5, text="مجلس الوزراء يقرر تعطيل الدوام الرسمي يوم الأحد المقبل في عموم المحافظات")]
    poll()
    did3 = [k for k in MP.DRAFTS if k not in (did, did2)][0]
    MP.DRAFTS[did3]["ts"] -= MP.DRAFT_TTL + 5
    before = api.n("sendPhoto", CH) + api.n("sendAnimation", CH)
    api.ups = [_cb(5, did3, "h")]
    assert poll() == 0 and api.n("sendPhoto", CH) + api.n("sendAnimation", CH) == before
    assert "انتهت" in api.last("answerCallbackQuery")["text"]

    # 7) «تعديل» ← المحرر يرد بنص مصحح ← مسودة جديدة بأزرار ← نشر بالنص المصحح حرفياً
    saved["sigs"].clear()  # خبر حريق آخر: نعزل فحص التكرار عن حريق الشورجة أعلاه
    api.ups = [_msg(6, text="الدفاع المدني يعلن السيطرة على حريق في مخازن بمنطقة جميلة شرقي بغداد")]
    poll()
    did4 = [k for k in MP.DRAFTS if k not in (did, did2, did3)][0]
    api.ups = [_cb(6, did4, "e")]
    poll()
    draft_msg = MP.DRAFTS[did4]["msg"]
    api.ups = [_msg(7, text="الدفاع المدني: السيطرة على حريق مخازن في منطقة جميلة دون إصابات\nالمصدر: مديرية الدفاع المدني",
                    reply_to_message={"message_id": draft_msg})]
    g0 = gem["n"]
    poll()
    assert gem["n"] == g0, "التعديل بنص المحرر بلا نموذج"
    did5 = [k for k in MP.DRAFTS if k not in (did, did2, did3, did4)][0]
    assert MP.DRAFTS[did4]["state"] == "replaced" and MP.DRAFTS[did5]["src"] == "مديرية الدفاع المدني"
    api.ups = [_cb(7, did5, "n")]
    assert poll() == 1 and "حريق مخازن في منطقة جميلة دون إصابات" in api.last("sendPhoto")["caption"]
    # «إلغاء»
    api.ups = [_msg(8, text="محافظ البصرة يعلن عطلة رسمية يوم غد الخميس في المحافظة لمناسبة دينية")]
    poll()
    did6 = [k for k in MP.DRAFTS if k not in (did, did2, did3, did4, did5)][0]
    api.ups = [_cb(8, did6, "x"), _cb(9, did6, "h")]
    assert poll() == 0 and MP.DRAFTS[did6]["state"] == "cancelled"

    # 8) تعذر التفريغ ← إبلاغ المحرر بلا مسودة
    MP._gem = lambda prompt, parts=None: None
    k0 = len(MP.DRAFTS)
    api.ups = [_msg(9, voice={"file_id": "v2", "duration": 10})]
    poll()
    assert len(MP.DRAFTS) == k0 and "تعذر تفريغ" in api.last("sendMessage")["text"]
    # بصمة أطول من 60 ثانية
    api.ups = [_msg(10, voice={"file_id": "v3", "duration": 75})]
    poll()
    assert "أطول من 60" in api.last("sendMessage")["text"]
    # رسالة برابط/أمر آخر: ليست لبوابة المراسل (تبقى لصندوق المحررين)
    assert MP.insider_kind({"text": "شوفوا هذا الخبر https://ina.iq/123 مهم جداً"}) is None
    assert MP.insider_kind({"text": "/حكم 12 كاذب"}) is None and MP.insider_kind({"video": {}}) is None
    # فحص الأرقام: رقم بالعنوان غير موجود بالمدخل ← تحذير
    blk, warn = MP._check("وزارة الصحة تعلن إصابة 12 شخصاً في حادث سير ببغداد", "وزارة الصحة: إصابة اشخاص بحادث سير")
    assert blk is None and any("12" in w for w in warn)
    # سقف Gemini المستقل (30 بالساعة)
    MP.INS_CALLS[:] = [time.time()] * MP.INS_PER_HOUR
    assert MP.understand("text", text="أي شيء")[1] == "cap"
    MP.INS_CALLS.clear()
    assert marks, "التعليم في manual_done.json"


def run_radars():
    saved = _patch()
    now = time.time()
    SR.STATE.update(quakes={}, ioda={"last_alert": 0, "active": False}, usd={"read": {}, "last_alert": {}}, posts=[])
    sent, replies, dms, drafts = [], [], [], []
    ctx = {"send": lambda head, hot, src, extra, ref: (sent.append((head, hot, src, extra, ref)), (True, "", 7000 + len(sent)))[1],
           "reply": lambda mid, txt: (replies.append((mid, txt)), True)[1],
           "dm": lambda txt, _: dms.append(txt), "draft": lambda head, det, src, group: drafts.append((head, det, src, group))}
    iso = datetime.fromtimestamp(now - 120, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0Z")
    usgs = {"features": [
        {"id": "us1", "properties": {"mag": 4.2, "place": "8 km NE of Halabjah, Iraq", "time": (now - 100) * 1000, "type": "earthquake", "url": "u"},
         "geometry": {"coordinates": [46.03, 35.22, 10.0]}},
        {"id": "us2", "properties": {"mag": 5.4, "place": "12 km SW of Sarpol-e Zahab, Iran", "time": (now - 300) * 1000, "type": "earthquake", "url": "u"},
         "geometry": {"coordinates": [45.75, 34.40, 12.0]}},
        {"id": "us3", "properties": {"mag": 4.6, "place": "western Iran", "time": (now - 200) * 1000, "type": "earthquake", "url": "u"},
         "geometry": {"coordinates": [47.10, 33.90, 8.0]}},  # قرب العراق لكن أقل من 5.0 ← لا نشر
        {"id": "us4", "properties": {"mag": 6.1, "place": "Japan", "time": (now - 100) * 1000, "type": "earthquake", "url": "u"},
         "geometry": {"coordinates": [140.0, 36.0, 30.0]}}]}
    emsc = {"features": [{"id": "e1", "properties": {"unid": "e1", "time": iso, "flynn_region": "IRAN-IRAQ BORDER REGION", "lat": 35.25, "lon": 46.0,
                                                    "depth": 10.0, "mag": 4.0}}]}
    fetch = lambda url, timeout=15: usgs if "usgs" in url else emsc  # noqa: E731
    SR.quake_tick(ctx, fetch)
    assert len(sent) == 2, sent
    heads = [s[0] for s in sent]
    assert any("4.2" in h and "حلبجة (العراق)" in h for h in heads), heads
    assert any("5.4" in h and "سربل ذهاب (إيران)" in h for h in heads), heads
    assert all(s[1] for s in sent) and any("المركز الأوروبي" in s[2] and "الأمريكي" in s[2] for s in sent), "دمج المصدرين وذكرهما"
    assert all("العمق" in s[3] for s in sent)
    # الدورة التالية بالبيانات نفسها: لا تكرار
    SR.quake_tick(ctx, fetch)
    assert len(sent) == 2 and not replies
    # تعديل القوة 0.3+ ← رد «تحديث» مرة واحدة
    usgs["features"][0]["properties"]["mag"] = 4.6
    SR.quake_tick(ctx, fetch)
    assert len(replies) == 1 and "4.6" in replies[0][1] and len(sent) == 2
    SR.quake_tick(ctx, fetch)
    assert len(replies) == 1
    # هزة قديمة (أكثر من 15 دقيقة) لا تُنشر
    usgs["features"].append({"id": "us5", "properties": {"mag": 4.9, "place": "Baghdad, Iraq", "time": (now - 1800) * 1000, "type": "earthquake"},
                             "geometry": {"coordinates": [44.4, 33.3, 5]}})
    SR.quake_tick(ctx, fetch)
    assert len(sent) == 2
    assert SR.in_iraq(33.31, 44.36) and SR.in_iraq(30.51, 47.78) and SR.in_iraq(36.87, 42.99) and not SR.in_iraq(34.31, 47.07) and not SR.in_iraq(37.0, 40.0)

    # IODA: هبوط ≥30% بالمؤشرين ← رسالة خاصة مرة واحدة
    def ioda(bgp_now, ping_now):
        f = int(now - 3 * 3600)
        return {"data": [[{"datasource": "bgp", "from": f, "step": 300, "values": [3100] * 33 + [bgp_now] * 3},
                          {"datasource": "ping-slash24", "from": f, "step": 600, "values": [850] * 16 + [ping_now] * 2}]]}
    assert not SR.ioda_tick(ctx, lambda u, timeout=25: ioda(3050, 840)) and not dms
    assert SR.ioda_tick(ctx, lambda u, timeout=25: ioda(1500, 300)) and len(dms) == 1 and "انقطاع إنترنت" in dms[0]
    assert not SR.ioda_tick(ctx, lambda u, timeout=25: ioda(1400, 280)) and len(dms) == 1, "مرة لكل حدث"
    assert not SR.ioda_tick(ctx, lambda u, timeout=25: ioda(1500, 2000)) and len(dms) == 1, "BGP وحده لا يكفي"

    # الدولار: قراءات القناة نفسها، قفزة ≥1.5% خلال 30 دقيقة ← مسودة للمحررين (لا نشر)
    assert SR.parse_rates("سعر الدولار  - بغداد\n\n168.250") == {"بغداد": 168250}
    assert SR.parse_rates("دۆلار 💵 هەولێر 168,150 🟢") == {"أربيل": 168150}
    assert SR.parse_rates("آخر أسعار الدولار\n🏛️ بغداد\n168,100\n🏛️ أربيل\n168,000\n💱 بغداد – الصيرفات\n169,000") == {"بغداد": 168100, "أربيل": 168000}
    assert SR.parse_rates("سعر الذهب الآن >> 950،000") == {}
    dt = lambda s: datetime.fromtimestamp(now - s, timezone.utc)  # noqa: E731
    posts = {"dollarirq": [{"id": 1, "text": "سعر الدولار - بغداد\n168.000", "t": dt(1500)}, {"id": 2, "text": "سعر الدولار - بغداد\n168.300", "t": dt(900)}]}
    pf = lambda ch: (posts.get(ch, []), ch)  # noqa: E731
    SR.usd_tick(ctx, pf)
    assert not drafts
    posts["dollarirq"].append({"id": 3, "text": "سعر الدولار - بغداد\n171.250", "t": dt(60)})
    SR.usd_tick(ctx, pf)
    assert len(drafts) == 1 and "ارتفاع" in drafts[0][0] and "171,250" in drafts[0][0] and "بغداد" in drafts[0][0], drafts
    SR.usd_tick(ctx, pf)
    assert len(drafts) == 1, "لا تكرار"
    assert not [s for s in sent if "دولار" in s[0]], "الدولار لا يُنشر تلقائياً"

    # الدولار عبر آلية بوابة المراسل: مسودة لكل محرر بمجموعة مشتركة ← زر نشر واحد ← نشر مرة واحدة
    api = Api()
    real = SR.make_ctx("tok", CH, api=api)
    MP._ED.update(t=time.time(), ids={ED: "محرر", "222": "محرر2"})
    real["draft"](drafts[0][0], drafts[0][1], drafts[0][2], drafts[0][3])
    ids = [k for k, d in MP.DRAFTS.items() if d["group"] == drafts[0][3]]
    assert len(ids) == 2 and api.n("sendPhoto") == 0
    eds = MP.editors("tok", CH)
    assert MP.handle_callback("tok", CH, _cb(20, ids[0], "n", uid=MP.DRAFTS[ids[0]]["owner"])["callback_query"], eds, api)
    assert not MP.handle_callback("tok", CH, _cb(21, ids[1], "n", uid=MP.DRAFTS[ids[1]]["owner"])["callback_query"], eds, api)
    assert api.n("sendPhoto", CH) == 1
    st = SR.status()
    assert st["quake"]["posted"] == 2 and st["ioda"]["alerts"] == 1 and st["usd"]["alerts"] == 1


def run():
    from tools import live_feed
    keep_feed = live_feed.publish
    keep = (MP._gem, MP._file, T.fastlane_sigs, T.publish_main_sigs, tg_card.card_news4, tg_card.breaking_anim, dict(MP._ED))
    try:
        run_insider()
        run_radars()
    finally:
        MP._gem, MP._file, T.fastlane_sigs, T.publish_main_sigs, tg_card.card_news4, tg_card.breaking_anim = keep[:6]
        MP._ED.clear()
        MP._ED.update(keep[6])
        MP.DRAFTS.clear()
        live_feed.publish = keep_feed
    print("test_insider ok")


if __name__ == "__main__":
    run()
