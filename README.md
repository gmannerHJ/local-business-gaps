# Local Business Gaps

Per-city counts of how many businesses and other places the open Overture Maps data lists, and how many
of them have no website in the data, split by category. Counts only: no names, phone numbers or addresses.

This dataset and its pages are produced by an automated pipeline run by one person with AI agents.
The numbers are computed from the source and are not checked by hand.

## What is in the repository

| Path | Content |
|---|---|
| `cities.py` | Builds the city list from the Overture divisions theme (population, boundary). |
| `cities/cities.json`, `cities/boundaries.parquet` | The generated list (200 cities, 92 countries) and one boundary polygon per city. |
| `compute.py` | Counts places per city and writes `data/<country>/<city>.json`. |
| `build_pages.py` | Builds the static site in `docs/` (city, country, index, methodology, downloads, sitemap). |
| `.github/workflows/refresh.yml` | Monthly check for a new Overture release; recomputes this dataset when there is one. |

## Method

1. **Source.** Overture Maps Foundation public release (GeoParquet on public cloud storage). The files are
   queried in place with DuckDB over HTTP range requests and a bounding-box filter, so only the row groups
   covering a city are read. Nothing is downloaded in bulk. The latest release id is read from
   `https://stac.overturemaps.org/catalog.json`.
2. **Cities.** Localities of class `city` with a Wikidata id and at least 100,000 people in the divisions
   theme, taken in descending population, at most 5 per country, 200 in total. The boundary is the
   division's land polygon when the source has a usable one, otherwise a circle of 10, 15 or 20 km around
   the centre point, depending on population. The full rule is in the docstring of `cities.py`.
3. **Counts.** A place is counted when it lies inside the boundary, has `confidence >= 0.5` and is not marked
   `permanently_closed`. "No website listed" means the record's `websites` field is missing, empty or holds
   only blank entries (some records carry a list whose only entry is an empty string). The split uses
   Overture's `basic_category` (ten largest) and the first level of `taxonomy.hierarchy`.
4. **Confidence threshold.** Overture documents `confidence` as "a value between 0 and 1 representing the
   likelihood that the place exists" and recommends no cutoff. 0.5 keeps records rated more likely to exist
   than not. The number of places below the threshold is published for every city.

The exact SQL is in `compute.py` and is printed on the site's methodology page.

## Limits

- A missing `websites` field does not prove a business has no website. Some listed websites are social
  media pages or dead links.
- Overture's coverage is uneven between countries, cities and categories. Low counts often reflect thin
  source data, not few businesses. Compare cities with care.
- The places theme includes non-commercial places (parks, schools, government offices).
- `confidence` is not calibrated to be comparable across data providers.
- City populations and boundaries are whatever the divisions theme holds. Some cities are represented by a
  wider administrative area, 77 of the 200 use a circle because the source has no usable polygon, and some
  well-known cities are missing because the source gives them no population, class or Wikidata id.
- Boundary polygons are simplified to about 20 m.

## Run it

```
pip install -r requirements.txt          # duckdb 1.5.6
python cities.py                         # optional: regenerate the city list (about 10 minutes)
python compute.py --only fr/paris,us/chicago
python compute.py --batch 0/4            # a quarter of the list
python build_pages.py                    # writes docs/
```

No account or key is needed. Requests carry a descriptive User-Agent.

## Licence and attribution

Place data: Overture Maps Foundation, [overturemaps.org](https://overturemaps.org), places theme. Sources and
licences as listed at <https://docs.overturemaps.org/attribution/>:

- Meta, Microsoft, PinMeTo, Krick, RenderSEO, DAC, BrightQuery: CDLA Permissive 2.0
- Foursquare: Apache 2.0. Copyright 2024 Foursquare Labs, Inc. All rights reserved. Data transformed to the
  Overture schema.
- AllThePlaces: CC0 1.0

City populations and boundaries: Overture divisions theme, licensed under the Open Database License (ODbL).
© OpenStreetMap contributors, Overture Maps Foundation. Other sources in that theme: geoBoundaries, Esri
Community Maps contributors and Land Information New Zealand (LINZ), each under CC BY 4.0.

In this repository:

- `cities/cities.json` and `cities/boundaries.parquet` are derived from the divisions theme and are offered
  under the [Open Database License 1.0](https://opendatacommons.org/licenses/odbl/1-0/); see `cities/LICENSE`.
  The same applies to the `population`, `area_km2`, `boundary` and `bbox` fields that the files in `data/`
  and `docs/data/` repeat from the city list.
- The count fields in `data/` and `docs/data/` are offered under
  [CDLA Permissive 2.0](https://cdla.dev/permissive-2-0/); see `LICENSE-DATA`. Please credit Overture Maps
  Foundation when you reuse them.
- The code is offered under the MIT licence; see `LICENSE`.

This project is not affiliated with or endorsed by the Overture Maps Foundation or its data providers.
