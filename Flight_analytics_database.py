import hashlib
import os
import tomllib
from datetime import date, datetime
from getpass import getpass
from pathlib import Path

import mysql.connector
from mysql.connector import Error


def _local_mysql_secrets():
    secrets_path = Path(__file__).parent / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        return {}
    with secrets_path.open("rb") as secrets_file:
        return tomllib.load(secrets_file).get("mysql", {})


_MYSQL_SECRETS = _local_mysql_secrets()
DATABASE_NAME = os.getenv("MYSQL_DATABASE") or _MYSQL_SECRETS.get(
    "database", "flight_analytics"
)


def get_database_config(*, include_database=True, password=None, prompt=False):
    """Build MySQL configuration from environment variables or a supplied secret."""
    db_password = password or os.getenv("MYSQL_PASSWORD") or _MYSQL_SECRETS.get("password")
    if not db_password and prompt:
        db_password = getpass("MySQL password: ")
    if not db_password:
        raise RuntimeError(
            "MySQL password is not configured. Set MYSQL_PASSWORD or add it to "
            ".streamlit/secrets.toml."
        )

    config = {
        "host": os.getenv("MYSQL_HOST") or _MYSQL_SECRETS.get("host", "localhost"),
        "port": int(os.getenv("MYSQL_PORT") or _MYSQL_SECRETS.get("port", 3306)),
        "user": os.getenv("MYSQL_USER") or _MYSQL_SECRETS.get("user", "root"),
        "password": db_password,
    }
    if include_database:
        config["database"] = DATABASE_NAME
    return config

def to_local_datetime(value):
    """Convert an AeroDataBox local ISO timestamp to a timezone-naive datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=None)


def make_flight_id(
    flight_number,
    origin_iata,
    destination_iata,
    scheduled_departure=None,
    scheduled_arrival=None,
    fallback_date=None,
):
    """Return a stable ID for one dated flight occurrence."""
    occurrence = scheduled_departure or scheduled_arrival or fallback_date or "unknown-time"
    if isinstance(occurrence, (datetime, date)):
        occurrence = occurrence.isoformat()
    identity = "|".join(
        str(value or "").strip().upper()
        for value in (flight_number, origin_iata, destination_iata, occurrence)
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


TABLE_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS airport (
        airport_id INT AUTO_INCREMENT PRIMARY KEY,
        icao_code VARCHAR(10) UNIQUE,
        iata_code VARCHAR(10) UNIQUE,
        name VARCHAR(255),
        city VARCHAR(255),
        country VARCHAR(255),
        continent VARCHAR(50),
        latitude DOUBLE,
        longitude DOUBLE,
        timezone VARCHAR(50)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS aircraft (
        aircraft_id INT AUTO_INCREMENT PRIMARY KEY,
        registration VARCHAR(32) UNIQUE,
        model VARCHAR(255),
        manufacturer VARCHAR(255),
        icao_type_code VARCHAR(32),
        owner VARCHAR(255)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS flights (
        flight_id CHAR(64) PRIMARY KEY,
        flight_number VARCHAR(32) NOT NULL,
        aircraft_registration VARCHAR(32),
        origin_iata VARCHAR(10),
        destination_iata VARCHAR(10),
        scheduled_departure DATETIME,
        actual_departure DATETIME,
        revised_departure DATETIME,
        scheduled_arrival DATETIME,
        actual_arrival DATETIME,
        revised_arrival DATETIME,
        status VARCHAR(64),
        airline_code VARCHAR(10),
        aircraft_model VARCHAR(255)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS airport_delays (
        delay_id INT AUTO_INCREMENT PRIMARY KEY,
        airport_iata VARCHAR(10) NOT NULL,
        delay_date DATE NOT NULL,
        total_flights INT NOT NULL DEFAULT 0,
        delayed_flights INT NOT NULL DEFAULT 0,
        avg_delay_min INT NOT NULL DEFAULT 0,
        median_delay_min INT NOT NULL DEFAULT 0,
        canceled_flights INT NOT NULL DEFAULT 0,
        UNIQUE KEY uq_airport_delays_iata_date (airport_iata, delay_date)
    )
    """,
]

