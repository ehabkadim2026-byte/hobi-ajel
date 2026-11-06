"""تشخيص فحص الشعارات بالصور: يطبع رد كل نموذج خاماً (بلا أسرار)."""
import base64, io, json, os, sys, urllib.request, urllib.error
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image
from tools.editorial import MODELS
from tools.fastbreak import WM_PROMPT
im = Image.new("RGB", (640, 360), (90, 120, 160)); b = io.BytesIO(); im.save(b, "JPEG")
data = base64.b64encode(b.getvalue()).decode()
key = os.environ.get("GEMINI_API_KEY", "").strip()
for model in MODELS:
    for mt in (4, 64):
        body = json.dumps({"contents": [{"parts": [{"inline_data": {"mime_type": "image/jpeg", "data": data}}, {"text": WM_PROMPT}]}],
                           "generationConfig": {"temperature": 0, "maxOutputTokens": mt}}).encode()
        req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", data=body,
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        try:
            d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
            c = (d.get("candidates") or [{}])[0]
            txt = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts", []))
            print(f"{model} mt={mt}: finish={c.get('finishReason')} text={txt[:30]!r} usage={d.get('usageMetadata', {}).get('thoughtsTokenCount')}")
        except urllib.error.HTTPError as e:
            print(f"{model} mt={mt}: HTTP {e.code}")
        except Exception as e:
            print(f"{model} mt={mt}: {type(e).__name__}")
