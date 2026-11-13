"""
eaip_update.py — ดึงข้อมูลสนามบินจาก eAIP Thailand (aip.caat.or.th) ฉบับล่าสุด
ผลลัพธ์: eaip_data.json  → นำไป Import ในแอป VFR Planner (ปุ่ม "Import ข้อมูล eAIP")

ดึง: AD 2 ทุกสนาม (ARP, elevation, runway, ความถี่ AD 2.18, navaid AD 2.19)
     ENR 4.1 (VOR/DME/NDB ทั่วประเทศ)
ใช้: python eaip_update.py            (เลือกฉบับที่มีผลบังคับใช้ล่าสุดอัตโนมัติ)
     python eaip_update.py 2026-10-29 (ระบุฉบับเอง)
ต้องติดตั้งก่อนครั้งแรก: pip install requests beautifulsoup4
"""
import json, os, re, sys, time, datetime
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


def section_text(soup, start_pat, end_pat, limit=8000):
    """ข้อความระหว่างหัวข้อ เช่น AD 2.22 → AD 2.23"""
    h = None
    for t in soup.find_all(["h1", "h2", "h3", "h4", "h5", "div", "p"]):
        tx = clean(t.get_text(" "))
        if re.search(start_pat, tx) and len(tx) < 120:
            h = t; break
    if not h:
        return ""
    out = []
    for el in h.find_all_next(string=True):
        tx = clean(el)
        if not tx:
            continue
        if re.search(end_pat, tx) and len(tx) < 120:
            break
        out.append(tx)
        if sum(len(x) for x in out) > limit:
            break
    return " ".join(out)


PT_RE = re.compile(r"([A-Z][A-Z0-9 ()/'.-]{1,40}?)\s*[:(,-]?\s*(\d{4,6}(?:\.\d+)?\s*[NS]\s*\d{5,7}(?:\.\d+)?\s*[EW])")


def find_points(text, src):
    pts = []
    for m in PT_RE.finditer(text or ""):
        name = clean(m.group(1)).strip(" (,-:")
        if not name or len(name) < 2 or re.fullmatch(r"[\d ]+", name):
            continue
        cm = C_RE.search(m.group(2))
        if not cm:
            continue
        lat, lon = _c(cm)
        if 4 < lat < 22 and 96 < lon < 107:
            pts.append({"name": name[-40:], "lat": lat, "lon": lon, "src": src})
    return pts


def cf_decode(soup):
    """Cloudflare ซ่อนอีเมลเป็น [email protected] — ถอดกลับเป็นอีเมลจริง"""
    for el in soup.select("[data-cfemail]"):
        try:
            h = el["data-cfemail"]; k = int(h[:2], 16)
            el.replace_with("".join(chr(int(h[i:i + 2], 16) ^ k) for i in range(2, len(h), 2)))
        except Exception:
            pass
    return soup


