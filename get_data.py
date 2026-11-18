# Downloads the data the dashboard uses and saves it in the data folder.
# Run this once before the dashboard (python get_data.py). After that the
# dashboard works offline. The dashboard's "Refresh live data" button calls
# the same functions.
#
# Air quality: DEFRA UK-AIR hourly data for two monitors
#   BMLD = Birmingham Ladywood (urban background)
#   BIRR = Birmingham A4540 Roadside
# Rainfall: Open-Meteo historical weather API (daily total for Ladywood)
# Elevation: Copernicus GLO-90 DEM, via the Open-Meteo elevation API
#
# Every download is checked before it is saved, so a failed or half-finished
# download never overwrites the data we already have.

import io
from pathlib import Path
from datetime import date, timedelta

import pandas as pd
import requests

DATA = Path(__file__).parent / "data"   # save next to this script

SITES = ["BMLD", "BIRR"]
FIRST_YEAR = 2025
DEFRA_URL = "https://uk-air.defra.gov.uk/datastore/data_files/site_data/{}_{}.csv"
RAIN_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
LADYWOOD = {"latitude": 52.4797, "longitude": -1.9180}

COLUMNS = {
    "Nitrogen dioxide": "NO2",
    "PM<sub>2.5</sub> particulate matter (Hourly measured)": "PM2.5",
    "PM<sub>10</sub> particulate matter (Hourly measured)": "PM10",
}

# points we want the ground level for (same coordinates as in app.py)
ELEVATION_POINTS = [
    ("zone", "Ladywood Middleway / Monument Rd", 52.4758, -1.9238),
    ("zone", "St Marks Crescent / King Edwards Rd", 52.4812, -1.9199),
    ("zone", "Ledsam St / community hub", 52.4799, -1.9237),
    ("zone", "Port Loop (brownfield)", 52.4819, -1.9308),
    ("zone", "Spring Hill / Dudley Rd", 52.4858, -1.9230),
    ("zone", "Five Ways roundabout", 52.4728, -1.9186),
    ("zone", "Birmingham Canal (Brindleyplace)", 52.4784, -1.9119),
    ("zone", "Edgbaston Reservoir (Reservoir Rd)", 52.4775, -1.9330),
    ("worksite", "Link Road verges", 52.4832, -1.9362),
    ("worksite", "A4540 Middleway", 52.4800, -1.9258),
    ("worksite", "Port Loop canal side", 52.4825, -1.9300),
    ("worksite", "Summerfield Park (just outside the ward)", 52.4837, -1.9408),
    ("worksite", "Estate car parks", 52.4812, -1.9199),
]


def read_defra(text, site):
    # the file has a few lines of notes before the real header
    lines = text.splitlines()
    start = [i for i, line in enumerate(lines) if line.startswith("Date,time")][0]
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    df = df.dropna(subset=["Date"])

    # DEFRA writes midnight as 24:00, which pandas can't read,
    # so add the hour onto the date instead
    hour = df["time"].str[:2].astype(int)
    df["time"] = pd.to_datetime(df["Date"], format="%d-%m-%Y") + pd.to_timedelta(hour, unit="h")

    out = pd.DataFrame({"time": df["time"], "site": site})
    for long_name, short_name in COLUMNS.items():
        if long_name in df.columns:
            out[short_name] = pd.to_numeric(df[long_name], errors="coerce")
        else:
            out[short_name] = float("nan")
    return out


def fetch_air_quality(timeout=60):
    # returns the hourly table, or raises an error if nothing could be downloaded
    frames = []
    for site in SITES:
        for year in range(FIRST_YEAR, date.today().year + 1):
            r = requests.get(DEFRA_URL.format(site, year), timeout=timeout)
            if r.status_code == 200 and "Date,time" in r.text:
                frames.append(read_defra(r.text, site))
    if not frames:
        raise RuntimeError("no air quality files could be downloaded from UK-AIR")
    aq = pd.concat(frames).drop_duplicates(["site", "time"]).sort_values(["site", "time"])
    if set(aq["site"]) != set(SITES):
        raise RuntimeError("one of the two monitors is missing from the download")
    return aq


