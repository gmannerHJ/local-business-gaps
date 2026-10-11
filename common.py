"""Shared settings and helpers for the pipeline."""
import json
import re
import unicodedata
import urllib.request
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent
CITIES_JSON = ROOT / "cities" / "cities.json"
BOUNDARIES = ROOT / "cities" / "boundaries.parquet"
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"

USER_AGENT = "local-business-gaps/1.0 (open data aggregates; github.com/gmannerHJ/local-business-gaps)"
STAC_CATALOG = "https://stac.overturemaps.org/catalog.json"
S3_BUCKET = "s3://overturemaps-us-west-2/release"
S3_REGION = "us-west-2"


def latest_release() -> str:
    """Latest Overture release id, read from Overture's public STAC catalog."""
    req = urllib.request.Request(STAC_CATALOG, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["latest"]


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(config={"custom_user_agent": USER_AGENT})
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
    con.execute(f"SET s3_region='{S3_REGION}';")
    con.execute("SET enable_progress_bar=false;")
    return con


def theme_path(release: str, theme: str, type_: str) -> str:
    return f"{S3_BUCKET}/{release}/theme={theme}/type={type_}/*"


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("ı", "i").replace("ł", "l").replace("Ł", "L").replace("đ", "d").replace("ø", "o").replace("ß", "ss")
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s


def load_cities() -> list[dict]:
    return json.loads(CITIES_JSON.read_text(encoding="utf-8"))["cities"]
