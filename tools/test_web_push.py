"""اختبارات تنبيهات الهاتف (Web Push) وشارة الموثوقية — بلا شبكة وبلا إرسال حقيقي."""
import base64
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import web_push as WP  # noqa: E402


def _ua():
    """اشتراك متصفح وهمي: مفتاح p256dh حقيقي + auth عشوائي، لفك التشفير بالاختبار."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    k = ec.generate_private_key(ec.SECP256R1())
    pub = k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = os.urandom(16)
    return k, {"endpoint": "https://fcm.googleapis.com/fcm/send/abc123", "keys": {"p256dh": WP.b64u(pub), "auth": WP.b64u(auth)}}


def _decrypt(k, sub, body):
    """فك RFC 8291 من جهة المتصفح (للتحقق من صحة التشفير)."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, idlen = body[:16], body[20]
    as_pub, ct = body[21:21 + idlen], body[21 + idlen:]
    ua_pub, auth = WP.unb64u(sub["keys"]["p256dh"]), WP.unb64u(sub["keys"]["auth"])
    shared = k.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_pub))

    def hk(s, ikm, info, n):
        prk = hmac.new(s, ikm, hashlib.sha256).digest()
        return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:n]
    ikm = hk(auth, shared, b"WebPush: info\x00" + ua_pub + as_pub, 32)
    pt = AESGCM(hk(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)).decrypt(hk(salt, ikm, b"Content-Encoding: nonce\x00", 12), ct, None)
    assert pt.endswith(b"\x02")
    return pt[:-1]


