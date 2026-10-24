"""Connect to the local Zetaris platform over JDBC.

    from zetaris_db import query
    rows = query("SELECT * FROM NY_TAXI.customers LIMIT 10")

Settings come from config (.env). A missing one raises config.MissingSetting.
Zetaris Lightning SQL, one statement per call. Use SHOW NAMESPACES IN ... / SHOW TABLES IN ...
rather than plain SHOW DATABASES / SHOW TABLES, which Zetaris rejects.
"""
import os

import jaydebeapi
import jpype.config

import config

# At Python exit, don't run the JVM's own shutdown: it waits for the thread that started the JVM, and in
# Streamlit that is a script thread that never finishes, so the process used to hang after Ctrl+C. The JDBC
# connection needs no Java-side cleanup; the OS closes the socket when the process ends.
jpype.config.destroy_jvm = False

DRIVER_CLASS = "com.zetaris.lightning.jdbc.LightningDriver"

_conn = None


def connect():
    """Return a shared connection, opening it on first use."""
    global _conn
    if _conn is None:
        os.environ["JAVA_HOME"] = config.require("JAVA_HOME")
        _conn = jaydebeapi.connect(
            DRIVER_CLASS,
            config.require("ZETARIS_JDBC_URL"),
            [config.require("ZETARIS_USER"), config.require("ZETARIS_PASSWORD")],
            config.require("ZETARIS_JDBC_JAR"),
        )
    return _conn


def query(sql):
    """Run one statement and return its rows as a list of tuples (empty for statements without results)."""
    cur = connect().cursor()
    try:
        cur.execute(sql)
        return cur.fetchall() if cur.description else []
    finally:
        cur.close()


def query_with_columns(sql):
    """Run one statement and return (column_names, rows)."""
    cur = connect().cursor()
    try:
        cur.execute(sql)
        if not cur.description:
            return [], []
        return [d[0] for d in cur.description], cur.fetchall()
    finally:
        cur.close()


def close():
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None
