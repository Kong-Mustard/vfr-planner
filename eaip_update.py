"""
eaip_update.py — ดึงข้อมูลสนามบินจาก eAIP Thailand (aip.caat.or.th) ฉบับล่าสุด
ผลลัพธ์: eaip_data.json  → นำไป Import ในแอป VFR Planner (ปุ่ม "Import ข้อมูล eAIP")

ดึง: AD 2 ทุกสนาม (ARP, elevation, runway, ความถี่ AD 2.18, navaid AD 2.19)
     ENR 4.1 (VOR/DME/NDB ทั่วประเทศ)
ใช้: python eaip_update.py            (เลือกฉบับที่มีผลบังคับใช้ล่าสุดอัตโนมัติ)
     python eaip_update.py 2026-10-29 (ระบุฉบับเอง)
ต้องติดตั้งก่อนครั้งแรก: pip install requests beautifulsoup4
"""
import json, re, sys, time, datetime
import requests
from bs4 import BeautifulSoup

BASE = "https://aip.caat.or.th/"
HDR = {"User-Agent": "Mozilla/5.0 (VFR Planner personal eAIP reader)"}
S = requests.Session(); S.headers.update(HDR)


def get(url):
    for i in range(3):
        try:
            r = S.get(url, timeout=30)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception as e:
            if i == 2:
                raise
            print("  ลองใหม่:", e); time.sleep(2)


def clean(t):
    return re.sub(r"\s+", " ", t or "").strip()


COORD = re.compile(r"(\d{6}(?:\.\d+)?)\s*([NS])[\s,/]*(\d{7}(?:\.\d+)?)\s*([EW])")


def dms(v, deg_digits):
    d = int(v[:deg_digits]); m = int(v[deg_digits:deg_digits + 2]); s = float(v[deg_digits + 2:] or 0)
    return d + m / 60 + s / 3600


def parse_coord(text):
    m = COORD.search(text.replace(" ", "") if text else "")
    if not m:
        m = COORD.search(text or "")
    if not m:
        return None, None
    lat = dms(m.group(1), 2) * (1 if m.group(2) == "N" else -1)
    lon = dms(m.group(3), 3) * (1 if m.group(4) == "E" else -1)
    return round(lat, 6), round(lon, 6)


def pick_edition(forced=None):
    html = get(BASE)
    dates = re.findall(r"(\d{4}-\d{2}-\d{2})-AIRAC", html)
    order = list(dict.fromkeys(dates))  # ตามลำดับบนหน้าเว็บ (บนสุดก่อน)
    if not order:
        sys.exit("หาฉบับ AIRAC บนหน้าเว็บไม่เจอ — หน้าเว็บอาจเปลี่ยนรูปแบบ")
    if forced:
        return forced, order
    today = datetime.date.today().isoformat()
    eff = [d for d in order if d <= today]
    chosen = max(eff) if eff else order[0]
    return chosen, order


def tables_by_section(soup, prefix):
    """คืน dict { '2.18': [table,...] } โดยดูหัวข้อที่อยู่ก่อนแต่ละตาราง"""
    out = {}
    for tb in soup.find_all("table"):
        h = tb.find_previous(["h1", "h2", "h3", "h4", "h5"])
        if not h:
            continue
        m = re.search(prefix + r"\.(\d+)\b", clean(h.get_text(" ")))
        if m:
            out.setdefault(m.group(1), []).append(tb)
    return out


def rows(tb):
    res = []
    for tr in tb.find_all("tr"):
        cells = [clean(td.get_text(" ")) for td in tr.find_all(["td", "th"])]
        if any(cells):
            res.append(cells)
    return res


