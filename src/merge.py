"""Official table (orient.by) for published stages + own calculation for later stages."""
import datetime, html, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import calc

def norm(s):
    return calc.norm_name(s)

def parse_official(path):
    t = open(path, encoding="utf-8", errors="ignore").read()
    out, dates = {}, None
    for m in re.finditer(r"<table.*?</table>", t, re.S):
        rows = re.findall(r"<tr.*?</tr>", m.group(0), re.S)
        cells = [[html.unescape(re.sub("<[^>]+>", "", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)] for r in rows]
        if not cells or "Прозвішча, Імя" not in " ".join(cells[0]):
            continue
        hdr = cells[0]
        g = re.findall(r"(?:<h\d[^>]*>|>)\s*([МЖ]1[2468])\s*<", t[:m.start()])[-1]
        di = [i for i, h in enumerate(hdr) if re.match(r"^\d\d\.\d\d$", h)]
        dates = [hdr[i] for i in di]
        out[g] = []
        for r in cells[1:]:
            if len(r) < len(hdr):
                continue
            pts = {hdr[i]: int(r[i]) for i in di if r[i].strip().lstrip("-").isdigit()}
            out[g].append({"n": r[1], "y": int(r[2]), "pts": pts, "place": int(r[-1]) if r[-1].isdigit() else None})
    return out, dates

RAT = os.path.join(HERE, "cache", "official.html")
os.makedirs(os.path.dirname(RAT), exist_ok=True)
open(RAT, "wb").write(calc.fetch("https://orient.by/rating/youth/121874-2026/"))
official, odates = parse_official(RAT)
R = calc.compute()
stages = R["stages"]
date2id = {}
for s in stages:
    d = s["date"][8:10] + "." + s["date"][5:7]
    if d in odates and s["official"]:
        date2id[d] = s["id"]
assert len(date2id) == len(odates), (date2id, odates)
new_ids = {s["id"] for s in stages if not s["official"]}

rows = {g: [{"n": p["n"], "y": p["y"], "po": p["place"], "s": {date2id[d]: v for d, v in p["pts"].items()}} for p in ps]
        for g, ps in official.items()}
# One person entered twice in the official table: (group, name kept, year, other spelling). Rows are joined
# only if they never share a stage.
SAME_PERSON = [("Ж14", "Рябикова Варвара", 2012, "Рябикова Варя")]
for g, keep, y, other in SAME_PERSON:
    a = next((r for r in rows.get(g, []) if r["n"] == keep and r["y"] == y), None)
    b = next((r for r in rows.get(g, []) if r["n"] == other and r["y"] == y), None)
    if a and b and not set(a["s"]) & set(b["s"]):
        a["s"].update(b["s"]); a["po"] = min(a["po"], b["po"]); rows[g].remove(b)
index = {}
for g, ps in rows.items():
    for r in ps:
        index.setdefault(norm(r["n"]), []).append((g, r))
matched = added = 0
for g, ps in R["tables"].items():
    for p in ps:
        newpts = {k: v for k, v in p["pts"].items() if k in new_ids}
        if not newpts:
            continue
        cands = index.get(norm(p["name"]), [])
        hit = next((r for gg, r in cands if gg == g and abs(r["y"] - p["year"]) <= 1), None) \
            or next((r for gg, r in cands if abs(r["y"] - p["year"]) <= 1), None)
        if not hit:  # same surname and year, first name written differently (Влад / Владислав)
            fam, first = norm(p["name"]).split(" ", 1) if " " in norm(p["name"]) else (norm(p["name"]), "")
            hit = next((r for r in rows.get(g, []) if r["po"] is not None and r["y"] == p["year"]
                        and norm(r["n"]).split(" ")[0] == fam and norm(r["n"]).split(" ", 1)[-1][:4] == first[:4]), None)
        if hit:
            hit["s"].update(newpts); matched += 1
        else:
            rows.setdefault(g, []).append({"n": p["name"], "y": p["year"], "po": None, "s": newpts}); added += 1
order = ["Ж12", "Ж14", "Ж16", "Ж18", "М12", "М14", "М16", "М18"]
out = {"updated": datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=3))).strftime("%Y-%m-%d %H:%M"),
       "planned": R["planned"], "stages": [s for s in stages if s["official"] or s["id"] in new_ids],
       "groups": {g: rows.get(g, []) for g in order}}
data = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
site = os.path.join(HERE, "..", "site")
os.makedirs(site, exist_ok=True)
open(os.path.join(site, "rating.json"), "w", encoding="utf-8").write(data)
page = open(os.path.join(HERE, "template.html"), encoding="utf-8").read().replace("__DATA__", data)
open(os.path.join(site, "index.html"), "w", encoding="utf-8").write(
    '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">' + page.replace('<meta name="claude:viewport-fit-sides" content="cover">', '').replace('<div class="wrap">', '</head><body><div class="wrap">', 1) + '</body></html>')
print("official rows", sum(len(v) for v in official.values()), "matched new results", matched, "new rows", added)
