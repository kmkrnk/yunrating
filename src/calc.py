"""Unofficial Belarus youth orienteering rating 2026.

Data: bfo-base.orient.by API (protocols of BFO competitions); stages that are not in
the base yet are read from obelarus.net result protocols.

Rules (Положение о республиканском юношеском рейтинге на 2026 год):
  points = K * 1000 * (2 * T_winner / T_runner - 1), K = 1.1 for class A, 1.0 for class B,
  rounded, floored at 0 (a non-finisher gets 0); points only in the runner's own age group
  or one older (M/W18 also in 20 and 21; in 21 only 21E when 21 is split into levels);
  best N distances count, N = ceil(12 * held / planned).
"""
from fractions import Fraction
import html, json, math, os, re, time, unicodedata, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
API = "http://bfo-base.orient.by/api/v1"
CACHE = os.path.join(HERE, "cache")
os.makedirs(CACHE, exist_ok=True)
YEAR = 2026
PLANNED = 20  # 22 distances in the 2026 calendar (Положение, п. 7) minus Vitebsk 05-06.09, which did not take place

# (source, id, class, competition, distance, date)
# The official table (orient.by, "Юноши 20.08") is taken as is; other stages are added on top.
STAGES = [
    ("base", 1048, "Б", "Брестский подснежник", "Классика", "2026-03-28"),
    ("base", 1049, "Б", "Брестский подснежник", "Спринт", "2026-03-29"),
    ("base", 1052, "Б", "Командный чемпионат Минской обл.", "Средняя", "2026-04-04"),
    ("base", 1053, "Б", "Командный чемпионат Минской обл.", "Спринт", "2026-04-05"),
    ("base", 1055, "Б", "Гродненская лесная многодневка", "Спринт", "2026-04-18"),
    ("base", 1056, "Б", "Гродненская лесная многодневка", "Средняя", "2026-04-19"),
    ("base", 1057, "Б", "Гродненская лесная многодневка", "Классика", "2026-04-20"),
    # not in the official table (protocols were never passed to the federation); groups split into А/В: only А counts
    ("obelarus", "260502r_mm", "Б", "Майская многодневка", "Средняя", "2026-05-02"),
    ("obelarus", "260503r_mm", "Б", "Майская многодневка", "Длинная", "2026-05-03"),
    ("base", 1076, "А", "Командный чемпионат БФО", "Длинная", "2026-05-16"),
    ("base", 1077, "А", "Командный чемпионат БФО", "Средняя", "2026-05-17"),
    ("obelarus", "260911r_spart", "А", "Республиканская спартакиада", "Спринт", "2026-09-11"),
    ("obelarus", "260912r_spart", "А", "Республиканская спартакиада", "Классика", "2026-09-12"),
    ("obelarus", "260913r_spart", "А", "Республиканская спартакиада", "Средняя", "2026-09-13"),
    ("obelarus", "261010r_homel", "Б", "Золотая осень", "Спринт", "2026-10-10"),
    ("obelarus", "261011r_homel", "Б", "Золотая осень", "Средняя", "2026-10-11"),
    ("base", 1157, "А", "Первенство РБ, Слуцк", "Средняя", "2026-10-17"),
    ("base", 1159, "А", "Первенство РБ, Слуцк", "Спринт", "2026-10-18"),
    ("obelarus", "261024r_kvm26", "Б", "Кубок г. Могилёва", "Средняя", "2026-10-24"),
    ("obelarus", "261025r_kvm26", "Б", "Кубок г. Могилёва", "Спринт", "2026-10-25"),
]
# Stages already in the official table, and disputed stages a viewer can switch on or off
# The BFO base leaves out non-finishers; the official table gives them 0. Take them from obelarus.
DNF_SOURCE = {1157: "261017r_slutsk", 1159: "261018r_slutsk"}
OFFICIAL = {"1048", "1049", "1052", "1053", "1055", "1056", "1057", "1076", "1077"}
KNOWN_YEARS = {}  # name -> birth year from the official table (filled by merge.py)
OPTIONAL = {}  # stages follow the official list on orient.by (competitions/2026/?kubok#unoshi)


