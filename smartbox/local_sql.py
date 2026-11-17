"""Resolve installation-local SQL calendar boundaries at query execution time."""
TOKEN = "__EW_TIMEZONE__"


def installation_timezone():
    import nordpool
    from zoneinfo import ZoneInfo
    return ZoneInfo(nordpool.price_timezone().key)


def local_sql(query):
    """Render the timezone marker without interpolating other query values.

    Keep normal psycopg/SQLAlchemy parameters bound by their existing callers.
    Resolve lazily so importing loggers cannot create a nordpool import cycle.
    """
    if not isinstance(query, str) or TOKEN not in query:
        return query
    name = installation_timezone().key
    return query.replace(TOKEN, "'" + name.replace("'", "''") + "'")
