# Ladywood Environmental Monitor - MINN Team 25
# FEBE1004A Design Project  (School of Mining Engineering)
#
# Run with:  streamlit run app.py
# Data comes from get_data.py (DEFRA UK-AIR, Open-Meteo, Copernicus DEM, CRVA 2025), saved in /data.
# The app only reads saved files, so it works offline. "Refresh live data" in the sidebar
# downloads the latest readings and keeps the saved data if the download fails.

import json
import math
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Ladywood Environmental Monitor", layout="wide")

# the data folder sits next to this file (works locally and on Streamlit Cloud)
DATA = Path(__file__).parent / "data"
BACKUP = Path(__file__).parent / "prototype_pr3" / "data"   # older copy of the CSVs, used if /data is damaged

# ---------------------------------------------------------------------------
# Settings and numbers we use
# ---------------------------------------------------------------------------
NAVY = "#1f4e79"
ORANGE = "#d9822b"
GREY = "#6b7280"
RED = "#b23b3b"
GREEN = "#2f7d4f"

SITE_NAMES = {"BMLD": "Ladywood (background)", "BIRR": "A4540 Roadside"}
SITE_COLOURS = {"Ladywood (background)": NAVY, "A4540 Roadside": ORANGE}

# annual mean limits in ug/m3: UK value and WHO 2021 guideline
LIMITS = {
    "NO2": {"UK": 40, "WHO": 10},
    "PM2.5": {"UK": 10, "WHO": 5},   # UK = England 2040 target
    "PM10": {"UK": 40, "WHO": 15},
}

# drainage assumptions for the Ladywood estate catchment
CATCHMENT_HA = 60          # catchment area in hectares (estimate)
RUNOFF_COEFF = 0.65        # rational method C for a mostly sealed area
DRAIN_CARRY_OVER = 0.55    # share of yesterday's water still in the sewers today
DRAIN_CAPACITY_MM = 15     # load at which the combined sewers are assumed to overflow (about 2% of days)

# Unit costs and storage from our research (CIRIA C753 SuDS Manual benchmarks)
INTERVENTIONS = {
    "Rain garden / bioswale": {"cost_low": 240, "cost_high": 300, "storage": 0.30},
    "Permeable paving": {"cost_low": 80, "cost_high": 130, "storage": 0.20},
    "Constructed wetland": {"cost_low": 120, "cost_high": 200, "storage": 0.40},
    "Vegetation / tree buffer": {"cost_low": 30, "cost_high": 60, "storage": 0.02},
    "Detention basin": {"cost_low": 30, "cost_high": 60, "storage": 0.40},
}

# Decision matrix from our research report (scores 1-5, 5 = best)
CRITERIA = ["Flood reduction", "Air quality", "Feasibility", "Cost", "Community benefit",
            "Measurability", "Mining link"]
DEFAULT_WEIGHTS = [25, 15, 15, 15, 15, 10, 5]
SCORES = {
    "Rain garden / bioswale": [4, 2, 4, 4, 4, 4, 4],
    "Permeable paving": [3, 1, 4, 2, 3, 3, 3],
    "Constructed wetland": [3, 1, 2, 2, 4, 3, 5],
    "Vegetation / tree buffer": [2, 5, 4, 4, 5, 3, 4],
    "Detention basin": [5, 1, 2, 3, 3, 4, 5],
}

# Risk zones. Flood and land ratings (1 = low, 5 = high) are our own desk estimates.
# Modelled NO2 / PM2.5 and the CRVA score were read off Birmingham City Council's CRVA 2025
# map at each point (22 Oct 2026). The NO2 map comes from the WM-Air model (University of Birmingham).
# The flood ratings are checked against the Environment Agency surface water map further down.
ZONES = pd.DataFrame([
    ["Ladywood Middleway / Monument Rd", 52.4758, -1.9238, 3, 2, 38.4, 11.6, 6.69],
    ["St Marks Crescent / King Edwards Rd", 52.4812, -1.9199, 4, 2, 28.9, 10.4, 6.49],
    ["Ledsam St / community hub", 52.4799, -1.9237, 3, 2, 30.3, 10.6, 6.49],
    ["Port Loop (brownfield)", 52.4819, -1.9308, 4, 5, 27.2, 10.5, 5.98],
    ["Spring Hill / Dudley Rd", 52.4858, -1.9230, 4, 3, 35.9, 11.4, 6.66],
    ["Five Ways roundabout", 52.4728, -1.9186, 3, 1, 47.8, 12.0, 6.85],
    ["Birmingham Canal (Brindleyplace)", 52.4784, -1.9119, 4, 3, 30.5, 10.4, 7.05],
    ["Edgbaston Reservoir (Reservoir Rd)", 52.4775, -1.9330, 2, 4, 25.2, 10.2, 5.55],
], columns=["Zone", "lat", "lon", "Flood (desk)", "Land", "Modelled NO2", "Modelled PM2.5", "CRVA score"])

EA_RADIUS_M = 250          # we look at the EA flood extent within this distance of each zone


def air_rating(no2):
    # 1-5 rating from modelled NO2 (ug/m3), bands chosen by us
    if no2 < 20:
        return 1
    elif no2 < 27:
        return 2
    elif no2 < 32:
        return 3
    elif no2 < 40:
        return 4
    return 5


def ea_rating(cover_pct):
    # 1-5 rating from the share of ground within 250 m that the EA map shows flooding.
    # The ward as a whole is 1.0%, so "above the ward average" starts at 4.
    if pd.isna(cover_pct):
        return np.nan
    if cover_pct < 0.25:
        return 1
    elif cover_pct < 0.5:
        return 2
    elif cover_pct < 1.0:
        return 3
    elif cover_pct < 2.0:
        return 4
    return 5


# Facts about Ladywood ward from the CRVA 2025 map service (worked out on 22 Oct 2026)
CRVA = {
    "ward_score": 6.75,          # mean CRVA score for Ladywood ward
    "ward_rank": 15,             # out of 69 Birmingham wards (1 = highest risk)
    "city_mean": 5.67,           # average of all ward scores
    "population": 32377,         # mid-2019 estimate, sum of the ward's LSOAs
    "lsoas_high": 5,             # of the 17 LSOAs rated High on average
    "imd_top10": 6,              # of 16 (2011) LSOAs in England's most deprived 10% (IMD 2019)
    "excess_yll": 22,            # % more years of life lost before 75 than expected (2012-17)
    "green_m2_pp": 6.5,          # m2 of green space per person (OS Open Greenspace)
    "surface_water_pct": 1.0,    # % of ward area in the EA surface water flood extent
    "buildings_near_flood": 13.8,  # % of buildings within 10 m of that extent
}

