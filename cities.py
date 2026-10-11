"""Build the city list from the Overture Maps divisions theme.

Run:  python cities.py [--release 2026-09-23.1]

Writes cities/cities.json (the list) and cities/boundaries.parquet (one polygon per city).
Other scripts import load_cities() from common.py; nothing here is typed in by hand.

Selection rule (all computed from Overture divisions, licence ODbL):
  1. Candidates: divisions with subtype 'locality', class 'city', a Wikidata id and
     population >= MIN_POPULATION.
  2. Boundary: the locality's own division_area polygon (land); if there is none, the land
     polygon of another division in the same country with the same Wikidata id (many large
     cities are modelled as a county or region). A polygon is rejected when it clearly does
     not correspond to the population figure: bounding box wider than MAX_SPAN_DEG, or
     population / bounding-box area outside [MIN_DENSITY, MAX_DENSITY] people per km2.
  3. If no polygon is accepted, the boundary is a circle around the division's point:
     10 km below 1 million people, 15 km from 1 to 5 million, 20 km above.
  4. Cities are taken in descending population. A city is skipped when its point lies in the
     bounding box of a larger selected city of the same country (boroughs, duplicates), or
     when its country already has MAX_PER_COUNTRY cities. Stop at TARGET cities.
"""
import argparse
import json
import math
import time

from common import BOUNDARIES, CITIES_JSON, connect, latest_release, slugify, theme_path

MIN_POPULATION = 100_000
MAX_PER_COUNTRY = 5
TARGET = 200
MAX_SPAN_DEG = 1.5
MIN_DENSITY = 50
MAX_DENSITY = 30_000
SIMPLIFY_DEG = 0.0002  # about 20 m; keeps the boundary file small


def radius_km(population: int) -> int:
    if population < 1_000_000:
        return 10
    if population <= 5_000_000:
        return 15
    return 20


def circle_wkt(lon: float, lat: float, r_km: float, n: int = 72) -> str:
    dlat = r_km / 110.574
    dlon = r_km / (111.320 * math.cos(math.radians(lat)))
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        pts.append((lon + dlon * math.cos(a), lat + dlat * math.sin(a)))
    pts.append(pts[0])
    return "POLYGON((" + ",".join(f"{x:.6f} {y:.6f}" for x, y in pts) + "))"


def bbox_km2(b: dict) -> float:
    lat = (b["ymin"] + b["ymax"]) / 2
    return (b["xmax"] - b["xmin"]) * 111.320 * math.cos(math.radians(lat)) * (b["ymax"] - b["ymin"]) * 110.574


