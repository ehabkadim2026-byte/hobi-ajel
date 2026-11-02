import json, re
from tools import analysis as A, editorial as E
for a in json.load(open("tools/_sample_ana.json", encoding="utf-8"))[:1]:
    ftxt = A._facts(a)
    old = E.MODELS[:]
    E.MODELS[:] = A.ART_MODELS
    out = A._gem_long(A.ART_PROMPT + ftxt)
    print("EXHAUSTED:", E._EXHAUSTED)
    print("RAW:\n", out)
    if out:
        extra = set(E.DIGITS.findall(out)) - set(E.DIGITS.findall(ftxt))
        print("EXTRA DIGITS:", extra, "| words:", len(out.split()), "| accuse:", bool(A.ACCUSE.search(out)))
        print("HEADS:", [h for h in A.ART_HEADS if h in out])
