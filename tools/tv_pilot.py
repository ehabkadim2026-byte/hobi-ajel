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
MAX_SEC, PER_RUN, EVERY_MIN = 300, 3, 15
SEEN = {"videos": 0, "no_public_file": 0}


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
        if d:
            SEEN["videos"] += 1
            if not vid:
                SEEN["no_public_file"] += 1  # فيديو كبير: تلغرام لا يعطي ملفاً عاماً ("افتح التطبيق للمشاهدة")
        t = re.search(r'<time[^>]+datetime="([^"]+)"', block)
        txt = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', block, re.S)
        if not (post and vid and d):
            continue
        out.append({"post": post.group(1), "video": html.unescape(vid.group(1)), "duration": dur(d.group(1)),
                    "posted": t.group(1) if t else None,
                    "caption": html.unescape(re.sub(r"<[^>]+>", " ", txt.group(1))).strip()[:400] if txt else ""})
    return out


PROMO = re.compile(r"(ترقبوا|ترقّبوا|يعرض|تعرض|الليلة|موعدكم|حلقة|الحلقة|برنامج|تابعونا|انتظرونا|قريباً|قريبا|إعلان|اعلان|رعاية|مسلسل|بث مباشر|البث المباشر)")
POST_LIMIT = 2


def auto_post(c, seg, data, st):
    """نشر تلقائي للقناة (بتفويض إيهاب 2026-11-01) فقط للمقطع الذي يجتاز كل الشروط:
    مصدر موثوق (قنوات التلفزيون العراقية الرسمية المدرجة) + مقطع تام + فيه هوك + غير مكرر. يرجع سبب القرار."""
    token = os.environ.get("MARSAD_TG_BOT_TOKEN", "").strip()
    if not token:
        return "لا توكن"
    cap = (c.get("caption") or "").strip()
    words = sum(len(x["t"].split()) for x in seg)
    low = sum(1 for x in seg if x["low"]) / len(seg) if seg else 1
    why = []
    if not 8 <= c["duration"] <= 180:
        why.append("المدة خارج 8–180 ث")
    if seg and words >= 8:  # مقطع فيه كلام: لازم واضح وما مقطوع بالنهاية
        if low > 0.3:
            why.append("صوت غير واضح")
        if seg[-1]["e"] > c["duration"] - 0.4 and c["duration"] > 25:
            why.append("الكلام مقطوع بنهاية المقطع")
    # مقطع مشهدي بلا كلام (لحظة قبض، سيول، حادث) مقبول: الهوك هنا هو الوصف الخبري نفسه
    if len(cap.split()) < 5 or PROMO.search(cap):
        why.append("وصف ترويجي أو ناقص (بلا هوك)")
    if len(data) > 48 * 1024 * 1024:
        why.append("أكبر من 48 ميغا")
    from tools.tg_video import excluded
    if excluded(c.get("channel_name", ""), cap):
        why.append("جهة مستبعدة")
    if st.get("posted_today", {}).get("n", 0) >= 40:
        why.append("سقف يومي")
    from tools.tg_push import title_sig, same_story, api, CHANNEL
    sig = title_sig(cap)
    prev = st.setdefault("posted_sigs", [])
    if any(same_story(sig, x) for x in prev):
        why.append("مكرر")
    if why or st.get("_posted_run", 0) >= POST_LIMIT:
        return "لم يُنشر: " + "، ".join(why or ["سقف الجولة"])
    from tools.editorial import edit_headline
    import html as H
    first = next((ln.strip() for ln in cap.split("\n") if len(ln.strip()) >= 8), cap[:200])
    head = edit_headline(first)
    caption = (f"<b>{H.escape(head)}</b>\n\n🎥 المصدر: {H.escape(c['channel_name'])}\n\nزورونا على الرابط للأخبار العاجلة 👇\n{CHANNEL}")
    chat_id = os.environ.get("MARSAD_TG_CHAT_ID", "").strip() or "@hassawassal"
    try:
        r = api(token, "sendVideo", files={"video": ("clip.mp4", data, "video/mp4")}, chat_id=chat_id, caption=caption[:1024],
                parse_mode="HTML", supports_streaming="true")
    except Exception as e:  # noqa: BLE001
        return f"فشل النشر: {type(e).__name__}"
    if not r.get("ok"):
        return "فشل النشر: " + str(r.get("description"))[:80]
    st["_posted_run"] = st.get("_posted_run", 0) + 1
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    pt = st.get("posted_today") if (st.get("posted_today") or {}).get("d") == day else {"d": day, "n": 0}
    pt["n"] += 1
    st["posted_today"] = pt
    prev.append({"w": sorted(sig[0]), "d": sorted(sig[1]), "ts": time.time()})
    st["posted_sigs"] = prev[-200:]
    return "نُشر بالقناة"


