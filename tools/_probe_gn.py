# مؤقت: يعدّ عناصر كل خلاصة Google News مقترحة
import urllib.request, sys, time
for u in open(sys.argv[1]).read().split():
    try:
        h = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/124"}), timeout=25).read().decode("utf-8", "replace")
        print(h.count("<item>"), u)
    except Exception as e:
        print("ERR", e, u)
    time.sleep(1.5)
