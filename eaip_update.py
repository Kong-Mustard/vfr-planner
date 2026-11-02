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


DBTOK = re.compile(r"\b[A-Z][A-Z0-9_]*;[A-Z0-9_]+;\d+\b")


def clean(t):
    t = DBTOK.sub(" ", t or "")
    return re.sub(r"\s+", " ", t).strip()


def strip_markup(soup):
    """ลบ element ที่ซ่อนรหัสฐานข้อมูล (เช่น class sdParams / display:none)"""
    for el in soup.select(".sdParams, [style*='display:none'], [style*='display: none']"):
        el.decompose()
    return soup


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


SVC = re.compile(r"^(APP|TWR|GND|ATIS|CDC|DEL|DART|ACC|FIS|AFIS|ASR|SRA|PAR|RADAR|DEP|ARR|APN|AMC|VOLMET|D-ATIS|CTL|INFO|MIL|GCA|OPS)\b", re.I)
FREQ = re.compile(r"\b(\d{3}\.\d{1,3})\b")
HOURS = re.compile(r"\b(H24|HJ|HN|HO|HX|O/R|\d{4}\s*-\s*\d{4})\b")


GUARD = {"121.5", "243.0"}  # ความถี่ฉุกเฉิน แสดงแยกในแอปอยู่แล้ว
CALL_SVC = [("ground", "GND"), ("delivery", "DEL"), ("tower", "TWR"), ("arrival", "ARR"),
            ("departure", "DEP"), ("approach", "APP"), ("radar", "RADAR"), ("final", "PAR"),
            ("information", "FIS"), ("control", "ACC"), ("apron", "APN")]


def callsign_svc(call):
    c = (call or "").lower()
    return next((v for k, v in CALL_SVC if k in c), "")


def freqs_of(text):
    out = []
    for f in FREQ.findall(text):
        v = float(f)
        if 108 <= v <= 400 and f not in out:
            out.append(f)
    return out


def parse_ad2(icao, html):
    soup = strip_markup(BeautifulSoup(html, "html.parser"))
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
    # AD 2.18 ATS communication — ทนต่อ rowspan: แยก service / callsign / ความถี่ ตามรูปแบบข้อความ
    last_svc = ""
    for tb in sec.get("2.18", []):
        for r in rows(tb):
            line = " ".join(r)
            if "DESIGNATION" in line.upper() or re.fullmatch(r"[\d\s]+", line):
                continue
            svc = ""
            for c in r[:2]:
                m = SVC.match(c)
                if m:
                    svc = m.group(1).upper(); break
            fq = freqs_of(line)
            call = next((c for c in r if re.search(r"[a-z]", c) and not SVC.fullmatch(c) and not FREQ.search(c) and len(c) < 60), "")
            hours = next((m.group(1) for c in r for m in [HOURS.search(c)] if m), "")
            if svc:
                last_svc = svc
            if not fq:
                # แถวที่มีแต่ callsign (เพราะ rowspan) → เติมให้รายการล่าสุดของ service เดียวกันที่ยังไม่มี callsign
                if call:
                    for e in reversed(ap["comm"]):
                        if e["svc"] == (svc or last_svc) and not e["callsign"]:
                            e["callsign"] = call; break
                    else:
                        ap["comm"].append({"svc": svc or last_svc, "callsign": call, "freq": "", "hours": hours, "rmk": ""})
                continue
            use = svc or callsign_svc(call) or last_svc
            fq = [f for f in fq if f not in GUARD]
            if fq:
                ap["comm"].append({"svc": use, "callsign": call, "freq": " / ".join(fq), "hours": hours, "rmk": ""})
    # รวมรายการ service เดียวกันที่ซ้ำ
    merged = []
    for e in ap["comm"]:
        if merged and merged[-1]["svc"] == e["svc"] and (not e["freq"] or not merged[-1]["freq"]) and (not e["callsign"] or e["callsign"] == merged[-1]["callsign"]):
            m = merged[-1]
            fs = [x for x in (m["freq"].split(" / ") + e["freq"].split(" / ")) if x]
            m["freq"] = " / ".join(dict.fromkeys(fs)); m["callsign"] = m["callsign"] or e["callsign"]; m["hours"] = m["hours"] or e["hours"]
        else:
            merged.append(e)
    ap["comm"] = [e for e in merged if e["freq"]]
    # AD 2.19 navaids
    for tb in sec.get("2.19", []):
        for r in rows(tb):
            line = " ".join(r)
            lat, lon = parse_coord(line)
            if lat is None or len(r) < 3:
                continue
            ident = next((c for c in r[1:3] if re.fullmatch(r"[A-Z]{1,4}", c)), r[1])
            fq = re.search(r"\d{3}(?:\.\d{1,3})?\s*(?:MHz|KHz|kHz)?(?:\s*\(?CH\s*\d+[XY]\)?)?", " ".join(r[1:4]), re.I)
            ap["navaids"].append({"type": r[0], "id": ident, "freq": fq.group(0).strip() if fq else r[2], "lat": lat, "lon": lon,
                                  "rmk": r[-1] if len(r) > 6 else ""})
    return ap


