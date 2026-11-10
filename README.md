# Air-tracker-Flight-analytics

Air Tracker is an end-to-end flight analytics project designed to analyze airline operations, identify the factors responsible for delays and cancellations, and reveal patterns in routes, airports, carriers, and travel periods. The project converts large volumes of historical flight records into operational insights that can support passengers, airlines, and airport-management teams.
# Flight analytics

A Python project that collects flight operations data from AeroDataBox through RapidAPI, stores it in MySQL, and explores it through SQL notebooks and an interactive Streamlit dashboard.

```text
AeroDataBox (RapidAPI) -> air_tracker.ipynb -> MySQL
                                             |-> app.py (Streamlit dashboard)
                                             |-> flight_sql_queries.ipynb
```

## Features

- Filter flights by status, airline, and scheduled departure date.
- View flight totals, delayed and canceled flights, airline counts, and route counts.
- Compare flight statuses, the 12 busiest airlines in the selected data, and the top 10 destination airports.
- Inspect the 50 most recent flights matching the filters.
- Collect airport metadata, arrivals, departures, and aircraft information, with optional aircraft API enrichment.
- Calculate daily airport delay summaries from stored flight timestamps.
- Explore 11 SQL analyses covering aircraft utilization, airport traffic, flight classification, airline statuses, cancellations, and delays.
- Cache API responses, pace requests, and limit requests per notebook run.

## Project structure

| File | Purpose |
| --- | --- |
| `app.py` | Streamlit dashboard backed by MySQL. |
| `Flight_analytics_database.py` | Database configuration, schema creation, migrations, indexes, and flight identity helpers. |
| `air_tracker.ipynb` | AeroDataBox data collection and MySQL loading pipeline. |
| `flight_sql_queries.ipynb` | SQL analysis notebook with pandas results. |
| `requirements.txt` | Python dependencies. |
| `.streamlit/config.toml` | Dashboard theme and Streamlit settings. |
| `.streamlit/secrets.toml.example` | Template for local MySQL credentials. |
| `Flight Analytics.pdf` | Accompanying project document. |

API responses are cached locally under `.cache/aerodatabox/`. The `.cache/`, `.venv/`, `backups/`, and local secrets file are excluded by `.gitignore`.

## Requirements

- Python **3.11 or newer**; the database module uses the standard-library `tomllib` module.
- A running MySQL server and an account with database, table, index, and migration privileges for initialization.
- A notebook editor such as VS Code with Jupyter support, or a separately installed Jupyter frontend.
- A RapidAPI key with access to the AeroDataBox endpoints used by the collection notebook. Available dates and endpoints depend on your API access.

The dashboard and SQL notebook use data already stored in MySQL; only data collection requires the API key.

## Setup

Run these commands from the project directory. The examples use Windows PowerShell.

### 1. Create an environment and install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

These commands use the environment's Python directly, so activating it is optional. On macOS or Linux, use `.venv/bin/python` instead of `.\.venv\Scripts\python.exe`.

### 2. Configure MySQL

If `.streamlit/secrets.toml` does not already exist, copy the example:

```powershell
Copy-Item .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edit `.streamlit/secrets.toml` with your connection details:

```toml
[mysql]
host = "localhost"
port = 3306
database = "flight_analytics"
user = "root"
password = "replace-with-your-password"
```

You can alternatively set environment variables in the terminal that launches Python or your notebook editor:

```powershell
$env:MYSQL_HOST = "localhost"
$env:MYSQL_PORT = "3306"
$env:MYSQL_DATABASE = "flight_analytics"
$env:MYSQL_USER = "your-mysql-user"
$env:MYSQL_PASSWORD = "your-mysql-password"
```

Nonempty environment values take precedence over the local secrets file. Host, port, database, and user default to `localhost`, `3306`, `flight_analytics`, and `root`; a password must be provided. The project does not automatically load `.env` files. Keep real credentials out of version control.

### 3. Initialize the database

```powershell
.\.venv\Scripts\python.exe Flight_analytics_database.py
```

The script creates the database, four tables, and flight query indexes. It also attempts to migrate older schemas, including date/time columns and flight IDs. Back up an existing database before running migrations, as they alter tables and replace migrated columns.

Successful initialization prints:

```text
MySQL database flight_analytics is ready
```

Initialization creates the schema; load flight records in the next step.

### 4. Collect flight data

Set your API key before starting the notebook editor so its Python kernel inherits the variable:

```powershell
$env:RAPIDAPI_KEY = "your-rapidapi-key"
```

Open `air_tracker.ipynb`, select `.venv` as the Python kernel, and run its cells in order. The notebook prompts for an API key or MySQL password when those values are not configured.

The pipeline loads airport metadata, collects flights, populates aircraft records, and calculates daily airport delay summaries. By default, it requests **yesterday's data**, based on the machine's local date, for these 15 airports:

```text
DXB SIN LHR JFK SYD DOH BKK CDG MAA DEL BOM BLR HYD CCU COK
```

Edit `AIRPORT_CODES` in the configuration cell to change the collection scope. Edit `flight_date` in the flight collection cell to request a different date supported by your API access. Each airport's flight collection uses two 12-hour windows.

Optional pipeline settings, configured before starting or restarting the kernel:

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `MAX_API_REQUESTS_PER_RUN` | `60` | Maximum network request attempts in a run, including retries. |
| `ENABLE_AIRCRAFT_ENRICHMENT` | `false` | Set to `true` to fetch additional aircraft metadata through the API. |
| `MAX_AIRCRAFT_REQUESTS_PER_RUN` | `15` | Maximum aircraft records selected for optional enrichment. |

Requests are spaced at least 1.1 seconds apart. Airport and aircraft responses use a seven-day cache; flight responses use a 24-hour cache. The notebook pauses further API work when its request budget is reached or quota handling requires it. This can leave a collection incomplete; inspect the notebook's messages before relying on the resulting totals. Request caps count HTTP attempts rather than provider billing units.

### 5. Start the dashboard

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the local URL printed by Streamlit, normally `http://localhost:8501`. Use the sidebar filters and the **Status overview**, **Destinations**, and **Flight data** tabs to explore loaded records.

