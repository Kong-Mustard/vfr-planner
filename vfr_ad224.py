# อ่าน VFR reporting points + เส้นทาง VFR จาก AD 2.24 "Tabular description" (ข้อความจาก pdftotext -layout)
# ใช้โดย eaip_update.py — แยกไฟล์ไว้ทดสอบกับข้อความตัวอย่างได้
import re

DMS = re.compile(r"(\d{1,2})\s*°\s*(\d{1,2})\s*'\s*(\d{1,2}(?:\.\d+)?)\s*(?:''|\"|”|′′)\s*([NS])\s*"
                 r"(\d{2,3})\s*°\s*(\d{1,2})\s*'\s*(\d{1,2}(?:\.\d+)?)\s*(?:''|\"|”|′′)\s*([EW])")
RAD = re.compile(r"R-\d{3}\s*/\s*[\d.]+\s*D(?:\s+[A-Z]{3})?")
ALTSEQ = re.compile(r"([A-Z0-9][A-Z0-9 .'/-]*?)\s*\[ALT\s*(\d{3,5})\]")


def _deg(d, m, s, h):
    v = int(d) + int(m) / 60 + float(s) / 3600
    return round(-v if h in "SW" else v, 6)


def _segs(line, a=0, b=None):
    """ช่วงข้อความที่คั่นด้วยช่องว่าง ≥2 ตัว → [(col, text)]"""
    b = len(line) if b is None else b
    out = []
    for m in re.finditer(r"\S+(?: \S+)*", line[a:b]):
        out.append((a + m.start(), m.group(0)))
    return out


def norm(n):
    return re.sub(r"[^A-Z0-9]", "", n.upper().replace("POINT", ""))


def short_of(n):
    m = re.match(r'["“”]?([A-Z0-9]{1,3})["“”]?\s+or\b', n)
    if m:
        return m.group(1)
    m = re.match(r"([A-Z0-9]{1,3})\s+POINT$", n.strip(), re.I)
    if m:
        return m.group(1).upper()
    return None


def parse_points(txt):
    L = txt.split("\n")
    if not re.search(r"Reporting", txt, re.I):
        return []
    coordline = set(i for i, l in enumerate(L) if DMS.search(l))
    # 1) แบ่งแต่ละพิกัดเป็นช่วงข้อความก่อนหน้า (ชื่อ / landmark / radial)
    items = []
    for i in sorted(coordline):
        l = L[i]
        prev = 0
        for m in DMS.finditer(l):
            rad = RAD.search(l, prev, m.start())
            rstart = rad.start() if rad else m.start()
            items.append({"i": i, "a": prev, "r": rstart, "m": m, "rad": rad, "sg": _segs(l, prev, rstart)})
            prev = m.end()
    # 2) คอลัมน์ชื่อ = ตำแหน่งเริ่มของข้อความแรกในแถวที่มี ≥2 ช่อง (ชื่อ + landmark) — แยกกลุ่มตารางซ้าย/ขวา
    cols = sorted(it["sg"][0][0] for it in items if len(it["sg"]) >= 2)
    ncs = []
    for c in cols:
        if not ncs or c - ncs[-1] > 6:
            ncs.append(c)
    if not ncs:
        ncs = sorted(set(it["sg"][0][0] for it in items if it["sg"])) or [0]

    def ncol(it):
        c = [x for x in ncs if it["a"] - 3 <= x < it["r"]]
        return c[0] if c else None

    pts = []
    for it in items:
        nc = ncol(it)
        if nc is None:
            continue
        i, sg = it["i"], it["sg"]
        nm, lm, used = "", [], set()
        if sg and abs(sg[0][0] - nc) <= 3:
            nm = sg[0][1]
            lm = [t for c, t in sg[1:]]
        else:
            lm = [t for c, t in sg]
            for d in (-1, 1, -2, 2):
                j = i + d
                if 0 <= j < len(L) and j not in coordline and L[j].strip():
                    s2 = [t for c, t in _segs(L[j], it["a"], min(len(L[j]), it["r"])) if abs(c - nc) <= 3]
                    if s2:
                        nm, used = s2[0], {j}
                        break
        # landmark ที่ห่อขึ้น/ลงบรรทัดข้างเคียง (ไม่ใช่บรรทัดพิกัดอื่น)
        for j in (i - 1, i + 1):
            if 0 <= j < len(L) and j not in coordline and j not in used:
                ex = [t for c, t in _segs(L[j], it["a"], min(len(L[j]), it["r"] + 4)) if c > nc + 3 and not RAD.match(t)]
                if j < i:
                    lm = ex + lm
                else:
                    lm = lm + ex
        nm = re.sub(r"\s+", " ", nm).strip()
        if not nm or nm == "-" or (re.search(r"VOR|DME|NDB", nm + " ".join(lm)) and not short_of(nm) and not re.search(r"[A-Z]{4}", nm.replace("VOR", "").replace("DME", ""))):
            continue
        if re.search(r"VOR|DME|NDB", nm) or (not short_of(nm) and re.search(r"VOR/DME|VOR Station|NDB", " ".join(lm))):
            continue
        g = it["m"].groups()
        p = {"n": nm, "lat": _deg(*g[:4]), "lon": _deg(*g[4:])}
        sc = short_of(nm)
        if sc:
            p["id"] = sc
        lm = [t for t in lm if t != "-"]
        if lm:
            p["lm"] = re.sub(r"\s+", " ", " ".join(lm))[:80]
        if it["rad"]:
            p["rd"] = re.sub(r"\s+", " ", it["rad"].group(0))
        pts.append(p)
    return pts


