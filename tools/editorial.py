"""تحرير «هسة وصل» بالقواعد — مجاني وفوري ولا يغيّر الحقائق.

ينظّف العنوان قبل النشر: يحذف تواقيع القنوات والهاشتاغات والإيموجي ووسوم «عاجل/خاص/بالفيديو» المكررة والروابط،
ويوحّد الترقيم والاقتباس والمسافات، ويقص الطول عند حد الكلمة. لا يضيف كلمة ولا يغيّر اسماً أو رقماً،
وإذا أفرغ التنظيف العنوان أو غيّر أرقامه نرجع للأصل.
"""
import re

EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍←-⇿■-◿]+")
TAGS = re.compile(r"^\s*(?:[\[\(«]?\s*(?:عاجل|عــاجل|عاااجل|خاص|حصري|بالفيديو|بالصور|فيديو|صور|متابعة|مباشر|الآن|هام|مهم|تحديث)\s*[\]\)»]?\s*(?:[|:：\-–—/…]|\.{2,})+\s*)+")
TAGS_END = re.compile(r"\s*[|\-–—]\s*(?:عاجل|خاص|بالفيديو)\s*$")
HASHTAG = re.compile(r"#[\w_؀-ۿ]+")
URL = re.compile(r"https?://\S+|t\.me/\S+|www\.\S+|@[A-Za-z0-9_]{4,}")
SIGN = re.compile(r"\s*[|\-–—]\s*(?:[؀-ۿA-Za-z0-9 .]{2,30})\s*(?:نيوز|news|نت|net|tv|تي ?في|الإخبارية|الاخبارية|الفضائية|برس|press|24|للأنباء|عراق)\s*$", re.I)
FOLLOW = re.compile(r"\s*(?:تابعونا|للمزيد|اشترك|رابط القناة|انضموا|التفاصيل في الرابط|التفاصيل بالرابط|التفاصيل:?)\s*.*$")
DIGITS = re.compile(r"\d+")


def clean_headline(title, max_len=170):
    if not title:
        return title
    t = URL.sub(" ", title)
    t = EMOJI.sub(" ", t)
    t = HASHTAG.sub(" ", t)
    t = FOLLOW.sub("", t)
    t = TAGS.sub("", t.strip())
    t = TAGS_END.sub("", t)
    t = SIGN.sub("", t)
    t = t.replace('"', "«", 1).replace('"', "»", 1) if t.count('"') >= 2 else t
    t = re.sub(r"\.{2,}", "…", t)
    t = re.sub(r"\s+([،,.:؛!؟?])", r"\1", t)
    t = re.sub(r"([،:؛])(?=\S)", r"\1 ", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" -–—|:،")
    if len(t) > max_len:
        cut = t[:max_len].rsplit(" ", 1)[0]
        t = cut.rstrip("،,:-") + "…"
    # حماية الحقائق: لا عنوان فارغ، ولا أرقام مفقودة
    if len(t) < 12 or sorted(DIGITS.findall(t)) != sorted(DIGITS.findall(URL.sub(" ", title))) and len(DIGITS.findall(t)) < len(DIGITS.findall(URL.sub(" ", title))):
        return " ".join(URL.sub(" ", title).split())[:max_len]
    return t
