import json
from tools import analysis as A
for a in json.load(open("tools/_sample_ana.json", encoding="utf-8")):
    r = A.write_article(a)
    print("=" * 30, a["title"])
    print(r[0] + "\n\n" + r[1] if r else "FAILED (guard or model)")
