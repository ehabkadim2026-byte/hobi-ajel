"""ترجمة عناوين المصادر الأجنبية (إنكليزي → عربي) مجاناً وبلا مفاتيح، داخل GitHub Actions.

يستخدم نموذج Argos Translate (OPUS-MT) عبر ctranslate2 + sentencepiece مباشرة (بدون torch).
- النموذج يُنزَّل مرة من فهرس Argos الرسمي ويُخزَّن في كاش Actions (~/argos).
- الترجمات تُحفظ في data/translations.json (مخبأة مع قاعدة البيانات) فلا يُترجم عنوان مرتين.
- أي فشل لا يوقف الجولة: يكتب الحالة في pwa/translate_status.json ويستمر التطبيق بالعنوان الأصلي.
ترجمة آلية: تُعرض في التطبيق بوسم «ترجمة آلية» مع العنوان الأصلي.
"""
import io
import json
import re
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from marsad import core  # noqa: E402

INDEX = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
MODEL_DIR = Path.home() / "argos" / "en_ar"
PIVOT = {"fa": Path.home() / "argos" / "fa_en", "tr": Path.home() / "argos" / "tr_en"}  # فارسي/تركي → إنكليزي → عربي
CACHE = ROOT / "data" / "translations.json"
STATUS = ROOT / "pwa" / "translate_status.json"
LATIN = re.compile(r"[A-Za-z]")
ARABIC = re.compile(r"[؀-ۿ]")


