"""Build the static site in docs/ from data/<country>/<city>.json.

Run:  python build_pages.py
Only cities that have a computed data file get a page. No page loads anything from another host.
"""
import csv
import html
import io
import json
import os
import shutil
from pathlib import Path

import cities as cities_mod
import compute
from common import DATA_DIR, DOCS_DIR, ROOT, load_cities

SITE_URL = os.environ.get("SITE_URL", "https://gmannerhj.github.io/local-business-gaps/").rstrip("/") + "/"
REPO_URL = os.environ.get("REPO_URL", "https://github.com/gmannerHJ/local-business-gaps")
SITE_NAME = "Local Business Gaps"

CSS = """
:root{--bg:#fff;--fg:#1c1e21;--mut:#5b6470;--line:#d9dde3;--acc:#0b5cad;--bar:#c8d9ec;--card:#f5f7fa}
@media(prefers-color-scheme:dark){:root{--bg:#14171a;--fg:#e6e8eb;--mut:#9aa4b1;--line:#2c333b;--acc:#7db7f0;--bar:#2b4764;--card:#1b2026}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main,header,footer{max-width:860px;margin:0 auto;padding:0 16px}
header{padding-top:14px;padding-bottom:10px;border-bottom:1px solid var(--line);font-size:14px}
header a{margin-right:14px}
a{color:var(--acc)}
h1{font-size:1.6rem;line-height:1.25;margin:22px 0 10px}
h2{font-size:1.15rem;margin:30px 0 8px}
p{margin:10px 0}
.lead{font-size:1.05rem}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:10px 12px}
.stat b{display:block;font-size:1.35rem;font-variant-numeric:tabular-nums}
.stat span{color:var(--mut);font-size:.85rem}
.tw{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.93rem;font-variant-numeric:tabular-nums}
th,td{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left;white-space:normal}
th{color:var(--mut);font-weight:600;font-size:.82rem}
.bar{display:inline-block;height:.7em;background:var(--bar);border-radius:2px;margin-right:6px;vertical-align:baseline}
.note{color:var(--mut);font-size:.9rem}
.box{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:10px 14px;margin:18px 0}
pre{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:12px;overflow-x:auto;font-size:.82rem;line-height:1.4}
footer{margin-top:40px;padding-top:14px;padding-bottom:30px;border-top:1px solid var(--line);color:var(--mut);font-size:.85rem}
"""

e = html.escape


def n(v) -> str:
    return f"{v:,}"


def pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


def label(cat: str) -> str:
    return cat.replace("_", " ").capitalize()


def page(path: Path, title: str, desc: str, body: str, rel: str, canonical: str, extra_head: str = "") -> None:
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(SITE_URL + canonical)}">
<style>{CSS}</style>{extra_head}
</head>
<body>
<header><a href="{rel}index.html"><b>{SITE_NAME}</b></a><a href="{rel}methodology/index.html">Methodology</a><a href="{rel}data/index.html">Data downloads</a></header>
<main>
{body}
</main>
<footer>
<p>Place data: Overture Maps Foundation, <a href="https://overturemaps.org">overturemaps.org</a>, places theme
(sources include Meta, Microsoft, PinMeTo, Krick, RenderSEO, DAC and BrightQuery under CDLA Permissive 2.0;
Foursquare under Apache 2.0, &copy; 2024 Foursquare Labs, Inc.; AllThePlaces under CC0 1.0).
City boundaries and populations: &copy; OpenStreetMap contributors, Overture Maps Foundation, divisions theme, available under the Open Database License.
Details on the <a href="{rel}methodology/index.html">methodology page</a>.</p>
<p>This site is produced by an automated pipeline run by one person with AI agents. The numbers are computed from the
source data and are not checked by hand. <a href="{e(REPO_URL)}">Source code and data</a>.</p>
</footer>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8", newline="\n")