def parse_ad2(icao, html, url=""):
    soup = strip_markup(cf_decode(BeautifulSoup(html, "html.parser")))
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
    # AD 2.3 ข้อ 12 Remarks → เบอร์โทร ARO / Briefing (ใช้โทรเปิดแผนการบิน)
    for tb in sec.get("2.3", []):
        for r in rows(tb):
            if len(r) >= 2 and any(c.strip().lower().startswith("remark") for c in r[:2]):
                txt = r[-1].strip()
                if not txt or txt.upper() in ("NIL", "-"):
                    continue
                ph = []
                for m in re.finditer(r"(Tel(?:ephone)?|Mobile|Mob|Phone|Fax|Hotline)\.?\s*(?:No\.?)?\s*:?\s*((?:\+?\d[\d\s\-()]{6,}\d)(?:\s*(?:,|/|or)\s*\+?\d[\d\s\-()]{6,}\d)*)", txt, re.I):
                    kind = m.group(1).capitalize().replace("Mob", "Mobile").replace("Mobileile", "Mobile")
                    for n in re.split(r"\s*(?:,|/|\bor\b)\s*", m.group(2)):
                        n = re.sub(r"\s+", " ", n).strip()
                        if len(re.sub(r"\D", "", n)) >= 8:
                            ph.append({"t": kind, "n": n})
                ap["rmk23"] = {"text": re.sub(r"\s+", " ", txt)[:1500], "phones": ph}
                break
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
    # AD 2.24 charts (ชื่อ + ลิงก์ PDF)
    ap["charts"] = []
    from urllib.parse import urljoin
    for tb in sec.get("2.24", []):
        for tr in tb.find_all("tr"):
            tds = tr.find_all(["td", "th"])
            if len(tds) < 2:
                continue
            name = clean(tds[0].get_text(" "))
            a = tr.find("a", href=True)
            if not name or name.lower().startswith("chart name") or not a:
                continue
            ap["charts"].append({"name": name, "page": clean(a.get_text(" ")), "url": urljoin(url, a["href"])})
    # AD 2.22 flight procedures (ข้อความ) + จุดที่มีพิกัด (reporting points ฯลฯ)
    ap["proc"] = section_text(soup, icao + r"\s+AD\s*2\.22\b", icao + r"\s+AD\s*2\.23\b")
    t17 = section_text(soup, icao + r"\s+AD\s*2\.17\b", icao + r"\s+AD\s*2\.18\b", 4000)
    ap["points"] = find_points(ap["proc"], "AD 2.22") + find_points(t17, "AD 2.17")
    # ATS airspace (CTR/ATZ) จาก AD 2.17 → polygon สำหรับชั้น "Control zone" ในแอป
    try:
        m = re.search(r"lateral limits?(.*?)(?:\b2\s*\.?\s*Vertical|Vertical limits?)", t17, re.I | re.S)
        lat_txt = (m.group(1) if m else t17.split("Vertical")[0])[:1500]
        poly, approx = parse_geom(lat_txt)
        vm = re.search(r"Vertical limits?\s*(.{0,80}?)(?:\b3\s*\.?\s*Airspace|Airspace class|$)", t17, re.I | re.S)
        cm = re.search(r"Airspace class(?:ification)?\s*:?\s*([A-G])\b", t17, re.I)
        nm = re.search(r"\b([A-Z][A-Z ]{2,30}\s(?:CTR|ATZ|CTA|TMA))\b", t17)
        kind = re.search(r"\((CTR|ATZ|CTA|TMA)\)|\b(CTR|ATZ)\b", t17)
        if not nm and kind:
            nm = re.match(r"(.*)", icao + " " + (kind.group(1) or kind.group(2)))
        if poly and len(poly) >= 4:
            ap["airspace"] = {"name": nm.group(1) if nm else icao + " CTR", "poly": [[round(a, 5), round(b, 5)] for a, b in poly],
                              "approx": approx, "vert": clean(vm.group(1)) if vm else "", "cls": cm.group(1) if cm else "", "text": clean(lat_txt)[:400]}
        elif t17:
            ap["airspace_text"] = clean(t17)[:500]
    except Exception as e:
        ap["airspace_err"] = str(e)[:120]
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


import math

C_RE = re.compile(r"(?<![\d.])(\d{4}(?:\d{2})?(?:\.\d+)?)\s*([NS])\s*(\d{5}(?:\d{2})?(?:\.\d+)?)\s*([EW])")


def _dm(v, dd):
    """รองรับ DDMMSS(.s) และ DDMM(.m)"""
    ip = v.split(".")[0]
    d = int(v[:dd]); rest = v[dd:]
    if len(ip) - dd == 4:  # MMSS
        return d + int(rest[:2]) / 60 + float(rest[2:]) / 3600
    return d + float(rest) / 60  # MM(.m)


def _c(m):
    lat = _dm(m.group(1), 2) * (1 if m.group(2) == "N" else -1)
    lon = _dm(m.group(3), 3) * (1 if m.group(4) == "E" else -1)
    return [round(lat, 5), round(lon, 5)]


def _dest(c, brg, nm):
    """จุดปลายทางจาก center ด้วย bearing (°T) และระยะ (NM) — spherical"""
    R = 3440.065; d = nm / R; b = math.radians(brg); la = math.radians(c[0]); lo = math.radians(c[1])
    la2 = math.asin(math.sin(la) * math.cos(d) + math.cos(la) * math.sin(d) * math.cos(b))
    lo2 = lo + math.atan2(math.sin(b) * math.sin(d) * math.cos(la), math.cos(d) - math.sin(la) * math.sin(la2))
    return [round(math.degrees(la2), 5), round(math.degrees(lo2), 5)]