WORKSITES = pd.DataFrame([
    ["Link Road verges", 52.4832, -1.9362, "Rain garden / bioswale"],
    ["A4540 Middleway", 52.4800, -1.9258, "Vegetation / tree buffer"],
    ["Port Loop canal side", 52.4825, -1.9300, "Constructed wetland"],
    ["Summerfield Park (just outside the ward)", 52.4837, -1.9408, "Detention basin"],
    ["Estate car parks", 52.4812, -1.9199, "Permeable paving"],
], columns=["Site", "lat", "lon", "Proposed intervention"])

MONITORS = pd.DataFrame([
    ["Birmingham Ladywood (DEFRA)", 52.481346, -1.918235],
    ["Birmingham A4540 Roadside (DEFRA)", 52.476145, -1.874978],
], columns=["Monitor", "lat", "lon"])

# Land stability check: brownfield made ground (infinite-slope screening check)
SLOPE = {"depth_m": 1.5, "unit_weight": 18.0, "cohesion": 2.0}   # slip depth, kN/m3, kPa
WATER_UNIT_WEIGHT = 9.81

# Phased rehabilitation plan, set out the way a mine closure plan is
ROADMAP = [
    ["0 · Baseline", 0, 3, "Months 0-3",
     "Keep the DEFRA monitors; add low-cost PM/NO2 sensors and a rain gauge at the CIVIC SQUARE hub; "
     "start a resident flood log", "12 months of baseline data with at least 75% data capture",
     "Pre-mining environmental baseline"],
    ["1 · Street interventions", 3, 12, "Months 3-12",
     "Rain gardens on the Link Road verges and a tree belt along the A4540 Middleway (the two top options)",
     "Fewer overload days than the baseline; at least 80% of plants survive", "Progressive rehabilitation"],
    ["2 · Urban retrofits", 12, 36, "Years 1-3",
     "Permeable paving in the estate car parks; constructed wetland at the Port Loop canal side",
     "Less runoff to the sewers; fewer storm overflow spills", "Passive mine-water treatment"],
    ["3 · Catchment attenuation", 36, 60, "Years 3-5",
     "Detention basin in Summerfield Park; regrade and plant made-ground slopes at Port Loop",
     "Factor of safety at least 1.5 on every reshaped slope", "Landform reshaping at closure"],
    ["4 · Aftercare", 60, 120, "Years 5-10",
     "Community maintenance plan, yearly dashboard review, adjust what is not working",
     "NO2 trending toward the WHO guideline; planting self-sustaining", "Aftercare and relinquishment"],
]


# ---------------------------------------------------------------------------
# Load data. Every file has a fallback, so a missing or damaged file shows a
# warning instead of stopping the dashboard.
# ---------------------------------------------------------------------------
def read_table(name, date_col, columns):
    for folder in (DATA, BACKUP):
        try:
            df = pd.read_csv(folder / name, parse_dates=[date_col])
            if set(columns) <= set(df.columns) and len(df) > 0:
                note = "" if folder == DATA else f"{name} was damaged or missing, so the backup copy is used."
                return df, note
        except Exception:
            continue
    empty = pd.DataFrame({c: pd.Series(dtype="datetime64[ns]" if c == date_col else "object") for c in columns})
    return empty, f"{name} could not be read, so these charts are empty."


def read_geojson(name):
    try:
        with open(DATA / name) as f:
            data = json.load(f)
        if data.get("features"):
            return data, ""
    except Exception:
        pass
    return {"type": "FeatureCollection", "features": []}, f"{name} could not be read, so that map layer is hidden."


@st.cache_data
def load_data():
    notes = []
    aq, note = read_table("aq_hourly.csv", "time", ["time", "site", "NO2", "PM2.5", "PM10"])
    notes.append(note)
    for col in ["NO2", "PM2.5", "PM10"]:
        aq[col] = pd.to_numeric(aq[col], errors="coerce")
    aq["site"] = aq["site"].map(SITE_NAMES)
    rain, note = read_table("rain_daily.csv", "date", ["date", "rain_mm"])
    notes.append(note)
    rain["rain_mm"] = pd.to_numeric(rain["rain_mm"], errors="coerce").fillna(0)
    rain = rain.sort_values("date").reset_index(drop=True)
    try:
        elev = pd.read_csv(DATA / "elevation.csv")
    except Exception:
        elev = pd.DataFrame(columns=["kind", "name", "lat", "lon", "elev_m"])
        notes.append("elevation.csv could not be read, so ground levels are not shown.")
    return aq, rain, elev, [n for n in notes if n]


@st.cache_data
def load_map_data():
    ward, n1 = read_geojson("ladywood_ward.geojson")
    lsoas, n2 = read_geojson("crva_lsoa.geojson")
    surface_water, n3 = read_geojson("surface_water.geojson")
    return ward, lsoas, surface_water, [n for n in (n1, n2, n3) if n]


def points_inside(lon, lat, ring):
    # ray-casting test: which of the points lie inside one polygon ring
    ring = np.asarray(ring, dtype=float)
    x1, y1 = ring[:, 0], ring[:, 1]
    x2, y2 = np.roll(x1, 1), np.roll(y1, 1)
    inside = np.zeros(len(lon), dtype=bool)
    for ax, ay, bx, by in zip(x1, y1, x2, y2):
        if ay == by:
            continue
        crosses = (ay > lat) != (by > lat)
        inside ^= crosses & (lon < (bx - ax) * (lat - ay) / (by - ay) + ax)
    return inside


@st.cache_data
def ea_flood_cover(zone_points, radius_m=EA_RADIUS_M):
    # % of the ground within radius_m of each zone that the EA map shows at risk of surface water flooding.
    # We lay a 10 m grid of points over a circle round each zone and count how many fall in the flood extent.
    _, _, surface_water, _ = load_map_data()
    polygons = []
    for feature in surface_water["features"]:
        geom = feature.get("geometry") or {}
        if geom.get("type") == "Polygon":
            polygons.append(geom["coordinates"])
        elif geom.get("type") == "MultiPolygon":
            polygons.extend(geom["coordinates"])
    if not polygons:
        return [np.nan] * len(zone_points)
    results = []
    for lat0, lon0 in zone_points:
        m_per_deg_lat = 111_195
        m_per_deg_lon = m_per_deg_lat * math.cos(math.radians(lat0))
        steps = np.arange(-radius_m, radius_m + 10, 10)
        dx, dy = np.meshgrid(steps, steps)
        keep = dx ** 2 + dy ** 2 <= radius_m ** 2
        lon = lon0 + dx[keep] / m_per_deg_lon
        lat = lat0 + dy[keep] / m_per_deg_lat
        flooded = np.zeros(len(lon), dtype=bool)
        for rings in polygons:
            outer = np.asarray(rings[0], dtype=float)
            if (outer[:, 0].max() < lon.min() or outer[:, 0].min() > lon.max()
                    or outer[:, 1].max() < lat.min() or outer[:, 1].min() > lat.max()):
                continue
            hit = points_inside(lon, lat, outer)
            for hole in rings[1:]:
                hit &= ~points_inside(lon, lat, hole)
            flooded |= hit
        results.append(round(flooded.mean() * 100, 2))
    return results


