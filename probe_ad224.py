# ชั่วคราว: ดาวน์โหลด VFR charts (AD 2.24) แล้วแปลงเป็นข้อความ — ผลเป็น artifact ไม่ commit
import json, os, re, subprocess, requests
os.makedirs("probe", exist_ok=True)
d=json.load(open("eaip_data.json")); S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 (VFR Planner personal eAIP reader)"
for ic,a in d["airports"].items():
    for ch in a.get("charts",[]):
        if "VFR" not in ch["name"].upper(): continue
        if "Tabular" not in ch["name"] or (ic=="VTBD" and not any(k in ch["page"] for k in ("9-3","9-14","9-23"))): continue
        fn=f"probe/{ic}_{ch['page'].split('-')[-2]}-{ch['page'].split('-')[-1]}"
        try:
            r=S.get(ch["url"],timeout=60); open(fn+".pdf","wb").write(r.content)
            subprocess.run(["pdftotext","-layout",fn+".pdf",fn+".txt"])
            print(fn, ch["name"][:90], len(r.content))
        except Exception as e: print("ERR",fn,e)
import glob
for fn in sorted(glob.glob("probe/*.txt")):
    t=open(fn,errors="ignore").read()
    print("=====",fn,len(t)); print(re.sub(r'\n\s*\n+','\n',t)[:7000])
