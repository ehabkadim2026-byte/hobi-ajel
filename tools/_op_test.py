import json
from tools import analysis as A
for a in json.load(open("tools/_sample_op.json", encoding="utf-8")):
    r = A.write_opinion(a)
    print("=" * 20, a["title"], "|", A.LAST_FINISH)
    print(r[0] + "\n\n" + r[1] if r else "FAILED")
