"""
Airport Operations Intelligence Dashboard
========================================
Reads the Gold models produced by dbt in PostgreSQL.

Run locally:
    streamlit run streamlit/backfill_dashboard.py

Run in Docker:
    docker compose up -d streamlit
"""

import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg2
import streamlit as st
from dotenv import load_dotenv


ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=False)

st.set_page_config(
    page_title="Airport Operations Intelligence",
    layout="wide",
)

TEMPLATE = "plotly_white"

Q_AIRPORT_SUMMARY = """
SELECT
    airport_icao,
    city,
    SUM(total_arrivals) AS arrivals,
    SUM(total_departures) AS departures,
    SUM(total_movements) AS total_movements,
    ROUND(AVG(total_movements), 0) AS avg_daily,
    MIN(flight_date) AS data_from,
    MAX(flight_date) AS data_to,
    COUNT(DISTINCT flight_date) AS days
FROM "GOLD".gld_daily_airport_traffic
GROUP BY airport_icao, city
ORDER BY total_movements DESC, airport_icao
"""

Q_DAILY_TREND = """
SELECT
    flight_date,
    airport_icao,
    city,
    total_arrivals,
    total_departures,
    total_movements
FROM "GOLD".gld_daily_airport_traffic
ORDER BY flight_date, airport_icao
"""

Q_HOURLY = """
SELECT
    airport_icao,
    city,
    departure_hour_local,
    SUM(flight_count) AS flights
FROM "GOLD".gld_hourly_flight_activity
GROUP BY airport_icao, city, departure_hour_local
ORDER BY airport_icao, departure_hour_local
"""

Q_AIRLINE_BY_AIRPORT = """
SELECT
    airport_icao,
    city,
    airline_name,
    alliance,
    SUM(total_flights) AS flights
FROM "GOLD".gld_airline_traffic
GROUP BY airport_icao, city, airline_name, alliance
ORDER BY airport_icao, flights DESC
"""

Q_ROUTES = """
SELECT
    departure_airport_icao,
    arrival_airport_icao,
    departure_city,
    arrival_city,
    total_flights,
    ROUND(avg_duration_min::numeric, 0) AS avg_duration_min,
    unique_aircraft,
    days_with_service
FROM "GOLD".gld_route_analysis
ORDER BY total_flights DESC, departure_airport_icao, arrival_airport_icao
"""


def get_connection():
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        user=os.getenv("POSTGRES_USER", "airflow"),
        password=os.getenv("POSTGRES_PASSWORD", "airflow"),
        database=os.getenv("POSTGRES_DB", "airflow"),
        connect_timeout=10,
        application_name="airport_streamlit_dashboard",
    )


@st.cache_data(ttl=300)
def run_query(sql: str) -> pd.DataFrame:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            columns = [column[0].lower() for column in cursor.description]
            rows = cursor.fetchall()

        return pd.DataFrame(rows, columns=columns)
    finally:
        conn.close()


def prepare_numeric(df, columns):
    result = df.copy()
    for column in columns:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    return result


def hour_label(value):
    if pd.isna(value):
        return "Unknown"

    total_minutes = round(float(value) * 60) % (24 * 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}"


st.title("Airport Operations Intelligence")

with st.sidebar:
    st.header("Data controls")
    st.caption('Source: PostgreSQL schema "GOLD"')

    if st.button("Refresh data", use_container_width=True):
        run_query.clear()

    st.caption("Query results are cached for up to 5 minutes.")

try:
    airport_df = run_query(Q_AIRPORT_SUMMARY)
    daily_df = run_query(Q_DAILY_TREND)
    hourly_df = run_query(Q_HOURLY)
    airline_df = run_query(Q_AIRLINE_BY_AIRPORT)
    routes_df = run_query(Q_ROUTES)
except Exception as exc:
    st.error(
        "Unable to read the Gold models. "
        "Check the database configuration and the dbt execution."
    )
    with st.expander("Technical details"):
        st.code(str(exc), language="text")
    st.stop()

if airport_df.empty:
    st.warning(
        "No airport data is available in the Gold models. "
        "Check OpenSky ingestion and run the dbt models."
    )
    st.stop()

airport_df = prepare_numeric(
    airport_df,
    ["arrivals", "departures", "total_movements", "avg_daily", "days"],
)
daily_df = prepare_numeric(
    daily_df,
    ["total_arrivals", "total_departures", "total_movements"],
)
hourly_df = prepare_numeric(
    hourly_df,
    ["departure_hour_local", "flights"],
)
airline_df = prepare_numeric(airline_df, ["flights"])
routes_df = prepare_numeric(
    routes_df,
    [
        "total_flights",
        "avg_duration_min",
        "unique_aircraft",
        "days_with_service",
    ],
)

