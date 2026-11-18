# Ladywood Environmental Monitor

FEBE1004A Design Project, MINN Team 25 (School of Mining Engineering).

An interactive Streamlit dashboard for Ladywood, Birmingham, that applies mining engineering ideas
(mine water management, dust monitoring, slope stability and closure planning) to the ward's flooding,
air quality and land problems, for the Engineering for People Design Challenge with CIVIC SQUARE.

## Run it
- Windows: double-click `run_windows.bat`
- Anywhere: `pip install -r requirements.txt` then `streamlit run app.py`

The dashboard reads saved files in `data/`, so it works offline. **Refresh live data** in the sidebar
downloads the latest DEFRA and Open-Meteo readings. If the download fails (no internet, a service is down),
the saved data is kept and a warning is shown. Run `python get_data.py` to refresh every file, including
elevation and the CRVA map layers.

## Tabs
| Tab | What it shows |
|---|---|
| Overview | Key indicators, community needs, project status |
| Air quality | Monthly means against UK and WHO values, daily cycle, measured vs modelled |
| Rainfall and flooding | Daily rainfall, estate runoff, days the sewers are likely overloaded |
| Hazard map | CRVA risk, EA surface water extent, risk zones, worksites; flood ratings checked against the EA map; land stability check |
| Interventions | Rehabilitation planner, decision matrix, robustness check, phased (closure-style) roadmap |
| Data and sources | Sources, fact check, limitations, CSV downloads |

## Data
DEFRA UK-AIR (hourly NO2, PM2.5, PM10 at Birmingham Ladywood and A4540 Roadside), Open-Meteo (daily rainfall),
Copernicus GLO-90 elevation (via Open-Meteo), Birmingham City Council CRVA 2025 map service (climate risk,
EA surface water extent, ward boundary), Engineering for People Challenge pack, and CIRIA C753 cost benchmarks
from our research report.

`prototype_pr3/` is the Progress Report 3 version, kept for reference. Its data files are also the
dashboard's backup copy if a file in `data/` is damaged.
