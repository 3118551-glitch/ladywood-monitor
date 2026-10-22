# Ladywood Environmental Monitor - Progress Report 3 prototype

Simpler, in-progress version of the dashboard at the stage expected for Progress Report 3.

Run: `./run_prototype.sh` from the project folder (or `streamlit run app.py` inside this folder).
Refresh data: `python get_data.py` inside this folder.

Data: DEFRA UK-AIR (air quality), Open-Meteo (rainfall), Birmingham City Council CRVA 2025 map service
(climate risk by neighbourhood, surface-water flood extent, ward boundary, deprivation, population, modelled NO2/PM2.5).
The Data and sources tab includes a fact check of our figures against the CRVA data.

Windows: double-click run_windows.bat.

Tabs: Overview, Air quality, Rainfall and flooding, Hazard map, Interventions (planner + decision matrix), Data and sources.
Planned for the final version: slope stability check, closure-style plan, flood zones checked against the EA map.