def fetch(url):
    req = urllib.request.Request(url, headers={
        "Accept": "application/json" if "/api/" in url else "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "ru,en;q=0.8",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def cached(key, url, ttl, parse):
    fn = os.path.join(CACHE, re.sub(r"[^\w.-]", "_", key))
    if os.path.exists(fn) and time.time() - os.path.getmtime(fn) < ttl:
        raw = open(fn, "rb").read()
    else:
        raw = fetch(url)
        open(fn, "wb").write(raw)
    return parse(raw)


def api(path, ttl=3600):
    return cached(path + ".json", API + path, ttl, lambda b: json.loads(b.decode("utf-8")))


def secs(t):
    t = (t or "").strip()
    if not re.match(r"^\d+:\d\d(:\d\d)?$", t):
        return None
    p = [int(x) for x in t.split(":")]
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]


def norm_group(name):
    """'Ж14' -> ('W', 14, ''); 'М21E' -> ('M', 21, 'E')."""
    n = unicodedata.normalize("NFKC", name or "").strip().upper()
    n = n.translate(str.maketrans({"Ж": "W", "М": "M", "Е": "E", "А": "A", "В": "B"}))
    m = re.match(r"^([MW])\s*(\d+)\s*([A-Z]*)", n)
    return (m.group(1), int(m.group(2)), m.group(3)) if m else None


def norm_name(s):
    s = unicodedata.normalize("NFKC", s or "").replace("ё", "е").replace("Ё", "Е")
    return re.sub(r"\s+", " ", s).strip().lower()


def rating_age(year):
    a = YEAR - int(year)
    if a <= 12: return 12      # 2014-2015 and younger
    if a <= 14: return 14      # 2012-2013
    if a <= 16: return 16      # 2010-2011
    if a <= 18: return 18      # 2008-2009
    return None


def eligible(rg, ran, top):
    """top: {(sex, age): top-level letter} for groups split into levels (21E, 14A ...)."""
    sex, age, sub = ran
    lvl = top.get((sex, age))
    if lvl and sub != lvl:
        return False
    if age == rg or age == rg + 2:
        return True
    return rg == 18 and age in (20, 21)


# ---- stage loaders: return list of (group_name, [ {name, year, club, t, placed, vk} ]) ----
def load_base(ev_id):
    out = []
    for d in api(f"/distances?eventId={ev_id}&perPage=1000"):
        g = norm_group(d["groupName"])
        if not g or g[1] not in (12, 14, 16, 18, 20, 21):
            continue
        lines = []
        for l in api(f"/protocol-lines?distanceId={d['id']}&perPage=1000"):
            placed = str(l.get("place") or "").strip().isdigit()
            year, club = l.get("year"), l.get("club") or ""
            if not year:  # non-finishers in the base: "КО «Случь» 3 2011 б/р" — year glued to the club
                m = re.search(r"\s((?:19|20)\d\d)(?:\s+\S+)?\s*$", club)
                if m:
                    year, club = m.group(1), club[:m.start()].strip()
            lines.append({"name": f"{l['lastname'] or ''} {l['firstname'] or ''}".strip(), "year": year,
                          "club": club, "t": secs(l.get("time")) if placed else None,
                          "placed": placed, "vk": bool(l.get("vk"))})
        out.append((d["groupName"], lines))
    return out


def load_obelarus(code):
    url = f"https://www.obelarus.net/results/{YEAR}/{code}.htm"

    def parse(raw):
        try:
            t = raw.decode("utf-8")
        except UnicodeDecodeError:
            t = raw.decode("cp1251")
        t = html.unescape(re.sub(r"<[^>]+>", "", t))
        # group headers: "Ж12" or "Ж12, 11 КП, 0.900 м"; non-foot groups (МТВОЖ16, Open, OPEN3) get their own block and are skipped later
        blocks = re.split(r"\n\s*([МЖ]\d\d[A-ZА-Я]?|МТВО\S*?|Open|OPEN\d*)(?:,[^\n]*)?[ \t\r]*\n", t)
        out = []
        for i in range(1, len(blocks) - 1, 2):
            gname, body = blocks[i], blocks[i + 1]
            head = next((l for l in body.split("\n") if "Фамилия" in l and "Результат" in l), None)
            if not head:
                continue
            lines = []
            if "Коллектив" in head:
                # older template (Спартакиада): "№ Фамилия, имя  Коллектив  Квал Номер ГР Результат Место ..."
                # its columns are not aligned with the header, so read the tail of each row by pattern
                c_team = head.index("Коллектив")
                for l in body.split("\n"):
                    if not re.match(r"^\s*\d+\s+\S", l):
                        continue
                    # "... Номер ГР Результат [Отставание] Место ...": bib, birth year, result, optional "+gap", place
                    m = re.search(r"\s(\d+)\s+(?:((?:19|20)\d\d)\s+)?(\d+:\d\d:\d\d|п\.?\s?п\S*|сн\S*|сош\S*|н\.?\s?ст\S*|н/с\S*|-)(?:\s+\+\S+)?(?:\s+=?\s*(\S+))?", l[c_team:])  # "= 13" is a shared place
                    if not m:
                        continue
                    res, place = m.group(3), m.group(4) or ""
                    if re.match(r"н\.?\s?ст|н/с", res.lower()):
                        continue  # did not start: not a participant, no points at all
                    placed = place.isdigit()
                    lines.append({"name": " ".join(re.sub(r"^\s*\d+\s+", "", l[:c_team]).split()), "year": m.group(2) or "",
                                  "club": re.split(r"\s{2,}", l[c_team:].strip())[0],
                                  "t": secs(res) if placed else None, "placed": placed, "vk": "в/к" in place or "в/к" in res})
                out.append((gname, lines))
                continue
            c_team, c_year, c_res, c_place = head.index("Команда"), head.index("Г.р."), head.index("Результат"), head.index("Место")
            for l in body.split("\n"):
                if not re.match(r"^\s*\d+\s+\S", l) or len(l) < c_place:
                    continue
                name = re.sub(r"^\s*\d+\s+", "", l[:c_team]).strip()
                cm = re.search(r"\s+([A-Z]{3})$", name)  # foreign athletes: "Степанова Анна   RUS"
                country = cm.group(1) if cm else ""
                name = name[:cm.start()] if cm else name
                year = l[c_year:c_year + 4].strip()
                res = l[c_res - 2:c_place].strip()
                place = l[c_place:c_place + 6].strip()
                if not year.isdigit():
                    continue
                placed = place.isdigit()
                lines.append({"name": name, "year": year, "club": l[c_team:c_year].strip(),
                              "t": secs(res) if placed else None, "placed": placed, "vk": "в/к" in place,
                              "foreign": country not in ("", "BLR")})
            out.append((gname, lines))
        return out

    return cached(code + ".htm", url, 3600, parse)


def points(cls, tw, t):
    """Положение п.4: К x 1000 x (2 x Тпоб / Туч - 1), rounded to a whole number (half up), never below 0. Exact arithmetic."""
    k = Fraction(11, 10) if cls == "А" else Fraction(1)
    v = k * 1000 * (2 * Fraction(tw, t) - 1)
    return max(0, math.floor(v + Fraction(1, 2)))


def find_protocol(date, keyword):
    """Code of the obelarus.net result protocol for that day whose page mentions keyword, or None."""
    ymd = date[2:4] + date[5:7] + date[8:10]
    try:
        index = cached(f"index_{ymd}.htm", f"https://www.obelarus.net/results/{YEAR}/", 600, lambda b: b.decode("utf-8", "replace"))
    except Exception as e:
        print("obelarus index not reachable:", e)
        return None
    for code in sorted(set(re.findall(rf'href="({ymd}r_[^"/]+)\.htm"', index))):
        try:
            raw = cached(code + ".page", f"https://www.obelarus.net/results/{YEAR}/{code}.htm", 600, lambda b: b)
        except Exception:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1251")
        title = re.search(r"<title>(.*?)</title>", text, re.S)
        body = text[text.find("resbody"):]
        head = (title.group(1) if title else "") + " " + html.unescape(re.sub(r"<[^>]+>", " ", body))[:1500]
        if keyword.lower() in head.lower():
            return code
    return None


def load_json(name):
    """Results saved in the repo (e.g. taken from live.obelarus.net before the protocol is out): [group, [lines]]."""
    data = json.load(open(os.path.join(HERE, "data", name + ".json"), encoding="utf-8"))
    return [(g, lines) for g, lines in data["groups"]]


def compute():
    persons = {}
    stages = []
    for src, sid, cls, comp, dist, date in STAGES:
        if src == "auto":
            code = find_protocol(date, sid)
            if not code:
                continue  # not held yet / protocol not published
            groups_try = load_obelarus(code)
            if sum(len(l) for g, l in groups_try if norm_group(g) and norm_group(g)[1] in (12, 14, 16, 18)) < 20:
                print("protocol", code, "found but not readable yet - skipped")
                continue
            src, sid = "obelarus", code
            print("new stage picked up:", comp, date, code)
        K = 1.1 if cls == "А" else 1.0
        groups = load_base(sid) if src == "base" else load_json(sid) if src == "json" else load_obelarus(sid)
        if src == "base" and sid in DNF_SOURCE:
            extra = {norm_group(g): [l for l in ls if not l["placed"] and not l["vk"]] for g, ls in load_obelarus(DNF_SOURCE[sid])}
            for gname, lines in groups:
                have = {norm_name(l["name"]) for l in lines}
                for l in extra.get(norm_group(gname), []):
                    if norm_name(l["name"]) not in have:
                        lines.append(l)
        names = [n for n in (norm_group(g) for g, _ in groups) if n]
        top = {}
        for n in names:
            if n[2]:
                subs = {m[2] for m in names if m[:2] == n[:2]}
                top[n[:2]] = "E" if "E" in subs else ("A" if "A" in subs else sorted(subs)[0])
        got = {}
        for gname, lines in groups:
            g = norm_group(gname)
            if not g:
                continue
            fin = [l for l in lines if l["t"] and not l["vk"]]
            if not fin:
                continue
            tw = min(l["t"] for l in fin)
            for l in lines:
                # foreigners set the winner's time like everyone else, but the rating is for Belarus athletes
                if not l["year"] or not str(l["year"]).isdigit() or l["vk"] or l.get("foreign"):
                    continue
                ky = KNOWN_YEARS.get(norm_name(l["name"]))
                if ky and abs(ky - int(l["year"])) <= 1:
                    l["year"] = ky
                rg = rating_age(l["year"])
                if rg is None or not eligible(rg, g, top):
                    continue
                pts = points(cls, tw, l["t"]) if l["t"] else 0
                key = (norm_name(l["name"]), int(l["year"]), g[0])
                if key not in got or pts > got[key]:
                    got[key] = pts
                p = persons.setdefault(key, {"name": l["name"], "year": int(l["year"]), "sex": g[0],
                                             "rg": rg, "club": l["club"], "pts": {}})
                p["club"] = l["club"] or p["club"]
        for key, v in got.items():
            persons[key]["pts"][str(sid)] = v
        stages.append({"id": str(sid), "date": date, "comp": comp, "dist": dist, "cls": cls,
                       "official": str(sid) in OFFICIAL, "optional": comp in OPTIONAL,
                       "on": OPTIONAL.get(comp, True)})
    # merge one child split by a different birth year in different sources
    base_ids = {str(x[1]) for x in STAGES if x[0] == "base"}
    by_name = {}
    for key, p in persons.items():
        by_name.setdefault((key[0], key[2]), []).append(key)
    for keys in by_name.values():
        keys.sort(key=lambda k: -sum(1 for s in persons[k]["pts"] if s in base_ids))
        for k in keys[1:]:
            a, b = persons[keys[0]], persons[k]
            if abs(a["year"] - b["year"]) <= 1 and not (set(a["pts"]) & set(b["pts"])):
                a["pts"].update(b["pts"])
                del persons[k]
    off_ids = {s["id"] for s in stages if s["official"]}
    held = sum(1 for s in stages if s["on"])
    N = math.ceil(12 * held / PLANNED)
    N_off = math.ceil(12 * len(off_ids) / PLANNED)
    tables = {}
    for p in persons.values():
        ranked = sorted(((k, v) for k, v in p["pts"].items() if any(s["id"] == k and s["on"] for s in stages)), key=lambda x: -x[1])
        best = ranked[:N]
        p["total"] = sum(v for _, v in best)
        p["avg"] = round(p["total"] / len(best)) if best else 0
        p["counted"] = [k for k, _ in best]
        p["total_off"] = sum(sorted((v for k, v in p["pts"].items() if k in off_ids), reverse=True)[:N_off])
        tables.setdefault(("М" if p["sex"] == "M" else "Ж") + str(p["rg"]), []).append(p)
    for rows in tables.values():
        rows.sort(key=lambda p: (-p["total_off"], p["name"]))
        for i, p in enumerate(rows):
            p["place_off"] = i + 1 if p["total_off"] > 0 else None
        rows.sort(key=lambda p: (-p["total"], -p["avg"], p["name"]))
        for i, p in enumerate(rows):
            p["place"] = i + 1
    return {"stages": stages, "N": N, "N_off": N_off, "held": held, "planned": PLANNED, "tables": tables}


if __name__ == "__main__":
    r = compute()
    print("held", r["held"], "N", r["N"], "N_off", r["N_off"])
    for g in ("М16", "Ж14"):
        print(g)
        for p in r["tables"][g][:8]:
            print("  ", p["place"], p["place_off"], p["name"], p["year"], p["total"], p["avg"], [p["pts"].get(s["id"], "") for s in r["stages"]])
