"""اختبارات «✅ أكدته الجهة الرسمية» وسجل قرارات المسار السريع بواجهة تلغرام وهمية (لا يُرسل شيء للقناة ولا يُلمس الإصدار).
تشغيل: python3 -m tools.test_confirm
"""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import confirm as CF  # noqa: E402
from tools import tg_push as T  # noqa: E402
from tools import confirm as _CF_names  # noqa: E402
_CF_names.SHOW_NAMES = _CF_names.SHOW_LINES = True
from tools import fastbreak as _FB_v, tg_push as _TP_v  # noqa: E402
_FB_v.SHOW_VERIFY = _TP_v.SHOW_VERIFY = True  # الاختبارات تتحقق من منطق الأسماء؛ الإنتاج بلا أسماء (إيهاب 06/11)


class Store:
    """بديل إصدار fastlane في الذاكرة."""
    def __init__(self):
        self.files = {}

    def get(self, n):
        return json.loads(json.dumps(self.files[n])) if n in self.files else None

    def put(self, n, d):
        self.files[n] = json.loads(json.dumps(d))


class Api:
    def __init__(self, ok=True, raise_=False):
        self.calls, self.ok, self.raise_ = [], ok, raise_

    def __call__(self, token, method, files=None, **kw):
        self.calls.append((method, kw))
        if self.raise_:
            raise RuntimeError("HTTP Error 400: Bad Request")
        if method.startswith("send"):
            return {"ok": True, "result": {"message_id": 9000 + len(self.calls)}}
        return {"ok": self.ok, "description": "" if self.ok else "Bad Request: message can't be edited"}


MAIN_CAP = ("<b>وزارة الخارجية تستدعي السفير التركي في بغداد احتجاجاً على القصف في دهوك</b>\n\n📌 المصدر: شفق نيوز\n"
            "⏳ التحقق: غير مؤكد بعد — مصدر واحد\n#دهوك\n\nزورونا على الرابط للأخبار العاجلة 👇\nhttps://t.me/akamedia_iq")
FAST_CAP = ("<b>وزارة الخارجية تستدعي السفير التركي في بغداد احتجاجاً على القصف في دهوك</b>\n\n📌 المصدر: السومرية\n#دهوك"
            "\n\nزورونا على الرابط للأخبار العاجلة 👇\nhttps://t.me/akamedia_iq")
TITLE = "وزارة الخارجية تستدعي السفير التركي في بغداد احتجاجاً على القصف في دهوك"
OFF_TITLE = "الخارجية العراقية تستدعي السفير التركي في بغداد وتسلمه مذكرة احتجاج على القصف في دهوك"
KB = json.dumps({"inline_keyboard": [[{"text": "📖 المصدر", "url": "https://t.me/x/1"}]]})


def fresh(store=None):
    store = store or Store()
    return store, CF.Ledger("main", store.get, store.put)