daily_df["flight_date"] = pd.to_datetime(daily_df["flight_date"])

airport_options = airport_df["airport_icao"].tolist()
city_map = dict(zip(airport_df["airport_icao"], airport_df["city"]))

selected = st.selectbox(
    "Select your airport",
    options=airport_options,
    format_func=lambda code: (
        f"{code} - {city_map.get(code) or 'Unknown city'}"
    ),
)

my = airport_df.loc[airport_df["airport_icao"] == selected].iloc[0]
my_daily = daily_df.loc[
    daily_df["airport_icao"] == selected
].sort_values("flight_date").copy()

st.caption(
    f"Selected airport reporting period: {my['data_from']} to {my['data_to']} "
    f"| {int(my['days'])} dates with data | Source: OpenSky Network"
)

st.info(
    "These indicators describe the observations available in this dataset. "
    "They are not a complete measure of airport capacity, congestion, "
    "passenger traffic or airline market share."
)

st.divider()

# ---------------------------------------------------------------------
# 1. Observed traffic
# ---------------------------------------------------------------------
st.header("1 - Observed Traffic Overview")

k1, k2, k3, k4, k5 = st.columns(5)

k1.metric("Total Movements", f"{int(my['total_movements']):,}")
k2.metric("Avg per Recorded Date", f"{float(my['avg_daily']):,.0f}")
k3.metric("Arrivals", f"{int(my['arrivals']):,}")
k4.metric("Departures", f"{int(my['departures']):,}")

imbalance = int(my["departures"]) - int(my["arrivals"])
total_movements = float(my["total_movements"])
imbalance_pct = (
    imbalance / total_movements * 100
    if total_movements > 0
    else 0
)

k5.metric(
    "Arr/Dep Imbalance",
    f"{imbalance_pct:+.1f}%",
    delta=f"{imbalance:+,} movements",
    delta_color="off",
)

st.caption(
    "An imbalance describes the available records; it does not by itself "
    "demonstrate aircraft repositioning or a need to change gate allocation. "
    "The daily average includes only dates present in the model."
)

st.divider()

# ---------------------------------------------------------------------
# 2. Daily trends and comparison
# ---------------------------------------------------------------------
st.header("2 - Daily Volume Trend & Peer Comparison")

peer_avg = (
    daily_df.loc[daily_df["airport_icao"] != selected]
    .groupby("flight_date", as_index=False)["total_movements"]
    .mean()
)

col_trend, col_bench = st.columns([3, 2])

with col_trend:
    fig_trend = go.Figure()

    fig_trend.add_trace(
        go.Scatter(
            x=my_daily["flight_date"],
            y=my_daily["total_movements"],
            name=selected,
            mode="lines+markers",
            line=dict(color="#636EFA", width=3),
        )
    )

    if not peer_avg.empty:
        fig_trend.add_trace(
            go.Scatter(
                x=peer_avg["flight_date"],
                y=peer_avg["total_movements"],
                name="Available Peer Average",
                mode="lines",
                line=dict(color="#AAAAAA", dash="dash", width=2),
            )
        )

    fig_trend.update_layout(
        template=TEMPLATE,
        xaxis_title="Date (UTC)",
        yaxis_title="Observed Daily Movements",
        legend=dict(orientation="h", y=-0.25),
        height=350,
        margin=dict(t=10),
    )
    st.plotly_chart(fig_trend, use_container_width=True)

with col_bench:
    ranking = airport_df[
        ["airport_icao", "city", "avg_daily"]
    ].sort_values("avg_daily").copy()

    ranking["label"] = (
        ranking["airport_icao"]
        + " - "
        + ranking["city"].fillna("Unknown city")
    )

    colors = [
        "#636EFA" if code == selected else "#D3D3D3"
        for code in ranking["airport_icao"]
    ]

    fig_rank = go.Figure(
        go.Bar(
            x=ranking["avg_daily"],
            y=ranking["label"],
            orientation="h",
            marker_color=colors,
        )
    )

    fig_rank.update_layout(
        template=TEMPLATE,
        xaxis_title="Avg Movements per Recorded Date",
        yaxis_title="",
        height=350,
        margin=dict(t=10),
    )
    st.plotly_chart(fig_rank, use_container_width=True)

rank = int((airport_df["avg_daily"] > my["avg_daily"]).sum()) + 1

