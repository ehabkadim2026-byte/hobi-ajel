"""تنبيهات الهاتف للعاجل (Web Push القياسي، مجاني بلا خادم): كل خبر ينشره المسار السريع (أو أمر محرر /نشر) يصل إشعاراً
لمن فعّل «🔔 تنبيهات العاجل» في تطبيق «هوبي عاجل» حتى والتطبيق مسكّر.

- مفتاح VAPID مشتق حتمياً من سرّ البوت: sha256("rasid-vapid:"+token) على P-256. العام في pwa/live.json (vapid)،
  والخاص لا يُكتب على القرص ولا يُطبع.
- الاشتراكات: التطبيق يرسل {sub, prefs} أو {endpoint, off:true} لموضوع ntfy عام مخصص (TOPIC+"-subs"). المسار السريع يقرؤه كل ~2 دقيقة،
  يتحقق من المضيف (خدمات الدفع الرسمية فقط) وصيغة المفاتيح، يزيل التكرار بالـendpoint، بسقف 2000، ويحفظ القائمة على إصدار fastlane
  (push_subs.json: عناوين الاشتراك ومفاتيح التشفير العامة للمتصفحات والتفضيلات فقط — لا أسرار لنا). 404/410 = اشتراك منتهٍ يُحذف.
- التشفير RFC 8291 (aes128gcm) والتوقيع RFC 8292 (VAPID ES256) بمكتبة cryptography مباشرة.
- كل شيء بخيط خلفي: لا يوقف حلقة النشر أبداً، والأخطاء تحذيرات فقط.
"""
import base64
import hashlib
import hmac
import json
import os
import queue
import re
import struct
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from tools.live_feed import TOPIC, _N, point_b64

SUBS_TOPIC = TOPIC + "-subs"
ASSET = "push_subs.json"
MAX_SUBS = 2000
POLL_SEC = 120
TTL = 3600
SUBJECT = "https://ehabkadim2026-byte.github.io/hobi-ajel/"
HOSTS = {"fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com"}
MODES = ("urgent", "important", "gov")
# المحافظات الـ18 ومدنها وأقضيتها: قاموس واحد مشترك مع التطبيق (حقل province، «محافظتي»، الخريطة) — tools/provinces.py
from tools.provinces import GOVS, mentions as _gov_mentions  # noqa: E402


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s):
    s = str(s or "")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _scalar(token):
    return int.from_bytes(hashlib.sha256(("rasid-vapid:" + token).encode()).digest(), "big") % (_N - 1) + 1


def vapid_public(token):
    """المفتاح العام (raw 65 بايت) بصيغة base64url كما يتوقع pushManager.subscribe — حساب بايثون صرف (للجولة الرئيسية بلا مكتبات)."""
    return b64u(base64.b64decode(point_b64(_scalar(token))))


def _vapid_key(token):
    from cryptography.hazmat.primitives.asymmetric import ec
    return ec.derive_private_key(_scalar(token), ec.SECP256R1())


# ---------------------------------------------------------------- التحقق والتفضيلات
def valid_sub(sub):
    """{endpoint, keys:{p256dh, auth}} صالح ومن خدمة دفع رسمية؟ يرجع النسخة النظيفة أو None."""
    try:
        ep = str(sub.get("endpoint") or "")
        u = urlparse(ep)
        host = (u.hostname or "").lower()
        if u.scheme != "https" or len(ep) > 1024 or not (host in HOSTS or host.endswith(".notify.windows.com")):
            return None
        keys = sub.get("keys") or {}
        p, a = unb64u(keys.get("p256dh")), unb64u(keys.get("auth"))
        if len(p) != 65 or p[0] != 4 or len(a) != 16:
            return None
        return {"endpoint": ep, "keys": {"p256dh": b64u(p), "auth": b64u(a)}}
    except Exception:  # noqa: BLE001
        return None