def retro_pass(clips, st):
    """مقاطع آخر 3 ساعات رُفضت بالشروط القديمة أو فشل نشرها: نعيد تقييمها مرة واحدة برابط فيديو جديد من صفحة المنشور."""
    from tools.tg_video import fetch_post
    cut = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
    for c in clips:
        if st.get("_posted_run", 0) >= POST_LIMIT:
            break
        if (c.get("auto") or "").startswith("نُشر") or c.get("retro") or (c.get("posted") or "") < cut:
            continue
        c["retro"] = True
        try:
            chn, mid = c["post_url"].rstrip("/").split("/")[-2:]
            p = fetch_post(chn, mid)
            if not p["video"]:
                continue
            data = get(p["video"], limit=60_000_000, timeout=60)
            cc = {"caption": c["caption"], "duration": c["duration"], "channel_name": c["channel"]}
            c["auto"] = auto_post(cc, c["segments"], data, st)
        except Exception as e:  # noqa: BLE001
            c["auto"] = f"خطأ: {type(e).__name__}"


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
                    # فك الصوت بـ ffmpeg من حزمة imageio-ffmpeg (المشغّل بلا ffmpeg، وPyAV يتعارض مع إصدارات faster-whisper)
                    import imageio_ffmpeg
                    import numpy as np
                    raw = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-i", str(v), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                                         capture_output=True, check=True, timeout=120).stdout
                    audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
                    segs, info = model.transcribe(audio, language="ar", beam_size=3, vad_filter=True)
                    seg = [{"s": round(x.start, 1), "e": round(x.end, 1), "t": x.text.strip(),
                            "low": (x.avg_logprob < -1.0) or (x.no_speech_prob > 0.6)} for x in segs]
                    try:
                        auto = auto_post(c, seg, v.read_bytes(), st)
                    except Exception as e:  # noqa: BLE001
                        auto = f"خطأ: {type(e).__name__}"
                low = sum(1 for x in seg if x["low"])
                clips.append({"post_url": f"https://t.me/{c['post']}", "channel": c["channel_name"], "posted": c["posted"],
                              "caption": c["caption"], "duration": c["duration"], "segments": seg,
                              "low_ratio": round(low / len(seg), 2) if seg else None,
                              "flag": "تفريغ آلي يحتاج مراجعة" + (" — جودة صوت منخفضة" if seg and low / len(seg) > 0.3 else ""),
                              "transcribed_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "auto": auto,
                              "secs": round(time.time() - t0, 1)})
                new += 1
                st["done"].append(c["post"])
            except Exception as e:  # noqa: BLE001
                errors[c["post"]] = f"{type(e).__name__}: {str(e)[:80]}"
                f = st.setdefault("fail", {})
                f[c["post"]] = f.get(c["post"], 0) + 1
                if f[c["post"]] >= 2:
                    st["done"].append(c["post"])
    retro_pass(clips, st)
    st.pop("_posted_run", None)
    st["done"] = st["done"][-500:]
    st["last"] = time.time()
    cut = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")  # آخر 24 ساعة فقط
    clips = [c for c in clips if (c.get("posted") or c["transcribed_utc"]) >= cut][-60:]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "channels": [n for _, n in CHANNELS],
                               "limits": "مقاطع ≤5 دقائق تنشرها القنوات على تلغرام فقط؛ لا بث مباشر؛ تفريغ آلي بلا نسب لمتحدث.",
                               "clips": clips}, ensure_ascii=False), encoding="utf-8")
    STATE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    print(f"::notice title=tv_auto::{json.dumps([c.get('auto') for c in clips[-new:]] if new else [], ensure_ascii=False)}")
    print(f"::notice title=tv_pilot::{json.dumps({'candidates': len(cand), 'seen': SEEN, 'new': new, 'total': len(clips), 'errors': errors, 'secs': [c.get('secs') for c in clips[-new:]] if new else []}, ensure_ascii=False)}")


if __name__ == "__main__":
    if "--due" in sys.argv:
        print("due=" + ("true" if due() else "false"))
    else:
        main()