def run():
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    tok = "123456:TEST-token-not-real"
    # 1) مفتاح VAPID: الحساب الصرف = cryptography، ويختلف عن مفتاح توقيع التغذية اللحظية
    raw = WP._vapid_key(tok).public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    assert WP.unb64u(WP.vapid_public(tok)) == raw and len(raw) == 65
    from tools import live_feed as LF
    assert base64.b64decode(LF.public_key_b64(tok)) != raw
    assert WP.vapid_public(tok) == WP.vapid_public(tok) and WP.vapid_public(tok + "x") != WP.vapid_public(tok)
    # 2) ترويسة VAPID: JWT موقّع يتحقق بالمفتاح العام
    h = WP.vapid_header(tok, "https://fcm.googleapis.com/fcm/send/abc")
    jwt = h.split("t=")[1].split(",")[0]
    a, b, sg = jwt.split(".")
    claims = json.loads(WP.unb64u(b))
    assert claims["aud"] == "https://fcm.googleapis.com" and claims["sub"].startswith("https://")
    sb = WP.unb64u(sg)
    pk = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
    pk.verify(encode_dss_signature(int.from_bytes(sb[:32], "big"), int.from_bytes(sb[32:], "big")), f"{a}.{b}".encode(), ec.ECDSA(hashes.SHA256()))
    assert h.endswith("k=" + WP.vapid_public(tok))
    # 3) التشفير aes128gcm يفكه المتصفح
    k, sub = _ua()
    msg = WP.payload_of({"id": "x/1", "title": "انفجار في بغداد", "urgent": True, "msg": 3200})
    out = json.loads(_decrypt(k, sub, WP.encrypt(sub, msg)))
    assert out["title"] == "🔴 عاجل" and out["url"] == "https://t.me/hassawassal/3200" and out["body"] == "انفجار في بغداد"
    assert json.loads(WP.payload_of({"title": "خبر", "urgent": False}))["title"] == "مهم"
    # 4) التحقق من الاشتراك: مضيفو الدفع الرسميون فقط وصيغة المفاتيح
    assert WP.valid_sub(sub)
    for host in ("updates.push.services.mozilla.com", "web.push.apple.com", "wns2-db5p.notify.windows.com"):
        assert WP.valid_sub({**sub, "endpoint": f"https://{host}/x"}), host
    for bad in ("http://fcm.googleapis.com/x", "https://evil.com/x", "https://fcm.googleapis.com.evil.com/x", "https://notify.windows.com.evil.io/x", ""):
        assert not WP.valid_sub({**sub, "endpoint": bad}), bad
    assert not WP.valid_sub({**sub, "keys": {"p256dh": WP.b64u(b"\x04" * 10), "auth": sub["keys"]["auth"]}})
    assert not WP.valid_sub({**sub, "keys": {"p256dh": sub["keys"]["p256dh"], "auth": "abc"}})
    # 5) التفضيلات
    U = {"title": "انفجار عبوة في البصرة", "urgent": True}
    I = {"title": "محافظ الديوانية يفتتح مستشفى", "urgent": False}
    assert WP.wants({"mode": "urgent"}, U) and not WP.wants({"mode": "urgent"}, I)
    assert WP.wants({"mode": "important"}, U) and WP.wants({"mode": "important"}, I)
    assert WP.wants({"mode": "gov", "gov": "البصرة"}, U) and not WP.wants({"mode": "gov", "gov": "البصرة"}, I)
    assert WP.wants({"mode": "gov", "gov": "القادسية"}, I)  # مركز المحافظة يكفي
    assert WP.clean_prefs({"mode": "gov"}) == {"mode": "urgent"} and WP.clean_prefs({"mode": "gov", "gov": "بابل"}) == {"mode": "gov", "gov": "بابل"}
    assert WP.clean_prefs({"mode": "hack"}) == {"mode": "urgent"} and len(WP.GOVS) == 18
    # 6) رسائل موضوع الاشتراكات: إضافة، تكرار، تحديث، إلغاء، سقف
    subs = {}
    assert WP.apply_msg(subs, json.dumps({"sub": sub, "prefs": {"mode": "important"}}), 10)
    assert WP.apply_msg(subs, json.dumps({"sub": sub, "prefs": {"mode": "gov", "gov": "بغداد"}}), 20) and len(subs) == 1
    assert subs[sub["endpoint"]]["prefs"]["gov"] == "بغداد"
    assert not WP.apply_msg(subs, json.dumps({"sub": sub, "prefs": {"mode": "urgent"}}), 5)  # أقدم: لا يغلب
    assert not WP.apply_msg(subs, "not json", 30) and not WP.apply_msg(subs, json.dumps({"sub": {"endpoint": "https://evil.com/x"}}), 30)
    assert WP.apply_msg(subs, json.dumps({"endpoint": sub["endpoint"], "off": True}), 40) and not subs
    big = {f"https://fcm.googleapis.com/{i}": {} for i in range(WP.MAX_SUBS)}
    assert not WP.apply_msg(big, json.dumps({"sub": sub}), 1) and len(big) == WP.MAX_SUBS
    # 7) المرسل بخدمات وهمية: يقرأ الاشتراكات، يحترم التفضيلات، يحذف 410، ويحفظ بلا مفتاح خاص
    k2, sub2 = _ua()
    sub2["endpoint"] = "https://updates.push.services.mozilla.com/wpush/v2/zz"
    saved, sent = [], []
    feed = [{"id": "m1", "time": 100, "event": "message", "message": json.dumps({"sub": sub, "prefs": {"mode": "urgent"}})},
            {"id": "m2", "time": 101, "event": "message", "message": json.dumps({"sub": sub2, "prefs": {"mode": "important"}})}]

    def fake_send(s, payload, urgent):
        sent.append((s["endpoint"], urgent))
        return 410 if "mozilla" in s["endpoint"] else 201
    S = WP.Sender(tok, load=lambda: [], save=saved.append, poll=lambda since: feed if since == "all" else [], send=fake_send)
    S.restore()
    S.refresh()
    assert len(S.subs) == 2 and S.since == "m2"
    S.persist(force=True)
    blob = json.dumps(saved[-1])
    assert saved[-1]["n"] == 2 and saved[-1]["since"] == "m2" and str(WP._scalar(tok)) not in blob and tok not in blob
    assert S.deliver({"title": "خبر مهم عادي", "urgent": False, "msg": 1}) == 0 and len(sent) == 1  # المشترك الثاني فقط (410 ← يُحذف)
    assert len(S.subs) == 1 and S.stats["gone"] == 1
    assert S.deliver({"title": "عاجل", "urgent": True, "msg": 2}) == 1 and sent[-1] == (sub["endpoint"], True)
    S2 = WP.Sender(tok, load=lambda: saved[-1], poll=lambda since: [])
    S2.restore()
    assert S2.since == "m2" and len(S2.subs) == 2
    # notify بلا مرسل = لا شيء، ولا استثناء
    WP.SENDER[0] = None
    WP.notify({"title": "x"})
    # 8) شارة الموثوقية
    from tools.export_pwa import trust_badge as TB
    from tools import reliability as R
    R.load(data={"sources": {  # جدول طبقات ثابت للاختبار (الحقيقي يتغير يومياً)
        "telegram:t.me/dijlahtvchannel": {"tier": "موثوقة", "name": "دجلة الفضائية — telegram", "net": "دجله"},
        "telegram:t.me/altaghiertvch": {"tier": "موثوقة", "name": "قناة التغيير الفضائية — telegram", "net": "التغيير"}}})
    off = {"url": "https://t.me/iraqipmo/100", "source_id": "telegram:t.me/iraqipmo", "source_name": "المكتب الإعلامي لرئيس مجلس الوزراء — telegram",
           "title": "رئيس الوزراء يوجه بصرف رواتب المتقاعدين يوم الأحد"}
    a1 = {"url": "https://t.me/someone/5", "source_id": "telegram:t.me/someone", "source_name": "قناة ما — telegram",
          "title": "رئيس الوزراء يوجه بصرف رواتب المتقاعدين يوم الأحد المقبل"}
    t1 = {"url": "https://t.me/dijlahtvchannel/9", "source_id": "telegram:t.me/dijlahtvchannel", "source_name": "دجلة الفضائية — telegram",
          "title": "صرف رواتب المتقاعدين يوم الأحد بتوجيه من رئيس الوزراء"}
    t2 = {"url": "https://t.me/altaghiertvch/7", "source_id": "telegram:t.me/altaghiertvch", "source_name": "قناة التغيير الفضائية — telegram",
          "title": "توجيه بصرف رواتب المتقاعدين يوم الأحد"}
    assert TB([off, a1], off["title"]) == "رسمي"
    assert TB([a1, off], a1["title"]) == "مؤكد"
    assert TB([a1, dict(off, title="المكتب الإعلامي ينفي توجيه رئيس الوزراء بصرف رواتب المتقاعدين يوم الأحد")], a1["title"]) != "مؤكد"
    assert TB([a1], a1["title"]) == "غير مؤكد"
    assert TB([t1, t2], t1["title"]) == "متطابق"
    assert TB([t1, dict(t1, url="https://t.me/dijlahtvchannel/10")], t1["title"]) == "غير مؤكد"  # الشبكة نفسها ≠ مصدران مستقلان
    assert TB([t1, t2], "مصادر: صرف رواتب المتقاعدين يوم الأحد") == "غير مؤكد"
    assert TB([a1, dict(a1, source_name="قناة أخرى — telegram", source_id="telegram:t.me/other")], a1["title"]) is None
    assert TB([off], off["title"], "ثبت عدم صحته") is None and TB([], "x") is None
    R._TRUST.clear()
    print("web_push ok")


if __name__ == "__main__":
    run()
