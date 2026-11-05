"""التغذية اللحظية للتطبيق (وتنبيهات الهاتف عبر tools/web_push.py): كل خبر ينشره المسار السريع يوصل لتطبيق «هوبي عاجل» خلال ثوانٍ بدل انتظار الجولة (5–9 دقائق).

- المسار السريع ينشر الخبر على موضوع ntfy.sh العام (مجاني بلا حساب)، والتطبيق يستمع له مباشرة (EventSource).
- الموضوع العام قد يكتب عليه أي أحد، لذلك كل رسالة موقّعة بمفتاح ECDSA P-256 مشتق من سرّ البوت؛
  التطبيق يتحقق من التوقيع بالمفتاح العام (pwa/live.json) ويرمي أي رسالة غير موقّعة. لا يُطبع السر ولا المفتاح الخاص.
- فشل ntfy لا يوقف شيئاً: النشر بخيط خلفي بمهلة قصيرة، والتطبيق يرجع للتحديث العادي.

الاستخدام في الجولة الرئيسية: python3 -m tools.live_feed  ← يكتب pwa/live.json (الموضوع + المفتاح العام).
"""
import base64
import hashlib
import json
import os
import threading
import urllib.request
from pathlib import Path

TOPIC = "hobi-ajel-live-v1-9c4e27"
ROOT = Path(__file__).resolve().parent.parent

# منحنى P-256
_P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
_A = _P - 3
_G = (0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
      0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5)


def _scalar(token):
    return int.from_bytes(hashlib.sha256(("rasid-live:" + token).encode()).digest(), "big") % (_N - 1) + 1


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0] and (p[1] + q[1]) % _P == 0:
        return None
    if p == q:
        lam = (3 * p[0] * p[0] + _A) * pow(2 * p[1], -1, _P) % _P
    else:
        lam = (q[1] - p[1]) * pow(q[0] - p[0], -1, _P) % _P
    x = (lam * lam - p[0] - q[0]) % _P
    return x, (lam * (p[0] - x) - p[1]) % _P


def public_key_b64(token):
    """المفتاح العام بصيغة raw غير مضغوطة (04||X||Y) — حساب بايثون صرف بلا مكتبات."""
    return point_b64(_scalar(token))


def point_b64(k):
    """k·G على P-256 بصيغة raw غير مضغوطة (base64)."""
    r, q = None, _G
    while k:
        if k & 1:
            r = _add(r, q)
        q = _add(q, q)
        k >>= 1
    raw = b"\x04" + r[0].to_bytes(32, "big") + r[1].to_bytes(32, "big")
    return base64.b64encode(raw).decode()


def _sign(token, data):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    key = ec.derive_private_key(_scalar(token), ec.SECP256R1())
    r, s = decode_dss_signature(key.sign(data, ec.ECDSA(hashes.SHA256())))
    return base64.b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).decode()  # IEEE P1363 كما يتوقع WebCrypto


def publish(token, item):
    """item: {id, title, t (ISO UTC), urgent, src, url, msg}. بخيط خلفي؛ لا يرفع استثناء أبداً."""
    def run():
        try:
            p = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            body = json.dumps({"p": p, "s": _sign(token, p.encode())}, ensure_ascii=False).encode()
            req = urllib.request.Request(f"https://ntfy.sh/{TOPIC}", data=body, method="POST",
                                         headers={"Content-Type": "text/plain; charset=utf-8", "Cache": "yes"})
            urllib.request.urlopen(req, timeout=6).read()
        except Exception as e:  # noqa: BLE001
            print("::warning title=live_feed::", type(e).__name__)
    threading.Thread(target=run, daemon=True).start()
    try:  # تنبيه الهاتف (Web Push) لمن اشترك — يعمل فقط داخل المسار السريع (web_push.start)، وإلا لا شيء
        from tools import web_push
        web_push.notify(item)
    except Exception:  # noqa: BLE001
        pass


def main():
    token = os.environ.get("MARSAD_TG_BOT_TOKEN", "").strip()
    if not token:
        return
    out = ROOT / "pwa" / "live.json"
    from tools import web_push
    out.write_text(json.dumps({"topic": TOPIC, "pub": public_key_b64(token), "max_age_min": 30,
                               "vapid": web_push.vapid_public(token), "subs_topic": web_push.SUBS_TOPIC}), encoding="utf-8")
    print("live.json ok")


if __name__ == "__main__":
    main()