def _brg(c, p):
    la1, la2 = math.radians(c[0]), math.radians(p[0]); dl = math.radians(p[1] - c[1])
    return (math.degrees(math.atan2(math.sin(dl) * math.cos(la2), math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dl))) + 360) % 360


def _arc(c, r, b1, b2, cw, step=5):
    if cw:
        span = (b2 - b1) % 360 or 360
    else:
        span = -((b1 - b2) % 360 or 360)
    n = max(2, int(abs(span) / step))
    return [_dest(c, b1 + span * i / n, r) for i in range(n + 1)]


def parse_geom(g):
    """คืน (polygon [[lat,lon],...], approx) จากข้อความ lateral limits"""
    approx = bool(re.search(r"boundary|border|coast", g, re.I))
    m = re.search(r"semi-circle\s+(\d+(?:\.\d+)?)\s*NM radius of\s*", g, re.I)
    if m:
        c = _c(C_RE.search(g, m.end())); r = float(m.group(1))
        fr = re.search(r"from\s*(\d+)\s*°?\s*to\s*(\d+)", g[m.end():])
        b1, b2 = (float(fr.group(1)), float(fr.group(2))) if fr else (0, 180)
        return [c] + _arc(c, r, b1, b2, True) + [c], approx
    m = re.search(r"circle\s+(?:of\s+)?(\d+(?:\.\d+)?)\s*NM radius", g, re.I) or re.search(r"circle\s*,?\s*(?:with\s+)?radius\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*NM", g, re.I)
    if m and "arc" not in g.lower():
        c = _c(C_RE.search(g, m.end())); r = float(m.group(1))
        return _arc(c, r, 0, 360, True, 10), approx
    ms = list(C_RE.finditer(g))
    pts, centers = [], []
    for k in ms:
        before = g[:k.start()].rstrip()
        (centers if before.endswith("(") else pts).append(k)
    poly = []; prev_end = 0; first_center = None
    lead = re.search(r"bounded by\s*(\d+(?:\.\d+)?)\s*NM arc", g, re.I)
    for i, k in enumerate(pts):
        p = _c(k)
        conn = g[prev_end:k.start()]
        am = re.search(r"arc", conn, re.I)
        if am and poly:
            rm = re.search(r"(\d+(?:\.\d+)?)\s*NM", conn)
            cm = C_RE.search(conn)
            c = _c(cm) if cm else (first_center and _c(first_center))
            if c and rm:
                cw = not re.search(r"counter|anti", conn, re.I)
                poly += _arc(c, float(rm.group(1)), _brg(c, poly[-1]), _brg(c, p), cw)[1:-1]
        poly.append(p); prev_end = k.end()
        if lead and first_center is None and centers:
            first_center = centers[0]
    tail = g[prev_end:]
    if re.search(r"arc to the starting point", tail, re.I) and lead and centers and poly:
        c = _c(centers[0]); r = float(lead.group(1))
        cw = not re.search(r"counter|anti", tail, re.I)
        poly += _arc(c, r, _brg(c, poly[-1]), _brg(c, poly[0]), cw)[1:-1]
    if poly and poly[0] != poly[-1]:
        poly.append(poly[0])
    return poly, approx


def parse_enr51(html):
    soup = strip_markup(BeautifulSoup(html, "html.parser"))
    out = []
    for tb in soup.find_all("table"):
        for r in rows(tb):
            line = " ".join(r)
            m = re.match(r"^(VT\s*([PRD])\s*-?\s*\d+[A-Z]?)\s+(.*)$", r[0] if r else "")
            if not m:
                continue
            ident = re.sub(r"\s+", "", m.group(1))
            name_geo = m.group(3)
            nm = re.match(r"^(.*?)\s+(Area bounded|Circle of|A circle|A semi-circle|Area \d)", name_geo)
            name = nm.group(1).strip() if nm else name_geo[:40]
            try:
                poly, approx = parse_geom(name_geo)
            except Exception as e:
                poly, approx = [], True
            vert = r[1] if len(r) > 1 else ""
            upper, _, lower = vert.partition("/")
            info = r[2] if len(r) > 2 else ""
            LBL = r"(?:Type of restriction|Nature of hazard/activity|Time of a\w*|Permission to entry|Inflight information|Contact agency)"
            def field(lbl):
                mm = re.search(lbl + r"\s*:\s*(.*?)(?=\s*" + LBL + r"\s*:|$)", info)
                return mm.group(1).strip() if mm else ""
            out.append({"id": ident, "type": m.group(2), "name": name, "upper": upper.strip(), "lower": lower.strip(),
                        "poly": poly, "approx": approx, "geom_text": name_geo,
                        "restriction": field("Type of restriction"), "activity": field("Nature of hazard/activity"),
                        "time": field(r"Time of a\w*"), "entry": field("Permission to entry"),
                        "info": field("Inflight information"), "contact": field("Contact agency")})
    return out


