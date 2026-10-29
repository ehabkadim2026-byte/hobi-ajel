"""تغيير رمز دخول التطبيق: python3 tools/set_code.py 123456   (أو "" لإلغاء الرمز)"""
import hashlib, re, sys
from pathlib import Path
code = sys.argv[1].strip() if len(sys.argv) > 1 else ""
h = hashlib.sha256(("hobi-ajel:" + code).encode()).hexdigest() if code else ""
p = Path(__file__).resolve().parent.parent / "pwa" / "index.html"
t = re.sub(r'const ACCESS_HASH = "[0-9a-f]*";', f'const ACCESS_HASH = "{h}";', p.read_text(encoding="utf-8"))
p.write_text(t, encoding="utf-8")
print("تم:", "رمز جديد" if code else "بلا رمز")