def city_table(rows: list[dict], rel: str, with_country: bool) -> str:
    head = "<th>City</th>" + ("<th>Country</th>" if with_country else "") + \
        "<th>Places</th><th>No website listed</th><th>Share</th>"
    out = [f'<div class="tw"><table><thead><tr>{head}</tr></thead><tbody>']
    for d in rows:
        c = d["counts"]
        cc = d["country"].lower()
        country = f'<td><a href="{rel}{cc}/index.html">{e(d["country_name"])}</a></td>' if with_country else ""
        out.append(
            f'<tr><td><a href="{rel}{cc}/{d["slug"]}/index.html">{e(d["city"])}</a></td>{country}'
            f'<td>{n(c["places"])}</td><td>{n(c["without_website"])}</td>'
            f'<td>{pct(c["share_without_website"])}</td></tr>')
    out.append("</tbody></table></div>")
    return "\n".join(out)


def cat_table(rows: list[dict], first: str) -> str:
    out = [f'<div class="tw"><table><thead><tr><th>{first}</th><th>Places</th><th>With website</th>'
           '<th>No website listed</th><th>Share with no website listed</th></tr></thead><tbody>']
    for r in rows:
        s = r["share_without_website"] or 0
        out.append(
            f'<tr><td>{e(label(r["category"]))}</td><td>{n(r["places"])}</td><td>{n(r["with_website"])}</td>'
            f'<td>{n(r["without_website"])}</td>'
            f'<td><span class="bar" style="width:{s * 60:.0f}px"></span>{pct(r["share_without_website"])}</td></tr>')
    out.append("</tbody></table></div>")
    return "\n".join(out)


def area_sentence(d: dict) -> str:
    b = d["boundary"]
    if b["kind"] == "division_area":
        return (f'Area covered: the {e(d["city"])} boundary polygon from the Overture divisions theme '
                f'({e(b["area_subtype"])} level, {n(b["area_km2"])} km<sup>2</sup>).')
    return (f'Area covered: a circle of {b["radius_km"]} km around the centre point of {e(d["city"])} '
            f'({n(b["area_km2"])} km<sup>2</sup>). The source has no usable boundary polygon for this city, '
            'so the circle includes neighbouring towns and may miss outer districts.')


