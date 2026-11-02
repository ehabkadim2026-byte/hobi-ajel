"""فحص كل نماذج Gemini/Gemma المجانية: أيها يعمل الآن (يطبع رمز الاستجابة فقط، بلا المفتاح)."""
import json, os, urllib.request, urllib.error
from tools.editorial import MODELS
key = os.environ.get("GEMINI_API_KEY", "").strip()
extra = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-flash-latest", "gemma-3-27b-it"]
for m in MODELS + extra:
    body = json.dumps({"contents": [{"parts": [{"text": "قل: نعم"}]}], "generationConfig": {"maxOutputTokens": 5}}).encode()
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent", data=body,
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"::notice title=llm {m}::200 OK")
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")[:160].replace("\n", " ")
        print(f"::notice title=llm {m}::{e.code} {msg}")
    except Exception as e:  # noqa: BLE001
        print(f"::notice title=llm {m}::{type(e).__name__}")