def parse_routes(txt):
    """คืน [{sec, dir, seq:[[ชื่อ, alt|None], ...]}]"""
    L = txt.split("\n")
    stop = next((i for i, l in enumerate(L) if re.search(r"^\s*(Reporting|Coordinates)\b|\bReporting\s+points", l, re.I) or DMS.search(l)), len(L))
    body = L[:stop]
    out = []
    if any("[ALT" in l for l in body):
        sec = dr = ""
        cur = None
        for l in body:
            s = l.strip()
            if re.fullmatch(r"(DEPARTURE|ARRIVAL|OUTBOUND|INBOUND|OVERFLY)", s):
                sec, dr = s, ""
                if s in ("OUTBOUND", "INBOUND"):
                    dr = s
                cur = None
                continue
            if re.fullmatch(r"[A-Z]+BOUND", s):
                dr = s
                cur = None
                continue
            if s.startswith("- ") or s == "-":
                cur = {"sec": sec, "dir": dr, "raw": s[1:].strip()}
                out.append(cur)
                continue
            if cur is not None and s and not re.match(r"(LIGHT AIRCRAFT WITHIN|CHANGE)", s):
                cur["raw"] += " " + s
            elif not s:
                cur = None
        res = []
        for r in out:
            raw = re.split(r"\bTHEN\b", r["raw"])[0]
            seq = []
            for part in re.split(r"\s+-\s+", raw):
                alts = [(re.sub(r"\s+", " ", a.strip(" -")), int(b)) for a, b in ALTSEQ.findall(part)]
                if alts:
                    seq.append([alts[0][0], alts[0][1]] + ([[a for a, _ in alts[1:]]] if len(alts) > 1 else []))
            if len(seq) >= 2:
                res.append({"sec": r["sec"], "dir": r["dir"], "seq": seq})
        return res
    # แบบบรรยาย: "ARR-RWY14/32 (From North)" แล้ว "Enter via ... NI POINT, then heading 168° to WB POINT ..."
    title = ""
    para = []

    def flush():
        if not para:
            return
        t = re.sub(r"\|\s*POINT", "I POINT", " ".join(para))  # OCR อ่าน I เป็น |
        hits = [(m.start(), m.group(1) or m.group(2)) for m in re.finditer(r"(?:\"([A-Z0-9]{1,3})\"|\b([A-Z0-9]{1,3}))\s*POINT\b", t)]
        # "Inbound via Khao Wang." — จุดที่เป็นชื่อสถานที่ (ไม่ใช่ X POINT)
        hits += [(m.start(1), m.group(1)) for m in re.finditer(r"\bvia\s+(?:the\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})(?=\s*[.,])", t)]
        seq = [[n, None] for _, n in sorted(hits)]
        if len(seq) >= 1:
            sec = "ARR" if title.upper().startswith("ARR") else "DEP" if title.upper().startswith("DEP") else ""
            res.append({"sec": sec, "dir": title, "seq": seq, "txt": re.sub(r"\s+", " ", t)[:300]})
        para.clear()

    res = []
    for l in body:
        s = re.sub(r"\s+", " ", l.strip())
        if re.match(r"(ARR|DEP)\s*-", s):
            flush()
            title = s
            continue
        if re.match(r"(Enter|Inbound|After|Depart|Exit|Leave|Proceed)\b", s):
            flush()
            para.append(s)
        elif para and s and not re.search(r"Coordinates|AERODROME ELEV|CHANGE", s):
            para.append(s)
            if s.endswith("."):
                flush()
    flush()
    return res


