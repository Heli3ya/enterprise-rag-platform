
import os
import threading
from pathlib import Path

import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

_pool = None
_pool_lock = threading.Lock()


def get_db_pool():
    """Create the PostgreSQL connection pool once per process."""
    global _pool

    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(
                    minconn=1,
                    maxconn=5,
                    dbname=os.getenv("DB_NAME"),
                    user=os.getenv("DB_USER"),
                    password=os.getenv("DB_PASSWORD"),
                    host=os.getenv("DB_HOST"),
                    port=os.getenv("DB_PORT"),
                    connect_timeout=5,
                )

    return _pool


def get_db_connection():
    """Get a connection from the bounded pool."""
    return get_db_pool().getconn()


def release_db_connection(connection, *, discard=False):
    """Return a connection to the pool or discard a broken connection."""
    if connection is None:
        return

    pool = get_db_pool()

    try:
        pool.putconn(connection, close=discard)
    except Exception:
        # Do not hide an earlier database exception.
        try:
            connection.close()
        except Exception:
            pass