def run():
    T.build_idf([TITLE, OFF_TITLE, "وزير النفط يبحث مع شركة بريطانية", "مجلس الوزراء يعقد جلسته الاعتيادية"])
    now = time.time()
    # الجهات الرسمية: الوزارة رسمية؛ واع (إعلام حكومي ناقل) والوكالات والقنوات الخاصة ليست جهة مُصدِرة
    assert CF.official_name("iqmofa") and CF.official_name("https://t.me/iqmofa/15779"), "iqmofa"
    assert CF.official_name("inainaiq") is None and CF.official_name("shafaaqnews") is None and CF.official_name("newsnina") is None

    # 1) سطر التأكيد بعد سطر التحقق، والأزرار تُعاد مع التعديل
    st, led = fresh()
    led.add_post(101, T.title_sig(TITLE), MAIN_CAP, "photo", False, title=TITLE, kb=KB, nid="c_1", ts=now - 1800)
    api = Api()
    assert CF.check(led, api, "TKN", "@akamedia_iq", "وزارة الخارجية العراقية", OFF_TITLE, now - 60, now=now) == 1
    m, kw = api.calls[0]
    assert m == "editMessageCaption" and kw["message_id"] == "101" and kw["reply_markup"] == KB and kw["parse_mode"] == "HTML"
    lines = kw["caption"].split("\n")
    i = next(k for k, x in enumerate(lines) if x.startswith("⏳ التحقق"))
    assert lines[i + 1].startswith("✅ أكدته: وزارة الخارجية العراقية — ") and lines[i + 1].endswith(" بغداد"), lines[i + 1]
    assert CF.html_ok(kw["caption"]) and kw["caption"].count("✅ أكدته") == 1
    # 2) مرة واحدة فقط: تكرار الجهة الرسمية لا يعدّل ثانية (حتى بعد إعادة التحميل من الإصدار)
    assert CF.check(led, api, "TKN", "@akamedia_iq", "وزارة الخارجية العراقية", OFF_TITLE, now - 30, now=now) == 0
    led2 = CF.Ledger("main", st.get, st.put)
    assert CF.check(led2, api, "TKN", "@akamedia_iq", "وزارة الخارجية العراقية", OFF_TITLE, now, now=now) == 0 and len(api.calls) == 1
    assert st.files["posted_main.json"]["posts"][0]["confirmed"] is True

    # 3) منشور المسار السريع بلا سطر تحقق: السطر بعد «📌 المصدر»، والمتحرك يُعدّل تعليقه
    st, led = fresh()
    led.add_post(102, T.title_sig(TITLE), FAST_CAP, "animation", False, title=TITLE, kb=KB, src="alsumariatviraq", ts=now - 600)
    api = Api()
    assert CF.check(led, api, "T", "@c", "وزارة الخارجية العراقية", OFF_TITLE, now, now=now) == 1
    cap = api.calls[0][1]["caption"].split("\n")
    assert cap[2].startswith("📌 المصدر") and cap[3].startswith("✅ أكدته"), cap

    # 4) لا تعديل: منشور رسمي أصلاً / أقدم من 6 ساعات / نفي رسمي / رقم مختلف / خبر آخر
    for rec_kw, title in [({"official": True}, OFF_TITLE), ({"ts": now - 6.5 * 3600}, OFF_TITLE),
                          ({}, "وزارة الخارجية تنفي استدعاء السفير التركي في بغداد احتجاجاً على القصف في دهوك"),
                          ({}, "وزير النفط يبحث مع شركة بريطانية تطوير حقل الرميلة")]:
        st, led = fresh()
        led.add_post(103, T.title_sig(TITLE), MAIN_CAP, "photo", rec_kw.get("official", False), title=TITLE, kb=KB, ts=rec_kw.get("ts", now - 600))
        api = Api()
        assert CF.check(led, api, "T", "@c", "وزارة الخارجية العراقية", title, now, now=now) == 0 and not api.calls, (rec_kw, title)
    st, led = fresh()
    t5 = "مقتل 5 أشخاص بانفجار عبوة ناسفة في قضاء الطارمية شمالي بغداد"
    led.add_post(104, T.title_sig(t5), MAIN_CAP, "photo", False, title=t5, ts=now - 600)
    api = Api()
    assert CF.check(led, api, "T", "@c", "خلية الإعلام الأمني", "مقتل 7 أشخاص بانفجار عبوة ناسفة في قضاء الطارمية شمالي بغداد", now, now=now) == 0

    # 5) تعليق يتجاوز 1024 حرفاً بعد الإضافة: لا استدعاء، ويُسجل فلا يُعاد
    st, led = fresh()
    long_cap = MAIN_CAP.replace("#دهوك", "#دهوك " + "ا" * 990)
    led.add_post(105, T.title_sig(TITLE), long_cap, "photo", False, title=TITLE, ts=now - 600)
    api = Api()
    assert CF.check(led, api, "T", "@c", "وزارة الخارجية العراقية", OFF_TITLE, now, now=now) == 0 and not api.calls
    assert st.files["posted_main.json"]["edited"][0]["ok"] is False

    # 6) فشل التعديل (استثناء أو ok=false): يُسجل ويُكمل بلا انهيار ولا إعادة
    for a in (Api(raise_=True), Api(ok=False)):
        st, led = fresh()
        led.add_post(106, T.title_sig(TITLE), MAIN_CAP, "photo", False, title=TITLE, ts=now - 600)
        assert CF.check(led, a, "SECRET", "@c", "وزارة الخارجية العراقية", OFF_TITLE, now, now=now) == 0
        assert CF.check(led, a, "SECRET", "@c", "وزارة الخارجية العراقية", OFF_TITLE, now, now=now) == 0 and len(a.calls) == 1
        assert "SECRET" not in json.dumps(st.files)

    # 7) منشور نصي (معاينة رابط): editMessageText مع خيارات المعاينة نفسها
    st, led = fresh()
    lp = json.dumps({"url": "https://x/cards/a.jpg", "prefer_large_media": True, "show_above_text": True})
    led.add_post(107, T.title_sig(TITLE), MAIN_CAP, "text", False, title=TITLE, kb=KB, lp=lp, ts=now - 600)
    api = Api()
    assert CF.check(led, api, "T", "@c", "وزارة الخارجية العراقية", OFF_TITLE, now, now=now) == 1
    assert api.calls[0][0] == "editMessageText" and api.calls[0][1]["link_preview_options"] == lp and "✅ أكدته" in api.calls[0][1]["text"]

    # 8) سقف 20 تعديلاً بالساعة (مجموع المسارين)
    st, led = fresh()
    st.files["posted_fast.json"] = {"posts": [], "edited": [{"mid": 1000 + k, "ts": now - 100, "ok": True, "by": "x"} for k in range(20)]}
    led.refresh_other()
    led.add_post(108, T.title_sig(TITLE), MAIN_CAP, "photo", False, title=TITLE, ts=now - 600)
    api = Api()
    assert CF.check(led, api, "T", "@c", "وزارة الخارجية العراقية", OFF_TITLE, now, now=now) == 0 and not api.calls

    # 9) المساران: المسار السريع يعدّل منشور الجولة الرئيسية، والجولة الرئيسية تراه معدّلاً فلا تكرر
    st = Store()
    main = CF.Ledger("main", st.get, st.put)
    main.add_post(109, T.title_sig(TITLE), MAIN_CAP, "photo", False, title=TITLE, nid="c_9", ts=now - 600)
    main.save()
    fast = CF.Ledger("fast", st.get, st.put)
    api = Api()
    assert CF.check(fast, api, "T", "@c", "وزارة الخارجية العراقية", OFF_TITLE, now, now=now) == 1
    main.refresh_other()
    assert not list(main.candidates(now))

    # 10) الجولة الرئيسية: عنقود فيه رابط جهة رسمية (t.me/iqmofa) يؤكد منشورنا من العنقود نفسه
    st, led = fresh()
    led.add_post(110, T.title_sig(TITLE), MAIN_CAP, "photo", False, title=TITLE, nid="c_10", ts=now - 1200)
    from datetime import datetime, timezone
    iso = datetime.fromtimestamp(now - 300, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    news = [{"id": "c_10", "title": OFF_TITLE, "timeline": [{"source": "شفق نيوز", "url": "https://shafaq.com/x", "pub": iso},
                                                         {"source": "وزارة الخارجية", "url": "https://t.me/iqmofa/15790", "pub": iso}]},
            {"id": "c_11", "title": "خبر بلا جهة رسمية", "timeline": [{"url": "https://t.me/shafaaqnews/1", "pub": iso}]}]
    api = Api()
    assert T.confirm_round("T", "@c", news, datetime.fromtimestamp(now, timezone.utc), api_fn=api, ledger=led) == 1

    # 11) send_pending يسجل المنشور (معرّف الرسالة، النوع، التعليق، الأزرار، الرسمية) في سجل الجولة الرئيسية
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        old = (T.PENDING, T.MSGS, T.CARDS, T.ANIM, T.SENT, T.api, T.fastlane_sigs, CF.gh_get, CF.gh_put)
        st = Store()
        try:
            T.PENDING, T.MSGS, T.CARDS, T.ANIM, T.SENT = td / "p.json", td / "m.json", td / "cards", td / "anim", td / "s.json"
            T.CARDS.mkdir()
            (T.CARDS / "a.jpg").write_bytes(b"\xff\xd8fake")
            sig = T.title_sig(TITLE)
            T.PENDING.write_text(json.dumps([{"id": "c_20", "card": "a.jpg", "text": MAIN_CAP, "b": False, "kb": KB, "now": True,
                                              "sig": {"w": sorted(sig[0]), "d": sorted(sig[1])}, "off": False, "title": TITLE, "src": "https://shafaq.com/x"}]),
                                 encoding="utf-8")
            api = Api()
            T.api, T.fastlane_sigs = api, (lambda *a, **k: [])
            CF.gh_get, CF.gh_put = st.get, st.put
            T.send_pending("T", "@c", only_breaking=True)
            assert "posted_main.json" in st.files, (T.DEBUG[-5:], api.calls)
            rec = st.files["posted_main.json"]["posts"][0]
            assert rec["message_id"] == 9001 and rec["kind"] == "photo" and rec["caption"] == MAIN_CAP and rec["kb"] == KB and not rec["official"]
            assert [c[0] for c in api.calls] == ["sendPhoto"]
        finally:
            T.PENDING, T.MSGS, T.CARDS, T.ANIM, T.SENT, T.api, T.fastlane_sigs, CF.gh_get, CF.gh_put = old

    # 12) سجل قرارات المسار السريع: دائري بحد DEC_MAX وحقول ثابتة، وأسباب العنوان غير الصالح محددة
    from tools import fastlane as F
    F.DECISIONS.clear()
    for k in range(F.DEC_MAX + 50):
        F.decide("ch", k, "عنوان " * 30, "skip", "dup")
    assert len(F.DECISIONS) == F.DEC_MAX and F.DECISIONS[0]["id"] == 50 and set(F.DECISIONS[0]) == {"t", "ch", "id", "head", "decision", "reason"}
    assert len(F.DECISIONS[0]["head"]) <= 80
    assert F.bad_title_reason("شنو صار بالحفلة اليوم يمعود") == "dialect"
    assert F.bad_title_reason("كتائب حزب الله: نرفض الاتفاق الأمني مع واشنطن") == "excluded"
    assert F.REASON["مكرر"] == "dup" and F.REASON["قديم"] == "fresh"
    F.DECISIONS.clear()
    print("test_confirm ok (12 حالات)")


if __name__ == "__main__":
    run()
