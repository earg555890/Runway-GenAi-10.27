"""My data mode: the student's own bank file, kept on this computer only (CLAUDE.md rule 7).

    mydata.save(rows, mapping, file_name)        # after importer.normalize_rows(): writes user_data/mydata/
    ds = mydata.dataset()                        # a Dataset with only bank data, through data_access
    today, start, end = mydata.dates(ds)         # her "today" (the file's last day), first day and end date
    with config.as_of(today, start, end, start):  # then every engine call works on her dates
        engine.project(engine.Scenario(), ds)

Files live in config.USER_DATA_DIR/mydata (gitignored; never committed, never in demo answers). With
DATA_BACKEND=zetaris the transactions are also registered in the local Zetaris as RUNWAY_MYDATA (its own Lightning
database, on this computer); otherwise they are read from the local file.
"""
import csv
import json
import time
from datetime import date, datetime, timedelta

import config
import data_access as da
import normalize

TABLE_COLUMNS = ["txn_id", "posted_date", "description", "amount", "running_balance"]


def folder():
    return config.USER_DATA_DIR / "mydata"


def exists():
    return (folder() / "transactions.csv").exists() and (folder() / "meta.json").exists()


def meta():
    return json.loads((folder() / "meta.json").read_text(encoding="utf-8")) if exists() else {}


def save(rows, mapping, file_name, balance_today=None, end_date=None, register=None):
    """Write the imported rows (importer.normalize_rows) and what was imported. register: also load it into the
    local Zetaris (default: when DATA_BACKEND is zetaris). Returns the meta dict."""
    out = folder()
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "transactions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(TABLE_COLUMNS)
        for i, r in enumerate(rows, start=1):
            w.writerow([f"MY-{i:04d}", r["date"].isoformat(), r["description"], f"{r['amount']:.2f}",
                        "" if r["balance"] is None else f"{r['balance']:.2f}"])
    m = {"file": file_name, "imported": datetime.now().isoformat(timespec="seconds"), "rows": len(rows),
         "first": rows[0]["date"].isoformat(), "last": rows[-1]["date"].isoformat(),
         "has_balance": any(r["balance"] is not None for r in rows),
         "balance_today": None if balance_today is None else str(balance_today),
         "end_date": end_date.isoformat() if end_date else None,
         "mapping": {k: v for k, v in mapping.to_dict().items() if k != "notes"}}
    (out / "meta.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    da.clear_cache("mydata_transactions")
    m["zetaris"] = None
    if register if register is not None else config.DATA_BACKEND == "zetaris":
        try:
            m["zetaris"] = register_zetaris()
        except Exception as exc:              # Zetaris down: the local file still works (rule 4)
            m["zetaris"] = f"not registered ({type(exc).__name__})"
        (out / "meta.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    return m


def update(**changes):
    m = meta()
    m.update({k: (v.isoformat() if isinstance(v, date) else v) for k, v in changes.items()})
    (folder() / "meta.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    return m


def clear():
    """Forget her data: delete user_data/mydata and its cached query results."""
    import shutil
    shutil.rmtree(folder(), ignore_errors=True)
    da.clear_cache("mydata_transactions")


def register_zetaris():
    """Copy her file into the local Zetaris driver container and register it as RUNWAY_MYDATA.transactions (its own
    Lightning database). Everything stays on this computer. Returns a short status line."""
    from load_zetaris import docker
    from zetaris_db import query
    start = time.perf_counter()
    db, container = da.SOURCE_DATABASES["mydata"], config.ZETARIS_CONTAINER
    target_dir = config.ZETARIS_DATA_ROOT.rsplit("/", 1)[0] + "/runway_mydata"
    docker("exec", container, "mkdir", "-p", target_dir)
    docker("cp", str(folder() / "transactions.csv"), f"{container}:{target_dir}/transactions.csv")
    if db in {row[0].upper() for row in query("SHOW LIGHTNING DATABASES")}:
        for row in query(f"SHOW TABLES IN {db}"):
            query(f"DROP LIGHTNING DATABASE TABLE {row[0]}")
        query(f"DROP LIGHTNING DATABASE {db}")
    query(f'CREATE LIGHTNING DATABASE {db} DESCRIBE BY "Runway, the student own bank file" OPTIONS ()')
    query(f'CREATE LIGHTNING FILESTORE TABLE transactions FROM {db} FORMAT csv OPTIONS '
          f'(path "{target_dir}/transactions.csv", header "true")')
    count = int(query(f"SELECT COUNT(*) FROM {db}.transactions")[0][0])
    return f"registered {db}.transactions ({count} rows) in {time.perf_counter() - start:.1f} s"


def dataset(backend=None):
    """Her Dataset, read through the named query (Zetaris if it's registered and DATA_BACKEND=zetaris, else the
    local file)."""
    backend = (backend or config.DATA_BACKEND).lower()
    m = meta()
    if backend == "zetaris" and not str(m.get("zetaris") or "").startswith("registered"):
        backend = "local"
    r = da.run("mydata_transactions", backend=backend)
    ds = normalize.build_mydata(r.rows, m, backend)
    ds.evidence = [r.evidence]
    return ds


def default_end(today):
    """The semester end, or 90 days after her last day if her file is past it."""
    return config.SEMESTER_END if config.SEMESTER_END > today else today + timedelta(days=90)


def dates(ds, m=None):
    """(today, first day, end date) for config.as_of(): today is the last day in her file."""
    m = m or meta()
    today = ds.checking_account.as_of
    end = date.fromisoformat(m["end_date"]) if m.get("end_date") else default_end(today)
    return today, ds.first_day, max(end, today + timedelta(days=1))
