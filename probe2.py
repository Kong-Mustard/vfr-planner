# ชั่วคราว: ดูโครงสร้าง ENR 2.1 + ทดลอง OCR VFR chart ที่เป็นภาพสแกน
import json, re, subprocess, sys
sys.argv = [sys.argv[0]]
import eaip_update as U
from bs4 import BeautifulSoup
d = json.load(open("eaip_data.json"))
root = f"{U.BASE}{d['edition']}-AIRAC/html/eAIP/"
h = U.get(root + "VT-ENR-2.1-en-GB.html")
soup = U.strip_markup(BeautifulSoup(h, "html.parser"))
for ti, tb in enumerate(soup.find_all("table")):
    R = U.rows(tb)
    print("#### TABLE", ti, len(R))
    for r in R[:70]:
        print(" | ".join(c[:160] for c in r)[:600])
for ic in ("VTPH", "VTUK"):
    for ch in d["airports"][ic]["charts"]:
        if "VFR" in ch["name"] and "Tabular" in ch["name"]:
            r = U.S.get(ch["url"], timeout=60); open("c.pdf", "wb").write(r.content)
            subprocess.run(["pdftoppm", "-r", "300", "-png", "-f", "1", "-l", "1", "c.pdf", "pg"])
            import glob
            png = sorted(glob.glob("pg*.png"))[-1]
            subprocess.run(["tesseract", png, "o", "--psm", "6"], capture_output=True)
            print("==== OCR", ic, ch["page"], ch["name"][:60]); print(open("o.txt").read()[:3500])
            for f in glob.glob("pg*.png"): __import__("os").remove(f)
            break