def chart_cat(name):
    u = name.upper()
    return "H" if "HELICOPTER" in u else "A"


# ---------- หน้า PDF ที่เป็นภาพสแกน: อ่านด้วย OCR แล้ว "ตรวจไขว้" กับ radial/DME ----------
# OCR อ่านตัวเลขพลาดได้ จึงรับเฉพาะจุดที่พิกัดตรงกับตำแหน่งที่คำนวณจาก radial/DME ของ VOR สนามนั้น
DMS_OCR = re.compile(r"(\d{1,2})\s*[°º]\s*(\d{1,2})\s*['’\"”]\s*(\d{1,2}(?:[.,]\d+)?)\s*['’\"”]{0,2}\s*([NS])\s*"
                     r"(\d{2,3})\s*[°º]\s*(\d{1,2})\s*['’\"”]\s*(\d{1,2}(?:[.,]\d+)?)\s*['’\"”]{0,2}\s*([EW])")
RAD_OCR = re.compile(r"R\s*-\s*(\d{3})\s*/\s*(\d{1,3}(?:\.\d)?)\s*D")


def _dest(lat, lon, brg, nm):
    import math
    R = 3440.065; d = nm / R; b = math.radians(brg); la = math.radians(lat); lo = math.radians(lon)
    la2 = math.asin(math.sin(la) * math.cos(d) + math.cos(la) * math.sin(d) * math.cos(b))
    lo2 = lo + math.atan2(math.sin(b) * math.sin(d) * math.cos(la), math.cos(d) - math.sin(la) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)


def _nm(a, b):
    import math
    la1, la2 = math.radians(a[0]), math.radians(b[0]); dl = math.radians(b[1] - a[1])
    return 3440.065 * math.acos(max(-1, min(1, math.sin(la1) * math.sin(la2) + math.cos(la1) * math.cos(la2) * math.cos(dl))))


def parse_points_ocr(txt, vor, var=0.0, log=print):
    """vor = (lat, lon) ของ VOR ที่ใช้อ้าง radial · var = magnetic variation (E บวก)"""
    pts, rej = [], 0
    L = [re.sub(r"[|\[\]{}]", " ", l) for l in txt.split("\n")]
    for i, l in enumerate(L):
        m = DMS_OCR.search(l)
        if not m:
            continue
        g = [x.replace(",", ".") for x in m.groups()]
        lat, lon = _deg(*g[:4]), _deg(*g[4:])
        rd = RAD_OCR.search(l)
        if not rd or not vor:
            rej += 1
            continue
        exp = _dest(vor[0], vor[1], float(rd.group(1)) + var, float(rd.group(2)))
        err, tol = _nm((lat, lon), exp), 0.35 + float(rd.group(2)) * 0.035
        if err > tol:
            rej += 1
            log(f"    OCR ไม่ผ่านการตรวจ radial/DME ({err:.1f} NM): {l.strip()[:90]}")
            continue
        head = l[:rd.start()].strip(" -")
        nm = head
        sc = short_of(head)
        if sc:
            nm = re.match(r'(.*?\bPoint)\b', head, re.I).group(1) if re.search(r"\bPoint\b", head, re.I) else head
        if not nm and i > 0:
            nm = L[i - 1].strip()
        if not nm or re.search(r"VOR|DME", nm):
            continue
        p = {"n": re.sub(r"\s+", " ", nm)[:60], "lat": lat, "lon": lon, "rd": f"R-{rd.group(1)} / {rd.group(2)}D", "ocr": 1}
        if sc:
            p["id"] = sc
            lm = head[len(nm):].strip()
            if lm:
                p["lm"] = lm[:60]
        pts.append(p)
    return pts, rej