def drain_load(rain_mm):
    # daily water load in the sewers (mm over the catchment): what is left from yesterday + today's runoff
    runoff = RUNOFF_COEFF * np.asarray(rain_mm, dtype=float)
    load = np.zeros_like(runoff)
    for i, r in enumerate(runoff):
        load[i] = (load[i - 1] * DRAIN_CARRY_OVER if i else 0) + r
    return load


def factor_of_safety(angle_deg, saturation, friction_deg, root_kpa=0.0):
    # infinite-slope factor of safety (Duncan, Wright and Brandon, 2014)
    b = math.radians(angle_deg)
    z, g, c = SLOPE["depth_m"], SLOPE["unit_weight"], SLOPE["cohesion"]
    normal = g * z * math.cos(b) ** 2
    water = WATER_UNIT_WEIGHT * saturation * z * math.cos(b) ** 2
    driving = g * z * math.sin(b) * math.cos(b)
    return (c + root_kpa + max(normal - water, 0) * math.tan(math.radians(friction_deg))) / driving


def num(value, fmt=".1f", unit=""):
    # format a number, or show "n/a" if the data is missing
    try:
        if value is None or pd.isna(value):
            return "n/a"
        return f"{value:{fmt}}{unit}"
    except (TypeError, ValueError):
        return "n/a"


def day(ts, fmt="%d %B %Y"):
    return "n/a" if ts is None or pd.isna(ts) else f"{ts:{fmt}}"


@contextmanager
def safe_section(name):
    # if something in one tab fails, show a message there and keep the rest of the dashboard running
    try:
        yield
    except Exception as e:
        st.warning(f"The {name} section could not be shown ({type(e).__name__}). The rest of the dashboard "
                   "still works; refreshing the page usually fixes this.")


def refresh_live_data():
    # download the latest Air quality and rainfall; keep the saved files if anything goes wrong
    import get_data
    old_aq, old_rain, _, _ = load_data()
    messages, ok = [], False
    for label, fetch, filename, date_col, old in [
            ("Air quality", get_data.fetch_air_quality, "aq_hourly.csv", "time", old_aq),
            ("Rainfall", get_data.fetch_rainfall, "rain_daily.csv", "date", old_rain)]:
        try:
            new = fetch(timeout=20)
            if len(old) and (len(new) < 0.9 * len(old) or new[date_col].max() < old[date_col].max()):
                raise ValueError("the download was shorter than the saved data")
            get_data.save(new, filename)
            messages.append(f"{label}: updated to {pd.to_datetime(new[date_col].max()):%d %b %Y}.")
            ok = True
        except Exception as e:
            messages.append(f"{label}: could not refresh ({type(e).__name__}), so the saved data is kept.")
    if ok:
        st.cache_data.clear()
    return ok, " ".join(messages)


aq, rain, elev, data_notes = load_data()
ward, lsoas, surface_water, map_notes = load_map_data()
last_date = aq["time"].max()
last_year = aq[aq["time"] > last_date - pd.Timedelta(days=365)] if pd.notna(last_date) else aq
rain_year = rain[rain["date"] > rain["date"].max() - pd.Timedelta(days=365)] if len(rain) else rain

# flood ratings: our desk estimate, checked against the EA surface water map
ZONES["EA flood cover (%)"] = ea_flood_cover(tuple(zip(ZONES["lat"], ZONES["lon"])))
ZONES["Flood (EA map)"] = ZONES["EA flood cover (%)"].apply(ea_rating)
ZONES["Flood check"] = np.where(ZONES["Flood (EA map)"].isna(), "Not checked",
                                np.where((ZONES["Flood (desk)"] - ZONES["Flood (EA map)"]).abs() <= 1,
                                         "Agrees (within 1)", "Disagrees - EA rating used"))
# keep our estimate where the EA map broadly agrees; use the EA-based rating where it does not
ZONES["Flood"] = np.where(ZONES["Flood check"] == "Disagrees - EA rating used",
                          ZONES["Flood (EA map)"], ZONES["Flood (desk)"]).astype(int)
ZONES["Air"] = ZONES["Modelled NO2"].apply(air_rating)
ZONES["Risk score"] = ZONES[["Flood", "Air", "Land"]].mean(axis=1).round(1)
ZONES["Main hazard"] = ZONES[["Flood", "Air", "Land"]].idxmax(axis=1).map(
    {"Flood": "Flooding", "Air": "Air quality", "Land": "Land stability"})
ZONES["Ground level (m)"] = ZONES["Zone"].map(
    elev[elev["kind"] == "zone"].set_index("name")["elev_m"] if len(elev) else {})


def yearly_mean(site, pollutant):
    return last_year[last_year["site"] == site][pollutant].mean()


def chart_style(fig, height=380):
    fig.update_layout(template="simple_white", height=height, margin=dict(l=10, r=10, t=40, b=10),
                      legend=dict(orientation="h", y=1.08, x=0, title=None), font=dict(size=13))
    fig.update_yaxes(showgrid=True, gridcolor="#e5e7eb")
    return fig


# ---------------------------------------------------------------------------
# Page header and sidebar
# ---------------------------------------------------------------------------
st.title("Ladywood Environmental Monitor")
st.write("FEBE1004A Dashboard Design. MINN Team 25."
         f"Air quality up to {day(last_date)}.")
for note in data_notes + map_notes:
    st.warning(note)

st.sidebar.header("Settings")
pollutant = st.sidebar.selectbox("Pollutant", ["NO2", "PM2.5", "PM10"])
window = st.sidebar.radio("Rainfall period", ["Last 90 days", "Last 365 days"])
st.sidebar.divider()
st.sidebar.subheader("Map Layers")
show_crva = st.sidebar.checkbox("Risk of climate By neighbourhood (CRVA)", value=True)
show_flood = st.sidebar.checkbox("Surface water flood extent (EA)", value=True)
show_ward = st.sidebar.checkbox("Ladywood ward boundary", value=True)
show_zones = st.sidebar.checkbox("Risk zones", value=True)
show_sites = st.sidebar.checkbox("Proposed worksites", value=True)
show_monitors = st.sidebar.checkbox("Air quality monitors", value=True)
map_style = st.sidebar.selectbox("Base map", ["Topographic", "Street map"])
st.sidebar.divider()
st.sidebar.subheader("Data")
st.sidebar.caption(f"Saved data: Air quality to {day(last_date, '%d %b %Y')}, "
                   f"rainfall to {day(rain['date'].max(), '%d %b %Y')}. The dashboard runs from theses saved "
                   "files, operates offline.")
