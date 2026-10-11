"""Count Overture places per city, with and without a website.

Run:  python compute.py --only fr/paris,us/chicago
      python compute.py --batch 0/4          (every city whose index % 4 == 0)
      python compute.py --all

Writes data/<country>/<city-slug>.json. Only counts are written. Rows about individual
places are held in memory for the duration of one city's query and are never stored.
"""
import argparse
import datetime
import json
import re
import time

from common import BOUNDARIES, DATA_DIR, connect, latest_release, load_cities, theme_path

# Overture describes `confidence` as "a value between 0 and 1 representing the likelihood
# that the place exists" and gives no recommended cutoff ("filter out data below whatever
# threshold suits your use case"). 0.5 keeps the records Overture rates as more likely to
# exist than not. Counts below the threshold are reported separately, not dropped silently.
CONFIDENCE_MIN = 0.5
TOP_CATEGORIES = 10

# A contact field counts as present only when it holds at least one non-blank entry.
# Some records carry a list whose only entry is an empty string (seen in release
# 2026-09-23.1 for websites and phones), and a plain length test would count those as
# having a website. array_to_string skips NULL entries, so the test in the query is true
# only when some entry has visible characters.

# {places} is the release path, the four bbox numbers and the boundary WKB are parameters.
CITY_QUERY = """
CREATE OR REPLACE TEMP TABLE city_places AS
SELECT
    confidence,
    operating_status,
    basic_category,
    taxonomy.hierarchy[1]              AS category_group,
    trim(coalesce(array_to_string(websites, ''), '')) <> '' AS has_website,
    trim(coalesce(array_to_string(phones, ''), ''))   <> '' AS has_phone,
    trim(coalesce(array_to_string(socials, ''), ''))  <> '' AS has_social,
    coalesce(len(websites), 0) > 0                          AS website_list_present
FROM read_parquet('{places}')
WHERE bbox.xmin BETWEEN $xmin AND $xmax
  AND bbox.ymin BETWEEN $ymin AND $ymax
  AND ST_Contains(ST_GeomFromWKB($boundary), ST_Point(ST_X(geometry), ST_Y(geometry)))
"""

KEPT = f"confidence >= {CONFIDENCE_MIN} AND operating_status IS DISTINCT FROM 'permanently_closed'"

TOTALS_QUERY = f"""
SELECT
    count(*) FILTER (WHERE {KEPT})                                        AS places,
    count(*) FILTER (WHERE {KEPT} AND has_website)                        AS with_website,
    count(*) FILTER (WHERE {KEPT} AND NOT has_website)                    AS without_website,
    count(*) FILTER (WHERE {KEPT} AND NOT has_website AND has_phone)      AS without_website_with_phone,
    count(*) FILTER (WHERE {KEPT} AND NOT has_website AND has_social)     AS without_website_with_social,
    count(*) FILTER (WHERE {KEPT} AND NOT has_website AND website_list_present) AS blank_website_entries,
    count(*) FILTER (WHERE confidence < {CONFIDENCE_MIN} OR confidence IS NULL) AS below_confidence,
    count(*) FILTER (WHERE confidence >= {CONFIDENCE_MIN}
                     AND operating_status = 'permanently_closed')        AS permanently_closed,
    count(*)                                                              AS in_boundary_all
FROM city_places
"""

SPLIT_QUERY = f"""
SELECT {{col}} AS category,
       count(*)                                AS places,
       count(*) FILTER (WHERE has_website)     AS with_website,
       count(*) FILTER (WHERE NOT has_website) AS without_website
FROM city_places
WHERE {KEPT} AND {{col}} IS NOT NULL
GROUP BY 1 ORDER BY places DESC, category {{limit}}
"""


def share(n: int, d: int):
    return round(n / d, 4) if d else None


def http_stats(plan_text: str) -> dict:
    """Bytes received and request counts from DuckDB's EXPLAIN ANALYZE output."""
    out = {}
    m = re.search(r"in:\s*([\d.]+)\s*(bytes|KiB|MiB|GiB)", plan_text)
    if m:
        mult = {"bytes": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}[m.group(2)]
        out["bytes_read"] = int(float(m.group(1)) * mult)
    for key, label in (("get_requests", "GET"), ("head_requests", "HEAD")):
        m = re.search(rf"#{label}:\s*(\d+)", plan_text)
        if m:
            out[key] = int(m.group(1))
    return out