def parse_enr41(html):
    soup = strip_markup(BeautifulSoup(html, "html.parser"))
    out = []
    for tb in soup.find_all("table"):
        for r in rows(tb):
            line = " ".join(r)
            lat, lon = parse_coord(line)
            if lat is None or len(r) < 3:
                continue
            m = re.search(r"(DVOR/DME|VOR/DME|VORTAC|DVOR|VOR|NDB/DME|NDB|TACAN|DME)", line.replace(" /", "/").replace("/ ", "/"))
            ident = next((c for c in r if re.fullmatch(r"[A-Z]{2,3}", c)), "")
            freq = next((c for c in r if re.search(r"\d+(\.\d+)?\s*(MHZ|KHZ|CH)", c, re.I)), "")
            out.append({"name": r[0], "type": m.group(1) if m else "", "id": ident, "freq": freq,
                        "lat": lat, "lon": lon})
    return out


def parse_enr51(html):
    """ยังเป็นตัวอ่านเบื้องต้น — จะปรับหลังเห็นรูปแบบหน้าจริง"""
    soup = strip_markup(BeautifulSoup(html, "html.parser"))
    out = []
    for tb in soup.find_all("table"):
        for r in rows(tb):
            line = " ".join(r)
            m = re.match(r"^(VT\s*[PRD]\s*-?\s*\d+[A-Z]?)\b", line)
            if m:
                out.append({"raw": r})
    return out


def debug_dump(name, html):
    import os
    os.makedirs("debug", exist_ok=True)
    with open(os.path.join("debug", name), "w", encoding="utf-8") as f:
        f.write(html)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    forced = args[0] if args else None
    ed, order = pick_edition(forced)
    print("ฉบับบนหน้าเว็บ (บนสุดก่อน):", ", ".join(order[:5]))
    print("เลือกใช้ฉบับ:", ed)
    root = f"{BASE}{ed}-AIRAC/html/eAIP/"
    menu = get(root + "VT-menu-en-GB.html")
    msoup = BeautifulSoup(menu, "html.parser")  # ห้าม strip เมนู (ส่วนที่พับไว้ซ่อนด้วย display:none)
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
            raw = get(url)
            if ic in ("VTPP", "VTBD") and "--debug" in sys.argv:
                debug_dump(f"AD2_{ic}.html", raw)
            ap = parse_ad2(ic, raw)
            nm = re.sub(r"^\s*" + ic + r"\s*[-—–]?\s*", "", names[ic])
            ap["name"] = "" if (not nm or "AERODROMES" in nm.upper()) else nm
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
        raw = get(root + "VT-ENR-4.1-en-GB.html")
        if "--debug" in sys.argv:
            debug_dump("ENR_4.1.html", raw)
        data["navaids"] = parse_enr41(raw)
        print(f"ENR 4.1 navaid {len(data['navaids'])} รายการ")
    except Exception as e:
        data["errors"].append(f"ENR 4.1: {e}")
    # ENR 5.1 Prohibited / Restricted / Danger areas
    try:
        raw = get(root + "VT-ENR-5.1-en-GB.html")
        if "--debug-enr5" in sys.argv:
            debug_dump("ENR_5.1.html", raw)
        data["areas"] = parse_enr51(raw)
        print(f"ENR 5.1 พื้นที่ {len(data['areas'])} แห่ง")
    except Exception as e:
        data["errors"].append(f"ENR 5.1: {e}")
    with open("eaip_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("\nบันทึกแล้ว: eaip_data.json")
    if data["errors"]:
        print("มีจุดที่อ่านไม่ได้", len(data["errors"]), "รายการ — ส่งไฟล์นี้ให้ Claude ดูเพื่อแก้สคริปต์")


if __name__ == "__main__":
    main()