if st.sidebar.button("Refresh live data", width="stretch"):
    with st.spinner("Downlaoding the latest DEFRA and Open-Meteo data..."):
        st.session_state["refresh_result"] = refresh_live_data()
    st.rerun()
if "refresh_result" in st.session_state:
    ok, message = st.session_state.pop("refresh_result")
    (st.sidebar.success if ok else st.sidebar.warning)(message)

Overview, air_tab, rain_tab, map_tab, plan_tab, data_tab = st.tabs(
    ["Overview", "Air quality", "Rainfall and flooding", "Hazard map", "Interventios", "Data and sorces"])

# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
with Overview, safe_section("Overview"):
    st.subheader("Key indicators")
    no2 = yearly_mean("Ladywood (background)", "NO2")
    pm25 = yearly_mean("Ladywood (background)", "PM2.5")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("NO2, 12-month mean", num(no2, unit=" µg/m³"))
    c1.caption("UK limit 40, WHO guideline 10")
    c2.metric("PM2.5, 12-month mean", num(pm25, unit=" µg/m³"))
    c2.caption("UK target 10, WHO guideline 5")
    c3.metric("Residents at severe flood risk", "10%")
    c3.caption("Challenge Pack p.44")
    c4.metric("Rainfall, last 12 months", num(rain_year["rain_mm"].sum() if len(rain_year) else np.nan, ".0f", " mm"))
    c4.caption("Open-Meteo, Ladywood")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Climate risk score (CRVA)", f"{CRVA['ward_score']}")
    c5.caption(f"Rank {CRVA['ward_rank']} of 69 wards, city average {CRVA['city_mean']}")
    c6.metric("Population", f"{CRVA['population']:,}")
    c6.caption("Mid-2019 estimate, Ladywood ward")
    c7.metric("Neighbourhoods in most deprived 10%", f"{CRVA['imd_top10']} of 16")
    c7.caption("Indices of Deprivation 2019")
    c8.metric("Extra years of life lost", f"+{CRVA['excess_yll']}%")
    c8.caption("Deaths before 75 vs expected, 2012-17")

    st.write("Even though Ladywood meets the UK’s limits for NO2 and PM2.5, Ladywood still goes beyond the stricter guidelines set by the WHO."
             "According to Birmingham City Council’s Climate Risk and Vulnerability Assessment, Ladywood is in the 25 percent of Birmingham wards that are most vulnerable to climate change."
             "To tackle these challenges, this dashboard concentrates on two environmental hazards: flooding and Air quality.")

    st.subheader("Community needs")
    needs = pd.DataFrame([
        ["10%", "of residents at risk of severe flooding", "Pack p.44"],
        ["40%", "of the population at risk of extreme heat", "Pack p.16"],
        ["72%", "of neighbourhoods have under 10% tree cover", "Pack p.16"],
        ["5 m²", "of green space per person (constituency)", "Pack p.16"],
        ["6.5 m²", "of green space per person (ward)", "CRVA 2025"],
        ["6%", "have a respiratory disease (e.g. asthma)", "Pack p.48"],
        ["57.9%", "of households have no car (England 23.5%)", "Pack p.49"],
        ["0", "river flood zones in the ward - flood risk is from surface water", "CRVA 2025"],
    ], columns=["Figure", "Meaning", "Source"])
    st.dataframe(needs, hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# Air quality
# ---------------------------------------------------------------------------
with air_tab, safe_section("Air quality"):
    st.subheader(f"Monthly mean {pollutant}")
    monthly = (aq.dropna(subset=[pollutant])
                 .groupby(["site", pd.Grouper(key="time", freq="MS")])[pollutant]
                 .agg(["mean", "count"]).reset_index().rename(columns={"mean": pollutant}))
    # DEFRA rule: only show a monthly mean if at least 75% of the hours in that month were measured
    monthly = monthly[monthly["count"] >= 0.75 * 24 * monthly["time"].dt.days_in_month]
    if monthly.empty:
        st.info(f"No {pollutant} readings are available, so this chart is empty.")
    else:
        fig = px.bar(monthly, x="time", y=pollutant, color="site", barmode="group",
                     color_discrete_map=SITE_COLOURS, labels={"time": "", pollutant: f"{pollutant} (µg/m³)"})
        fig.add_hline(y=LIMITS[pollutant]["UK"], line_dash="dash", line_color=GREY,
                      annotation_text=f"UK limit {LIMITS[pollutant]['UK']}", annotation_position="top left")
        fig.add_hline(y=LIMITS[pollutant]["WHO"], line_dash="dot", line_color=RED,
                      annotation_text=f"WHO guideline {LIMITS[pollutant]['WHO']}", annotation_position="top left")
        st.plotly_chart(chart_style(fig), width="stretch")
        st.caption("Following DEFRAs data capture rule, any month with than seventy‑five percent of hours recorded—including the current, unfinished month—is excluded."
                   "The twelve-month averages shown below are calculated using every hour.")

    c1, c2 = st.columns(2)
    for col, site in zip([c1, c2], SITE_NAMES.values()):
        value = yearly_mean(site, pollutant)
        col.metric(f"{site}, 12-month mean", num(value, unit=" µg/m³"))
        col.caption(f"{num(value / LIMITS[pollutant]['WHO'])} times the WHO guideline")

    st.subheader("Average by hour of day")
    hourly = aq.dropna(subset=[pollutant]).copy()
    hourly["hour"] = hourly["time"].dt.hour
    hourly = hourly.groupby(["site", "hour"])[pollutant].mean().reset_index()
    if not hourly.empty:
        fig2 = px.line(hourly, x="hour", y=pollutant, color="site", color_discrete_map=SITE_COLOURS,
                       labels={"hour": "Hour of day", pollutant: f"{pollutant} (µg/m³)"})
        fig2.update_xaxes(dtick=3)
        st.plotly_chart(chart_style(fig2, 320), width="stretch")

    st.subheader("Measured (DEFRA) vs modelled (WM-Air, CRVA map)")
    compare = pd.DataFrame([
        ["Ladywood monitor", yearly_mean("Ladywood (background)", "NO2"), 30.2,
         yearly_mean("Ladywood (background)", "PM2.5"), 10.5],
        ["A4540 Roadside monitor", yearly_mean("A4540 Roadside", "NO2"), 47.5,
         yearly_mean("A4540 Roadside", "PM2.5"), 12.2],
    ], columns=["Location", "NO2 measured", "NO2 modelled", "PM2.5 measured", "PM2.5 modelled"]).round(1)
    st.dataframe(compare, hide_index=True, width="stretch")
    st.write("The model is about twice the latest measurements, so it probably shows an earlier year, before the "
             "Clean Air Zone (the map does not say which year). Both agree the roadside is much worse than the "
             "background, so we use the model to rank our zones, not to report current levels.")

    with st.expander("How this works"):
        st.write("Hourly data is taken from two DEFRA monitors: one background station in Birmingham Ladywood and"
                 "the Birmingham A4540 roadside station right beside the ring road. Comparing these two shows"
                 "the amount of pollution created by traffic—just as comparing a background dust monitor"
                 "with a perimeter monitor at a mine. Spikes that appear during morning and evening rush hours confirm that "
                 "traffic is the driver.")

# ---------------------------------------------------------------------------
# Rainfall and flooding
# ---------------------------------------------------------------------------
with rain_tab, safe_section("Rainfall and flooding"):
    days = 90 if window == "Last 90 days" else 365
    rain_all = rain.copy()
    # rational method: runoff volume = C x rainfall depth x area (1 mm on 1 ha = 10 m3)
    rain_all["runoff_m3"] = RUNOFF_COEFF * rain_all["rain_mm"] * CATCHMENT_HA * 10
    rain_all["drain_load_mm"] = drain_load(rain_all["rain_mm"])   # uses the full record, so day 1 starts "warm"
    rain_all["overloaded"] = rain_all["drain_load_mm"] > DRAIN_CAPACITY_MM
    recent = rain_all[rain_all["date"] > rain_all["date"].max() - pd.Timedelta(days=days)] if len(rain_all) else rain_all

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total rainfall", num(recent["rain_mm"].sum() if len(recent) else np.nan, ".0f", " mm"))
    c2.metric("Wettest day", num(recent["rain_mm"].max(), ".1f", " mm"))
    c3.metric("Days over 10 mm", int((recent["rain_mm"] > 10).sum()))
    c4.metric("Days sewers likely overloaded", int(recent["overloaded"].sum()),
              help="Estimated from the drain load model below; see 'How this works'.")

    if recent.empty:
        st.info("No rainfall data is available, so the charts are empty.")
    else:
        fig = px.bar(recent, x="date", y="rain_mm", labels={"date": "", "rain_mm": "Rainfall (mm/day)"})
        fig.update_traces(marker_color=NAVY)
        st.plotly_chart(chart_style(fig, 300), width="stretch")

        st.subheader("Estimated runoff from the Ladywood estate")
        fig2 = px.line(recent, x="date", y="runoff_m3", labels={"date": "", "runoff_m3": "Runoff (m³/day)"})
        fig2.update_traces(line_color=ORANGE, name="Daily runoff", showlegend=True)
        over = recent[recent["overloaded"]]
        fig2.add_scatter(x=over["date"], y=over["runoff_m3"], mode="markers", name="Sewers likely overloaded",
                         marker=dict(color=RED, size=9))
        st.plotly_chart(chart_style(fig2, 300), width="stretch")

    with st.expander("How this works"):
        st.write(f"Runoff uses the rational method: runoff = C × rainfall × area, with C = {RUNOFF_COEFF} "
                 f"for a mostly sealed estate and a {CATCHMENT_HA} ha catchment. Both values are estimates. "
                 "Ladywood has combined sewers, so on heavy-rain days this water mixes with sewage and can "
                 "overflow into the canals. Holding water back at the surface is the same idea as stormwater "
                 "control at a mine.")
        st.write(f"Sewer overload check: the sewers are treated like a storage dam that drains slowly. Each day they "
                 f"hold {DRAIN_CARRY_OVER:.0%} of yesterday's water plus today's runoff. When this load passes "
                 f"{DRAIN_CAPACITY_MM} mm over the catchment we count the day as overloaded. The {DRAIN_CAPACITY_MM} mm "
                 "level was set so that this happens on about 2% of days, which fits the reported flooding and "
                 "storm overflow spills. It is a screening estimate, not a sewer model: a real design needs Severn "
                 "Trent's network data and hourly rainfall.")

# ---------------------------------------------------------------------------
# Hazard map
# ---------------------------------------------------------------------------
with map_tab, safe_section("Hazard map"):
    st.subheader("Risk zones and proposed worksites")
    fig = go.Figure()
    if show_crva and lsoas["features"]:
        fig.add_trace(go.Choroplethmap(
            geojson=lsoas, featureidkey="properties.LSOA21CD",
            locations=[f["properties"]["LSOA21CD"] for f in lsoas["features"]],
            z=[f["properties"]["MEAN"] for f in lsoas["features"]],
            text=[f["properties"]["LSOA21NM"] + "<br>" + f["properties"]["AVERAGE_RISK"] for f in lsoas["features"]],
            hovertemplate="%{text}<br>CRVA score %{z:.2f}<extra></extra>",
            colorscale=[[0, "#fff4e6"], [1, "#c2410c"]], zmin=5, zmax=8, marker_opacity=0.45,
            marker_line_width=0.5, marker_line_color="#9a3412", name="CRVA score",
            colorbar=dict(title="CRVA<br>score", x=0.99, len=0.5, thickness=12)))
    if show_zones:
        for hazard, colour in [("Flooding", NAVY), ("Air quality", ORANGE), ("Land stability", RED)]:
            z = ZONES[ZONES["Main hazard"] == hazard]
            if z.empty:
                continue
            fig.add_trace(go.Scattermap(
                lat=z["lat"], lon=z["lon"], mode="markers", name=f"Risk zone: {hazard.lower()}",
                marker=dict(size=z["Risk score"] * 7, color=colour, opacity=0.8),
                text=z["Zone"] + "<br>Risk score " + z["Risk score"].astype(str)
                     + "<br>Ground level " + z["Ground level (m)"].map(lambda v: num(v, ".0f", " m")),
                hoverinfo="text"))
    if show_sites:
        fig.add_trace(go.Scattermap(
            lat=WORKSITES["lat"], lon=WORKSITES["lon"], mode="markers", name="Proposed worksite",
            marker=dict(size=12, color="#111827"),
            text=WORKSITES["Site"] + "<br>" + WORKSITES["Proposed intervention"], hoverinfo="text"))
    if show_monitors:
        fig.add_trace(go.Scattermap(
            lat=MONITORS["lat"], lon=MONITORS["lon"], mode="markers", name="DEFRA monitor",
            marker=dict(size=12, color="#16a34a"), text=MONITORS["Monitor"], hoverinfo="text"))

    # extra map layers drawn straight from the GeoJSON files
    layers = []
    if show_flood and surface_water["features"]:
        layers.append({"source": surface_water, "type": "fill", "color": "#2563eb", "opacity": 0.55})
    if show_ward and ward["features"]:
        layers.append({"source": ward, "type": "line", "color": "#111827", "line": {"width": 2.5}})
    if map_style == "Topographic":
        layers.insert(0, {"below": "traces", "sourcetype": "raster",
                          "source": ["https://tile.opentopomap.org/{z}/{x}/{y}.png"],
                          "sourceattribution": "© OpenStreetMap contributors, SRTM | © OpenTopoMap"})
        fig.update_layout(map=dict(style="white-bg", layers=layers))
    else:
        fig.update_layout(map=dict(style="open-street-map", layers=layers))
    fig.update_layout(map_center=dict(lat=52.4800, lon=-1.9260), map_zoom=13.5, height=560,
                      margin=dict(l=0, r=0, t=0, b=0), legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.85)"))
    st.plotly_chart(fig, width="stretch")

    st.caption("Blue shading = Environment Agency risk of surface water flooding extent (published 2022). "
               "Orange shading = CRVA climate risk score for each neighbourhood. Black line = Ladywood ward. "
               "If the background map is blank, the map tiles need an internet connection; the data layers still work.")
    st.dataframe(ZONES[["Zone", "Flood", "Air", "Land", "Risk score", "Main hazard", "Modelled NO2", "CRVA score",
                        "Ground level (m)"]]
                 .sort_values("Risk score", ascending=False), hide_index=True, width="stretch")
    with st.expander("How the risk score works"):
        st.write("Each zone is rated 1 (low) to 5 (high) for flooding, Air quality and land stability, and "
                 "the risk score is the average. The air rating comes from the modelled NO2 on the CRVA map "
                 "(under 20 = 1, 20-27 = 2, 27-32 = 3, 32-40 = 4, over 40 = 5). The flood rating is our desk "
                 "estimate, checked against the Environment Agency map (see below). The land rating is our own "
                 "estimate of made ground and embankments. Ladywood has no river flood zones, so all its flood "
                 "risk is surface water. Spring Hill, Edgbaston Reservoir and Summerfield Park sit just outside "
                 "the ward boundary.")
        st.write("The CRVA score is Birmingham City Council's combined climate risk and vulnerability score "
                 "(higher = more at risk). Ladywood ward averages 6.75; scores across the city's wards run "
                 "from about 1.3 to 10.3. Ground level is from the Copernicus GLO-90 elevation model: lower "
                 "ground is where surface water collects.")

    st.subheader("Flood rating check against the Environment Agency map")
    st.dataframe(ZONES[["Zone", "Ground level (m)", "EA flood cover (%)", "Flood (desk)", "Flood (EA map)",
                        "Flood check", "Flood"]]
                 .rename(columns={"EA flood cover (%)": f"EA flood extent within {EA_RADIUS_M} m (%)",
                                  "Flood": "Rating used"}),
                 hide_index=True, width="stretch")
    agree = int((ZONES["Flood check"] == "Agrees (within 1)").sum())
    st.write(f"For each zone we measured how much of the ground within {EA_RADIUS_M} m falls inside the EA surface "
             f"water flood extent and turned it into a 1-5 rating (the ward as a whole is "
             f"{CRVA['surface_water_pct']}%, so anything above that rates 4 or 5). {agree} of {len(ZONES)} desk "
             "ratings agree with the EA map to within one point, so we keep them. Where they disagree we use the "
             "EA rating instead. The Birmingham Canal zone dropped because the EA map does not model canal "
             "embankment failure; that risk is covered by its land rating instead.")

    st.subheader("Land stability check (brownfield landforms)")
    st.write("Reshaping Port Loop or building a detention basin creates slopes in made ground (loose fill of ash, "
             "rubble and soil), much like a mine waste dump. Heavy rain soaks the fill and can trigger a shallow "
             "slide. This screening check shows how planting and drainage make a slope safer.")
    s1, s2 = st.columns(2)
    angle = s1.slider("Slope angle (°)", 10.0, 40.0, 26.0, 0.5)
    saturation = s1.slider("How wet the fill gets after heavy rain (0 = dry, 1 = fully soaked)", 0.0, 1.0, 0.8, 0.05)
    friction = s2.slider("Friction angle of the fill (°)", 20.0, 38.0, 30.0, 0.5)
    roots = s2.slider("Extra strength from plant roots (kPa)", 0.0, 15.0, 5.0, 0.5)
    cases = [("Bare made ground", saturation, 0.0, GREY),
             ("With planting", saturation, roots, GREEN),
             ("With planting and a toe drain", saturation * 0.5, roots, NAVY)]
    for col, (name, sat, root, _) in zip(st.columns(3), cases):
        fs = factor_of_safety(angle, sat, friction, root)
        col.metric(f"Factor of safety: {name.lower()}", f"{fs:.2f}")
        col.caption("Stable (1.5 or more)" if fs >= 1.5 else ("Marginal (1.0 to 1.5)" if fs >= 1.0 else "Fails (below 1.0)"))
    wetness = np.linspace(0, 1, 21)
    fig = go.Figure()
    for name, _, root, colour in cases:
        drain = 0.5 if "drain" in name else 1.0
        fig.add_scatter(x=wetness, y=[factor_of_safety(angle, m * drain, friction, root) for m in wetness],
                        mode="lines", name=name, line=dict(color=colour, width=2.5))
    fig.add_hline(y=1.5, line_dash="dash", line_color=ORANGE, annotation_text="1.5 target for public slopes",
                  annotation_position="top left")
    fig.add_hline(y=1.0, line_dash="dot", line_color=RED, annotation_text="1.0 slope fails",
                  annotation_position="bottom left")
    fig.add_vline(x=saturation, line_color=GREY, line_width=1)
    fig.update_xaxes(title="How wet the fill is (0 = dry, 1 = fully soaked)")
    fig.update_yaxes(title="Factor of safety")
    st.plotly_chart(chart_style(fig, 340), width="stretch")
    with st.expander("How this works"):
        st.write("This is the infinite-slope check that mining engineers use for waste dumps and that is set out in "
                 "Duncan, Wright and Brandon (2014). It compares the strength of the fill (friction, cohesion and "
                 "roots) with the weight pulling it downhill. Water in the fill pushes the grains apart and cuts "
                 "the friction, which is why wet slopes fail. A factor of safety below 1 means failure; 1.5 or more "
                 "is the usual target for permanent slopes the public can walk on (Read and Stacey, 2009).")
        st.write(f"Fixed values: slip surface {SLOPE['depth_m']} m deep, fill unit weight {SLOPE['unit_weight']:.0f} kN/m³, "
                 f"cohesion {SLOPE['cohesion']:.0f} kPa. A toe drain is assumed to halve how wet the fill gets. "
                 "This is a screening check only: a real design needs boreholes, laboratory tests and a full "
                 "slope stability analysis.")

# ---------------------------------------------------------------------------
# Interventions: planner and decision matrix
# ---------------------------------------------------------------------------
with plan_tab, safe_section("Interventions"):
    st.subheader("Rehabilitation planner")
    c1, c2 = st.columns(2)
    choice = c1.selectbox("Intervention", list(INTERVENTIONS))
    n_sites = c1.slider("Number of sites", 1, 50, 20)
    site_size = c2.number_input("Area per site (m²)", min_value=10, max_value=2000, value=40, step=10)
    budget = c2.number_input("Budget (£)", min_value=10000, max_value=2000000, value=250000, step=10000)

    info = INTERVENTIONS[choice]
    area = n_sites * site_size
    storage = area * info["storage"]
    cost = area * (info["cost_low"] + info["cost_high"]) / 2

    # water captured over the last year. We assume each m2 of intervention collects runoff from
    # 10 m2 of road or roof around it (C = 0.9 for hard surfaces). Each rainy day the storage can
    # fill up once and then drains away (infiltration).
    runoff_total = RUNOFF_COEFF * rain_year["rain_mm"] * CATCHMENT_HA * 10    # m3/day, whole catchment
    runoff_to_sites = 0.9 * rain_year["rain_mm"] / 1000 * area * 10           # m3/day reaching the sites
    captured = runoff_to_sites.clip(upper=storage)
    reduction = captured.sum() / runoff_total.sum() * 100 if runoff_total.sum() > 0 else np.nan

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total area", f"{area:,.0f} m²")
    m2.metric("Storage", f"{storage:,.0f} m³")
    m3.metric("Estimated cost", f"£{cost:,.0f}")
    m4.metric("Runoff captured per year", num(reduction, ".1f", "%"))
    if cost <= budget:
        st.success(f"Within budget (£{budget - cost:,.0f} left).")
    else:
        st.error(f"Over budget by £{cost - budget:,.0f}.")
    st.caption(f"Unit cost £{info['cost_low']}-{info['cost_high']} per m², storage {info['storage']} m³ per m² "
               "(from our research, based on the CIRIA SuDS Manual).")

    st.divider()
    st.subheader("Decision matrix")
    with st.expander("Change the criteria weights (%)"):
        weights = []
        cols = st.columns(4)
        for i, criterion in enumerate(CRITERIA):
            weights.append(cols[i % 4].number_input(criterion, 0, 100, DEFAULT_WEIGHTS[i], step=5))
    if sum(weights) == 0:
        st.warning("At least one weight must be above zero.")
    else:
        matrix = pd.DataFrame(SCORES, index=CRITERIA).T
        totals = (matrix * weights).sum(axis=1) / sum(weights)
        results = pd.DataFrame({"Intervention": totals.index, "Score (out of 5)": totals.round(2)})
        results = results.sort_values("Score (out of 5)")
        fig = px.bar(results, x="Score (out of 5)", y="Intervention", orientation="h", text="Score (out of 5)")
        fig.update_traces(marker_color=NAVY, texttemplate="%{text:.2f}", textposition="outside")
        fig.update_xaxes(range=[0, 5.4])
        fig.update_yaxes(title=None)
        st.plotly_chart(chart_style(fig, 320), width="stretch")
        st.write(f"Weights add up to {sum(weights)}% (scores are divided by the total, so they stay out of 5).")
        st.dataframe(matrix, width="stretch")
        top = results["Score (out of 5)"].max()
        best = results[results["Score (out of 5)"] == top]["Intervention"].tolist()
        st.info("Highest score: " + " and ".join(best) + f" ({top:.2f}).")

        st.subheader("Robustness check")
        st.write("The weights are judgements, so we test whether the answer changes when they change.")
        base = np.array(weights, dtype=float) / sum(weights)

        def shifted(criterion, share):
            # give one criterion a fixed share and scale the others down to fit
            i = CRITERIA.index(criterion)
            rest = base.sum() - base[i]
            w = base * (1 - share) / rest if rest > 0 else np.full(len(base), (1 - share) / (len(base) - 1))
            w[i] = share
            return w

        scenarios = {"Your weights": base, "Equal weights": np.full(len(CRITERIA), 1 / len(CRITERIA)),
                     "Flood-heavy (40%)": shifted("Flood reduction", 0.40),
                     "Air-heavy (35%)": shifted("Air quality", 0.35)}
        table = pd.DataFrame({name: matrix.to_numpy() @ w for name, w in scenarios.items()}, index=matrix.index)
        ranks = table.rank(ascending=False, method="min").astype(int)
        st.dataframe(table.map(lambda v: f"{v:.2f}") + " (#" + ranks.astype(str) + ")", width="stretch")

        # 4,000 random weight sets close to the chosen ones (each weight varies by roughly +/-30%)
        rng = np.random.default_rng(7)
        samples = rng.dirichlet(np.where(base > 0, base, 0.001) * 40, size=4000)
        winners = pd.Series(matrix.index[(matrix.to_numpy() @ samples.T).argmax(axis=0)])
        share_first = (winners.value_counts(normalize=True) * 100).reindex(matrix.index, fill_value=0).sort_values()
        fig = px.bar(x=share_first.values, y=share_first.index, orientation="h", text=share_first.values,
                     labels={"x": "% of 4,000 random weight sets where it ranks first", "y": ""})
        fig.update_traces(marker_color=GREEN, texttemplate="%{text:.0f}%", textposition="outside")
        fig.update_xaxes(range=[0, 110])
        st.plotly_chart(chart_style(fig, 280), width="stretch")
        leaders = share_first[share_first >= 10].sort_values(ascending=False)
        if len(leaders) > 1:
            st.write("Under random weight changes, " + " and ".join(f"{n} wins {v:.0f}%" for n, v in leaders.items())
                     + " of the time. The leaders win on different hazards (flooding and Air quality), so the "
                       "evidence supports a hybrid scheme: rain gardens for surface water and a tree belt along "
                       "the A4540 for particulates.")
        else:
            st.write(f"{share_first.index[-1]} ranks first in {share_first.iloc[-1]:.0f}% of random weight sets, "
                     "so the choice holds up well when the weights change.")

    st.divider()
    st.subheader("Phased rehabilitation roadmap (closure-style plan)")
    st.write("Mines must plan their closure before work starts, with phases, measurable completion criteria and "
             "aftercare agreed with the community (ICMM, 2019). We use the same structure, so each step can be "
             "checked on this dashboard.")
    roadmap = pd.DataFrame(ROADMAP, columns=["Phase", "start", "end", "When", "Actions", "Completion criterion",
                                             "Mining closure parallel"])
    no2_now = yearly_mean("Ladywood (background)", "NO2")
    roadmap.loc[4, "Completion criterion"] += f" (now {num(no2_now, unit=' µg/m³')}, guideline 10)"
    fig = go.Figure(go.Bar(x=roadmap["end"] - roadmap["start"], base=roadmap["start"], y=roadmap["Phase"],
                           orientation="h", marker_color=[GREY, NAVY, NAVY, ORANGE, GREEN],
                           text=roadmap["When"], textposition="auto",
                           hovertemplate="%{y}: %{text}<extra></extra>"))
    fig.update_yaxes(autorange="reversed", title=None)
    fig.update_xaxes(title="Months from start", range=[0, 120], dtick=12)
    st.plotly_chart(chart_style(fig, 260), width="stretch")
    st.dataframe(roadmap[["Phase", "When", "Actions", "Completion criterion", "Mining closure parallel"]],
                 hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# Data and sources
# ---------------------------------------------------------------------------
with data_tab, safe_section("Data and sources"):
    st.subheader("Data used")
    c1, c2, c3 = st.columns(3)
    c1.metric("Hourly Air quality records", f"{len(aq):,}")
    c2.metric("Days of rainfall", f"{len(rain):,}")
    c3.metric("Elevation points", f"{len(elev):,}")
    st.markdown("""
| Data | Source | Used for |
|---|---|---|
| Hourly NO2, PM2.5, PM10 | [DEFRA UK-AIR](https://uk-air.defra.gov.uk/data/) | Indicators, Air quality charts |
| Daily rainfall | [Open-Meteo historical weather API](https://open-meteo.com/en/docs/historical-weather-api) | Rainfall, runoff and sewer overload |
| Ground level | [Copernicus GLO-90 elevation model](https://doi.org/10.5270/ESA-c5d3d65), via the [Open-Meteo elevation API](https://open-meteo.com/en/docs/elevation-api) | Hazard map, flood check |
| Climate risk (CRVA), surface water flood extent, deprivation, population, green space, modelled NO2/PM2.5 | [Birmingham City Council CRVA 2025 map service](https://maps.birmingham.gov.uk/server/rest/services/CRVA/CRVA_2025/MapServer) | Overview, hazard map, zone air ratings, flood check |
| Community figures | [Engineering for People Design Challenge 2025-26](https://www.ewb-uk.org/upskill/design-challenges/engineering-for-people-design-challenge/) | Community needs |
| Unit costs and storage | CIRIA C753 *The SuDS Manual*, via our research report | Planner |
| Slope stability method and targets | Duncan, Wright and Brandon (2014) *Soil strength and slope stability*; Read and Stacey (2009) | Land stability check |
| Closure planning structure | [ICMM (2019) Integrated mine closure: good practice guide](https://www.icmm.com/website/publications/pdfs/environmental-stewardship/2019/guidance_integrated-mine-closure.pdf) | Phased roadmap |
| Air quality guidelines | [WHO 2021 guidelines](https://www.who.int/publications/i/item/9789240034228) | Limit lines |
| Base maps | OpenStreetMap contributors, OpenTopoMap | Hazard map |
""")
    st.subheader("Fact check against the CRVA 2025 data")
    st.write("We cross-checked the figures we had gathered against Birmingham City Council's CRVA 2025 map "
             "service (checked 22 October 2026).")
    no2_bg = yearly_mean("Ladywood (background)", "NO2")
    pm25_bg = yearly_mean("Ladywood (background)", "PM2.5")
    facts = pd.DataFrame([
        ["NO2 is below the UK limit but above the WHO guideline", f"DEFRA: {num(no2_bg, unit=' µg/m³')} (12 months)",
         "Modelled 25-48 µg/m³ across our zones (older year)", "Agrees"],
        ["PM2.5 is above the WHO guideline everywhere", f"DEFRA: {num(pm25_bg, unit=' µg/m³')}; research report",
         "Modelled 10.2-12.0 µg/m³ at every zone", "Agrees"],
        ["10% of residents at severe flood risk", "Challenge Pack p.44",
         "1% of ward area flooded; 3.2% of buildings touch the extent, 13.8% within 10 m", "Plausible (residents not mapped)"],
        ["Flood risk comes from surface water", "Our assumption",
         "No river flood zone 2 or 3 inside the ward", "Confirmed"],
        ["Our zone flood ratings", "Desk estimates",
         f"{agree} of {len(ZONES)} within one point of the EA map (Hazard map tab)", "Checked; one corrected"],
        ["5 m² of green space per person", "Challenge Pack p.16 (constituency)",
         "6.5 m² per person in the ward", "Broadly agrees; both below WHO 9 m²"],
        ["Ward population 26,900", "Research report",
         "32,377 (mid-2019 estimate)", "Updated - older figure"],
        ["63% of LSOAs in the most deprived 10%", "Research report (constituency)",
         "6 of 16 (38%) in the ward", "Different area - do not mix"],
        ["72% of neighbourhoods have under 10% tree cover", "Challenge Pack p.16",
         "Woodland is 0.6% of the ward (street trees not counted)", "Cannot check directly"],
        ["Summerfield Park is in Ladywood", "Our worksite list",
         "Just outside the ward boundary", "Corrected"],
    ], columns=["Claim", "Our source", "CRVA 2025 shows", "Result"])
    st.dataframe(facts, hide_index=True, width="stretch")

    st.subheader("Known limitations")
    st.write("- The CRVA summer temperature layer gives values of 12-14 °C, which cannot be summer maximums, "
             "so we have not used it until we know its units.\n"
             "- The modelled NO2 and PM2.5 do not state their year.\n"
             "- Flood ratings are checked against the EA surface water map, which is itself a national screening "
             "map; land ratings are still our own estimates.\n"
             "- The runoff and sewer overload model uses one runoff coefficient for the whole estate and daily "
             "rainfall only, so it cannot show which street floods or short, intense storms.\n"
             "- The slope check is a screening calculation with assumed soil values, not a site investigation.\n"
             "- Worksite locations are proposals, not surveyed sites.")
    d1, d2 = st.columns(2)
    d1.download_button("Download Air quality data (CSV)", aq.to_csv(index=False), "ladywood_air_quality.csv")
    d2.download_button("Download rainfall data (CSV)", rain.to_csv(index=False), "ladywood_rainfall.csv")
