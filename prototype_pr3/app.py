# Ladywood Environmental Monitor - prototype for Progress Report 3
# FEBE1004A Design Project 5 (School of Mining Engineering)
#
# Run with:  streamlit run app.py
# Data comes from get_data.py (DEFRA UK-AIR and Open-Meteo), saved in /data.

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Ladywood Environmental Monitor", layout="wide")

# ---------------------------------------------------------------------------
# Settings and numbers we use
# ---------------------------------------------------------------------------
NAVY = "#1f4e79"
ORANGE = "#d9822b"
GREY = "#6b7280"
RED = "#b23b3b"

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

# Risk zones - ratings 1 (low) to 5 (high) are our own estimates for now.
# TODO: check flood ratings against the Environment Agency surface water map
ZONES = pd.DataFrame([
    ["Ladywood Middleway / Monument Rd", 52.4758, -1.9238, 3, 5, 2, "Air quality"],
    ["St Marks Crescent / King Edwards Rd", 52.4812, -1.9199, 4, 3, 2, "Flooding"],
    ["Ledsam St / community hub", 52.4799, -1.9237, 3, 4, 2, "Air quality"],
    ["Port Loop (brownfield)", 52.4819, -1.9308, 4, 2, 5, "Land stability"],
    ["Spring Hill / Dudley Rd", 52.4858, -1.9230, 4, 3, 3, "Flooding"],
    ["Five Ways roundabout", 52.4728, -1.9186, 3, 5, 1, "Air quality"],
    ["Birmingham Canal (Brindleyplace)", 52.4784, -1.9119, 4, 2, 3, "Flooding"],
    ["Edgbaston Reservoir (Reservoir Rd)", 52.4775, -1.9330, 2, 2, 4, "Land stability"],
], columns=["Zone", "lat", "lon", "Flood", "Air", "Land", "Main hazard"])
ZONES["Risk score"] = ZONES[["Flood", "Air", "Land"]].mean(axis=1).round(1)

WORKSITES = pd.DataFrame([
    ["Link Road verges", 52.4832, -1.9362, "Rain garden / bioswale"],
    ["A4540 Middleway", 52.4800, -1.9258, "Vegetation / tree buffer"],
    ["Port Loop canal side", 52.4825, -1.9300, "Constructed wetland"],
    ["Summerfield Park", 52.4837, -1.9408, "Detention basin"],
    ["Estate car parks", 52.4812, -1.9199, "Permeable paving"],
], columns=["Site", "lat", "lon", "Proposed intervention"])

MONITORS = pd.DataFrame([
    ["Birmingham Ladywood (DEFRA)", 52.481346, -1.918235],
    ["Birmingham A4540 Roadside (DEFRA)", 52.476145, -1.874978],
], columns=["Monitor", "lat", "lon"])


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
@st.cache_data
def load_data():
    aq = pd.read_csv("data/aq_hourly.csv", parse_dates=["time"])
    aq["site"] = aq["site"].map(SITE_NAMES)
    rain = pd.read_csv("data/rain_daily.csv", parse_dates=["date"])
    return aq, rain


aq, rain = load_data()
last_date = aq["time"].max()
last_year = aq[aq["time"] > last_date - pd.Timedelta(days=365)]


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
st.write("FEBE1004A Design Project 5, School of Mining Engineering. Prototype for Progress Report 3. "
         f"Air quality data up to {last_date:%d %B %Y}.")

st.sidebar.header("Settings")
pollutant = st.sidebar.selectbox("Pollutant", ["NO2", "PM2.5", "PM10"])
window = st.sidebar.radio("Rainfall period", ["Last 90 days", "Last 365 days"])
st.sidebar.divider()
st.sidebar.subheader("Map layers")
show_zones = st.sidebar.checkbox("Risk zones", value=True)
show_sites = st.sidebar.checkbox("Proposed worksites", value=True)
show_monitors = st.sidebar.checkbox("Air quality monitors", value=True)
map_style = st.sidebar.selectbox("Base map", ["Topographic", "Street map"])

overview, air_tab, rain_tab, map_tab, plan_tab, data_tab = st.tabs(
    ["Overview", "Air quality", "Rainfall and flooding", "Hazard map", "Interventions", "Data and sources"])

# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------
with overview:
    st.subheader("Key indicators")
    no2 = yearly_mean("Ladywood (background)", "NO2")
    pm25 = yearly_mean("Ladywood (background)", "PM2.5")
    rain_year = rain[rain["date"] > rain["date"].max() - pd.Timedelta(days=365)]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("NO2, 12-month mean", f"{no2:.1f} µg/m³")
    c1.caption("UK limit 40, WHO guideline 10")
    c2.metric("PM2.5, 12-month mean", f"{pm25:.1f} µg/m³")
    c2.caption("UK target 10, WHO guideline 5")
    c3.metric("Residents at severe flood risk", "10%")
    c3.caption("Challenge pack p.44")
    c4.metric("Rainfall, last 12 months", f"{rain_year['rain_mm'].sum():.0f} mm")
    c4.caption("Open-Meteo, Ladywood")

    st.write("Ladywood meets the UK annual limits for NO2 and PM2.5 but is above the stricter WHO "
             "guidelines. Flooding and air quality are the two hazards this dashboard focuses on.")

    left, right = st.columns(2)
    with left:
        st.subheader("Community needs")
        needs = pd.DataFrame([
            ["10%", "of residents at risk of severe flooding", "p.44"],
            ["40%", "of the population at risk of extreme heat", "p.16"],
            ["72%", "of neighbourhoods have under 10% tree cover", "p.16"],
            ["5 m²", "of green space per person", "p.16"],
            ["6%", "have a respiratory disease (e.g. asthma)", "p.48"],
            ["57.9%", "of households have no car (England 23.5%)", "p.49"],
        ], columns=["Figure", "Meaning", "Challenge pack"])
        st.dataframe(needs, hide_index=True, width="stretch")
    with right:
        st.subheader("Prototype status")
        status = pd.DataFrame([
            ["Air quality data (DEFRA)", "Done"],
            ["Rainfall data and runoff estimate", "Done"],
            ["Hazard map with risk zones", "Done (estimated ratings)"],
            ["Intervention planner and decision matrix", "Done"],
            ["Check flood zones against EA map", "In progress"],
            ["Slope stability check for brownfield landforms", "Planned"],
            ["Phased rehabilitation (closure-style) plan", "Planned"],
        ], columns=["Feature", "Status"])
        st.dataframe(status, hide_index=True, width="stretch")

# ---------------------------------------------------------------------------
# Air quality
# ---------------------------------------------------------------------------
with air_tab:
    st.subheader(f"Monthly mean {pollutant}")
    monthly = (aq.dropna(subset=[pollutant])
                 .groupby(["site", pd.Grouper(key="time", freq="MS")])[pollutant]
                 .mean().reset_index())
    fig = px.bar(monthly, x="time", y=pollutant, color="site", barmode="group",
                 color_discrete_map=SITE_COLOURS, labels={"time": "", pollutant: f"{pollutant} (µg/m³)"})
    fig.add_hline(y=LIMITS[pollutant]["UK"], line_dash="dash", line_color=GREY,
                  annotation_text=f"UK limit {LIMITS[pollutant]['UK']}", annotation_position="top left")
    fig.add_hline(y=LIMITS[pollutant]["WHO"], line_dash="dot", line_color=RED,
                  annotation_text=f"WHO guideline {LIMITS[pollutant]['WHO']}", annotation_position="top left")
    st.plotly_chart(chart_style(fig), width="stretch")

    c1, c2 = st.columns(2)
    for col, site in zip([c1, c2], SITE_NAMES.values()):
        value = yearly_mean(site, pollutant)
        col.metric(f"{site}, 12-month mean", f"{value:.1f} µg/m³")
        col.caption(f"{value / LIMITS[pollutant]['WHO']:.1f} times the WHO guideline")

    st.subheader("Average by hour of day")
    hourly = aq.dropna(subset=[pollutant]).copy()
    hourly["hour"] = hourly["time"].dt.hour
    hourly = hourly.groupby(["site", "hour"])[pollutant].mean().reset_index()
    fig2 = px.line(hourly, x="hour", y=pollutant, color="site", color_discrete_map=SITE_COLOURS,
                   labels={"hour": "Hour of day", pollutant: f"{pollutant} (µg/m³)"})
    st.plotly_chart(chart_style(fig2, 320), width="stretch")

    with st.expander("How this works"):
        st.write("Hourly data comes from two DEFRA monitors: Birmingham Ladywood, an urban background "
                 "site, and Birmingham A4540 Roadside next to the ring road. The difference between them "
                 "shows how much pollution comes from traffic. This is the same idea as comparing a "
                 "background dust monitor with a fence-line monitor at a mine. Peaks in the morning and "
                 "evening rush hours point to traffic as the main source.")