The dashboard caches database results for five minutes. It reads MySQL when the app reruns and the cache has expired; there is no automatic data collection or timed page refresh. After loading new data, clear Streamlit's cache or restart the dashboard to see updates immediately.

### 6. Run the SQL analyses

Open `flight_sql_queries.ipynb` with the same Python environment and run the helper cell before the query cells. The notebook covers:

1. Total flights by aircraft model.
2. Aircraft assigned to more than five flights.
3. Airports with more than five outbound flights.
4. Top three destination airports by arrivals.
5. Domestic or international flight classification.
6. Five most recent arrivals at DEL.
7. Airports with no arriving flights.
8. Flight status counts by airline.
9. Canceled flights with aircraft and airport details.
10. City pairs served by more than two aircraft models.
11. Delayed-flight percentages by destination airport.

## Data model and interpretation

| Table | Contents | Identifier |
| --- | --- | --- |
| `airport` | Airport codes, names, location, country, and timezone. | `airport_id`; unique IATA and ICAO codes. |
| `aircraft` | Registration, model, manufacturer, type code, and owner. | `aircraft_id`; unique registration. |
| `flights` | Routes, flight numbers, aircraft, airline codes, statuses, and scheduled/actual/revised times. | SHA-256 `flight_id` for a dated flight occurrence. |
| `airport_delays` | Daily flight, delay, and cancellation summaries per airport. | `delay_id`; unique airport/date pair. |

Flight IDs incorporate the flight number, origin, destination, and occurrence time or fallback date. The ingestion notebook uses upserts for airport, flight, and aircraft records and replaces daily delay summaries for the selected airport/date pairs. Tables are related through airport codes and aircraft registrations; the schema does not declare foreign keys.

- **Local timestamps:** API local timestamps are stored as timezone-naive MySQL `DATETIME` values. Departure filters use the departure airport's local date. Cross-timezone comparisons need additional timezone handling.
- **Delay definitions:** The dashboard's delayed count and the SQL destination delay percentage count records whose status is exactly `Delayed`. The daily summary also counts a flight as delayed when its actual departure or arrival is more than 15 minutes late. Summary averages and medians use available actual-versus-scheduled differences, with negative values clamped to zero.
- **Coverage:** Results describe the data collected for the configured airports and dates. Airport names fall back to codes when metadata is missing; domestic/international classification can be `Unknown` when either airport's country is unavailable.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `MySQL password is not configured` | Set `MYSQL_PASSWORD` or add a password under `[mysql]` in `.streamlit/secrets.toml`. |
| Connection refused or access denied | Confirm MySQL is running and check the host, port, user, password, and account privileges. |
| Missing database or tables | Run `Flight_analytics_database.py` with the same database configuration as the dashboard. |
| Dashboard reports an empty flights table | Run the collection notebook and check that flights were successfully loaded. |
| API rejects a request or pauses collection | Review the reported status and quota messages, API key access, requested dates, and request budget. |
| Dashboard still shows old data | Clear Streamlit's cache or restart the app after updating MySQL. |
| Imports fail in a notebook | Select the project's `.venv` kernel and install `requirements.txt` into that environment. |

Restart the dashboard or notebook kernel after changing credentials or environment variables, because configuration is read when the database module is imported.
