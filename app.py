from datetime import date

import mysql.connector
import pandas as pd
import streamlit as st

from Flight_analytics_database import get_database_config


st.set_page_config(
    page_title="Flight analytics",
    page_icon=":material/flight:",
    layout="wide",
)


@st.cache_data(ttl=300, max_entries=2, show_spinner="Loading flight data...")
def load_flights():
    """Load source data using a short-lived, per-query MySQL connection."""
    connection = mysql.connector.connect(**get_database_config())
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute(
            """
            SELECT
                f.flight_id,
                f.flight_number,
                COALESCE(NULLIF(f.aircraft_registration, ''), f.aircraft_model, 'Unknown') AS aircraft,
                COALESCE(NULLIF(f.airline_code, ''), 'Unknown') AS airline,
                COALESCE(NULLIF(f.status, ''), 'Unknown') AS status,
                f.origin_iata,
                COALESCE(origin.name, f.origin_iata, 'Unknown') AS origin,
                f.destination_iata,
                COALESCE(destination.name, f.destination_iata, 'Unknown') AS destination,
                f.scheduled_departure,
                f.actual_arrival
            FROM flights AS f
            LEFT JOIN airport AS origin ON origin.iata_code = f.origin_iata
            LEFT JOIN airport AS destination ON destination.iata_code = f.destination_iata
            ORDER BY f.scheduled_departure DESC
            """
        )
        columns = [description[0] for description in cursor.description]
        flights = pd.DataFrame(cursor.fetchall(), columns=columns)
    finally:
        cursor.close()
        connection.close()

    for column in ("scheduled_departure", "actual_arrival"):
        flights[column] = pd.to_datetime(flights[column], errors="coerce")
    return flights


def filter_flights(flights):
    with st.sidebar:
        st.subheader(":material/filter_alt: Filters")
        statuses = sorted(flights["status"].dropna().unique().tolist())
        selected_statuses = st.multiselect(
            "Flight status", statuses, default=statuses, key="flight_status"
        )
        airlines = sorted(flights["airline"].dropna().unique().tolist())
        selected_airlines = st.multiselect(
            "Airline (optional)", airlines, key="airline"
        )

        valid_dates = flights["scheduled_departure"].dropna().dt.date
        start_date = valid_dates.min() if not valid_dates.empty else date.today()
        end_date = valid_dates.max() if not valid_dates.empty else date.today()
        selected_dates = st.date_input(
            "Scheduled departure (airport local time)",
            value=(start_date, end_date),
            min_value=start_date,
            max_value=end_date,
            key="departure_dates",
        )

    filtered = flights[flights["status"].isin(selected_statuses)]
    if selected_airlines:
        filtered = filtered[filtered["airline"].isin(selected_airlines)]
    if isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
        departure_dates = filtered["scheduled_departure"].dt.date
        filtered = filtered[departure_dates.between(*selected_dates)]
    return filtered


def show_overview(flights):
    delayed = flights["status"].eq("Delayed")
    canceled = flights["status"].isin(["Canceled", "Cancelled"])

    with st.container(horizontal=True):
        st.metric("Flights", f"{len(flights):,}", border=True)
        st.metric(
            "Delayed",
            f"{delayed.sum():,}",
            f"{delayed.mean() * 100:.1f}%" if len(flights) else "0%",
            border=True,
        )
        st.metric(
            "Canceled",
            f"{canceled.sum():,}",
            f"{canceled.mean() * 100:.1f}%" if len(flights) else "0%",
            border=True,
        )
        st.metric("Airlines", f"{flights['airline'].nunique():,}", border=True)
        st.metric(
            "Routes",
            f"{flights[['origin_iata', 'destination_iata']].drop_duplicates().shape[0]:,}",
            border=True,
        )

    if flights.empty:
        st.info("No flights match the selected filters.")
        return

    status_tab, destination_tab, data_tab = st.tabs(
        ["Status overview", "Destinations", "Flight data"]
    )

    with status_tab:
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                st.subheader("Flights by status")
                status_counts = (
                    flights["status"]
                    .value_counts()
                    .rename_axis("status")
                    .reset_index(name="flights")
                )
                st.bar_chart(status_counts, x="status", y="flights", horizontal=True)
        with right:
            with st.container(border=True):
                st.subheader("Airline activity")
                airline_counts = (
                    flights["airline"]
                    .value_counts()
                    .head(12)
                    .rename_axis("airline")
                    .reset_index(name="flights")
                )
                st.bar_chart(airline_counts, x="airline", y="flights")

    with destination_tab:
        with st.container(border=True):
            st.subheader("Top destination airports")
            destinations = (
                flights.groupby(["destination_iata", "destination"], dropna=False)
                .size()
                .reset_index(name="arriving_flights")
                .sort_values("arriving_flights", ascending=False)
                .head(10)
            )
            destinations["airport"] = (
                destinations["destination_iata"].fillna("Unknown")
                + " · "
                + destinations["destination"].fillna("Unknown")
            )
            st.bar_chart(destinations, x="airport", y="arriving_flights")

    with data_tab:
        with st.container(border=True):
            st.subheader("Latest flights")
            columns = [
                "flight_number",
                "airline",
                "aircraft",
                "origin_iata",
                "destination_iata",
                "status",
                "scheduled_departure",
                "actual_arrival",
            ]
            st.dataframe(
                flights[columns].head(50),
                hide_index=True,
                width="stretch",
                key="latest_flights",
                column_config={
                    "scheduled_departure": st.column_config.DatetimeColumn(
                        "Scheduled departure", format="YYYY-MM-DD HH:mm"
                    ),
                    "actual_arrival": st.column_config.DatetimeColumn(
                        "Actual arrival", format="YYYY-MM-DD HH:mm"
                    ),
                },
            )


st.title(":material/flight: Flight analytics")
st.caption("Flight operations view powered by MySQL")

try:
    all_flights = load_flights()
except (mysql.connector.Error, RuntimeError, ValueError) as error:
    st.error(f"Unable to load flight data: {error}")
    st.info(
        "Run Flight_analytics_database.py and configure .streamlit/secrets.toml, "
        "then restart this dashboard."
    )
    st.stop()

if all_flights.empty:
    st.warning("The flights table is empty. Load flight data before opening the dashboard.")
    st.stop()

filtered_flights = filter_flights(all_flights)
st.caption(f"Showing {len(filtered_flights):,} of {len(all_flights):,} flights")
show_overview(filtered_flights)
