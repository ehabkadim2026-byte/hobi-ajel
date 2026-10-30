"""طبقة التحقق وتتبع الأصل (على مستوى الحدث).

حالات التحقق الخمس:
  غير متحقق            — لا دليل كافٍ بعد. عدم العثور على تأكيد لا يجعل الخبر إشاعة.
  منسوب لمصدر رسمي     — صدر عن جهة رسمية أو نُسب إليها صراحة. يثبت أنها قالته، لا أن كل ما فيه صحيح.
  مؤيد بمصادر مستقلة   — جهتان فأكثر لا تنقل إحداهما عن الأخرى ولا عن المصدر نفسه، ونصوصها ليست نسخاً متطابقة.
  متنازع عليه          — ظهر نفي أو تكذيب أو تصحيح ضمن الحدث نفسه.
  ثبت عدم صحته         — حكم محرر فقط (عبر البوت)، لا يصدر آلياً أبداً.
"""
import re

from marsad.core import outlet_key
from marsad.textnorm import norm_ar, tokens

DENY = [norm_ar(w) for w in ["ينفي", "تنفي", "نفى", "نفت", "نفي", "تكذيب", "يكذب", "تكذب", "عار عن الصحة", "عاري عن الصحة", "غير صحيح",
                              "لا صحة", "مفبرك", "مفبركة", "خبر كاذب", "اخبار كاذبة", "مزيف", "مزيفة", "تصحيح"]]
DENY_EN = re.compile(r"\b(denies|denied|deny|false claim|fake|fabricated|debunk)", re.I)
CITED_RX = re.compile(r"(?:نقلاً|نقلا)\s+عن\s+([^\n،,.:؛\"«»]{3,45})|(?:بحسب|حسب|وفقاً\s*لـ?|وفقا\s*لـ?|طبقاً\s*لـ?)\s*([^\n،,.:؛\"«»]{3,45})"
                      r"|(?:ذكرت|أفادت|افادت|أعلنت|اعلنت|أكدت|اكدت|قالت|قال)\s+([^\n،,.:؛\"«»]{3,45})")
ANON_RX = re.compile(r"(مصدر|مصادر)\s+(أمني|امني|مطلع|سياسي|حكومي|خاص|مطلعة|أمنية|امنية|مقرب|مقربة)")
OFFICIAL_RX = re.compile(r"(وزارة|وزير|هيئة|مجلس|قيادة|خلية|مديرية|رئاسة|رئيس|محافظة|محافظ|الناطق|المتحدث|المكتب الإعلامي|المكتب الاعلامي|البنك المركزي|المفوضية|الحكومة|السفارة|القضاء|المحكمة)")
DENY_WORDS = set(DENY)


def cited_source(text):
    """المصدر الذي يستند إليه النص (أول نسبة صريحة)، أو «مصدر غير مسمى»، أو None."""
    t = text or ""
    if ANON_RX.search(t[:300]):
        return "مصدر غير مسمى"
    m = CITED_RX.search(t[:400])
    if not m:
        return None
    s = next(g for g in m.groups() if g)
    s = " ".join(s.split()[:4]).strip(" -–")
    return s if len(s) >= 3 else None


def _jac(a, b):
    a, b = set(a), set(b)
    return len(a & b) / max(1, len(a | b))