def fetch_rainfall(timeout=60):
    end = date.today() - timedelta(days=1)
    params = {**LADYWOOD, "daily": "precipitation_sum", "timezone": "Europe/London"}
    r = requests.get(RAIN_URL, params={**params, "start_date": f"{FIRST_YEAR}-01-01", "end_date": str(end)},
                     timeout=timeout)
    r.raise_for_status()
    daily = r.json()["daily"]
    rain = pd.DataFrame({"date": pd.to_datetime(daily["time"]), "rain_mm": daily["precipitation_sum"]}).dropna()

    # the archive is a few days behind, so top up the last days from the forecast service
    try:
        r = requests.get(FORECAST_URL, params={**params, "past_days": 14, "forecast_days": 1}, timeout=timeout)
        r.raise_for_status()
        f = r.json()["daily"]
        recent = pd.DataFrame({"date": pd.to_datetime(f["time"]), "rain_mm": f["precipitation_sum"]}).dropna()
        recent = recent[recent["date"].dt.date <= end]
        rain = pd.concat([rain, recent]).drop_duplicates("date", keep="first")
    except (requests.RequestException, KeyError, ValueError):
        pass   # the archive alone is fine
    if rain.empty:
        raise RuntimeError("Open-Meteo returned no rainfall")
    return rain.sort_values("date").reset_index(drop=True)


def fetch_elevation(timeout=60):
    r = requests.get(ELEVATION_URL, timeout=timeout, params={
        "latitude": ",".join(str(p[2]) for p in ELEVATION_POINTS),
        "longitude": ",".join(str(p[3]) for p in ELEVATION_POINTS)})
    r.raise_for_status()
    heights = r.json()["elevation"]
    return pd.DataFrame([(*p, h) for p, h in zip(ELEVATION_POINTS, heights)],
                        columns=["kind", "name", "lat", "lon", "elev_m"])


def save(df, filename):
    # write to a temporary file first, then swap it in, so a crash halfway
    # through never leaves a broken file behind
    tmp = DATA / (filename + ".tmp")
    df.to_csv(tmp, index=False)
    tmp.replace(DATA / filename)


# Birmingham City Council Climate Risk and Vulnerability Assessment (CRVA) 2025
# https://maps.birmingham.gov.uk/server/rest/services/CRVA/CRVA_2025/MapServer
CRVA_URL = "https://maps.birmingham.gov.uk/server/rest/services/CRVA/CRVA_2025/MapServer/{}/query"
WARD_BOX = "-1.9355,52.4673,-1.8901,52.4867"   # rectangle around Ladywood ward

# the 17 neighbourhoods (2021 LSOAs) whose centre is inside Ladywood ward
LADYWOOD_LSOAS = ["E01033620", "E01033616", "E01033627", "E01033557", "E01033618", "E01033625",
                  "E01033617", "E01009146", "E01034948", "E01034949", "E01033624", "E01009141",
                  "E01009143", "E01009153", "E01033626", "E01009140", "E01033564"]


def crva_query(layer, filename, **params):
    params.update({"outSR": 4326, "f": "geojson"})
    r = requests.get(CRVA_URL.format(layer), params=params, timeout=120)
    r.raise_for_status()
    if not r.json().get("features"):          # keep the old file if the server sent nothing useful
        print("no features returned for", filename, "- kept the old file")
        return
    tmp = DATA / (filename + ".tmp")
    tmp.write_text(r.text)
    tmp.replace(DATA / filename)
    print("saved", filename)


def get_crva():
    # layer 12 = CRVA by ward (we only keep Ladywood's outline)
    crva_query(12, "ladywood_ward.geojson", where="WARDNME='LADYWOOD'", outFields="WARDNME,MEAN,AVERAGE_RISK")
    # layer 15 = CRVA score for each 2021 LSOA
    codes = ",".join(f"'{c}'" for c in LADYWOOD_LSOAS)
    crva_query(15, "crva_lsoa.geojson", where=f"LSOA21CD IN ({codes})",
               outFields="LSOA21CD,LSOA21NM,MEAN,AVERAGE_RISK,MAXIMUM_RISK")
    # layer 1546 = Environment Agency risk of surface water flooding extent
    crva_query(1546, "surface_water.geojson", geometry=WARD_BOX, geometryType="esriGeometryEnvelope",
               inSR=4326, spatialRel="esriSpatialRelIntersects", outFields="pub_date")


if __name__ == "__main__":
    DATA.mkdir(exist_ok=True)
    for name, fetch, filename in [("air quality", fetch_air_quality, "aq_hourly.csv"),
                                  ("rainfall", fetch_rainfall, "rain_daily.csv"),
                                  ("elevation", fetch_elevation, "elevation.csv")]:
        try:
            df = fetch()
            save(df, filename)
            print("saved", len(df), name, "rows")
        except Exception as e:
            print("could not update", name, f"({e}) - kept the old file")
    try:
        get_crva()
    except Exception as e:
        print("could not update the CRVA layers", f"({e}) - kept the old files")