st.caption(
    f"Observed-volume rank: {rank} of {len(airport_df)} airports. "
    "Coverage and recorded dates may differ between airports. "
    "Missing dates are not automatically treated as zero traffic."
)

volumes = my_daily["total_movements"]

if len(volumes) >= 6:
    earlier_avg = volumes.iloc[:3].mean()
    recent_avg = volumes.iloc[-3:].mean()

    if earlier_avg > 0:
        trend_pct = (recent_avg / earlier_avg - 1) * 100
        st.caption(
            f"Latest 3 recorded dates versus earliest 3 recorded dates: "
            f"{trend_pct:+.1f}% observed movements."
        )

st.divider()

# ---------------------------------------------------------------------
# 3. Hourly profile
# ---------------------------------------------------------------------
st.header("3 - Hourly Observation Profile")

st.warning(
    "Model limitation: the current hourly model uses departure timestamps "
    "for both arrival and departure observations and applies a fixed UTC "
    "offset. This is not yet a validated local-time airport movement profile."
)

my_hourly = hourly_df.loc[
    hourly_df["airport_icao"] == selected
].copy()

unknown_hour_count = int(
    my_hourly.loc[
        my_hourly["departure_hour_local"].isna(), "flights"
    ].sum()
)

my_hourly = my_hourly.dropna(
    subset=["departure_hour_local", "flights"]
).sort_values("departure_hour_local")

if my_hourly.empty:
    st.info("No hourly observations with a known local-hour value.")
else:
    peak = my_hourly.loc[my_hourly["flights"].idxmax()]
    hourly_total = my_hourly["flights"].sum()

    fig_hourly = go.Figure(
        go.Bar(
            x=my_hourly["departure_hour_local"],
            y=my_hourly["flights"],
            marker_color="#636EFA",
            customdata=[
                hour_label(value)
                for value in my_hourly["departure_hour_local"]
            ],
            hovertemplate=(
                "Model hour: %{customdata}"
                "<br>Observations: %{y:,}<extra></extra>"
            ),
        )
    )

    fig_hourly.update_layout(
        template=TEMPLATE,
        xaxis_title="Model Local-Hour Value",
        yaxis_title="Observations over Selected Airport Reporting Period",
        xaxis=dict(dtick=1),
        height=350,
        margin=dict(t=10),
    )
    st.plotly_chart(fig_hourly, use_container_width=True)

    c1, c2, c3 = st.columns(3)
    c1.metric("Peak Model Hour", hour_label(peak["departure_hour_local"]))
    c2.metric("Peak Observations", f"{int(peak['flights']):,}")
    c3.metric(
        "Share of Known-Hour Observations",
        f"{peak['flights'] / hourly_total * 100:.1f}%"
        if hourly_total > 0
        else "N/A",
    )

if unknown_hour_count:
    st.caption(
        f"{unknown_hour_count:,} observations have no local-hour value "
        "and are excluded from the hourly chart."
    )

st.divider()

# ---------------------------------------------------------------------
# 4. Airline composition
# ---------------------------------------------------------------------
st.header("4 - Observed Airline Composition")

all_airlines = airline_df.loc[
    airline_df["airport_icao"] == selected
].copy()

if all_airlines.empty:
    st.info("No airline observations are available for this airport.")
else:
    observed_total = all_airlines["flights"].sum()
    unknown_total = all_airlines.loc[
        all_airlines["airline_name"].isna(), "flights"
    ].sum()

    st.caption(
        f"Records with an unmatched airline name: "
        f"{int(unknown_total):,} of {int(observed_total):,} "
        "airline-model observations. Records without a callsign prefix "
        "are excluded upstream."
    )

    matched = all_airlines.dropna(subset=["airline_name"])

    my_airlines = (
        matched.groupby("airline_name", as_index=False)["flights"]
        .sum()
        .sort_values("flights", ascending=False)
        .reset_index(drop=True)
    )

    matched_total = my_airlines["flights"].sum()

    if my_airlines.empty or matched_total <= 0:
        st.info("No matched airlines are available for the composition chart.")
    else:
        my_airlines["share_pct"] = (
            my_airlines["flights"] / matched_total * 100
        )

        top5 = my_airlines.head(5).copy()
        others_count = matched_total - top5["flights"].sum()
        pie_data = top5[["airline_name", "flights"]].copy()

        if others_count > 0:
            pie_data = pd.concat(
                [
                    pie_data,
                    pd.DataFrame(
                        {
                            "airline_name": ["Other Matched Airlines"],
                            "flights": [others_count],
                        }
                    ),
                ],
                ignore_index=True,
            )

        col_pie, col_table = st.columns([2, 3])

        with col_pie:
            fig_pie = px.pie(
                pie_data,
                values="flights",
                names="airline_name",
                hole=0.4,
                template=TEMPLATE,
            )
            fig_pie.update_traces(
                textposition="inside",
                textinfo="percent+label",
            )
            fig_pie.update_layout(
                height=350,
                margin=dict(t=10, b=10),
                showlegend=False,
            )
            st.plotly_chart(fig_pie, use_container_width=True)

        with col_table:
            display_airlines = top5.rename(
                columns={
                    "airline_name": "Airline",
                    "flights": "Observed Records",
                    "share_pct": "Share of Matched Records %",
                }
            )

            st.dataframe(
                display_airlines,
                use_container_width=True,
                hide_index=True,
            )

            hhi = (my_airlines["share_pct"] ** 2).sum()
            st.metric("Observed Composition HHI", f"{hhi:,.0f}")

        st.caption(
            "Shares and HHI are calculated over matched airline-model "
            "records only. They do not measure passenger, seat, revenue "
            "or complete airport market shares."
        )