def polygon_ok(pop: int, b: dict) -> bool:
    if b["xmax"] - b["xmin"] > MAX_SPAN_DEG or b["ymax"] - b["ymin"] > MAX_SPAN_DEG:
        return False
    km2 = bbox_km2(b)
    return km2 > 0 and MIN_DENSITY <= pop / km2 <= MAX_DENSITY


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", default=None)
    args = ap.parse_args()
    release = args.release or latest_release()
    con = connect()
    div = theme_path(release, "divisions", "division")
    area = theme_path(release, "divisions", "division_area")
    t0 = time.time()

    # One pass over the division file: every division that has a Wikidata id, plus countries.
    con.execute(f"""
        CREATE TABLE div AS
        SELECT id, country, subtype, class, names."primary" AS name, names.common['en'] AS name_en,
               population, wikidata, ST_X(geometry) AS lon, ST_Y(geometry) AS lat
        FROM read_parquet('{div}')
        WHERE wikidata IS NOT NULL OR subtype = 'country'
    """)
    con.execute(f"""
        CREATE TABLE loc AS SELECT * FROM div
        WHERE subtype = 'locality' AND class = 'city' AND wikidata IS NOT NULL
          AND population >= {MIN_POPULATION}
    """)
    con.execute("""
        CREATE TABLE sib AS SELECT d.id, d.wikidata, d.country, d.subtype FROM div d
        WHERE d.subtype NOT IN ('locality', 'country')
          AND EXISTS (SELECT 1 FROM loc l WHERE l.wikidata = d.wikidata AND l.country = d.country)
    """)
    print(f"divisions read in {time.time() - t0:.0f}s; candidates:",
          con.execute("SELECT count(*) FROM loc").fetchone()[0], flush=True)

    # One pass over the small columns of division_area for those divisions (no geometry yet).
    t1 = time.time()
    con.execute(f"""
        CREATE TABLE ar AS
        SELECT id AS area_id, division_id, subtype, bbox
        FROM read_parquet('{area}')
        WHERE is_land AND division_id IN (SELECT id FROM loc UNION SELECT id FROM sib)
    """)
    print(f"division_area ids read in {time.time() - t1:.0f}s", flush=True)

    countries = dict(con.execute(
        "SELECT country, coalesce(name_en, name) FROM div WHERE subtype = 'country'").fetchall())
    own = {r[0]: (r[1], r[2], r[3]) for r in con.execute(
        "SELECT division_id, area_id, subtype, bbox FROM ar WHERE division_id IN (SELECT id FROM loc)").fetchall()}
    sib_rows = con.execute("""
        SELECT s.wikidata, s.country, ar.area_id, ar.subtype, ar.bbox
        FROM sib s JOIN ar ON ar.division_id = s.id""").fetchall()
    by_wd: dict = {}
    for wd, cc, aid, st, b in sib_rows:
        by_wd.setdefault((wd, cc), []).append((aid, st, b))

    rows = con.execute("""
        SELECT id, country, name, name_en, population, wikidata, lon, lat FROM loc
        ORDER BY population DESC, (name_en IS NULL), id""").fetchall()

    chosen, per_country, seen_wd, slugs = [], {}, set(), set()
    for id_, cc, name, name_en, pop, wd, lon, lat in rows:
        if len(chosen) >= TARGET:
            break
        if cc not in countries or wd in seen_wd or per_country.get(cc, 0) >= MAX_PER_COUNTRY:
            continue
        display = name_en or name
        slug = slugify(display)
        if not slug or (cc, slug) in slugs:
            continue
        if any(c["country"] == cc and c["bbox"][0] <= lon <= c["bbox"][2] and c["bbox"][1] <= lat <= c["bbox"][3]
               for c in chosen):
            continue
        cands = []
        if id_ in own:
            cands.append(own[id_])
        cands += sorted(by_wd.get((wd, cc), []), key=lambda t: bbox_km2(t[2]))
        pick = next((c for c in cands if polygon_ok(pop, c[2])), None)
        if pick:
            b = pick[2]
            city_bbox = [b["xmin"], b["ymin"], b["xmax"], b["ymax"]]
            boundary = {"kind": "division_area", "area_id": pick[0], "area_subtype": pick[1]}
        else:
            r = radius_km(pop)
            dlat = r / 110.574
            dlon = r / (111.320 * math.cos(math.radians(lat)))
            city_bbox = [lon - dlon, lat - dlat, lon + dlon, lat + dlat]
            boundary = {"kind": "radius", "radius_km": r}
        chosen.append({
            "slug": slug, "name": display, "local_name": name, "country": cc,
            "country_name": countries[cc], "population": pop, "division_id": id_, "wikidata": wd,
            "lon": round(lon, 6), "lat": round(lat, 6),
            "bbox": [round(v, 6) for v in city_bbox], "boundary": boundary,
        })
        per_country[cc] = per_country.get(cc, 0) + 1
        seen_wd.add(wd)
        slugs.add((cc, slug))

    # Fetch only the selected polygons. Each area's exact bbox.xmin lets the reader skip
    # every row group whose statistics do not contain it.
    t2 = time.time()
    con.execute("CREATE TABLE b (slug VARCHAR, country VARCHAR, geom GEOMETRY)")
    want = [c for c in chosen if c["boundary"]["kind"] == "division_area"]
    xmin_of = dict(con.execute("SELECT area_id, bbox.xmin FROM ar").fetchall())
    for c in want:
        aid = c["boundary"]["area_id"]
        con.execute(f"""
            INSERT INTO b
            SELECT ?, ?, ST_SimplifyPreserveTopology(geometry, {SIMPLIFY_DEG})
            FROM read_parquet('{area}') WHERE bbox.xmin = ? AND id = ?
        """, [c["slug"], c["country"], xmin_of[aid], aid])
    for c in chosen:
        if c["boundary"]["kind"] == "radius":
            con.execute("INSERT INTO b VALUES (?, ?, ST_GeomFromText(?))",
                        [c["slug"], c["country"], circle_wkt(c["lon"], c["lat"], c["boundary"]["radius_km"])])
    print(f"{len(want)} polygons fetched in {time.time() - t2:.0f}s", flush=True)

    areas = {(s, cc): a for s, cc, a in con.execute(
        "SELECT slug, country, ST_Area_Spheroid(ST_FlipCoordinates(geom)) / 1e6 FROM b").fetchall()}
    for c in chosen:
        c["boundary"]["area_km2"] = round(areas[(c["slug"], c["country"])], 1)
    missing = [c["slug"] for c in chosen if (c["slug"], c["country"]) not in areas]
    assert not missing, missing

    CITIES_JSON.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY (SELECT slug, country, ST_AsWKB(geom) AS wkb FROM b ORDER BY country, slug) "
                f"TO '{BOUNDARIES.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
    out = {
        "source": "Overture Maps divisions theme",
        "release": release,
        "licence": "ODbL 1.0",
        "rule": {"min_population": MIN_POPULATION, "max_per_country": MAX_PER_COUNTRY, "target": TARGET,
                 "max_span_deg": MAX_SPAN_DEG, "density_range_per_km2": [MIN_DENSITY, MAX_DENSITY],
                 "simplify_deg": SIMPLIFY_DEG},
        "cities": chosen,
    }
    CITIES_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(chosen)} cities in {len(per_country)} countries; total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