def _get(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "MarsadHobi/0.3"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def ensure_model(frm="en", to="ar", d=None):
    d = d or MODEL_DIR
    if (d / "ready").exists():
        return
    idx = json.loads(_get(INDEX))
    pkg = next(p for p in idx if p.get("from_code") == frm and p.get("to_code") == to)
    blob = _get(pkg["links"][0], timeout=600)
    d.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        z.extractall(d)
    (d / "ready").write_text(json.dumps({"version": pkg.get("package_version")}))


def load_translator(d=None):
    import ctranslate2
    import sentencepiece as spm
    d = d or MODEL_DIR
    mb = next(d.rglob("model.bin"))
    sp_path = next(d.rglob("sentencepiece.model"))
    return ctranslate2.Translator(str(mb.parent), device="cpu", inter_threads=2), spm.SentencePieceProcessor(model_file=str(sp_path))


URL_RX = re.compile(r"https?://|www\.|\.com\b|\.net\b|\.org\b")


# مسرد قبل الترجمة: اختصارات عراقية يخطئ فيها النموذج (مثلاً KRG ترجمها «كوريا الشمالية»)
PRE = [(r"\bKRG\b", "Kurdistan Regional Government"), (r"\bKRI\b", "Kurdistan Region"), (r"\bPMF\b", "Popular Mobilization Forces"),
       (r"\bKDP\b", "Kurdistan Democratic Party"), (r"\bPUK\b", "Patriotic Union of Kurdistan"), (r"\bShengal\b", "Sinjar"),
       (r"\bSulaimani\b|\bSulaymani\b|\bSlemani\b", "Sulaymaniyah"), (r"\bHewler\b|\bHawler\b", "Erbil"),
       (r"\bShafaq News\b", "Shafaq"), (r"\bCBI\b", "Central Bank of Iraq"), (r"\bISIS\b|\bISIL\b|\bIslamic State\b", "Daesh"), (r"\bPM\b", "Prime Minister"), (r"\bgraft\b", "corruption"), (r"\bMP\b", "lawmaker"), (r"\bMPs\b", "lawmakers"), (r" - [A-Z][\w .&]+$", ""), (r"\.\.", ": ")]
# تصحيح بعد الترجمة لأسماء معروفة
POST = [("شافاق", "شفق"), ("سوليماني", "السليمانية"), ("السليمانيه", "السليمانية"), ("الشنغال", "سنجار"), ("شنغال", "سنجار"),
        ("جمهورية كوريا الشعبية الديمقراطية", "إقليم كردستان"), ("أربيل أربيل", "أربيل"), ("داعش داعش", "داعش"), ("الشفاق", "شفق"), ("نظام المعلومات الإسلامية", "داعش"), ("دائرة الاستخبارات الإسلامية", "داعش"), ("الدولة الإسلامية", "داعش")]
VERSION = 4


def pre(text):
    for a, b in PRE:
        text = re.sub(a, b, text)
    return text


def post(text):
    import html
    text = html.unescape(text).replace(" ،", "،").replace(" .", ".")
    for a, b in POST:
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()


def needs(text, lang="en"):
    if not text or URL_RX.search(text) or len(text.split()) < 3:
        return False
    if lang == "fa":
        return bool(ARABIC.search(text))
    return len(LATIN.findall(text)) > 8 and not ARABIC.search(text)


def main(limit=500, budget_s=90):
    t0 = time.time()
    cache = {}
    try:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
        if cache.get("_v") != VERSION:
            cache = {}
    except Exception:  # noqa: BLE001
        pass
    status = {"ok": False, "translated_now": 0, "cached": len(cache), "error": None}
    try:
        con = core.connect()
        todo, pivot = [], {"fa": [], "tr": []}
        for (t, lang) in con.execute("SELECT DISTINCT i.title, s.lang FROM items i JOIN sources s ON s.id=i.source_id "
                                     "WHERE s.lang IN ('en','fa','tr') AND i.collected_utc >= datetime('now','-2 day') ORDER BY i.collected_utc DESC"):
            t = (t or "").strip()
            if t in cache:
                continue
            if lang == "en" and needs(t) and t not in todo:
                todo.append(t)
            elif lang in pivot and needs(t, lang) and t not in pivot[lang]:
                pivot[lang].append(t)
        todo = todo[:limit]
        # فارسي/تركي: نترجم للإنكليزي أولاً (نموذج مستقل)، ثم يمر بنفس مسار إنكليزي→عربي. الترجمة الوسيطة تُضعف الدقة: تُوسم آلياً.
        via = {}
        for lang, lst in pivot.items():
            lst = lst[:120]
            if not lst or time.time() - t0 > budget_s * 0.4:
                continue
            try:
                ensure_model(lang, "en", PIVOT[lang])
                ptr, psp = load_translator(PIVOT[lang])
                res = ptr.translate_batch([psp.encode(x, out_type=str) for x in lst], beam_size=2, max_decoding_length=160)
                for src, r in zip(lst, res):
                    en = psp.decode(r.hypotheses[0]).replace("▁", " ").strip()
                    if en and len(LATIN.findall(en)) > 8:
                        via[en] = src
                        if en not in todo:
                            todo.append(en)
                status.setdefault("pivot", {})[lang] = len(lst)
            except Exception as e:  # noqa: BLE001
                status.setdefault("pivot_error", {})[lang] = f"{type(e).__name__}: {e}"[:120]
        if todo:
            ensure_model()
            tr, sp = load_translator()
            for i in range(0, len(todo), 16):
                if time.time() - t0 > budget_s:
                    break
                batch = todo[i:i + 16]
                res = tr.translate_batch([sp.encode(pre(x), out_type=str) for x in batch], beam_size=2, max_decoding_length=160)
                for src, r in zip(batch, res):
                    out = post(sp.decode(r.hypotheses[0]).replace("▁", " "))
                    if out and ARABIC.search(out) and len(out.split()) >= 0.45 * len(src.split()):
                        cache[via.get(src, src)] = out
                        status["translated_now"] += 1
        status["ok"] = True
        status["sample"] = [[k, cache[k]] for k in todo[:5] if k in cache]
    except Exception as e:  # noqa: BLE001
        status["error"] = f"{type(e).__name__}: {e}"[:300]
    cache = {k: v for k, v in cache.items() if k != "_v" and (needs(k) or needs(k, "fa")) and k != v}
    if len(cache) > 6000:
        cache = dict(list(cache.items())[-4000:])
    cache["_v"] = VERSION
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    status.update(cached=len(cache) - 1, seconds=round(time.time() - t0, 1))
    STATUS.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    print(status)


if __name__ == "__main__":
    main()
