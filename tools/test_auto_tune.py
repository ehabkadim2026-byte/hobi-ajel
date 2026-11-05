"""اختبارات الضبط الذاتي للمسار السريع (بلا شبكة): دمج fastlane_auto.json بالطبقات، والترقية/التنزيل/المرشحون على قاعدة SQLite مؤقتة.
تشغيل: python3 -m tools.test_auto_tune
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import auto_tune as A  # noqa: E402

BASE = {"channels": ["IraqiPMO", "SecMedCell"], "breaking": ["dijlahtvchannel", "slowch", "geedarbaghdad"], "hot": ["dijlahtvchannel", "slowch"],
        "agency": ["dijlahtvchannel"], "intl": ["ajanews"], "loud": ["SecMedCell"]}


def test_merge():
    m = A.merge(BASE, {"promote": ["NewFast", "newfast", "dijlahtvchannel", "IraqiPMO", "nujaba_news", "bad handle!", "Gone"],
                       "demote": ["SLOWCH", "IraqiPMO", "gone"]})
    assert m["channels"] == ["IraqiPMO", "SecMedCell"], m["channels"]           # الرسمية لا تُنزَّل أبداً
    assert "slowch" not in m["breaking"] and "slowch" not in m["hot"], m          # التنزيل من كل الطبقات غير الرسمية (بلا حساسية حالة الأحرف)
    assert m["breaking"].count("dijlahtvchannel") == 1                            # الموجود بطبقة لا يُكرر
    assert "NewFast" in m["breaking"] and "newfast" not in m["breaking"]          # إضافة واحدة للمعرّف نفسه
    assert "nujaba_news" not in m["breaking"] and "bad handle!" not in m["breaking"]  # المستبعد والمعرّف غير الصالح لا يُضافان
    assert "Gone" not in m["breaking"]                                            # المُنزَّل لا يُرقّى في الوقت نفسه
    assert "IraqiPMO" not in m["breaking"]
    assert A.merge(BASE, None) == {k: list(BASE.get(k) or []) for k in ("channels",) + A.TIER_KEYS}  # ملف مفقود = الإعداد كما هو
    assert BASE["breaking"] == ["dijlahtvchannel", "slowch", "geedarbaghdad"]     # الأصل لا يتغير (الدمج في نسخة)
    many = A.merge(BASE, {"promote": [f"chan{i:03d}" for i in range(80)]})
    assert len(many["breaking"]) == 3 + A.CAP_TOTAL


def _db(now):
    from marsad import core
    con = core.connect(":memory:")
    iso = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    srcs = ["telegram:t.me/FastNew", "telegram:t.me/RegularSlow", "telegram:t.me/dijlahtvchannel", "telegram:t.me/slowch",
            "telegram:t.me/geedarbaghdad", "telegram:t.me/nujaba_news", "telegram:t.me/o1", "telegram:t.me/o2", "telegram:t.me/o3"]
    for s in srcs:
        con.execute("INSERT INTO sources(id, name, url, region) VALUES(?,?,?,?)", (s, s.split("/")[-1] + " — telegram", "https://t.me/" + s.split("/")[-1], "العراق"))
        con.execute("INSERT INTO fetch_log(source_id, at_utc, ok, n_items, n_new) VALUES(?,?,1,5,0)", (s, iso(now - timedelta(hours=1))))
    k = 0
    for c in range(4):  # 4 أحداث عراقية: FastNew والمستبعد أول ناشر
        t0 = now - timedelta(days=1, hours=c)
        for j, s in enumerate(["telegram:t.me/FastNew", "telegram:t.me/nujaba_news", "telegram:t.me/RegularSlow", "telegram:t.me/dijlahtvchannel",
                               "telegram:t.me/o1", "telegram:t.me/o2", "telegram:t.me/o3"]):
            t = t0 + timedelta(minutes=0 if j < 2 else 3 + j)
            k += 1
            con.execute("INSERT INTO items(id, source_id, source_name, title, text, published_utc, collected_utc, time_precision, cluster_id, url, canon_url) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (f"i{k}", s, s, f"وزارة الداخلية العراقية تعلن القبض على عصابة في بغداد رقم {c}",
                         "تابعونا t.me/UnseenIraqNews و @UnseenIraqNews و https://www.newsite-iq.com/a/1" if s.endswith(("o1", "o2")) else "نص",
                         iso(t), iso(t + timedelta(minutes=1)), "exact", f"c{c}", f"https://t.me/x/{k}", f"https://t.me/x/{k}"))
    return con


def test_compute():
    now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    con = _db(now)
    trust = {"sources": {
        "telegram:t.me/FastNew": {"name": "قناة سريعة — telegram", "tier": "عادية", "first_rate": 0.4, "n": 40, "median_lead_min": 1.0},
        "telegram:t.me/RegularSlow": {"name": "بطيئة", "tier": "عادية", "first_rate": 0.4, "n": 40, "median_lead_min": 9.0},
        "telegram:t.me/nujaba_news": {"name": "مستبعدة", "tier": "موثوقة", "first_rate": 0.9, "n": 90, "median_lead_min": 0.5},
        "telegram:t.me/slowch": {"name": "ضعيفة", "tier": "ضعيفة", "score": 30, "denied_rate": 0.1}}}
    dec = {"items": [{"t": "2026-11-05T10:00:00Z", "ch": "geedarbaghdad", "id": i, "decision": "skip", "reason": "not_iraq"} for i in range(25)]
           + [{"t": "2026-11-05T10:00:00Z", "ch": "ajanews", "id": i, "decision": "skip", "reason": "not_iraq"} for i in range(25)]}
    r = A.compute(con, trust, dec, None, BASE, now)
    assert r["promote"] == ["FastNew"], r["promote"]                # البطيئة (تأخر 9 د) والمستبعدة لا تُرقّيان
    assert "slowch" in r["demote"] and "geedarbaghdad" in r["demote"], r["demote"]
    assert "ajanews" not in r["demote"] and "IraqiPMO" not in r["demote"]  # المنافس/الدولي والرسمي لا يُنزَّلان
    assert any(c["ref"] == "t.me/UnseenIraqNews" and c["cited_by"] == 2 for c in r["candidates"]), r["candidates"]
    assert any(c["ref"] == "newsite-iq.com" for c in r["candidates"]), r["candidates"]
    assert "+1 للمسار السريع" in A.summary_line(r)
    # اليوم التالي: الترقية والتنزيل يبقيان، ولا ترقية مكررة
    r2 = A.compute(con, trust, {"items": []}, r, BASE, now + timedelta(days=1))
    assert r2["promote"] == ["FastNew"] and r2["today"]["promoted"] == [] and "slowch" in r2["demote"], r2
    m = A.merge(BASE, r2)
    assert "FastNew" in m["breaking"] and "slowch" not in m["breaking"]
    # بعد 8 أيام ينتهي التنزيل ويُعاد التقييم
    r3 = A.compute(con, {"sources": {}}, {"items": []}, r2, BASE, now + timedelta(days=8))
    assert "geedarbaghdad" not in r3["demote"], r3["demote"]


def test_fastlane_loader():
    """fastlane.load_auto: يدمج في الذاكرة من الإعداد الأصلي (لا تراكم بين التحميلات)، وفشل التنزيل يُبقي الضبط الحالي."""
    import copy
    from tools import fastlane as FL
    keep, get = copy.deepcopy({k: FL.CFG.get(k) for k in FL.AUTO_BASE}), FL.gh_get
    try:
        off = FL.AUTO_BASE["channels"][0]
        brk = next(c for c in FL.AUTO_BASE["breaking"] if c not in FL.AUTO_BASE["channels"])
        FL.gh_get = lambda a: {"updated_utc": "x", "promote": ["ZzAutoNew1"], "demote": [brk, off]} if a == "fastlane_auto.json" else []
        assert FL.load_auto()["promote"] == 1
        assert "ZzAutoNew1" in FL.CFG["breaking"] and brk not in FL.CFG["breaking"] and brk not in FL.CFG.get("hot", [])
        assert off in FL.CFG["channels"]
        FL.gh_get = lambda a: {"updated_utc": "y", "promote": [], "demote": []}
        FL.load_auto()
        assert "ZzAutoNew1" not in FL.CFG["breaking"] and brk in FL.CFG["breaking"]  # يُبنى من الأصل كل مرة
        FL.gh_get = lambda a: {"updated_utc": "z", "promote": ["ZzAutoNew2"], "demote": []}
        FL.load_auto()
        FL.gh_get = lambda a: []  # تعذر التنزيل
        assert FL.load_auto() is None and "ZzAutoNew2" in FL.CFG["breaking"]
    finally:
        FL.gh_get = get
        FL.CFG.update(keep)


def run():
    test_merge()
    test_compute()
    test_fastlane_loader()
    print("test_auto_tune ok")


if __name__ == "__main__":
    run()