def build_city(d: dict) -> None:
    c, x = d["counts"], d["excluded"]
    cc = d["country"].lower()
    rel = "../../"
    name = f'{d["city"]}, {d["country_name"]}'
    rel_date = d["overture_release"][:10]
    blank = d.get("blank_website_entries", 0)
    blank_note = f' ({n(blank)} of the places counted here have a list with only blank entries)' if blank else ""
    title = f'Places with no website listed in {name}: counts by category'
    desc = (f'Overture Maps release {d["overture_release"]} lists {n(c["places"])} places in {d["city"]}; '
            f'{n(c["without_website"])} ({pct(c["share_without_website"])}) have no website listed in the data. '
            'Counts by category, free to download.')
    body = f"""<p class="note"><a href="{rel}index.html">All cities</a> &rsaquo; <a href="../index.html">{e(d["country_name"])}</a></p>
<h1>Places with no website listed in {e(name)}</h1>
<p class="lead">The open Overture Maps places data (release {e(d["overture_release"])}) lists <b>{n(c["places"])}</b> businesses and
other places in {e(d["city"])}. <b>{n(c["without_website"])}</b> of them ({pct(c["share_without_website"])}) have no website listed in the data.</p>
<div class="stats">
<div class="stat"><b>{n(c["places"])}</b><span>places counted</span></div>
<div class="stat"><b>{n(c["with_website"])}</b><span>with a website</span></div>
<div class="stat"><b>{n(c["without_website"])}</b><span>with no website listed</span></div>
<div class="stat"><b>{pct(c["share_without_website"])}</b><span>share with no website listed</span></div>
</div>
<p>Of the {n(c["without_website"])} places with no website listed, {n(c["without_website_with_phone"])} have a phone number
in the data and {n(c["without_website_with_social"])} have a social media link.</p>

<h2>Ten largest categories in {e(d["city"])}</h2>
{cat_table(d["top_categories"], "Category")}
<p class="note">Categories are Overture's <code>basic_category</code> labels. {n(d["uncategorised"])} counted places have no category.</p>

<h2>By category group</h2>
{cat_table(d["category_groups"], "Group")}
<p class="note">Groups are the top level of Overture's place taxonomy. Some groups are not businesses
(for example community and government, or geographic entities).</p>

<h2>What "no website listed" means here</h2>
<p>A place is counted as having no website listed when the <code>websites</code> field of its Overture record is missing,
empty or holds only blank entries{blank_note}. That is a statement about the data, not about the business: a missing field does not prove the business has no website,
and some listed websites are social media pages or dead links. Overture's coverage is uneven between countries, cities
and categories, so compare cities with care. The counts include every kind of place Overture lists, not only commercial businesses.</p>
<p>{area_sentence(d)}</p>
<p>Counted: places with an Overture confidence score of at least {d["confidence_min"]} that are not marked permanently closed.
Not counted: {n(x["below_confidence"])} places in the same area with a lower or missing confidence score, and
{n(x["permanently_closed"])} marked permanently closed. The totals depend on this cutoff: a higher or lower threshold
gives different numbers. See the <a href="{rel}methodology/index.html">methodology</a> for the exact query.</p>

<p class="note">Overture release {e(d["overture_release"])} (dated {e(rel_date)}). Computed {e(d["run"]["computed_at"][:10])}.
Download this city's numbers: <a href="{rel}data/{cc}/{d["slug"]}.json">JSON</a>. All cities:
<a href="{rel}data/cities.csv">CSV</a>.</p>"""
    page(DOCS_DIR / cc / d["slug"] / "index.html", title, desc, body, rel, f'{cc}/{d["slug"]}/')


def build_country(cc: str, rows: list[dict]) -> None:
    cname = rows[0]["country_name"]
    places = sum(d["counts"]["places"] for d in rows)
    without = sum(d["counts"]["without_website"] for d in rows)
    title = f'Places with no website listed in {cname}: counts by city'
    desc = (f'{len(rows)} {"city" if len(rows) == 1 else "cities"} in {cname}: how many places the open Overture Maps data lists '
            f'and how many have no website listed. {n(without)} of {n(places)} places have no website listed in the data.')
    body = f"""<p class="note"><a href="../index.html">All cities</a></p>
<h1>Places with no website listed in {e(cname)}, by city</h1>
<p class="lead">Across the {len(rows)} {"city" if len(rows) == 1 else "cities"} computed for {e(cname)}, the open Overture Maps places data lists
<b>{n(places)}</b> businesses and other places. <b>{n(without)}</b> ({pct(without / places if places else None)}) have no website listed in the data.</p>
{city_table(rows, "../", False)}
<p class="note">Cities are selected by population from the Overture divisions theme, at most {cities_mod.MAX_PER_COUNTRY} per country.
A missing website field does not prove a business has no website; see each city page and the
<a href="../methodology/index.html">methodology</a>.</p>"""
    page(DOCS_DIR / cc / "index.html", title, desc, body, "../", f"{cc}/")


