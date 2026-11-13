# ชั่วคราว: ดาวน์โหลด VFR charts (AD 2.24) แล้วแปลงเป็นข้อความ — ผลเป็น artifact ไม่ commit
import json, os, re, subprocess, requests
os.makedirs("probe", exist_ok=True)
d=json.load(open("eaip_data.json")); S=requests.Session(); S.headers["User-Agent"]="Mozilla/5.0 (VFR Planner personal eAIP reader)"
for ic,a in d["airports"].items():
    for ch in a.get("charts",[]):
        if "VFR" not in ch["name"].upper(): continue
        if ic not in ("VTBD","VTPH","VTUK","VTPP") and "Tabular" not in ch["name"]: continue
        fn=f"probe/{ic}_{ch['page'].split('-')[-2]}-{ch['page'].split('-')[-1]}"
        try:
            r=S.get(ch["url"],timeout=60); open(fn+".pdf","wb").write(r.content)
            subprocess.run(["pdftotext","-layout",fn+".pdf",fn+".txt"])
            print(fn, ch["name"][:90], len(r.content))
        except Exception as e: print("ERR",fn,e)