def parse_ad2(icao, html):
    soup = BeautifulSoup(html, "html.parser")
    sec = tables_by_section(soup, r"AD\s*2")
    sec = {"2." + k: v for k, v in sec.items()}
    ap = {"icao": icao, "lat": None, "lon": None, "elev_ft": None, "rwy": [], "comm": [], "navaids": []}
    # AD 2.2
    for tb in sec.get("2.2", []):
        for r in rows(tb):
            line = " ".join(r)
            if "ARP" in line.upper() and ap["lat"] is None:
                ap["lat"], ap["lon"] = parse_coord(line)
            if "ELEVATION" in line.upper() and ap["elev_ft"] is None:
                m = re.search(r"(-?\d+(?:\.\d+)?)\s*FT", line, re.I)
                if m:
                    ap["elev_ft"] = float(m.group(1))
    # AD 2.12 runway
    for tb in sec.get("2.12", []):
        for r in rows(tb):
            if r and re.fullmatch(r"\d{2}[LRC]?", r[0]):
                ap["rwy"].append(r[0])
    # AD 2.18 ATS communication
    last_svc = ""
    for tb in sec.get("2.18", []):
        for r in rows(tb):
            if len(r) < 3 or "DESIGNATION" in r[0].upper() or r[0].strip() in ("1", "1 2"):
                continue
            svc = r[0] or last_svc; last_svc = svc
            ap["comm"].append({"svc": svc, "callsign": r[1], "freq": r[2],
                               "hours": r[3] if len(r) > 3 else "", "rmk": r[4] if len(r) > 4 else ""})
    # AD 2.19 navaids
    for tb in sec.get("2.19", []):
        for r in rows(tb):
            line = " ".join(r)
            lat, lon = parse_coord(line)
            if lat is None or len(r) < 3:
                continue
            ap["navaids"].append({"type": r[0], "id": r[1], "freq": r[2], "lat": lat, "lon": lon,
                                  "rmk": r[-1] if len(r) > 6 else ""})
    return ap


def parse_enr41(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tb in soup.find_all("table"):
        for r in rows(tb):
            line = " ".join(r)
            lat, lon = parse_coord(line)
            if lat is None or len(r) < 3:
                continue
            m = re.search(r"\b(VOR/DME|VORTAC|VOR|DME|NDB|TACAN)\b", line)
            ident = next((c for c in r if re.fullmatch(r"[A-Z]{2,3}", c)), "")
            freq = next((c for c in r if re.search(r"\d+(\.\d+)?\s*(MHZ|KHZ|CH)", c, re.I)), "")
            out.append({"name": r[0], "type": m.group(1) if m else "", "id": ident, "freq": freq,
                        "lat": lat, "lon": lon})
    return out


def main():
    forced = sys.argv[1] if len(sys.argv) > 1 else None
    ed, order = pick_edition(forced)
    print("ฉบับบนหน้าเว็บ (บนสุดก่อน):", ", ".join(order[:5]))
    print("เลือกใช้ฉบับ:", ed)
    root = f"{BASE}{ed}-AIRAC/html/eAIP/"
    menu = get(root + "VT-menu-en-GB.html")
    msoup = BeautifulSoup(menu, "html.parser")
    names = {}
    for a in msoup.find_all("a", href=True):
        m = re.search(r"VT-AD-2\.([A-Z]{4})-en-GB\.html", a["href"])
        if m:
            names.setdefault(m.group(1), clean(a.get_text(" ")))
    icaos = sorted(names)
    print(f"พบ AD 2 ทั้งหมด {len(icaos)} สนาม")
    data = {"source": "eAIP Thailand (CAAT)", "edition": ed, "fetched": datetime.datetime.now().isoformat(timespec="minutes"),
            "airports": {}, "navaids": [], "errors": []}
    for i, ic in enumerate(icaos, 1):
        url = root + f"VT-AD-2.{ic}-en-GB.html"
        try:
            ap = parse_ad2(ic, get(url))
            ap["name"] = re.sub(r"^\s*" + ic + r"\s*[-—–]?\s*", "", names[ic]) or ic
            ap["url"] = url
            data["airports"][ic] = ap
            print(f"[{i}/{len(icaos)}] {ic} ความถี่ {len(ap['comm'])} รายการ, navaid {len(ap['navaids'])}, พิกัด {'OK' if ap['lat'] else 'ไม่พบ'}")
            if ap["lat"] is None:
                data["errors"].append(f"{ic}: อ่านพิกัด ARP ไม่ได้")
        except Exception as e:
            print(f"[{i}/{len(icaos)}] {ic} ผิดพลาด: {e}")
            data["errors"].append(f"{ic}: {e}")
        time.sleep(0.4)
    try:
        data["navaids"] = parse_enr41(get(root + "VT-ENR-4.1-en-GB.html"))
        print(f"ENR 4.1 navaid {len(data['navaids'])} รายการ")
    except Exception as e:
        data["errors"].append(f"ENR 4.1: {e}")
    with open("eaip_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("\nบันทึกแล้ว: eaip_data.json")
    if data["errors"]:
        print("มีจุดที่อ่านไม่ได้", len(data["errors"]), "รายการ — ส่งไฟล์นี้ให้ Claude ดูเพื่อแก้สคริปต์")


if __name__ == "__main__":
    main()