def build(ap_charts, fetch_text, log=print, ocr_text=None, vor_of=None):
    """ap_charts: {icao: [chart,...]} · fetch_text(url) -> ข้อความ pdftotext
    คืน {icao: {"pts": [...], "rt": [...]}} โดย rt.seq = [[ชื่อ, alt, lat, lon, ทางเลือก?], ...]"""
    raw = {}
    for ic, charts in ap_charts.items():
        pts, rts, last_sec = [], [], {}
        for ch in charts:
            nm = ch.get("name", "")
            if "VFR" not in nm.upper() or "TABULAR" not in nm.upper():
                continue
            base = re.sub(r"\s*\(Tabular.*$", "", nm, flags=re.I).strip()
            try:
                t = fetch_text(ch["url"])
            except Exception as e:
                log(f"  {ic} {ch.get('page')}: โหลดไม่ได้ {e}")
                continue
            ocr = False
            if not t or len(t.strip()) < 50:
                if not ocr_text:
                    continue  # หน้าเป็นภาพสแกน — อ่านข้อความไม่ได้
                try:
                    t = ocr_text(ch["url"])
                except Exception as e:
                    log(f"  {ic} {ch.get('page')}: OCR ไม่ได้ {e}")
                    continue
                ocr = True
            if ocr:
                vor, var = (vor_of(ic) if vor_of else (None, 0.0))
                P, rej = parse_points_ocr(t, vor, var, log)
                log(f"  {ic} {ch.get('page')}: OCR ได้ {len(P)} จุด (ตัดทิ้ง {rej})")
            else:
                P = parse_points(t)
            R = parse_routes(t)
            for r in R:
                if not r["sec"]:
                    r["sec"] = last_sec.get(base, "")
                last_sec[base] = r["sec"] or last_sec.get(base, "")
                r["c"] = chart_cat(nm)
                if "OVERFLY" in nm.upper():
                    r["dir"] = r["dir"] or r["sec"]
                    r["sec"] = "OVERFLY"
                r["ch"] = base
            pts += P
            rts += R
        if pts or rts:
            raw[ic] = (pts, rts)
    # พจนานุกรมจุดรวมทุกสนาม (ชื่อเดียวกันใช้ร่วมกัน เช่น จุดรอบกรุงเทพ VTBD/VTBS)
    G, G2 = {}, {}
    for ic, (pts, _) in raw.items():
        for p in pts:
            G.setdefault(norm(p["n"]), p)
            G2.setdefault(norm(p["n"]).replace("H", ""), p)
    out = {}
    for ic, (pts, rts) in raw.items():
        P, seen = [], set()
        for p in pts:
            k = norm(p["n"])
            if k not in seen:
                seen.add(k)
                P.append(p)
        byid = {p["id"]: p for p in P if p.get("id")}
        R, rseen = [], set()
        for r in rts:
            seq = []
            for it in r["seq"]:
                n = it[0]
                p = byid.get(n) if r.get("txt") else None
                p = p or next((q for q in P if norm(q["n"]) == norm(n)), None) or G.get(norm(n))
                p = p or G2.get(norm(n).replace("H", ""))
                p = p or next((q for q in P if len(norm(n)) >= 5 and norm(q["n"]).startswith(norm(n))), None)  # สะกดต่างกันในเอกสาร เช่น SANAP TUEP / SANAP THUEP
                e = [p["id"] if p and p.get("id") else n, it[1], p["lat"] if p else None, p["lon"] if p else None]
                if len(it) > 2:
                    e.append(it[2])
                seq.append(e)
            key = (r["c"], r["sec"], r["dir"], tuple(e[0] for e in seq))
            if key in rseen or sum(1 for e in seq if e[2] is not None) < 2:
                continue
            rseen.add(key)
            o = {"c": r["c"], "ch": r["ch"], "sec": r["sec"], "dir": r["dir"], "seq": seq}
            if r.get("txt"):
                o["txt"] = r["txt"]
            R.append(o)
        out[ic] = {"pts": P, "rt": R}
        log(f"  VFR {ic}: จุด {len(P)} · เส้นทาง {len(R)}")
    return out