def build_index(all_rows: list[dict], listed: int) -> None:
    by_country: dict = {}
    for d in all_rows:
        by_country.setdefault(d["country"], []).append(d)
    releases = sorted({d["overture_release"] for d in all_rows})
    title = "Places with no website listed, by city: open counts from Overture Maps"
    desc = (f'For {len(all_rows)} cities in {len(by_country)} countries: how many places the open Overture Maps data lists '
            'and how many have no website listed in the data, by category. Free JSON and CSV downloads.')
    countries = " &middot; ".join(
        f'<a href="{cc.lower()}/index.html">{e(rows[0]["country_name"])}</a> ({len(rows)})'
        for cc, rows in sorted(by_country.items(), key=lambda kv: kv[1][0]["country_name"]))
    ld = json.dumps({
        "@context": "https://schema.org", "@type": "Dataset", "name": title, "description": desc,
        "url": SITE_URL, "isAccessibleForFree": True,
        "license": ["https://cdla.dev/permissive-2-0/", "https://opendatacommons.org/licenses/odbl/1-0/"],
        "isBasedOn": "https://overturemaps.org",
        "distribution": [
            {"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": SITE_URL + "data/cities.csv"},
            {"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": SITE_URL + "data/cities.json"}],
    })
    body = f"""<h1>Places with no website listed, by city</h1>
<p class="lead">For each city: how many businesses and other places the open Overture Maps data lists, and how many of them
have no website listed in the data, split by category. Counts only, free to use and download.</p>
<p>{len(all_rows)} cities in {len(by_country)} countries are computed so far, out of {listed} on the city list.
Overture release{"s" if len(releases) > 1 else ""}: {e(", ".join(releases))}.</p>
<p class="note">A missing website field does not prove a business has no website, and Overture's coverage differs a lot
between countries. Read the <a href="methodology/index.html">methodology</a> before comparing cities.</p>
<h2>Countries</h2>
<p>{countries}</p>
<h2>Cities</h2>
{city_table(sorted(all_rows, key=lambda d: (d["country_name"], d["city"])), "", True)}"""
    page(DOCS_DIR / "index.html", title, desc, body, "", "",
         f'\n<script type="application/ld+json">{ld}</script>')