def clean_prefs(p):
    p = p if isinstance(p, dict) else {}
    mode = p.get("mode") if p.get("mode") in MODES else "urgent"
    gov = p.get("gov") if p.get("gov") in GOVS else None
    if mode == "gov" and not gov:
        mode = "urgent"
    return {"mode": mode, **({"gov": gov} if mode == "gov" else {})}


def wants(prefs, item):
    """هل يريد هذا المشترك هذا الخبر؟ عاجل فقط / عاجل ومهم (كل ما ينشره المسار السريع مهم) / محافظة (ذكرها بنص الخبر)."""
    mode = prefs.get("mode")
    if mode == "urgent":
        return bool(item.get("urgent"))
    if mode == "important":
        return True
    if mode == "gov":
        return _gov_mentions(item.get("title") or "", prefs.get("gov"))
    return False


def apply_msg(subs, msg, ts):
    """رسالة من موضوع الاشتراكات ← تحديث القاموس subs (endpoint → سجل). يرجع True إذا تغيّر شيء."""
    try:
        o = json.loads(msg) if isinstance(msg, str) else msg
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(o, dict):
        return False
    if o.get("off"):
        ep = str(o.get("endpoint") or "")
        return subs.pop(ep, None) is not None
    s = valid_sub(o.get("sub") or {})
    if not s:
        return False
    old = subs.get(s["endpoint"])
    if old and old.get("ts", 0) > ts:
        return False
    if not old and len(subs) >= MAX_SUBS:
        return False
    subs[s["endpoint"]] = {"sub": s, "prefs": clean_prefs(o.get("prefs")), "ts": ts}
    return True


# ---------------------------------------------------------------- التشفير والإرسال
def _hkdf(salt, ikm, info, n):
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:n]