RTE = re.compile(r"^\s*(?:[▲△▼*]\s*)?(?!FL\d|SFC|GND)([A-Z]{1,2}\d{1,3}[A-Z]?)(?:\s|$|\()")


SEG_TRK = re.compile(r"(\d{3})\s*°\s*(\d{3})\s*°")
SEG_DST = re.compile(r"(\d+(?:\.\d+)?)\s*NM")
SEG_LIM = re.compile(r"(FL\s*\d{2,3}|UNL|\d[\d ]*\s*ft|SFC|GND)\s+(FL\s*\d{2,3}|\d[\d ]*\s*ft|SFC|GND)")


def _alt(v):
    v = v.replace(" ", "")
    return v.replace("ft", " ft") if "ft" in v else v


def parse_seg(line):
    """แถวข้อมูลช่วงเส้นทาง: Track MAG ↓↑, Dist, Upper/Lower, Minimum flight altitude, Lateral limits, FL series, class"""
    t, d = SEG_TRK.search(line), SEG_DST.search(line)
    if not t or not d:
        return None
    sg = {"trk": t.group(1), "rtrk": t.group(2), "dist": float(d.group(1))}
    rest = line[d.end():]
    lm = SEG_LIM.search(rest)
    if lm:
        sg["up"], sg["lo"] = _alt(lm.group(1)), _alt(lm.group(2))
        tail = rest[lm.end():]
        lm2 = SEG_LIM.match(tail.strip())
        if lm2:
            tail = tail.strip()[lm2.end():]
        mf = re.match(r"\s*(\d[\d ]{0,6}?)\s*ft\b", tail)
        if mf:
            sg["mfa"] = int(mf.group(1).replace(" ", ""))
            tail = tail[mf.end():]
        ll = re.match(r"\s*(\d{1,2}(?:\.\d)?)\b", tail)
        if ll:
            sg["ll"] = float(ll.group(1))
    fs = re.findall(r"\b(Odd|Even)\b", rest)
    if fs:
        sg["fl"] = "/".join(fs)
    c = re.search(r"\[\s*Class\s*([A-G])\s*\]", rest)
    if c:
        sg["cls"] = c.group(1)
    return sg


