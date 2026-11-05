"""اختبارات «العاجل على مرحلتين» وقراءة الوثائق الرسمية وإصلاحات العنوان/الموضوع وأنواع تحديثات البوت — بواجهة تلغرام ونموذج وهميين
(لا يُرسل شيء للقناة ولا يُلمس الإصدار ولا الشبكة).
تشغيل: python3 -m tools.test_fastbreak
"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import confirm as CF  # noqa: E402
from tools import fastbreak as FB  # noqa: E402
from tools import tg_push as T  # noqa: E402
from tools.test_confirm import Store  # noqa: E402

KB = json.dumps({"inline_keyboard": [[{"text": "📖 المصدر", "url": "https://t.me/x/1"}]]})
FIRST = "خلية الإعلام الأمني: مقتل 3 إرهابيين بضربة جوية في وادي الشاي جنوبي كركوك"
FULL = (FIRST + "\nوأوضحت الخلية أن الضربة نفذتها طائرات القوة الجوية بناءً على معلومات استخبارية دقيقة.\n"
        "وأشارت إلى أن القوات الأمنية باشرت بتفتيش المنطقة بحثاً عن مخلفات الإرهابيين.\n#كركوك\nتابعونا على https://t.me/x")
LATER_OFF = "خلية الإعلام الأمني تعلن مقتل 3 إرهابيين بضربة جوية دقيقة في وادي الشاي جنوبي كركوك"


class Api:
    def __init__(self, media_ok=True):
        self.calls, self.media_ok = [], media_ok

    def __call__(self, token, method, files=None, **kw):
        self.calls.append((method, kw, files))
        if method == "getUpdates":
            return {"ok": True, "result": []}
        if method.startswith("send"):
            return {"ok": True, "result": {"message_id": 7000 + len(self.calls)}}
        if method == "editMessageMedia" and not self.media_ok:
            return {"ok": False, "description": "Bad Request: wrong type"}
        return {"ok": True}

    def n(self, m):
        return sum(1 for x in self.calls if x[0] == m)


def _job(mid, loud=True, official=False, photo=None, ch="alsumariatviraq", sent_at=None):
    now = time.time()
    return {"mid": mid, "sent_at": sent_at or now - 50, "src_ts": now - 80, "ch": ch, "first": FIRST, "text": FULL, "head": FB.fast_head(FIRST),
            "loud": loud, "src": "السومرية", "when": "2026-11-05T07:00:00Z", "photo": photo, "photo_future": None, "img": None, "kb": KB,
            "tags": ["#كركوك"], "official": official, "ref": ch}


def _ledger(mid, cap, kind="photo"):
    st = Store()
    led = CF.Ledger("fast", st.get, st.put)
    led.add_post(mid, T.title_sig(FIRST), cap, kind, False, title=FIRST, kb=KB, src="alsumariatviraq", ts=time.time() - 50)
    return st, led


def run_two_stage():
    T.build_idf([FIRST, LATER_OFF, "وزير النفط يبحث مع شركة بريطانية", "مجلس الوزراء يعقد جلسته الاعتيادية"])
    # الحرج: جهة رسمية + حدث/عاجل/MUST، أو صيغة الوميض؛ والتكهنات والجهة غير الرسمية بلا وميض لا
    assert FB.critical("خلية الإعلام الأمني", False, FIRST, False)
    assert FB.critical("وزارة التربية", False, "وزارة التربية: تعطيل الدوام الرسمي في بغداد غداً الخميس بسبب الأمطار", False)
    assert not FB.critical("وزارة التربية", False, "أنباء عن تعطيل الدوام الرسمي في بغداد غداً بسبب الأمطار", False)
    assert not FB.critical("وزارة الزراعة", False, "وزير الزراعة يستقبل وفداً من منظمة الفاو لبحث التعاون", False)
    assert not FB.critical(None, True, FIRST, False) and FB.critical(None, True, FIRST, True)
    # عنوان القواعد بلا نموذج: يحذف ذيل اسم الموقع
    assert FB.fast_head("ترامب: الحرب في إيران ستنتهي قريباً » وكالة الانباء العراقية (واع) | اخبار العراق") == "ترامب: الحرب في إيران ستنتهي قريباً"
    # التفاصيل: من النص الكامل، بلا تكرار العنوان ولا هاشتاغ ولا رابط
    d = FB.detail_lines(FULL, FB.fast_head(FIRST))
    assert len(d) == 2 and d[0].startswith("وأوضحت الخلية") and not any("#" in x or "http" in x for x in d), d
    # التعليق لا يتجاوز 1024: تُحذف التفاصيل أولاً
    cap = FB.build_caption("عنوان " * 30, True, "مصدر", ["ثانٍ", "تفصيل طويل " * 90], ["أ", "ب"], "⏳ التحقق: غير مؤكد بعد")
    assert cap and CF.visible_len(cap) <= 1024 and "تفصيل طويل" not in cap

    # 1) المسار الكامل: بطاقة ثابتة أُرسلت ← بعد ~45 ث يُعدّل المنشور نفسه للمتحركة بعنوان محرر وتفاصيل وسطر «✅ أكدته» مرة واحدة
    cap0 = FB.build_caption(FB.fast_head(FIRST), True, "السومرية", tags=["#كركوك"])
    st, led = _ledger(501, cap0)
    api = Api()
    en = FB.Enricher(after=45, workers=0, edit_headline=lambda t, context="": "خلية الإعلام الأمني: مقتل 3 إرهابيين بضربة جوية في وادي الشاي جنوبي كركوك",
                     anim=lambda *a, **k: b"MP4", card=lambda *a, **k: b"JPG", fetch=None)
    en.add(_job(501))
    assert en.jobs[0]["due"] - en.jobs[0]["sent_at"] == 45
    recent = [{"ch": "iqmofa", "name": "وزارة الخارجية", "first": LATER_OFF, "text": LATER_OFF, "ts": time.time() - 20, "ref": "iqmofa"},
              {"ch": "alsumariatviraq", "name": "السومرية", "first": FIRST, "text": FULL, "ts": time.time() - 80, "ref": "alsumariatviraq"}]
    assert en.tick(recent, led, api, "TKN", "@c", now=time.time() - 30) == 0 and len(en.jobs) == 1, "قبل الموعد لا شيء"
    assert en.tick(recent, led, api, "TKN", "@c") == 1
    m, kw, files = [c for c in api.calls if c[0].startswith("edit")][0]
    assert m == "editMessageMedia" and kw["message_id"] == "501" and kw["reply_markup"] == KB and files["m"][1] == b"MP4"
    media = json.loads(kw["media"])
    assert media["type"] == "animation" and media["media"] == "attach://m" and media["parse_mode"] == "HTML"
    c = media["caption"]
    assert c.startswith("<b>🔴 عاجل | خلية الإعلام الأمني") and "وأوضحت الخلية" in c and "ونقلته أيضاً: وزارة الخارجية" in c, c
    assert c.count("✅ أكدته: وزارة الخارجية") == 1 and "#كركوك" in c and CF.visible_len(c) <= 1024 and CF.html_ok(c)
    assert led.data["posts"][0]["kind"] == "animation"
    assert 501 in led.edited_ids("enrich") and 501 in led.edited_ids("off"), "التأكيد مسجل فلا يعيده confirm.check"
    n_edits = len(api.calls)
    assert CF.check(led, api, "TKN", "@c", "وزارة الخارجية", LATER_OFF, time.time(), now=time.time()) == 0 and len(api.calls) == n_edits
    # مرة واحدة فقط
    en.add(_job(501))
    en.tick(recent, led, api, "TKN", "@c", now=time.time() + 60)
    assert len(api.calls) == n_edits, "إثراء مرة واحدة"
    assert FB.STATUS["anim_ok"] >= 1

    # 2) تأكيد أضيف بعد النشر (confirm.check) يبقى، ولا سطر تأكيد ثانٍ؛ المتحرك يتعذر ← تعديل التعليق وحده
    st, led = _ledger(502, cap0)
    led.mark(led.data["posts"][0], True, "وزارة الداخلية", typ="off", cap=CF.add_confirm(cap0, CF.confirm_line("وزارة الداخلية", time.time())))
    api = Api(media_ok=False)
    en = FB.Enricher(after=45, workers=0, edit_headline=None, anim=lambda *a, **k: b"MP4", card=None, fetch=None)
    en.add(_job(502))
    assert en.tick(recent, led, api, "TKN", "@c", now=time.time() + 5) == 1
    assert [c[0] for c in api.calls] == ["editMessageMedia", "editMessageCaption"]
    c = api.calls[-1][1]["caption"]
    assert c.count("✅ أكدته") == 1 and "✅ أكدته: وزارة الداخلية" in c and "⏳" not in c, c
    assert led.data["posts"][0]["kind"] == "photo"

    # 3) جهة رسمية مُصدِرة: «✅ التحقق: صادر عن جهة رسمية»؛ عنوان لم يتغير وبلا وسائط جديدة ← تعليق فقط؛ لا مصادر لاحقة ← لا «نقلته»
    st, led = _ledger(503, cap0)
    api = Api()
    en = FB.Enricher(after=45, workers=0, edit_headline=None, anim=None, card=lambda *a, **k: b"JPG", fetch=None)
    j = _job(503, loud=False, official=True, ch="SMN_Iraq")
    en.add(j)
    assert en.tick([], led, api, "TKN", "@c", now=time.time() + 5) == 1
    assert api.calls[0][0] == "editMessageCaption" and "✅ التحقق: صادر عن جهة رسمية" in api.calls[0][1]["caption"]
    assert "نقلته" not in api.calls[0][1]["caption"]

    # 4) سقف 20 تعديلاً بالساعة: لا إثراء؛ وموعد فائت (> 120 ث) يُترك
    st, led = _ledger(504, cap0)
    for i in range(CF.MAX_EDITS_HOUR):
        led.data["edited"].append({"mid": 9000 + i, "ts": time.time(), "ok": True, "type": "off"})
    api = Api()
    en = FB.Enricher(after=45, workers=0, edit_headline=None, anim=None, card=None, fetch=None)
    en.add(_job(504))
    en.tick([], led, api, "TKN", "@c", now=time.time() + 5)
    assert not api.calls, "السقف يمنع"
    en.add(_job(504, sent_at=time.time() - 400))
    en.tick([], led, api, "TKN", "@c")
    assert not api.calls and not en.jobs

    # 5) القياس: الوسيط بالجلسة
    lt = FB.Lat()
    for v in (1.0, 3.0, 2.0, 10.0):
        lt.add("fast", v)
    s = lt.summary()["fast"]
    assert s["n"] == 4 and s["med_s"] == 2.5 and s["last_s"] == 10.0


def run_ocr():
    FB.OCR_CALLS.clear()
    good = json.dumps({"readable": True, "document": True, "issuer": "وزارة التربية", "date": datetime.now().strftime("%d/%m/%Y"), "public": True,
                       "decision": "تعطيل الدوام الرسمي في مدارس بغداد يوم الخميس بسبب الأمطار",
                       "text": "وزارة التربية — المديرية العامة لتربية بغداد. تقرر تعطيل الدوام الرسمي في مدارس بغداد يوم الخميس بسبب الأمطار الغزيرة"})
    calls = []

    def gem(prompt, max_tokens=0, temperature=0, parts=None, timeout=0):
        calls.append(parts)
        return gem.out
    gem.out = good
    d, code = FB.ocr_doc(b"JPEG", "وزارة التربية", gem=gem)
    assert code == "ocr" and d["head"].startswith("وزارة التربية: تعطيل الدوام") and calls[0][0]["inline_data"]["mime_type"] == "image/jpeg", (d, code)
    # كلمة ليست في الوثيقة ← لا نشر (لا اختلاق)
    x = json.loads(good)
    x["decision"] = "تعطيل الدوام الرسمي في مدارس بغداد يوم الخميس بسبب الفيضانات والسيول"
    gem.out = json.dumps(x)
    assert FB.ocr_doc(b"JPEG", "وزارة التربية", gem=gem) == (None, "ocr_unsafe")
    for k, v, code in (("readable", False, "ocr_unreadable"), ("document", False, "ocr_not_doc"), ("public", False, "ocr_not_public"),
                       ("date", "01/01/2025", "ocr_old")):
        x = json.loads(good)
        x[k] = v
        gem.out = json.dumps(x)
        assert FB.ocr_doc(b"JPEG", "", gem=gem)[1] == code, code
    gem.out = "ليست JSON"
    assert FB.ocr_doc(b"JPEG", "", gem=gem)[1] == "ocr_unreadable"
    gem.out = None
    assert FB.ocr_doc(b"JPEG", "", gem=gem)[1] == "ocr_unavailable"
    # سقف 20 بالساعة منفصل، وسقف النموذج العام يُحترم
    FB.OCR_CALLS[:] = [time.time()] * FB.OCR_PER_HOUR
    n = len(calls)
    assert FB.ocr_doc(b"JPEG", "", gem=gem)[1] == "ocr_cap" and len(calls) == n
    FB.OCR_CALLS.clear()
    assert FB.ocr_doc(b"JPEG", "", gem=gem, gem_ok=lambda: False)[1] == "ocr_cap" and len(calls) == n
    FB.OCR_CALLS.clear()


def run_photo_only_scrape():
    """صورة بلا نص في صفحة t.me/s تبقى (كانت تُهمل) حتى تصل لقراءة الوثيقة."""
    from tools import fastlane as FL
    page = ('<meta property="og:title" content="وزارة التربية">'
            '<div class="tgme_widget_message_wrap"><div data-post="moedu_iq/77"><a class="tgme_widget_message_photo_wrap" '
            "style=\"width:1px;background-image:url('https://cdn4.telesco.pe/file/x.jpg')\"></a>"
            '<time datetime="2026-11-05T07:00:00+00:00"></time></div></div>')

    class R:
        def __init__(self, b):
            self.b = b

        def read(self):
            return self.b.encode()
    keep = FL.urllib.request.urlopen
    FL.urllib.request.urlopen = lambda *a, **k: R(page)
    try:
        posts, name = FL.latest_posts("moedu_iq")
    finally:
        FL.urllib.request.urlopen = keep
    assert len(posts) == 1 and posts[0]["text"] == "" and posts[0]["img"].endswith("x.jpg") and name == "وزارة التربية", posts


def run_title_topic():
    from marsad.textnorm import strip_site_suffix as S, norm_ar
    from marsad.collect import _google_news
    from tools import export_pwa as E
    from tools.editorial import clean_headline
    gn = "ترامب: الحرب في إيران ستنتهي قريباً » وكالة الانباء العراقية (واع) | اخبار العراق - وكالة الانباء العراقية (واع)"
    it = _google_news([{"title": gn}])[0]
    assert it["title"] == "ترامب: الحرب في إيران ستنتهي قريباً", it
    assert S("وزير النفط: «سنرفع الإنتاج» وكالة الانباء العراقية (واع)") == "وزير النفط: «سنرفع الإنتاج»"
    assert S("الصدر: «لن نشارك » في الانتخابات المقبلة") == "الصدر: «لن نشارك » في الانتخابات المقبلة", "فاصل داخل الجملة يبقى"
    assert S("السوداني يستقبل وفد وكالة الطاقة الذرية") == "السوداني يستقبل وفد وكالة الطاقة الذرية"
    assert clean_headline("قصف يستهدف حقل كورمور في السليمانية » شفق نيوز") == "قصف يستهدف حقل كورمور في السليمانية"
    assert E.clean_title("x", ["مجلس الوزراء يقرر تعطيل الدوام الرسمي يوم الأحد المقبل » وكالة الانباء العراقية (واع) | اخبار العراق"]) == \
        "مجلس الوزراء يقرر تعطيل الدوام الرسمي يوم الأحد المقبل"
    road = "المرور تعلن افتتاح طريق جديد باتجاه ساحة التحرير وسط بغداد"
    body = road + "\nوذلك ضمن فكرة تخفيف الزخم مع انتشار الدوريات، والمديرية تنادي المواطنين بالالتزام وتذكرة بالتعليمات"
    assert E.topic_of(norm_ar(road), road) != "رياضة" and E.topic_of(norm_ar(body), body) == "خدمات", E.topic_of(norm_ar(body), body)
    sport = "المنتخب العراقي لكرة القدم يفوز في مباراة الدوري"
    assert E.topic_of(norm_ar(sport), sport) == "رياضة"
    assert E.topic_of(norm_ar("Iraqi army transport convoy"), "Iraqi army transport convoy") == "أمن", "sport ليست جزءاً من transport"


def run_allowed_updates():
    """كل قرّاء getUpdates يطلبون الاتحاد نفسه (رسائل + أزرار + منشورات القنوات)، وصندوق المحررين يمرر منشور قناة الرصد التلفزيوني."""
    want = ["message", "callback_query", "channel_post"]
    assert json.loads(T.ALLOWED_UPDATES) == want
    from tools import manual_pub as MP
    api = Api()
    MP.poll("TKN", "@c", set(), api=api, bg=False, save=lambda s: None)
    gu = [kw for m, kw, _ in api.calls if m == "getUpdates"][0]
    assert json.loads(gu["allowed_updates"]) == want and "offset" not in gu, "بلا offset: لا يسرق تحديثات غيره"
    from tools import tg_inbox as I
    from tools import tv_source
    got = []
    ups = [{"update_id": 10, "channel_post": {"message_id": 5, "date": int(time.time()), "chat": {"id": -100, "username": "ejolh", "type": "channel"},
                                             "video": {"duration": 30}, "caption": "x"}},
           {"update_id": 11, "callback_query": {"id": "q1", "data": "i:abc:n"}}]
    calls = []

    def fake(token, method, **kw):
        calls.append((method, kw))
        if method == "getUpdates":
            return {"ok": True, "result": ups}
        return {"ok": True, "result": []}
    keep = (I.api, I.SENT, tv_source.handle, os.environ.get("MARSAD_TG_BOT_TOKEN"), os.environ.get("MARSAD_TG_CHAT_ID"))
    with tempfile.TemporaryDirectory() as td:
        try:
            I.api = fake
            I.SENT = Path(td) / "sent.json"
            tv_source.handle = lambda token, chat_id, post, sent, eds: got.append(post["message_id"]) or "ok"
            os.environ["MARSAD_TG_BOT_TOKEN"] = "TKN"
            os.environ["MARSAD_TG_CHAT_ID"] = "@c"
            I.main()
        finally:
            I.api, I.SENT, tv_source.handle = keep[:3]
            for k, v in (("MARSAD_TG_BOT_TOKEN", keep[3]), ("MARSAD_TG_CHAT_ID", keep[4])):
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    gu = [kw for m, kw in calls if m == "getUpdates"][0]
    assert json.loads(gu["allowed_updates"]) == want, gu
    assert got == [5], "منشور قناة الرصد التلفزيوني وصل لـ tv_source"


def run():
    run_two_stage()
    run_ocr()
    run_photo_only_scrape()
    run_title_topic()
    run_allowed_updates()
    print("test_fastbreak ok")


if __name__ == "__main__":
    run()