st.divider()

# ---------------------------------------------------------------------
# 5. Routes
# ---------------------------------------------------------------------
st.header("5 - Observed Route Connectivity")

st.caption(
    "Current route counts inherit the Silver observation grain: "
    "the same flight may be represented as both an arrival and a departure. "
    "The route model has not yet been revised to count unique flights."
)

airport_routes = routes_df.loc[
    (routes_df["departure_airport_icao"] == selected)
    | (routes_df["arrival_airport_icao"] == selected)
].copy()

if airport_routes.empty:
    st.info("No routes are available for this airport.")
else:
    destinations = set(
        airport_routes.loc[
            airport_routes["departure_airport_icao"] == selected,
            "arrival_airport_icao",
        ].dropna()
    )

    destinations.update(
        airport_routes.loc[
            airport_routes["arrival_airport_icao"] == selected,
            "departure_airport_icao",
        ].dropna()
    )
    destinations.discard(selected)

    r1, r2 = st.columns(2)
    r1.metric("Directed Route Pairs", len(airport_routes))
    r2.metric("Other Airports Connected", len(destinations))

    top_routes = airport_routes.sort_values(
        "total_flights", ascending=False
    ).head(10).copy()

    top_routes["route"] = (
        top_routes["departure_airport_icao"]
        + " → "
        + top_routes["arrival_airport_icao"]
    )

    col_routes, col_mix = st.columns([3, 2])

    with col_routes:
        fig_routes = px.bar(
            top_routes.sort_values("total_flights"),
            x="total_flights",
            y="route",
            orientation="h",
            color="avg_duration_min",
            color_continuous_scale="Blues",
            labels={
                "total_flights": "Observed Records",
                "route": "",
                "avg_duration_min": "Avg Duration (min)",
            },
            template=TEMPLATE,
        )
        fig_routes.update_layout(
            height=400,
            margin=dict(t=10),
            yaxis=dict(dtick=1),
        )
        st.plotly_chart(fig_routes, use_container_width=True)

    with col_mix:
        valid_duration_routes = airport_routes.dropna(
            subset=["avg_duration_min"]
        ).copy()

        def classify_duration(minutes):
            if minutes < 120:
                return "Under 2 hours"
            if minutes < 360:
                return "2 to under 6 hours"
            return "6 hours or more"

        valid_duration_routes["duration_band"] = (
            valid_duration_routes["avg_duration_min"].apply(
                classify_duration
            )
        )

        mix = (
            valid_duration_routes.groupby(
                "duration_band", as_index=False
            )["total_flights"]
            .sum()
        )

        if not mix.empty:
            fig_mix = px.pie(
                mix,
                values="total_flights",
                names="duration_band",
                hole=0.4,
                template=TEMPLATE,
                title="All Route Records by Route-Average Duration",
            )
            fig_mix.update_traces(
                textposition="inside",
                textinfo="percent+label",
            )
            fig_mix.update_layout(
                height=350,
                margin=dict(t=50, b=10),
                showlegend=False,
            )
            st.plotly_chart(fig_mix, use_container_width=True)

    st.caption(
        "Duration bands classify each route by its average duration, "
        "not individual flights. Duration outliers are still included "
        "in the current Gold models."
    )

st.divider()

st.caption(
    "Airport Operations Intelligence | "
    "Source: OpenSky Network API | "
    "Pipeline: Airflow → PostgreSQL → dbt → Streamlit | "
    "Dataset coverage and quality limitations apply."
)