import datetime
import logging
import os
import pathlib

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

    filepath: str = str(pathlib.Path(os.path.abspath(__file__)).parents[1])

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


# Copyright (C) 2022-present HyperGH

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see: https://www.gnu.org/licenses