def encrypt(sub, payload, _eph=None, _salt=None):
    """RFC 8291: جسم aes128gcm (ترويسة + نص مشفر) لاشتراك المتصفح."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import serialization
    ua_pub = unb64u(sub["keys"]["p256dh"])
    auth = unb64u(sub["keys"]["auth"])
    eph = _eph or ec.generate_private_key(ec.SECP256R1())
    as_pub = eph.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = eph.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub))
    ikm = _hkdf(auth, shared, b"WebPush: info\x00" + ua_pub + as_pub, 32)
    salt = _salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ct = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack(">IB", 4096, len(as_pub)) + as_pub + ct


def vapid_header(token, endpoint, now=None):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    u = urlparse(endpoint)
    head = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int((now or time.time()) + 12 * 3600), "sub": SUBJECT},
                             separators=(",", ":")).encode())
    r, s = decode_dss_signature(_vapid_key(token).sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
    jwt = f"{head}.{claims}.{b64u(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={jwt}, k={vapid_public(token)}"


def payload_of(item):
    msg = item.get("msg")
    url = f"https://t.me/hassawassal/{msg}" if msg else SUBJECT
    return json.dumps({"title": "🔴 عاجل" if item.get("urgent") else "مهم", "body": (item.get("title") or "")[:240],
                       "url": url, "tag": str(item.get("id") or "")[:64]}, ensure_ascii=False).encode()


def send_one(token, sub, payload, urgent, opener=urllib.request.urlopen):
    """يرجع رمز HTTP (أو 0 عند خطأ الشبكة)."""
    req = urllib.request.Request(sub["endpoint"], data=encrypt(sub, payload), method="POST", headers={
        "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream", "TTL": str(TTL),
        "Urgency": "high" if urgent else "normal", "Authorization": vapid_header(token, sub["endpoint"])})
    try:
        with opener(req, timeout=10) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return 0


# ---------------------------------------------------------------- المرسل الخلفي
class Sender:
    def __init__(self, token, load=None, save=None, poll=None, send=None):
        self.token = token
        self.q = queue.Queue(maxsize=200)
        self.subs, self.since, self.dirty = {}, "all", False
        self._load, self._save = load, save
        self._poll = poll or self.poll_ntfy
        self._send = send or (lambda sub, payload, urgent: send_one(token, sub, payload, urgent))
        self.stats = {"subs": 0, "sent": 0, "gone": 0, "fail": 0}
        self.last_poll = 0.0
        self.last_save = 0.0

    def restore(self):
        d = self._load() if self._load else None
        if isinstance(d, dict):
            for r in d.get("subs") or []:
                s = valid_sub(r.get("sub") or {})
                if s and len(self.subs) < MAX_SUBS:
                    self.subs[s["endpoint"]] = {"sub": s, "prefs": clean_prefs(r.get("prefs")), "ts": r.get("ts", 0)}
            self.since = d.get("since") or self.since

    def persist(self, force=False):
        if self._save and self.dirty and (force or time.time() - self.last_save >= POLL_SEC):
            self._save({"since": self.since, "n": len(self.subs), "subs": list(self.subs.values()),
                        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            self.dirty, self.last_save = False, time.time()

    def poll_ntfy(self, since):
        url = f"https://ntfy.sh/{SUBS_TOPIC}/json?poll=1&since={since}"
        body = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "hobi-ajel"}), timeout=15).read().decode("utf-8", "replace")
        out = []
        for ln in body.splitlines():
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            if e.get("event") == "message":
                out.append(e)
        return out

    def refresh(self):
        self.last_poll = time.time()
        for e in self._poll(self.since):
            if apply_msg(self.subs, e.get("message") or "", e.get("time") or 0):
                self.dirty = True
            if e.get("id"):
                self.since = e["id"]
                self.dirty = True
        self.stats["subs"] = len(self.subs)
        self.persist()

    def deliver(self, item):
        targets = [r for r in list(self.subs.values()) if wants(r["prefs"], item)]
        if not targets:
            return 0
        payload = payload_of(item)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(8) as ex:
            codes = list(ex.map(lambda r: (r, self._send(r["sub"], payload, bool(item.get("urgent")))), targets))
        n = 0
        for r, code in codes:
            if 200 <= code < 300:
                n += 1
            elif code in (404, 410):
                self.subs.pop(r["sub"]["endpoint"], None)
                self.stats["gone"] += 1
                self.dirty = True
            else:
                self.stats["fail"] += 1
        self.stats["sent"] += n
        self.stats["subs"] = len(self.subs)
        return n

    def loop(self, until):
        try:
            self.restore()
        except Exception as e:  # noqa: BLE001
            print("::warning title=web_push restore::", type(e).__name__)
        while time.time() < until:
            try:
                if time.time() - self.last_poll >= POLL_SEC:
                    self.refresh()
            except Exception as e:  # noqa: BLE001
                self.last_poll = time.time()
                print("::warning title=web_push poll::", type(e).__name__)
            try:
                item = self.q.get(timeout=5)
            except queue.Empty:
                continue
            try:
                self.deliver(item)
                self.persist()
            except Exception as e:  # noqa: BLE001
                print("::warning title=web_push send::", type(e).__name__)
        try:
            self.persist(force=True)
        except Exception:  # noqa: BLE001
            pass


SENDER = [None]


def start(token, until, load=None, save=None):
    """يبدأ المرسل الخلفي (المسار السريع فقط). load/save = قراءة/كتابة push_subs.json على إصدار fastlane."""
    try:
        if SENDER[0] is None and token:
            s = Sender(token, load, save)
            threading.Thread(target=s.loop, args=(until,), daemon=True).start()
            SENDER[0] = s
    except Exception as e:  # noqa: BLE001
        print("::warning title=web_push start::", type(e).__name__)


def notify(item):
    """يُستدعى بعد كل منشور ناجح بالقناة. لا يرفع استثناء ولا ينتظر."""
    try:
        if SENDER[0] is not None:
            SENDER[0].q.put_nowait(dict(item))
    except Exception:  # noqa: BLE001
        pass


def status():
    return dict(SENDER[0].stats) if SENDER[0] is not None else None
