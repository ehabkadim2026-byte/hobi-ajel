"""قوائم المتابعة (config/follow.json): مطابقة الشخصيات والجهات والقضايا على مستوى الحدث + نوع الرصد.

نوع الرصد لكل حدث مطابق لشخصية/جهة:
  رصد مباشر      — مادة من حساب الجهة نفسها المرصود (قناة تلغرام رسمية أو موقعها).
  إدخال يدوي     — أدخله محرر عبر البوت (رابط/نص/صورة).
  نقل عن مصدر    — وصلنا عبر وسيلة إعلام نقلت التصريح؛ ليس رصداً مباشراً للحساب الأصلي.
الحسابات التي لا نصل إليها رسمياً (فيسبوك، X) تُعرض «متعذّر الوصول المباشر» ولا ندّعي رصدها.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from marsad.textnorm import norm_ar

ROOT = Path(__file__).resolve().parent.parent


def load():
    try:
        return json.loads((ROOT / "config" / "follow.json").read_text(encoding="utf-8"))["follow"]
    except Exception:  # noqa: BLE001
        return []


def _dom(u):
    try:
        h = urlsplit(u or "").netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except ValueError:
        return ""


class Matcher:
    def __init__(self, follow=None):
        self.follow = follow if follow is not None else load()
        self.rx = []
        for f in self.follow:
            ar = [norm_ar(t) for t in f.get("terms_ar", []) if t]
            ar_rx = re.compile(r"(^|\s)(و|ب|ل|ال|لل)?(" + "|".join(re.escape(t) for t in sorted(ar, key=len, reverse=True)) + r")(\s|$)") if ar else None
            en = [t for t in f.get("terms_en", []) if t]
            en_rx = re.compile(r"\b(" + "|".join(re.escape(t) for t in en) + r")\b", re.I if any(len(t) > 4 for t in en) else 0) if en else None
            exc = [norm_ar(x) for x in f.get("exclude", [])]
            acc = f.get("accounts") or {}
            own_tg = (acc.get("telegram") or "").lower().rstrip("/")
            own_dom = _dom(acc.get("website"))
            self.rx.append((f, ar_rx, en_rx, exc, own_tg, own_dom))

    def match(self, ntext, raw, rows):
        """ntext: نص الحدث موحّداً، raw: النص الخام، rows: مواد الحدث (url, platform). يرجع [{id, prov}]."""
        hits = []
        padded = " " + ntext + " "
        for f, ar_rx, en_rx, exc, own_tg, own_dom in self.rx:
            if exc and any(x in ntext for x in exc):
                continue
            if not ((ar_rx and ar_rx.search(padded)) or (en_rx and en_rx.search(raw))):
                continue
            prov = None
            if f.get("kind") != "topic":
                prov = "نقل عن مصدر"
                for r in rows:
                    u = (r["url"] or "").lower()
                    if r["platform"] == "manual":
                        prov = "إدخال يدوي"
                    if r["platform"] == "facebook_notif":
                        prov = "إشعار فيسبوك"
                    if (own_tg and u.startswith(own_tg + "/")) or (own_dom and _dom(u).endswith(own_dom)):
                        prov = "رصد مباشر"
                        break
            hits.append({"id": f["id"], "prov": prov})
        return hits


def accounts_status(f, health_by_url, gn_domains):
    """حالة كل حساب لشخصية/جهة: كيف نرصده فعلاً."""
    acc = f.get("accounts") or {}
    out = []
    tg = acc.get("telegram")
    if tg:
        h = health_by_url.get(tg.lower().rstrip("/"))
        out.append({"k": "تلغرام", "url": tg, "how": "رصد مباشر" if h else "غير مُضاف",
                    "state": h["state"] if h else None, "last": h["last_success"] if h else None})
    web = acc.get("website")
    if web:
        d = _dom(web)
        out.append({"k": "الموقع", "url": web, "how": "عبر Google News" if any(d and d in g for g in gn_domains) else "غير مرصود (لا RSS متاح)",
                    "state": None, "last": None})
    if acc.get("facebook"):
        out.append({"k": "فيسبوك", "url": acc["facebook"], "how": "متعذّر الوصول المباشر — نتابع النقل عنه والإدخال اليدوي", "state": None, "last": None})
    if acc.get("x"):
        out.append({"k": "X", "url": acc["x"], "how": "متعذّر الوصول المباشر (الوصول الرسمي مدفوع)", "state": None, "last": None})
    if acc.get("youtube"):
        out.append({"k": "يوتيوب", "url": acc["youtube"], "how": "متعذّر حالياً (خلاصات يوتيوب محجوبة عن خوادمنا)", "state": None, "last": None})
    if not out:
        out.append({"k": "—", "url": None, "how": "لا حساب رسمي مؤكد — نعتمد على النقل والبحث والإدخال اليدوي", "state": None, "last": None})
    return out