INDEX_STATEMENTS = [
    ("idx_flights_origin_iata", "CREATE INDEX idx_flights_origin_iata ON flights (origin_iata)"),
    ("idx_flights_destination_iata", "CREATE INDEX idx_flights_destination_iata ON flights (destination_iata)"),
    (
        "idx_flights_aircraft_registration",
        "CREATE INDEX idx_flights_aircraft_registration ON flights (aircraft_registration)",
    ),
    ("idx_flights_status", "CREATE INDEX idx_flights_status ON flights (status)"),
    ("idx_flights_airline_code", "CREATE INDEX idx_flights_airline_code ON flights (airline_code)"),
    (
        "idx_flights_scheduled_departure",
        "CREATE INDEX idx_flights_scheduled_departure ON flights (scheduled_departure)",
    ),
]


def create_index(cursor, index_name, statement):
    """Create an index while treating an existing index as successful."""
    try:
        cursor.execute(statement)
    except Error as error:
        if getattr(error, "errno", None) != 1061:
            raise


def _column_types(cursor, table_name):
    cursor.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (DATABASE_NAME, table_name),
    )
    return {name: data_type.lower() for name, data_type in cursor.fetchall()}


def _migrate_datetime_column(connection, cursor, column_name):
    column_types = _column_types(cursor, "flights")
    if column_name not in column_types:
        cursor.execute(f"ALTER TABLE flights ADD COLUMN {column_name} DATETIME NULL")
        return
    if column_types[column_name] in {"datetime", "timestamp"}:
        return

    temporary_column = f"{column_name}_migration"
    if temporary_column not in column_types:
        cursor.execute(f"ALTER TABLE flights ADD COLUMN {temporary_column} DATETIME NULL")
    else:
        cursor.execute(f"UPDATE flights SET {temporary_column} = NULL")

    cursor.execute(
        f"SELECT flight_id, {column_name} FROM flights WHERE {column_name} IS NOT NULL"
    )
    updates = []
    for flight_id, value in cursor.fetchall():
        try:
            updates.append((to_local_datetime(value), flight_id))
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Cannot migrate {column_name} value {value!r} for flight {flight_id}"
            ) from error
    if updates:
        cursor.executemany(
            f"UPDATE flights SET {temporary_column} = %s WHERE flight_id = %s", updates
        )
    connection.commit()

    cursor.execute(f"SELECT COUNT(*) FROM flights WHERE {column_name} IS NOT NULL")
    source_count = cursor.fetchone()[0]
    cursor.execute(f"SELECT COUNT(*) FROM flights WHERE {temporary_column} IS NOT NULL")
    migrated_count = cursor.fetchone()[0]
    if source_count != migrated_count:
        raise RuntimeError(
            f"Refusing to replace {column_name}: migrated {migrated_count} of {source_count} values"
        )

    cursor.execute(
        f"ALTER TABLE flights DROP COLUMN {column_name}, "
        f"CHANGE COLUMN {temporary_column} {column_name} DATETIME NULL"
    )


def _migrate_delay_date(connection, cursor):
    column_types = _column_types(cursor, "airport_delays")
    if column_types.get("delay_date") == "date":
        return

    temporary_column = "delay_date_migration"
    if temporary_column not in column_types:
        cursor.execute(
            f"ALTER TABLE airport_delays ADD COLUMN {temporary_column} DATE NULL"
        )
    else:
        cursor.execute(f"UPDATE airport_delays SET {temporary_column} = NULL")

    cursor.execute("SELECT delay_id, delay_date FROM airport_delays WHERE delay_date IS NOT NULL")
    updates = []
    for delay_id, value in cursor.fetchall():
        parsed = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
        updates.append((parsed, delay_id))
    if updates:
        cursor.executemany(
            f"UPDATE airport_delays SET {temporary_column} = %s WHERE delay_id = %s",
            updates,
        )
    connection.commit()

    cursor.execute("SELECT COUNT(*) FROM airport_delays WHERE delay_date IS NOT NULL")
    source_count = cursor.fetchone()[0]
    cursor.execute(
        f"SELECT COUNT(*) FROM airport_delays WHERE {temporary_column} IS NOT NULL"
    )
    if cursor.fetchone()[0] != source_count:
        raise RuntimeError("Refusing to replace delay_date because some values did not migrate")

    cursor.execute(
        "ALTER TABLE airport_delays DROP COLUMN delay_date, "
        f"CHANGE COLUMN {temporary_column} delay_date DATE NOT NULL"
    )