def assess(rows, verdict=None):
    """rows: مواد الحدث مرتبة زمنياً (dict: source_name, url, title, text, official, platform, published_utc, collected_utc).
    يرجع: vstatus، vwhy، cited (المصدر المستند إليه الغالب)، origin (أقدم نشر رصدته المنظومة)، independent."""
    if not rows:
        return {"vstatus": "غير متحقق", "vwhy": "لا مواد", "cited": None, "origin": None, "independent": 0}
    first = rows[0]
    origin = {"source": first["source_name"], "url": first["url"], "pub": first["published_utc"], "seen": first["collected_utc"],
              "cited": cited_source((first["title"] or "") + " " + (first["text"] or "")), "manual": first["platform"] == "manual"}
    # استقلالية: جهة واحدة لكل منفذ؛ النسخ المتطابقة نصياً أو المستندة لنفس المصدر تُحسب مصدراً واحداً
    seen_outlets, groups, toks_list = set(), set(), []
    cites = []
    for r in rows:
        ok = outlet_key(r["source_name"])
        if ok in seen_outlets:
            continue
        seen_outlets.add(ok)
        body = (r["title"] or "") + " " + (r["text"] or "")
        c = cited_source(body)
        if c:
            cites.append(c)
        tk = tokens(body[:400])
        if any(_jac(tk, t2) >= 0.75 for t2 in toks_list):
            continue  # نسخة شبه حرفية من نص سبق
        toks_list.append(tk)
        groups.add(norm_ar(c) if c else "self:" + ok)
    independent = len([g for g in groups if g != norm_ar("مصدر غير مسمى")]) + (1 if norm_ar("مصدر غير مسمى") in groups else 0)
    main_cite = max(set(cites), key=cites.count) if cites else None
    denial = None
    for r in rows[1:]:
        nt = norm_ar((r["title"] or "") + " " + (r["text"] or "")[:300])
        if any(w in nt for w in DENY) or DENY_EN.search(r["title"] or ""):
            denial = r
            break
    if verdict:
        st, why = verdict.get("status"), "حكم محرر: " + (verdict.get("note") or verdict.get("by") or "")
    elif denial:
        st, why = "متنازع عليه", f"نفي/تصحيح لدى {denial['source_name']}"
    elif main_cite == "مصدر غير مسمى" and not any(r["official"] and not cited_source((r["title"] or "") + " " + (r["text"] or "")) for r in rows):
        st, why = "غير متحقق", "منسوب إلى مصدر غير مسمى (حتى لو نقلته وسيلة رسمية)"
    elif independent >= 2:
        st, why = "مؤيد بمصادر مستقلة", f"{independent} مصادر مستقلة (بعد استبعاد النسخ والنقل عن المصدر نفسه)"
    elif any(r["official"] for r in rows):
        src = next(r["source_name"] for r in rows if r["official"])
        st, why = "منسوب لمصدر رسمي", f"صادر عن {src} — يثبت التصريح لا صحة كل مضمونه"
    elif main_cite and main_cite != "مصدر غير مسمى" and OFFICIAL_RX.search(main_cite):
        st, why = "منسوب لمصدر رسمي", f"منسوب إلى «{main_cite}» حسب الناقل — لم نرصد الأصل الرسمي"
    else:
        st, why = "غير متحقق", ("نقل عن مصدر غير مسمى" if main_cite == "مصدر غير مسمى" else "مصدر واحد أو نسخ متطابقة")
    return {"vstatus": st, "vwhy": why, "cited": main_cite, "origin": origin, "independent": independent}


def is_denial(title):
    nt = norm_ar(title or "")
    return any(w in nt for w in DENY) or bool(DENY_EN.search(title or ""))


def cross_disputes(items):
    """النفي غالباً يُنشر كحدث منفصل. نربط كل حدث نفي بالحدث الذي ينفيه (تشابه الكلمات بعد حذف كلمات النفي)."""
    deny_tok = {t for w in DENY for t in tokens(w)} | set(tokens("صحة الأنباء الأخبار المتداولة ما تداولته مواقع"))
    denials = [o for o in items if is_denial(o.get("title_orig") or o["title"])]
    if not denials:
        return
    toks = {o["id"]: set(tokens(o["title"])) - deny_tok for o in items}
    for d in denials:
        td = toks[d["id"]]
        if len(td) < 3:
            continue
        for o in items:
            if o is d or o["vstatus"] in ("ثبت عدم صحته",) or is_denial(o["title"]):
                continue
            to = toks[o["id"]]
            inter = len(td & to)
            if inter >= 3 and inter / max(1, min(len(td), len(to))) >= 0.5 and (o["first_utc"] or "") <= (d["latest_utc"] or "~"):
                o["vstatus"] = "متنازع عليه"
                o["vwhy"] = f"نفي/تصحيح لدى {(d['sources'] or [{}])[0].get('name')}: «{d['title'][:90]}»"
                o["disputed_by"] = d["id"]