def build_methodology(listed: int) -> None:
    title = "Methodology: how the counts are computed"
    desc = ("Source, licence, city selection rule, confidence threshold and the exact DuckDB query behind the "
            "per-city counts of places with no website listed.")
    rule = e(cities_mod.__doc__.split("Selection rule", 1)[1])
    body = f"""<h1>Methodology</h1>
<p>Every number on this site is computed by code from the public Overture Maps release. Nothing is entered by hand.
The pipeline is run by one person with AI agents; the code is in the <a href="{e(REPO_URL)}">repository</a>.
This site is not affiliated with or endorsed by the Overture Maps Foundation or its data providers.</p>

<h2>Source</h2>
<p>Overture Maps Foundation, <a href="https://overturemaps.org">overturemaps.org</a>: the <b>places</b> theme for the
counts and the <b>divisions</b> theme for city populations and boundaries. The data is GeoParquet on public cloud storage.
It is queried in place with DuckDB over HTTP range requests, filtered by bounding box, so only the parts of the files that
cover a city are read. Each page states the Overture release it was computed from.</p>

<h2>Cities</h2>
<p>The city list ({listed} cities) is generated from the Overture divisions theme by this rule:</p>
<pre>Selection rule{rule}</pre>
<p>Limits of this rule: population figures and boundaries are whatever the divisions theme holds, so some cities are
represented by a wider administrative area and some well-known cities are missing because the source gives them no
population, no class or no Wikidata id. Boundary polygons are simplified to about 20 m.</p>

<h2>What is counted</h2>
<p>A place is counted when it lies inside the city boundary, has <code>confidence &gt;= {compute.CONFIDENCE_MIN}</code>
and is not marked <code>permanently_closed</code>.</p>
<p>Overture documents <code>confidence</code> as "a value between 0 and 1 representing the likelihood that the place exists"
and gives no recommended cutoff. {compute.CONFIDENCE_MIN} keeps the records rated more likely to exist than not. Overture also
notes that the score is not calibrated to be strictly comparable across data providers, so the threshold does not behave the same way
everywhere. Each city page reports how many places fell below the threshold. The totals move with the cutoff, so read
every count as "at confidence {compute.CONFIDENCE_MIN} or higher".</p>
<p>"No website listed" means the <code>websites</code> field of the record is missing, empty or holds only blank
entries. Some records carry a list whose only entry is an empty string; those are counted as no website listed, and the
same rule is applied to phone numbers and social links. It does not prove the business has no
website. Some listed websites are social media pages or no longer work. Categories are Overture's
<code>basic_category</code> labels; groups are the first level of <code>taxonomy.hierarchy</code>. The places theme
includes non-commercial places such as parks, schools and government offices; the group table on each city page shows them.</p>

<h2>The query</h2>
<p>Per city, the rows inside the boundary are selected into a temporary in-memory table with only the columns below.
No names, addresses, phone numbers or coordinates are selected, and no per-place rows are written anywhere.</p>
<pre>{e(compute.CITY_QUERY.strip())}</pre>
<p>Totals:</p>
<pre>{e(compute.TOTALS_QUERY.strip())}</pre>
<p>Category and group splits (<code>col</code> is <code>basic_category</code> with <code>LIMIT {compute.TOP_CATEGORIES}</code>, or <code>category_group</code>):</p>
<pre>{e(compute.SPLIT_QUERY.format(col="{col}", limit="{limit}").strip())}</pre>

<h2>Licence and attribution</h2>
<p>Places theme sources and their licences, as listed at
<a href="https://docs.overturemaps.org/attribution/">docs.overturemaps.org/attribution</a>: Meta, Microsoft, PinMeTo, Krick,
RenderSEO, DAC and BrightQuery under CDLA Permissive 2.0; Foursquare under Apache 2.0 (&copy; 2024 Foursquare Labs, Inc.,
transformed to the Overture schema); AllThePlaces under CC0 1.0.</p>
<p>Divisions theme: Open Database License (ODbL). &copy; OpenStreetMap contributors, Overture Maps Foundation. Other
sources in that theme: geoBoundaries, Esri Community Maps contributors and Land Information New Zealand, under CC BY 4.0.
The city list and boundary file in the repository, and the <code>population</code>, <code>area_km2</code> and
<code>boundary</code> fields in the downloads, are derived from the divisions theme and are offered under the
<a href="https://opendatacommons.org/licenses/odbl/1-0/">Open Database License 1.0</a>.</p>
<p>The count fields published here are offered under <a href="https://cdla.dev/permissive-2-0/">CDLA Permissive 2.0</a>.
Please credit Overture Maps Foundation when you reuse them.</p>

<h2>Updates</h2>
<p>A scheduled job checks once a month for a new Overture release and, when there is one, recomputes the cities and
rebuilds these pages.</p>"""
    page(DOCS_DIR / "methodology" / "index.html", title, desc, body, "../", "methodology/")


SUMMARY_COLS = ["country", "country_name", "city", "slug", "population", "boundary_kind", "area_km2", "places",
                "with_website", "without_website", "share_without_website", "without_website_with_phone",
                "without_website_with_social", "below_confidence", "permanently_closed", "overture_release",
                "computed_at"]


def summary_row(d: dict) -> dict:
    return {
        "country": d["country"], "country_name": d["country_name"], "city": d["city"], "slug": d["slug"],
        "population": d["population"], "boundary_kind": d["boundary"]["kind"],
        "area_km2": d["boundary"]["area_km2"], **d["counts"], **d["excluded"],
        "overture_release": d["overture_release"], "computed_at": d["run"]["computed_at"],
    }


