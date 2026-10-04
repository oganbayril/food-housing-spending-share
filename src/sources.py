"""Download helpers for Eurostat and OECD data.

Both sources offer an SDMX web API that can return plain CSV, which pandas
reads directly. Every download is saved untouched to data/raw/ first, so the
processing can always be re-run (and checked) against exactly what was
received.
"""

from pathlib import Path

import pandas as pd
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
CHECKS_DIR = PROCESSED_DIR / "checks"

EUROSTAT_URL = "https://ec.europa.eu/eurostat/api/dissemination/sdmx/2.1/data"
OECD_URL = "https://sdmx.oecd.org/public/rest/data"


def _download(url, filename):
    """Download a URL and save the response text to data/raw/<filename>."""
    print(f"Downloading {url}")
    response = requests.get(url, timeout=120)
    response.raise_for_status()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / filename
    path.write_text(response.text, encoding="utf-8")
    print(f"  saved to {path}")
    return path


def download_eurostat(dataset, key, filename, start_year=None, end_year=None):
    """Download a Eurostat dataset as CSV and return it as a DataFrame.

    `key` selects values for each dimension, in the dataset's own order,
    separated by dots. Several values go together with "+", and an empty
    slot means "all values". Example for nama_10_co3_p3 (freq.unit.coicop.geo):
        "A.CP_MNAC.TOTAL+CP01."  -> annual, one unit, two items, all countries
    """
    url = f"{EUROSTAT_URL}/{dataset}/{key}/?format=SDMX-CSV"
    if start_year is not None:
        url += f"&startPeriod={start_year}"
    if end_year is not None:
        url += f"&endPeriod={end_year}"
    path = _download(url, filename)
    return pd.read_csv(path)


def download_oecd(dataflow, key, filename, start_year=None, end_year=None):
    """Download an OECD Data Explorer dataflow as CSV and return a DataFrame.

    `dataflow` is "<agency>,<dataflow id>,<version>", e.g.
    "OECD.SDD.NAD,DSD_NAMAIN10@DF_TABLE5_T501,". `key` works like Eurostat's.
    """
    url = f"{OECD_URL}/{dataflow}/{key}?dimensionAtObservation=AllDimensions&format=csvfilewithlabels"
    if start_year is not None:
        url += f"&startPeriod={start_year}"
    if end_year is not None:
        url += f"&endPeriod={end_year}"
    path = _download(url, filename)
    return pd.read_csv(path)


def save_check(df, filename):
    """Save the output of an investigation to data/processed/checks/."""
    CHECKS_DIR.mkdir(parents=True, exist_ok=True)
    path = CHECKS_DIR / filename
    df.to_csv(path, index=False)
    print(f"Saved {path}")
