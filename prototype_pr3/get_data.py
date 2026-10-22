# Downloads the data the dashboard uses and saves it in the data folder.
# Run this once before the dashboard (python get_data.py). After that the
# dashboard works offline.
#
# Air quality: DEFRA UK-AIR hourly data for two monitors
#   BMLD = Birmingham Ladywood (urban background)
#   BIRR = Birmingham A4540 Roadside
# Rainfall: Open-Meteo historical weather API (daily total for Ladywood)

import io
from datetime import date, timedelta

import pandas as pd
import requests

SITES = ["BMLD", "BIRR"]
YEARS = [2025, 2026]
DEFRA_URL = "https://uk-air.defra.gov.uk/datastore/data_files/site_data/{}_{}.csv"
RAIN_URL = "https://archive-api.open-meteo.com/v1/archive"

COLUMNS = {
    "Nitrogen dioxide": "NO2",
    "PM<sub>2.5</sub> particulate matter (Hourly measured)": "PM2.5",
    "PM<sub>10</sub> particulate matter (Hourly measured)": "PM10",
}


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
        out[short_name] = pd.to_numeric(df[long_name], errors="coerce")
    return out


def get_air_quality():
    frames = []
    for site in SITES:
        for year in YEARS:
            print("downloading", site, year)
            r = requests.get(DEFRA_URL.format(site, year), timeout=60)
            if r.status_code == 200:
                frames.append(read_defra(r.text, site))
    aq = pd.concat(frames).drop_duplicates(["site", "time"])
    aq.to_csv("data/aq_hourly.csv", index=False)
    print("saved", len(aq), "air quality rows")


def get_rainfall():
    params = {
        "latitude": 52.4797, "longitude": -1.9180,
        "start_date": "2025-01-01", "end_date": str(date.today() - timedelta(days=1)),
        "daily": "precipitation_sum", "timezone": "Europe/London",
    }
    r = requests.get(RAIN_URL, params=params, timeout=60)
    daily = r.json()["daily"]
    rain = pd.DataFrame({"date": daily["time"], "rain_mm": daily["precipitation_sum"]}).dropna()
    rain.to_csv("data/rain_daily.csv", index=False)
    print("saved", len(rain), "days of rainfall")


if __name__ == "__main__":
    get_air_quality()
    get_rainfall()
