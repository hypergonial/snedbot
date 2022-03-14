import datetime
import logging
import os

import hikari


async def backup_database() -> hikari.File:
    """Attempts to back up the database via pg_dump into the db_backup directory"""
    logging.info("Performing daily database backup...")

    username: str = os.getenv("POSTGRES_USER") or "postgres"
    password: str = os.getenv("POSTGRES_PASSWORD") or ""
    hostname: str = os.getenv("POSTGRES_HOST") or "sned-db"
    port: str = os.getenv("POSTGRES_PORT") or "5432"
    db_name: str = os.getenv("POSTGRES_DB") or "sned"

    os.environ["PGPASSWORD"] = password

    filepath: str = os.path.dirname(os.path.realpath(__file__))

    if not os.path.isdir(os.path.join(filepath, "db", "backup")):
        os.mkdir(os.path.join(filepath, "db", "backup"))

    now = datetime.datetime.now(datetime.timezone.utc)

    filename: str = f"{now.year}-{now.month}-{now.day}_{now.hour}_{now.minute}_{now.second}.pgdmp"
    backup_path: str = os.path.join(filepath, "db", "backup", filename)

    return_code = os.system(
        f"pg_dump -Fc -c -U {username} -d {db_name} -h {hostname} -p {port} --quote-all-identifiers -w > {backup_path}"
    )
    os.environ["PGPASSWORD"] = ""

    if return_code != 0:
        raise RuntimeError("pg_dump failed to create a database backup file!")

    logging.info("Database backup complete!")
    return hikari.File(backup_path)
