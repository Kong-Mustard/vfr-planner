"""ดึง NOTAM ของสนามบินในไทย + FIR VTBB จาก FAA NOTAM Search (ข้อมูลสากล ICAO) → notam.json
แอปโหลดเองในแท็บ NOTAM — ถ้าดึงไม่ได้ แอปยังใช้การวางข้อความเองได้เหมือนเดิม"""
import json, time, datetime, urllib.request, urllib.parse

URL = "https://notams.aim.faa.gov/notamSearch/search"
BASE = {"searchType": "0", "designatorForAccountable": "", "latDegrees": "", "latMinutes": "0", "latSeconds": "0",
        "longDegrees": "", "longMinutes": "0", "longSeconds": "0", "radius": "10", "sortColumns": "5 false", "sortDirection": "true",
        "designatorForNotamNumberSearch": "", "notamNumber": "", "radiusSearchOnDesignator": "false", "radiusSearchDesignator": "",
        "latitudeDirection": "N", "longitudeDirection": "W", "freeFormText": "", "flightPathText": "", "flightPathDivertAirfields": "",
        "flightPathBuffer": "4", "flightPathIncludeNavaids": "true", "flightPathIncludeArtcc": "false", "flightPathIncludeTfr": "true",
        "flightPathIncludeRegulatory": "false", "flightPathResultsType": "All NOTAMs", "archiveDate": "", "archiveDesignator": "",
        "notamsOnly": "false", "filters": "", "minRunwayLength": "", "minRunwayWidth": "", "runwaySurfaceTypes": "",
        "predefinedAbraka": "", "predefinedDabraka": "", "flightPathAddlBuffer": "", "recaptchaToken": ""}


def post(locs, offset):
    data = dict(BASE, designatorsForLocation=",".join(locs), offset=str(offset))
    req = urllib.request.Request(URL, data=urllib.parse.urlencode(data).encode(), headers={
        "User-Agent": "Mozilla/5.0 (vfr-planner)", "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json", "Origin": "https://notams.aim.faa.gov", "Referer": "https://notams.aim.faa.gov/notamSearch/nsapp.html"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main():
    ids = sorted(k for k in json.load(open("eaip_data.json"))["airports"] if k.startswith("VT"))
    locs = ["VTBB"] + ids
    out = {"fetched": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%MZ"), "source": "FAA NOTAM Search (ICAO international)",
           "notams": [], "errors": []}
    seen = set()
    for i in range(0, len(locs), 10):
        grp = locs[i:i + 10]
        off = 0
        while True:
            try:
                d = post(grp, off)
            except Exception as e:
                out["errors"].append(f"{grp[0]}..: {e}"[:200]); break
            for n in d.get("notamList", []):
                msg = n.get("icaoMessage") or n.get("traditionalMessage") or ""
                key = (n.get("facilityDesignator"), n.get("notamNumber"), msg[:40])
                if key in seen or not msg:
                    continue
                seen.add(key)
                out["notams"].append({"loc": n.get("icaoId") or n.get("facilityDesignator"), "id": n.get("notamNumber"),
                                      "icao": msg.strip(), "plain": (n.get("plainLanguageMessage") or "")[:1500],
                                      "start": n.get("startDate"), "end": n.get("endDate"), "keyword": n.get("keyword")})
            end, total = d.get("endRecordCount", 0), d.get("totalNotamCount", 0)
            if not d.get("notamList") or end >= total or off > 600:
                break
            off = end
            time.sleep(0.6)
        time.sleep(0.6)
    print(len(out["notams"]), "NOTAM", out["errors"][:3])
    if out["notams"] or not out["errors"]:
        json.dump(out, open("notam.json", "w"), ensure_ascii=False, indent=0)
    else:
        # ดึงไม่ได้เลย: เก็บสถานะไว้ แต่ไม่ทับ NOTAM ชุดเก่า
        try:
            old = json.load(open("notam.json"))
        except Exception:
            old = {"notams": []}
        old["last_error"] = {"at": out["fetched"], "errors": out["errors"][:5]}
        json.dump(old, open("notam.json", "w"), ensure_ascii=False, indent=0)


if __name__ == "__main__":
    main()