def compute_city(con, city: dict, release: str, boundary_wkb: bytes) -> dict:
    places = theme_path(release, "places", "place")
    xmin, ymin, xmax, ymax = city["bbox"]
    params = {"xmin": xmin, "xmax": xmax, "ymin": ymin, "ymax": ymax, "boundary": boundary_wkb}
    t0 = time.time()
    plan = con.execute("EXPLAIN ANALYZE " + CITY_QUERY.format(places=places), params).fetchall()
    seconds = time.time() - t0
    stats = http_stats("\n".join(str(c) for row in plan for c in row))

    cols = [d[0] for d in con.execute(TOTALS_QUERY).description]
    tot = dict(zip(cols, con.execute(TOTALS_QUERY).fetchone()))

    def split(col: str, limit: str) -> list[dict]:
        rows = con.execute(SPLIT_QUERY.format(col=col, limit=limit)).fetchall()
        return [{"category": c, "places": n, "with_website": w, "without_website": wo,
                 "share_without_website": share(wo, n)} for c, n, w, wo in rows]

    uncategorised = con.execute(
        f"SELECT count(*) FROM city_places WHERE {KEPT} AND basic_category IS NULL").fetchone()[0]
    result = {
        "city": city["name"],
        "local_name": city["local_name"],
        "slug": city["slug"],
        "country": city["country"],
        "country_name": city["country_name"],
        "population": city["population"],
        "wikidata": city["wikidata"],
        "division_id": city["division_id"],
        "boundary": city["boundary"],
        "bbox": city["bbox"],
        "overture_release": release,
        "confidence_min": CONFIDENCE_MIN,
        "counts": {
            "places": tot["places"],
            "with_website": tot["with_website"],
            "without_website": tot["without_website"],
            "share_without_website": share(tot["without_website"], tot["places"]),
            "without_website_with_phone": tot["without_website_with_phone"],
            "without_website_with_social": tot["without_website_with_social"],
        },
        "excluded": {
            "below_confidence": tot["below_confidence"],
            "permanently_closed": tot["permanently_closed"],
        },
        "uncategorised": uncategorised,
        # Places counted as "no website listed" whose websites list exists but holds only blank entries.
        "blank_website_entries": tot["blank_website_entries"],
        "top_categories": split("basic_category", f"LIMIT {TOP_CATEGORIES}"),
        "category_groups": split("category_group", ""),
        "run": {
            "computed_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "query_seconds": round(seconds, 1),
            **stats,
        },
    }
    con.execute("DROP TABLE city_places")
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--only", help="comma-separated country/slug, e.g. fr/paris,us/chicago")
    g.add_argument("--batch", help="k/n: cities whose position in the list satisfies index %% n == k")
    g.add_argument("--all", action="store_true")
    ap.add_argument("--release", default=None)
    args = ap.parse_args()

    cities = load_cities()
    if args.only:
        want = {s.strip().lower() for s in args.only.split(",")}
        key = lambda c: f"{c['country'].lower()}/{c['slug']}"
        unknown = want - {key(c) for c in cities}
        if unknown:
            raise SystemExit(f"not in cities.json: {sorted(unknown)}")
        cities = [c for c in cities if key(c) in want]
    elif args.batch:
        k, n = (int(x) for x in args.batch.split("/"))
        cities = [c for i, c in enumerate(cities) if i % n == k]

    release = args.release or latest_release()
    con = connect()
    boundaries = {(s, cc): bytes(w) for s, cc, w in con.execute(
        f"SELECT slug, country, wkb FROM read_parquet('{BOUNDARIES.as_posix()}')").fetchall()}

    t_all = time.time()
    total_bytes = 0
    for i, city in enumerate(cities, 1):
        res = compute_city(con, city, release, boundaries[(city["slug"], city["country"])])
        if res["counts"]["with_website"] + res["counts"]["without_website"] != res["counts"]["places"]:
            raise SystemExit(f"count mismatch for {city['country']}/{city['slug']}")
        out = DATA_DIR / city["country"].lower() / f"{city['slug']}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        c, r = res["counts"], res["run"]
        total_bytes += r.get("bytes_read", 0)
        print(f"[{i}/{len(cities)}] {city['country']} {city['slug']}: places={c['places']} "
              f"without_website={c['without_website']} ({c['share_without_website']}) "
              f"{r['query_seconds']}s {r.get('bytes_read', 0) / 1e6:.1f}MB "
              f"{r.get('get_requests', '?')} GETs", flush=True)
    print(f"done: {len(cities)} cities, {time.time() - t_all:.0f}s, {total_bytes / 1e6:.0f}MB read, release {release}")


if __name__ == "__main__":
    main()