def _migrate_flight_ids(connection, cursor):
    cursor.execute(
        """
        SELECT flight_id, flight_number, origin_iata, destination_iata,
               scheduled_departure, scheduled_arrival
        FROM flights
        """
    )
    rows = cursor.fetchall()
    if rows and all(
        len(str(row[0])) == 64
        and all(char in "0123456789abcdef" for char in str(row[0]).lower())
        for row in rows
    ):
        return

    column_types = _column_types(cursor, "flights")
    if "flight_id_migration" not in column_types:
        cursor.execute("ALTER TABLE flights ADD COLUMN flight_id_migration CHAR(64) NULL")
    updates = [
        (
            make_flight_id(
                flight_number,
                origin_iata,
                destination_iata,
                scheduled_departure,
                scheduled_arrival,
            ),
            old_id,
        )
        for old_id, flight_number, origin_iata, destination_iata, scheduled_departure, scheduled_arrival in rows
    ]
    if updates:
        cursor.executemany(
            "UPDATE flights SET flight_id_migration = %s WHERE flight_id = %s", updates
        )
    connection.commit()

    cursor.execute(
        "SELECT COUNT(*), COUNT(DISTINCT flight_id_migration) FROM flights "
        "WHERE flight_id_migration IS NOT NULL"
    )
    row_count, unique_count = cursor.fetchone()
    if row_count != len(rows) or unique_count != len(rows):
        raise RuntimeError("Refusing to replace flight IDs because generated IDs are not unique")

    cursor.execute(
        "ALTER TABLE flights DROP PRIMARY KEY, DROP COLUMN flight_id, "
        "CHANGE COLUMN flight_id_migration flight_id CHAR(64) NOT NULL, "
        "ADD PRIMARY KEY (flight_id)"
    )


def migrate_existing_schema(connection, cursor):
    """Upgrade tables created by older project versions without losing rows."""
    for column_name in (
        "scheduled_departure",
        "actual_departure",
        "scheduled_arrival",
        "actual_arrival",
    ):
        _migrate_datetime_column(connection, cursor, column_name)

    column_types = _column_types(cursor, "flights")
    for column_name in ("revised_departure", "revised_arrival"):
        if column_name not in column_types:
            cursor.execute(f"ALTER TABLE flights ADD COLUMN {column_name} DATETIME NULL")

    _migrate_delay_date(connection, cursor)
    _migrate_flight_ids(connection, cursor)

    try:
        cursor.execute(
            "ALTER TABLE airport_delays ADD UNIQUE INDEX "
            "uq_airport_delays_iata_date (airport_iata, delay_date)"
        )
    except Error as error:
        if getattr(error, "errno", None) != 1061:
            raise


def initialize_database():
    """Create or migrate the flight analytics database, tables, and indexes."""
    connection = None
    cursor = None
    try:
        connection = mysql.connector.connect(**get_database_config(include_database=False))
        cursor = connection.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DATABASE_NAME}`")
        cursor.execute(f"USE `{DATABASE_NAME}`")

        for statement in TABLE_STATEMENTS:
            cursor.execute(statement)

        migrate_existing_schema(connection, cursor)

        for index_name, statement in INDEX_STATEMENTS:
            create_index(cursor, index_name, statement)

        connection.commit()
        print(f"MySQL database {DATABASE_NAME} is ready")
    except (Error, RuntimeError, ValueError) as error:
        if connection is not None:
            connection.rollback()
        print(f"Database initialization failed: {error}")
        raise
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None and connection.is_connected():
            connection.close()


if __name__ == "__main__":
    initialize_database()
