"""توصيل التنبيهات. الافتراضي: صندوق صادر محلي فقط.
بوت تلغرام يعمل فقط إذا وُضع السرّان كمتغيرات بيئة على الخادم (لا في الكود ولا في المحادثة):
  MARSAD_TG_BOT_TOKEN  ،  MARSAD_TG_CHAT_ID  (محادثة Ehab نفسه فقط)
ولا يُرسل إلا للمستويين «عاجل» و«مهم»، وفقط بالأمر الصريح `cli notify --deliver`.
"""
import json
import os
import urllib.parse
import urllib.request

from .textnorm import to_baghdad


def format_alert(a):
    b = json.loads(a["body"])
    head = "🔴" if a["level"] == "عاجل" else "🟠"
    return (f"{head} {a['level']}{' — تحديث' if a['is_update'] else ''}\n{b['ماذا حدث']}\n"
            f"متى: {to_baghdad(b['متى'])}\nلماذا: {b['لماذا يستحق الانتباه']}\n"
            f"التحقق: {b['درجة التحقق']}\nالجديد: {b['الجديد']}\nالمقترح: {b['الإجراء البحثي المقترح']}\n{b['الرابط']}")


def deliver(con, dry_run=True):
    token, chat = os.environ.get("MARSAD_TG_BOT_TOKEN"), os.environ.get("MARSAD_TG_CHAT_ID")
    pending = con.execute("SELECT * FROM alerts WHERE delivery='outbox' AND level IN ('عاجل','مهم') "
                          "ORDER BY id").fetchall()
    if dry_run or not (token and chat):
        return {"status": "غير مفعّل — صندوق صادر محلي", "pending": len(pending)}
    sent = 0
    for a in pending:
        data = urllib.parse.urlencode({"chat_id": chat, "text": format_alert(a),
                                       "disable_web_page_preview": "true"}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=20)
        con.execute("UPDATE alerts SET delivery='sent' WHERE id=?", (a["id"],))
        sent += 1
    con.commit()
    return {"status": "أُرسل", "sent": sent}