# ---------------------------------------------------------------------------
# Rainfall and flooding
# ---------------------------------------------------------------------------
with rain_tab:
    days = 90 if window == "Last 90 days" else 365
    recent = rain[rain["date"] > rain["date"].max() - pd.Timedelta(days=days)].copy()
    # rational method: runoff volume = C x rainfall depth x area (1 mm on 1 ha = 10 m3)
    recent["runoff_m3"] = RUNOFF_COEFF * recent["rain_mm"] * CATCHMENT_HA * 10

    c1, c2, c3 = st.columns(3)
    c1.metric("Total rainfall", f"{recent['rain_mm'].sum():.0f} mm")
    c2.metric("Wettest day", f"{recent['rain_mm'].max():.1f} mm")
    c3.metric("Days over 10 mm", int((recent["rain_mm"] > 10).sum()))

    fig = px.bar(recent, x="date", y="rain_mm", labels={"date": "", "rain_mm": "Rainfall (mm/day)"})
    fig.update_traces(marker_color=NAVY)
    st.plotly_chart(chart_style(fig, 300), width="stretch")

    st.subheader("Estimated runoff from the Ladywood estate")
    fig2 = px.line(recent, x="date", y="runoff_m3", labels={"date": "", "runoff_m3": "Runoff (m³/day)"})
    fig2.update_traces(line_color=ORANGE)
    st.plotly_chart(chart_style(fig2, 300), width="stretch")

    with st.expander("How this works"):
        st.write(f"Runoff uses the rational method: runoff = C × rainfall × area, with C = {RUNOFF_COEFF} "
                 f"for a mostly sealed estate and a {CATCHMENT_HA} ha catchment. Both values are estimates. "
                 "Ladywood has combined sewers, so on heavy-rain days this water mixes with sewage and can "
                 "overflow into the canals. Holding water back at the surface is the same idea as stormwater "
                 "control at a mine.")
        st.write("Next step: compare the runoff with the sewer capacity to find the days when flooding starts.")

# ---------------------------------------------------------------------------
# Hazard map
# ---------------------------------------------------------------------------
with map_tab:
    st.subheader("Risk zones and proposed worksites")
    fig = go.Figure()
    if show_zones:
        for hazard, colour in [("Flooding", NAVY), ("Air quality", ORANGE), ("Land stability", RED)]:
            z = ZONES[ZONES["Main hazard"] == hazard]
            fig.add_trace(go.Scattermap(
                lat=z["lat"], lon=z["lon"], mode="markers", name=f"Risk zone: {hazard.lower()}",
                marker=dict(size=z["Risk score"] * 7, color=colour, opacity=0.8),
                text=z["Zone"] + "<br>Risk score " + z["Risk score"].astype(str), hoverinfo="text"))
    if show_sites:
        fig.add_trace(go.Scattermap(
            lat=WORKSITES["lat"], lon=WORKSITES["lon"], mode="markers", name="Proposed worksite",
            marker=dict(size=12, color="#111827"),
            text=WORKSITES["Site"] + "<br>" + WORKSITES["Proposed intervention"], hoverinfo="text"))
    if show_monitors:
        fig.add_trace(go.Scattermap(
            lat=MONITORS["lat"], lon=MONITORS["lon"], mode="markers", name="DEFRA monitor",
            marker=dict(size=12, color="#16a34a"), text=MONITORS["Monitor"], hoverinfo="text"))

    if map_style == "Topographic":
        fig.update_layout(map=dict(style="white-bg", layers=[{
            "below": "traces", "sourcetype": "raster",
            "source": ["https://tile.opentopomap.org/{z}/{x}/{y}.png"],
            "sourceattribution": "© OpenStreetMap contributors, SRTM | © OpenTopoMap"}]))
    else:
        fig.update_layout(map=dict(style="open-street-map"))
    fig.update_layout(map_center=dict(lat=52.4800, lon=-1.9260), map_zoom=13.5, height=560,
                      margin=dict(l=0, r=0, t=0, b=0), legend=dict(x=0.01, y=0.99, bgcolor="rgba(255,255,255,0.85)"))
    st.plotly_chart(fig, width="stretch")

    st.dataframe(ZONES.drop(columns=["lat", "lon"]).sort_values("Risk score", ascending=False),
                 hide_index=True, width="stretch")
    with st.expander("How the risk score works"):
        st.write("Each zone is rated 1 (low) to 5 (high) for flooding, air quality and land stability, and "
                 "the risk score is the average. Ratings are our own estimates from the map, the DEFRA data "
                 "and the Challenge pack. We still need to check the flood ratings against the Environment "
                 "Agency's long-term flood risk map, and we plan to weight the hazards instead of averaging them.")

