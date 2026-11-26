import os
import logging
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import execute_batch
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE SCHEMA IF NOT EXISTS RAW;
CREATE TABLE IF NOT EXISTS RAW.RAW_FLIGHTS (
    icao24 VARCHAR,
    first_seen TIMESTAMP,
    est_departure_airport VARCHAR,
    last_seen TIMESTAMP,
    est_arrival_airport VARCHAR,
    callsign VARCHAR,
    est_departure_airport_horiz_distance INT,
    est_departure_airport_vert_distance INT,
    est_arrival_airport_horiz_distance INT,
    est_arrival_airport_vert_distance INT,
    departure_airport_candidates_count INT,
    arrival_airport_candidates_count INT,
    flight_direction VARCHAR,
    queried_airport VARCHAR,
    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

INSERT_SQL = """
INSERT INTO RAW.RAW_FLIGHTS (
    icao24, first_seen, est_departure_airport, last_seen,
    est_arrival_airport, callsign,
    est_departure_airport_horiz_distance, est_departure_airport_vert_distance,
    est_arrival_airport_horiz_distance, est_arrival_airport_vert_distance,
    departure_airport_candidates_count, arrival_airport_candidates_count,
    flight_direction, queried_airport, ingested_at
) VALUES (
    %(icao24)s, %(first_seen)s, %(est_departure_airport)s, %(last_seen)s,
    %(est_arrival_airport)s, %(callsign)s,
    %(est_departure_airport_horiz_distance)s, %(est_departure_airport_vert_distance)s,
    %(est_arrival_airport_horiz_distance)s, %(est_arrival_airport_vert_distance)s,
    %(departure_airport_candidates_count)s, %(arrival_airport_candidates_count)s,
    %(flight_direction)s, %(queried_airport)s, %(ingested_at)s
);
"""

def get_postgres_connection():
    """Create a PostgreSQL connection using environment variables."""
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ.get("POSTGRES_PORT", 5432),
        database=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )

def create_raw_table_if_not_exists(conn):
    """Ensure the RAW_FLIGHTS table exists in PostgreSQL."""
    with conn.cursor() as cursor:
        cursor.execute(CREATE_TABLE_SQL)
    conn.commit()
    logger.info("RAW_FLIGHTS table ready.")

def _unix_to_timestamp(ts):
    """Convert a Unix timestamp (seconds) to a datetime string, or None."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def load_flights(conn, flights):
    """
    Insert a list of flight dicts into PostgreSQL RAW.RAW_FLIGHTS.
    """
    if not flights:
        logger.info("No flights to load.")
        return 0

    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for f in flights:
        rows.append(
            {
                "icao24": f.get("icao24"),
                "first_seen": _unix_to_timestamp(f.get("firstSeen")),
                "est_departure_airport": f.get("estDepartureAirport"),
                "last_seen": _unix_to_timestamp(f.get("lastSeen")),
                "est_arrival_airport": f.get("estArrivalAirport"),
                "callsign": (f.get("callsign") or "").strip() or None,
                "est_departure_airport_horiz_distance": f.get(
                    "estDepartureAirportHorizDistance"
                ),
                "est_departure_airport_vert_distance": f.get(
                    "estDepartureAirportVertDistance"
                ),
                "est_arrival_airport_horiz_distance": f.get(
                    "estArrivalAirportHorizDistance"
                ),
                "est_arrival_airport_vert_distance": f.get(
                    "estArrivalAirportVertDistance"
                ),
                "departure_airport_candidates_count": f.get(
                    "departureAirportCandidatesCount"
                ),
                "arrival_airport_candidates_count": f.get(
                    "arrivalAirportCandidatesCount"
                ),
                "flight_direction": f.get("flight_direction"),
                "queried_airport": f.get("queried_airport"),
                "ingested_at": now,
            }
        )

    with conn.cursor() as cursor:
        execute_batch(cursor, INSERT_SQL, rows, page_size=500)
    
    conn.commit()
    logger.info("Loaded %d flight records into PostgreSQL.", len(rows))
    return len(rows)