def parse_enr3(html, page):
    """ENR 3.x ATS routes → [{id, page, pts:[{name,lat,lon}]}] (อ่านแบบลำดับแถว: แถวชื่อเส้นทาง แล้วตามด้วยแถวจุดที่มีพิกัด)"""
    soup = strip_markup(BeautifulSoup(html, "html.parser"))
    out, cur, sample, pend = [], None, [], ""
    for tb in soup.find_all("table"):
        for r in rows(tb):
            line = " ".join(r)
            if 10 <= len(sample) < 40 or len(sample) < 10:
                sample.append(line[:160])
            lat, lon = parse_coord(line)
            if lat is None:
                cm = C_RE.search(line)
                if cm:
                    lat, lon = _c(cm)
            if lat is None and cur is not None and cur["pts"]:
                sg = parse_seg(line)
                if sg and "seg" not in cur["pts"][-1]:
                    cur["pts"][-1]["seg"] = sg
                    continue
            if lat is None:
                m = RTE.match(line)
                if m and len(line) < 140 and not re.search(r"Route availability|Remarks", line[:40]) or (m and "Route availability" in line):
                    cur = {"id": m.group(1), "page": page, "pts": []}
                    out.append(cur)
                    pend = ""
                else:
                    pm = re.search(r"\(\s*([A-Z]{2,5})\s*\)|\b([A-Z]{5})\b", line)
                    if pm and len(line) < 80:
                        pend = pm.group(1) or pm.group(2)
                continue
            if cur is None:
                continue
            m = COORD.search(line) or C_RE.search(line)
            head = line[:m.start()] if m else line
            req = bool(re.search(r"[△∆Δ]", head))
            name = re.sub(r"[▲△▼◆◇●○*]", " ", head)
            name = re.sub(r"unknown reference:\s*\S+|[∆Δ]", " ", name)
            idm = re.search(r"\(\s*([A-Z]{2,5})\s*\)", name)
            name = (idm.group(1) if idm else clean(name))[:30] or pend
            pend = ""
            if not cur["pts"] or (cur["pts"][-1]["lat"], cur["pts"][-1]["lon"]) != (lat, lon):
                pt = {"name": name, "lat": lat, "lon": lon}
                if req:
                    pt["req"] = 1   # △ = on request (ไม่บังคับรายงาน) · ▲ = compulsory
                cur["pts"].append(pt)
    return [r for r in out if len(r["pts"]) >= 2], sample


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
            if ic in ("VTPP", "VTSB", "VTBH", "VTCC") and "--debug" in sys.argv:
                debug_dump(f"AD2_{ic}.html", raw)
            ap = parse_ad2(ic, raw, url)
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
    # ENR 4.4 significant points (ชื่อจุด 5 ตัวอักษร + พิกัด) — ใช้พิมพ์ชื่อจุดในแอปได้
    try:
        raw = get(root + "VT-ENR-4.4-en-GB.html")
        if "--debug" in sys.argv:
            debug_dump("ENR_4.4.html", raw)
        sp = []
        for tb in strip_markup(BeautifulSoup(raw, "html.parser")).find_all("table"):
            for r in rows(tb):
                if r and re.fullmatch(r"[A-Z]{5}", r[0]):
                    cm = C_RE.search(" ".join(r[1:3]))
                    if cm:
                        lat, lon = _c(cm)
                        sp.append({"name": r[0], "lat": lat, "lon": lon})
        data["sigpoints"] = sp
        print(f"ENR 4.4 จุด {len(sp)} จุด")
    except Exception as e:
        data["errors"].append(f"ENR 4.4: {e}")
    # ENR 3.x ATS routes (airways) — ใช้วาดเส้นแบบ enroute chart
    data["airways"] = []
    for pg in ("3.1", "3.2", "3.3", "3.4"):
        try:
            raw = get(root + f"VT-ENR-{pg}-en-GB.html")
            aw, sample = parse_enr3(raw, pg)
            data["airways"] += aw
            print(f"ENR {pg} เส้นทาง {len(aw)} เส้น")
        except Exception as e:
            data["errors"].append(f"ENR {pg}: {e}")
    # ENR 5.1 Prohibited / Restricted / Danger areas
    try:
        raw = get(root + "VT-ENR-5.1-en-GB.html")
        if "--debug-enr5" in sys.argv:
            debug_dump("ENR_5.1.html", raw)
        data["areas"] = parse_enr51(raw)
        print(f"ENR 5.1 พื้นที่ {len(data['areas'])} แห่ง")
    except Exception as e:
        data["errors"].append(f"ENR 5.1: {e}")
    # AD 2.24 VFR reporting points + เส้นทาง VFR (จาก PDF "Tabular description" — ต้องมี pdftotext)
    try:
        import shutil, subprocess, tempfile
        import vfr_ad224
        if shutil.which("pdftotext"):
            def pdf_text(u):
                r = S.get(u, timeout=60)
                r.raise_for_status()
                with tempfile.TemporaryDirectory() as td:
                    fp = os.path.join(td, "c.pdf")
                    open(fp, "wb").write(r.content)
                    subprocess.run(["pdftotext", "-layout", fp, fp + ".txt"], check=True, timeout=60)
                    time.sleep(0.3)
                    return open(fp + ".txt", errors="ignore").read()
            vfr = vfr_ad224.build({ic: a.get("charts", []) for ic, a in data["airports"].items()}, pdf_text)
            for ic, v in vfr.items():
                data["airports"][ic]["vfr"] = v
        else:
            data["errors"].append("AD 2.24 VFR: ไม่มี pdftotext (poppler-utils)")
    except Exception as e:
        data["errors"].append(f"AD 2.24 VFR: {e}")
    with open("eaip_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("\nบันทึกแล้ว: eaip_data.json")
    if data["errors"]:
        print("มีจุดที่อ่านไม่ได้", len(data["errors"]), "รายการ — ส่งไฟล์นี้ให้ Claude ดูเพื่อแก้สคริปต์")


if __name__ == "__main__":
    main()