# ---------------------------------------------------------------------------
# Interventions: planner and decision matrix
# ---------------------------------------------------------------------------
with plan_tab:
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
    rain_year = rain[rain["date"] > rain["date"].max() - pd.Timedelta(days=365)]
    runoff_total = RUNOFF_COEFF * rain_year["rain_mm"] * CATCHMENT_HA * 10    # m3/day, whole catchment
    runoff_to_sites = 0.9 * rain_year["rain_mm"] / 1000 * area * 10           # m3/day reaching the sites
    captured = runoff_to_sites.clip(upper=storage)
    reduction = captured.sum() / runoff_total.sum() * 100

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total area", f"{area:,.0f} m²")
    m2.metric("Storage", f"{storage:,.0f} m³")
    m3.metric("Estimated cost", f"£{cost:,.0f}")
    m4.metric("Runoff captured per year", f"{reduction:.1f}%")
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
        fig.update_traces(marker_color=NAVY)
        fig.update_xaxes(range=[0, 5])
        st.plotly_chart(chart_style(fig, 320), width="stretch")
        st.write(f"Weights add up to {sum(weights)}% (scores are divided by the total, so they stay out of 5).")
        st.dataframe(matrix, width="stretch")
        top = results["Score (out of 5)"].max()
        best = results[results["Score (out of 5)"] == top]["Intervention"].tolist()
        st.info("Highest score: " + " and ".join(best) + f" ({top:.2f}).")

# ---------------------------------------------------------------------------
# Data and sources
# ---------------------------------------------------------------------------
with data_tab:
    st.subheader("Data used")
    c1, c2 = st.columns(2)
    c1.metric("Hourly air quality records", f"{len(aq):,}")
    c2.metric("Days of rainfall", f"{len(rain):,}")
    st.markdown("""
| Data | Source | Used for |
|---|---|---|
| Hourly NO2, PM2.5, PM10 | [DEFRA UK-AIR](https://uk-air.defra.gov.uk/data/) | Indicators, air quality charts |
| Daily rainfall | [Open-Meteo historical weather API](https://open-meteo.com/en/docs/historical-weather-api) | Rainfall and runoff |
| Community figures | [Engineering for People Design Challenge 2025-26](https://www.ewb-uk.org/upskill/design-challenges/engineering-for-people-design-challenge/) | Community needs |
| Unit costs and storage | CIRIA C753 *The SuDS Manual*, via our research report | Planner |
| Air quality guidelines | [WHO 2021 guidelines](https://www.who.int/publications/i/item/9789240034228) | Limit lines |
| Base maps | OpenStreetMap contributors, OpenTopoMap | Hazard map |
""")
    st.subheader("Known limitations")
    st.write("- Risk zone ratings are estimates and still need checking against the Environment Agency map.\n"
             "- The runoff model uses one runoff coefficient for the whole estate and daily rainfall only.\n"
             "- Worksite locations are proposals, not surveyed sites.")
    st.download_button("Download air quality data (CSV)", aq.to_csv(index=False), "ladywood_air_quality.csv")
