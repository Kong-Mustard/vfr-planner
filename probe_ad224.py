# ชั่วคราว: สำรวจ AD 2.24 (VFR charts) — ผลเป็น artifact ไม่ commit
import re, sys, os, json
sys.argv=[sys.argv[0]]
import eaip_update as E
from bs4 import BeautifulSoup
os.makedirs("probe", exist_ok=True)
ed,_=E.pick_edition(); root=f"{E.BASE}{ed}-AIRAC/html/eAIP/"
out={}
for ic in ["VTBD","VTCC","VTBK","VTPP"]:
    raw=E.get(root+f"VT-AD-2.{ic}-en-GB.html"); open(f"probe/{ic}.html","w").write(raw)
    soup=BeautifulSoup(raw,"html.parser"); links=[]
    for a in soup.find_all("a",href=True):
        t=E.clean(a.get_text(" "))
        if re.search(r"\.pdf",a["href"],re.I) or "VFR" in t.upper() or "CHART" in t.upper(): links.append([t,a["href"]])
    out[ic]=links
    for t,h in links:
        if "VFR" in t.upper() and h.lower().endswith(".pdf"):
            url=h if h.startswith("http") else E.S.get(root).url.rsplit("/",1)[0]+"/"+h
            try:
                from urllib.parse import urljoin
                r=E.S.get(urljoin(root+f"VT-AD-2.{ic}-en-GB.html",h),timeout=60);fn="probe/"+ic+"_"+re.sub(r"\W+","_",t)[:50]+".pdf";open(fn,"wb").write(r.content);print("got",fn,len(r.content))
            except Exception as e: print("ERR",e)
json.dump(out,open("probe/links.json","w"),indent=1,ensure_ascii=False)
print(json.dumps(out,ensure_ascii=False)[:3000])
