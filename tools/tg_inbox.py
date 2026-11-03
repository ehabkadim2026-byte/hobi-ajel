"""صندوق المحررين في بوت تلغرام: إدخال يدوي سريع + أحكام التحقق.

المحررون = مشرفو قناة الفريق (يُقرأون من تلغرام نفسه، بلا كلمات سر). أي شخص آخر يراسل البوت يُرفض بأدب.
- يرسل المحرر للبوت (رسالة خاصة) رابط منشور مع نصه، أو صورة مع تعليق فيه الرابط والنص
  ← يدخل القاعدة مادةً من نوع «إدخال يدوي» باسم المحرر، ويمر بالتجميع والتحقق مثل غيره.
- /حكم <رقم_الحدث> <كاذب|متنازع|مستقل|رسمي|إلغاء> [ملاحظة] ← حكم تحقق يدوي يظهر في التطبيق.
- /start ← تسجيل المحرر لاستلام تنبيهات قوائم المتابعة بالخاص.
الحالة في data/tg_sent.json (نفس ملف البوت المخبأ) تحت مفاتيح تبدأ بـ «_».
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.tg_push import api, load, SENT, CHAT  # noqa: E402

URL = re.compile(r"https?://\S+")
VERDICTS = {"كاذب": "ثبت عدم صحته", "متنازع": "متنازع عليه", "مستقل": "مؤيد بمصادر مستقلة", "رسمي": "منسوب لمصدر رسمي"}
HELP = ("أهلاً بك في صندوق محرري «هوبي عاجل».\n\n"
        "• إدخال يدوي: أرسل رابط المنشور (فيسبوك أو غيره) مع نصه، أو صورة وتعليقها فيه الرابط والنص. يدخل قائمة الرصد موسوماً «إدخال يدوي».\n"
        "• حكم تحقق: /حكم <رقم الحدث> كاذب|متنازع|مستقل|رسمي|إلغاء [ملاحظة]\n"
        "  (رقم الحدث تجده أسفل تفاصيل الخبر في التطبيق)\n"
        "• نشر فيديو: حوّل (Forward) منشور الفيديو للبوت ← ينتشر بالقناة بأي حجم مع ذكر المصدر. أو أرسل رابط المنشور (للفيديوات الصغيرة فقط).\n"
        "• نشر فوري بالقناة: /نشر عنوان الخبر — وللعاجل الذي يومض: /عاجل عنوان الخبر. سطر اختياري «المصدر: الجهة»، وتكدر ترفق صورة وتكتب الأمر بتعليقها. يُنشر خلال ثوانٍ بالقالب.\n"
        "• تنبيهات المتابعة (الشخصيات والقضايا) تصلك هنا بالخاص.")


def main():
    token = os.environ.get("MARSAD_TG_BOT_TOKEN", "").strip()
    if not token:
        print("no token")
        return
    sent = load(SENT, {})
    chat = load(CHAT, {})
    chat_id = os.environ.get("MARSAD_TG_CHAT_ID", "").strip() or chat.get("id") or "@hassawassal"  # القناة عامة: اسمها يكفي
    now = datetime.now(timezone.utc)
    stats = {"updates": 0, "manual": 0, "verdicts": 0, "rejected": 0}
    try:
        if chat_id and now.timestamp() - sent.get("_editors_t", 0) > 3600:
            adm = api(token, "getChatAdministrators", chat_id=chat_id).get("result", [])
            sent["_editors"] = {str(a["user"]["id"]): a["user"].get("first_name") or "محرر" for a in adm if not a["user"].get("is_bot")}
            sent["_editors_t"] = now.timestamp()
        editors = sent.get("_editors", {})
        try:
            from tools.tg_push import MSGS
            dead = set(load(MSGS, {}).get("_subs_dead") or [])
            for d in dead:
                (sent.get("_subs") or {}).pop(d, None)
        except Exception:  # noqa: BLE001
            pass
        ups = api(token, "getUpdates", offset=sent.get("_offset", 0), timeout=0,
                  allowed_updates=json.dumps(["message", "channel_post"])).get("result", [])
        manual = []
        for u in ups:
            sent["_offset"] = u["update_id"] + 1
            cp = u.get("channel_post")
            if cp:
                from tools import tv_source
                if tv_source.is_source(cp.get("chat") or {}):
                    try:
                        why = tv_source.handle(token, chat_id, cp, sent, sent.get("_editor_chats", {}))
                    except Exception as e:  # noqa: BLE001
                        why = f"خطأ: {type(e).__name__}"
                    stats.setdefault("tv_source", []).append(why)
                continue
            m = u.get("message") or {}
            if (m.get("chat") or {}).get("type") != "private":
                continue
            stats["updates"] += 1
            uid = str((m.get("from") or {}).get("id"))
            cid = m["chat"]["id"]
            text0 = (m.get("text") or "").strip()
            from tools import subs as SB
            if uid not in editors:
                # المتابعون: اشتراكات المحافظات والمواضيع (أي رسالة غير أمر اشتراك تُعاد لها قائمة الأزرار)
                try:
                    if not SB.handle(token, api, cid, text0 or "/start", sent):
                        api(token, "sendMessage", chat_id=cid, text="اختر محافظة أو موضوعاً من الأزرار حتى تصلك أخباره 👇", reply_markup=SB.keyboard())
                    stats["subs_msgs"] = stats.get("subs_msgs", 0) + 1
                except Exception as e:  # noqa: BLE001
                    stats["subs_err"] = type(e).__name__
                continue
            if SB.is_command(text0) and not text0.startswith("/start"):
                SB.handle(token, api, cid, text0, sent)  # المحرر يقدر يشترك أيضاً
                continue
            sent.setdefault("_editor_chats", {})[uid] = cid
            text = (m.get("text") or m.get("caption") or "").strip()
            if text.startswith("/start") or text.startswith("/help") or text == "مساعدة":
                api(token, "sendMessage", chat_id=cid, text=HELP)
                continue
            if text.startswith("/مصدر"):
                parts = text.split()
                if len(parts) >= 3 and parts[1] in ("قبول", "رفض"):
                    sent.setdefault("_src_decisions", {})[parts[2]] = parts[1]
                    msg = f"✅ سُجّل «{parts[1]}» للمصدر {parts[2]}. يُطبق خلال دقيقتين."
                else:
                    msg = "الصيغة: /مصدر قبول <المفتاح> أو /مصدر رفض <المفتاح> (المفتاح من مركز العمليات بالتطبيق)"
                api(token, "sendMessage", chat_id=cid, text=msg)
                continue
            if text.startswith("/حكم") or text.startswith("/verdict"):
                parts = text.split(maxsplit=3)
                if len(parts) >= 3 and (parts[2] in VERDICTS or parts[2] == "إلغاء"):
                    vs = sent.setdefault("_verdicts", {})
                    if parts[2] == "إلغاء":
                        vs.pop(parts[1], None)
                        msg = "أُلغي الحكم."
                    else:
                        vs[parts[1]] = {"status": VERDICTS[parts[2]], "note": parts[3] if len(parts) > 3 else "", "by": editors[uid],
                                        "at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
                        msg = f"✅ سُجّل الحكم «{VERDICTS[parts[2]]}» على الحدث {parts[1]}. يظهر في التطبيق خلال دقيقتين."
                    stats["verdicts"] += 1
                else:
                    msg = "الصيغة: /حكم <رقم الحدث> كاذب|متنازع|مستقل|رسمي|إلغاء [ملاحظة]"
                api(token, "sendMessage", chat_id=cid, text=msg)
                continue
            from tools import manual_pub as MP
            if MP.is_cmd(m):  # احتياط: إذا المسار السريع متوقف ننشر من هنا، وإلا نتجاوز ما نشره
                key = f"{cid}:{m['message_id']}"
                done_m = MP.done_ids()
                if key not in done_m:
                    ok, msg = MP.publish(token, chat_id, m, editors.get(uid, "محرر"))
                    done_m.add(key)
                    MP.mark_done(done_m)
                    api(token, "sendMessage", chat_id=cid, reply_to_message_id=m["message_id"], text=msg[:1000])
                    stats["manual_pub"] = stats.get("manual_pub", 0) + int(ok)
                continue
            from tools import tg_video
            if tg_video.handle_forward(token, chat_id, cid, m):
                stats["video"] = stats.get("video", 0) + 1
                continue
            if tg_video.handle(token, chat_id, cid, m["message_id"], text):
                stats["video"] = stats.get("video", 0) + 1
                continue
            urls = URL.findall(text)
            if not text and not m.get("photo"):
                continue
            body = URL.sub("", text).strip()
            if len(body) < 8:
                api(token, "sendMessage", chat_id=cid, text="أرسل نص المنشور مع الرابط حتى يدخل الرصد (النص هو ما نبحث ونجمّع عليه).")
                continue
            link = urls[0] if urls else f"https://manual.hobi-ajel.local/{uid}/{m['message_id']}"
            first = next((ln.strip() for ln in body.split("\n") if len(ln.strip()) >= 8), body)[:220]
            manual.append({"source_id": "manual:editors", "source_name": f"إدخال يدوي — {editors[uid]}", "url": link, "platform": "manual",
                           "title": first, "text": body + ("\n[مرفقة صورة عبر البوت]" if m.get("photo") else ""),
                           "published_utc": datetime.fromtimestamp(m["date"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                           "date_confirmed": False})
            api(token, "sendMessage", chat_id=cid, reply_to_message_id=m["message_id"],
                text="✅ دخل قائمة الرصد كإدخال يدوي" + (" (بدون رابط أصلي)" if not urls else "") + ". يظهر بالتطبيق خلال دقيقتين موسوماً «إدخال يدوي».")
        if manual:
            from marsad import core
            con = core.connect()
            con.execute("INSERT OR IGNORE INTO sources(id, name, url, platform, category, region, lang, method, official, status, added_by) "
                        "VALUES('manual:editors', 'إدخال يدوي (المحررون)', 'https://t.me/hassawassal', 'manual', 'إدخال يدوي', 'العراق', 'ar', 'manual', 0, 'يعمل', 'البوت')")
            core.ingest_batch(con, {"items": manual})
            con.commit()
            stats["manual"] = len(manual)
        SENT.write_text(json.dumps(sent, ensure_ascii=False), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        stats["error"] = f"{type(e).__name__}: {str(e).replace(token, '***')[:150]}"
    stats["editors"] = len(sent.get("_editors", {}))
    stats["subscribers"] = sum(1 for v in (sent.get("_subs") or {}).values() if v.get("p") or v.get("t"))
    stats["editor_chats"] = len(sent.get("_editor_chats", {}))
    print(f"::notice title=tg_inbox::{json.dumps(stats, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