def write_csv(path: Path, cols: list[str], rows: list[dict]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8", newline="\n")


def build_data(all_rows: list[dict]) -> None:
    out = DOCS_DIR / "data"
    out.mkdir(parents=True, exist_ok=True)
    summary = [summary_row(d) for d in all_rows]
    write_csv(out / "cities.csv", SUMMARY_COLS, summary)
    (out / "cities.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n",
                                     encoding="utf-8", newline="\n")
    cats = []
    for d in all_rows:
        for level, key in (("basic_category_top10", "top_categories"), ("category_group", "category_groups")):
            for r in d[key]:
                cats.append({"country": d["country"], "city": d["city"], "slug": d["slug"], "level": level, **r})
    write_csv(out / "categories.csv", ["country", "city", "slug", "level", "category", "places", "with_website",
                                       "without_website", "share_without_website"], cats)
    for d in all_rows:
        dst = out / d["country"].lower() / f'{d["slug"]}.json'
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(DATA_DIR / d["country"].lower() / f'{d["slug"]}.json', dst)
    body = f"""<h1>Data downloads</h1>
<p>All files are generated by the pipeline from the Overture Maps release named in each row. They contain counts only.</p>
<ul>
<li><a href="cities.csv">cities.csv</a>: one row per city ({len(all_rows)} rows): population, area, places, with and without a website listed, share.</li>
<li><a href="cities.json">cities.json</a>: the same as JSON.</li>
<li><a href="categories.csv">categories.csv</a>: per city, the ten largest categories and every category group.</li>
<li>Per city: <code>data/&lt;country&gt;/&lt;city&gt;.json</code>, linked from each city page.</li>
</ul>
<p>Licences (<a href="LICENSE.txt">LICENSE.txt</a>): the count fields are offered under
<a href="https://cdla.dev/permissive-2-0/">CDLA Permissive 2.0</a>; please credit Overture Maps Foundation, overturemaps.org.
The <code>population</code>, <code>area_km2</code>, <code>boundary_kind</code> and <code>boundary</code> fields come from the
Overture divisions theme (&copy; OpenStreetMap contributors, Overture Maps Foundation) and are offered under the
<a href="https://opendatacommons.org/licenses/odbl/1-0/">Open Database License 1.0</a>. See the
<a href="../methodology/index.html">methodology</a> for sources, limits and attribution.</p>"""
    shutil.copyfile(ROOT / "LICENSE-DATA", out / "LICENSE.txt")
    page(out / "index.html", "Data downloads: places with no website listed, by city (JSON, CSV)",
         "Download per-city counts of places with and without a website listed, computed from open Overture Maps data, as CSV or JSON.",
         body, "../", "data/")


def main() -> None:
    listed = load_cities()
    all_rows = []
    for c in listed:
        f = DATA_DIR / c["country"].lower() / f'{c["slug"]}.json'
        if f.exists():
            all_rows.append(json.loads(f.read_text(encoding="utf-8")))
    if not all_rows:
        raise SystemExit("no data files; run compute.py first")

    if DOCS_DIR.exists():
        shutil.rmtree(DOCS_DIR)
    DOCS_DIR.mkdir()
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")

    urls = ["", "methodology/", "data/"]
    by_country: dict = {}
    for d in all_rows:
        by_country.setdefault(d["country"].lower(), []).append(d)
        build_city(d)
        urls.append(f'{d["country"].lower()}/{d["slug"]}/')
    for cc, rows in by_country.items():
        build_country(cc, sorted(rows, key=lambda d: -d["counts"]["places"]))
        urls.append(f"{cc}/")
    build_index(all_rows, len(listed))
    build_methodology(len(listed))
    build_data(all_rows)

    lastmod = max(d["run"]["computed_at"] for d in all_rows)[:10]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"<url><loc>{e(SITE_URL + u)}</loc><lastmod>{lastmod}</lastmod></url>" for u in urls]
    sm.append("</urlset>")
    (DOCS_DIR / "sitemap.xml").write_text("\n".join(sm) + "\n", encoding="utf-8", newline="\n")
    (DOCS_DIR / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}sitemap.xml\n",
                                         encoding="utf-8", newline="\n")
    print(f"built {len(all_rows)} city pages, {len(by_country)} country pages -> {DOCS_DIR}")


if __name__ == "__main__":
    main()
