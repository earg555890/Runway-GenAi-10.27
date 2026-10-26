"""Load Maya's CSVs into the local Zetaris platform. Idempotent: safe to rerun.

    .venv/Scripts/python load_zetaris.py                          # all eight sources
    .venv/Scripts/python load_zetaris.py opportunities meal_plan  # only these sources (the others stay as they are)

1. Copies data/maya/<source>/*.csv into the driver container (config.ZETARIS_DATA_ROOT/<source>/).
2. Drops RUNWAY_TEST and any existing RUNWAY_* source databases (tables first, then the database).
3. Creates one Lightning database per source and one FILESTORE table per CSV.
4. Counts rows per table, compares them with the CSV, and clears the Zetaris query cache.
PDFs are display-only and are not loaded.
"""
import csv
import subprocess
import sys
import time

import config
from data_access import SOURCE_DATABASES, clear_cache
from zetaris_db import query


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def timed(label, fn, *args):
    start = time.perf_counter()
    value = fn(*args)
    print(f"  {time.perf_counter() - start:6.1f}s  {label}")
    return value


def drop_database(db):
    for row in query(f"SHOW TABLES IN {db}"):
        query(f"DROP LIGHTNING DATABASE TABLE {row[0]}")   # row[0] is "DB.table"
    query(f"DROP LIGHTNING DATABASE {db}")


def main():
    total_start = time.perf_counter()
    container, root = config.ZETARIS_CONTAINER, config.ZETARIS_DATA_ROOT
    only = sys.argv[1:]
    unknown = set(only) - set(SOURCE_DATABASES)
    if unknown:
        sys.exit(f"unknown source(s) {sorted(unknown)}; known: {sorted(SOURCE_DATABASES)}")
    sources = {s: db for s, db in SOURCE_DATABASES.items() if not only or s in only}

    print(f"Copying CSVs to {container}:{root}")
    if only:
        for source in sources:
            docker("exec", container, "rm", "-rf", f"{root}/{source}")
    else:
        docker("exec", container, "rm", "-rf", root, root.rsplit("/", 1)[0] + "/runway_test")
    tables = []   # (source, db, table, container_path, csv_rows)
    for source, db in sources.items():
        docker("exec", container, "mkdir", "-p", f"{root}/{source}")
        for path in sorted((config.DATA_DIR / source).glob("*.csv")):
            target = f"{root}/{source}/{path.name}"
            docker("cp", str(path), f"{container}:{target}")
            with open(path, newline="", encoding="utf-8") as f:
                csv_rows = sum(1 for _ in csv.reader(f)) - 1
            tables.append((source, db, path.stem, target, csv_rows))
    print(f"  {len(tables)} CSV files copied")

    print("Dropping old databases")
    existing = {row[0].upper() for row in query("SHOW LIGHTNING DATABASES")}
    for db in (["RUNWAY_TEST"] if not only else []) + list(sources.values()):
        if db in existing:
            timed(f"drop {db}", drop_database, db)

    print("Creating databases and tables")
    for source, db in sources.items():
        timed(f"create {db}", query, f'CREATE LIGHTNING DATABASE {db} DESCRIBE BY "Runway demo source, {source}" OPTIONS ()')
    for source, db, table, target, _ in tables:
        timed(f"register {db}.{table}", query,
              f'CREATE LIGHTNING FILESTORE TABLE {table} FROM {db} FORMAT csv OPTIONS (path "{target}", header "true")')

    print("Row counts (Zetaris vs CSV)")
    mismatches = 0
    for source, db, table, _, csv_rows in tables:
        start = time.perf_counter()
        count = int(query(f"SELECT COUNT(*) FROM {db}.{table}")[0][0])
        ok = count == csv_rows
        mismatches += not ok
        print(f"  {time.perf_counter() - start:6.1f}s  {db}.{table:<14} zetaris={count:<4} csv={csv_rows:<4} {'OK' if ok else 'MISMATCH'}")

    clear_cache()   # cached query results may describe the old tables
    print(f"\nTotal time: {time.perf_counter() - total_start:.1f}s; {len(tables)} tables; "
          f"{'all row counts match' if not mismatches else f'{mismatches} MISMATCHES'}")
    sys.exit(1 if mismatches else 0)


if __name__ == "__main__":
    main()
