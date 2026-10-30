"""تجربة تلفزيون محدودة: تفريغ مقاطع قصيرة تنشرها القنوات العراقية رسمياً على قنواتها العامة في تلغرام.

- لا بث مباشر ولا برامج كاملة: فقط مقاطع ≤ 3 دقائق منشورة علناً، ونحتفظ بالنص والتوقيت والرابط فقط (لا نخزن الفيديو).
- التفريغ آلي (faster-whisper small، عربي) — كل مقطع موسوم «تفريغ آلي يحتاج مراجعة»، والمقاطع منخفضة الثقة مُعلّمة.
- لا ننسب أي عبارة لمتحدث: النموذج لا يميّز المقدّم من الضيف. نعرض نص القناة المرافق كما هو.
- يعمل في سير عمل منفصل (لا يبطئ دورة الرصد)، كل ~20 دقيقة، حتى 3 مقاطع جديدة في كل مرة.
الناتج: tv.json يُرفع إلى إصدار «tv-pilot»، ويقرأه سير العمل الرئيسي ويضعه في التطبيق.
"""
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "tv_state.json"
OUT = ROOT / "data" / "tv.json"
CHANNELS = [("IraqiaGTV", "قناة العراقية العامة"), ("alsumariatviraq", "السومرية"), ("alsharqiyagroup", "الشرقية"),
            ("dijlahtvchannel", "دجلة"), ("utviraq", "UTV"), ("alrabiaatv", "الرابعة"), ("ASIATV1", "آسيا"), ("alawlatv", "الأولى"),
            ("rafidenchannel", "الرافدين"), ("alforat_tv", "الفرات")]
UA = {"User-Agent": "Mozilla/5.0 (HobiAjel TV pilot)"}
MAX_SEC, PER_RUN, EVERY_MIN = 180, 3, 15


def get(url, limit=None, timeout=25):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read(limit) if limit else r.read()


def dur(s):
    p = [int(x) for x in s.split(":")]
    return p[0] * 60 + p[1] if len(p) == 2 else p[0] * 3600 + p[1] * 60 + p[2]


def find_clips(ch):
    page = get(f"https://t.me/s/{ch}").decode("utf-8", "replace")
    out = []
    for block in page.split('class="tgme_widget_message_wrap')[1:]:
        post = re.search(r'data-post="([^"]+)"', block)
        vid = re.search(r'<video[^>]+src="([^"]+)"', block)
        d = re.search(r'message_video_duration[^>]*>([\d:]+)<', block)
        t = re.search(r'<time[^>]+datetime="([^"]+)"', block)
        txt = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', block, re.S)
        if not (post and vid and d):
            continue
        out.append({"post": post.group(1), "video": html.unescape(vid.group(1)), "duration": dur(d.group(1)),
                    "posted": t.group(1) if t else None,
                    "caption": html.unescape(re.sub(r"<[^>]+>", " ", txt.group(1))).strip()[:400] if txt else ""})
    return out


def due():
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"last": 0}
    return time.time() - st.get("last", 0) >= EVERY_MIN * 60


def main():
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"done": [], "last": 0}
    st.pop("fail", None) if len(st.get("fail", {})) > 200 else None
    if time.time() - st.get("last", 0) < EVERY_MIN * 60 and "--force" not in sys.argv:
        print("tv: not due")
        return
    clips = json.loads(OUT.read_text(encoding="utf-8")).get("clips", []) if OUT.exists() else []
    cand, errors = [], {}
    for ch, name in CHANNELS:
        try:
            for c in find_clips(ch):
                if c["post"] not in st["done"] and 5 <= c["duration"] <= MAX_SEC:
                    c["channel"], c["channel_name"] = ch, name
                    cand.append(c)
        except Exception as e:  # noqa: BLE001
            errors[ch] = f"{type(e).__name__}: {str(e)[:80]}"
    cand.sort(key=lambda c: c["posted"] or "", reverse=True)
    new = 0
    if cand:
        from faster_whisper import WhisperModel
        model = WhisperModel("small", device="cpu", compute_type="int8")
        for c in cand[:PER_RUN]:
            t0 = time.time()
            try:
                with tempfile.TemporaryDirectory() as td:
                    v = Path(td) / "v.mp4"
                    v.write_bytes(get(c["video"], limit=60_000_000, timeout=60))
                    # faster-whisper يفك الصوت من الفيديو مباشرة عبر PyAV (لا حاجة لـ ffmpeg على المشغّل)
                    segs, info = model.transcribe(str(v), language="ar", beam_size=3, vad_filter=True)
                    seg = [{"s": round(x.start, 1), "e": round(x.end, 1), "t": x.text.strip(),
                            "low": (x.avg_logprob < -1.0) or (x.no_speech_prob > 0.6)} for x in segs]
                low = sum(1 for x in seg if x["low"])
                clips.append({"post_url": f"https://t.me/{c['post']}", "channel": c["channel_name"], "posted": c["posted"],
                              "caption": c["caption"], "duration": c["duration"], "segments": seg,
                              "low_ratio": round(low / len(seg), 2) if seg else None,
                              "flag": "تفريغ آلي يحتاج مراجعة" + (" — جودة صوت منخفضة" if seg and low / len(seg) > 0.3 else ""),
                              "transcribed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "secs": round(time.time() - t0, 1)})
                new += 1
                st["done"].append(c["post"])
            except Exception as e:  # noqa: BLE001
                errors[c["post"]] = f"{type(e).__name__}: {str(e)[:80]}"
                f = st.setdefault("fail", {})
                f[c["post"]] = f.get(c["post"], 0) + 1
                if f[c["post"]] >= 2:
                    st["done"].append(c["post"])
    st["done"] = st["done"][-500:]
    st["last"] = time.time()
    cut = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")
    clips = [c for c in clips if (c.get("posted") or c["transcribed_utc"]) >= cut][-60:]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "channels": [n for _, n in CHANNELS],
                               "limits": "مقاطع ≤3 دقائق تنشرها القنوات على تلغرام فقط؛ لا بث مباشر؛ تفريغ آلي بلا نسب لمتحدث.",
                               "clips": clips}, ensure_ascii=False), encoding="utf-8")
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    print(f"::notice title=tv_pilot::{json.dumps({'candidates': len(cand), 'new': new, 'total': len(clips), 'errors': errors, 'secs': [c.get('secs') for c in clips[-new:]] if new else []}, ensure_ascii=False)}")


if __name__ == "__main__":
    if "--due" in sys.argv:
        print("due=" + ("true" if due() else "false"))
    else:
        main()
