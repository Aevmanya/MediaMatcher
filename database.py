"""PostgreSQL database helpers for MediaMatcher.

Configure connection details in Streamlit secrets under [postgresql].
Never commit database credentials.
"""

import base64
import hashlib
import hmac
import os
import secrets as _secrets

import psycopg2
import streamlit as st


def _read_postgresql_config():
    """Read PostgreSQL settings from Streamlit secrets or environment."""
    try:
        section = st.secrets.get("postgresql", {})
    except (FileNotFoundError, RuntimeError):
        section = {}

    def value(key, env_key=None, default=None):
        env_key = env_key or f"POSTGRESQL_{key.upper()}"
        return section.get(key, os.environ.get(env_key, default))

    config = {
        "host": value("host"),
        "user": value("user"),
        "password": value("password"),
        "dbname": value("database", default="defaultdb"),
        "port": int(value("port", default=5432)),
        "sslmode": value("sslmode", default="require"),
        "connect_timeout": 10,
    }
    missing = [key for key in ("host", "user", "password", "dbname") if not config[key]]
    if missing:
        raise RuntimeError(
            "PostgreSQL configuration is missing: " + ", ".join(missing) +
            ". Add a [postgresql] section to Streamlit secrets or configure "
            "the corresponding POSTGRESQL_* environment variables."
        )
    return config


def _connect():
    return psycopg2.connect(**_read_postgresql_config())


db = _connect()
cursor = db.cursor()


def _ensure_schema():
    """Create the app's tables if this is a new, empty database."""
    global cursor
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id SERIAL PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            phone TEXT,
            password TEXT NOT NULL,
            languages TEXT,
            start_year INTEGER,
            end_year INTEGER,
            genres TEXT,
            favourite_movies TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS favourites (
            favourite_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            movie_id BIGINT NOT NULL,
            movie_title TEXT NOT NULL,
            UNIQUE (user_id, movie_id)
        )
        """
    )
    db.commit()


def _execute(sql, params=None):
    """Reconnect if the PostgreSQL connection was closed, then execute SQL."""
    global db, cursor
    try:
        if db.closed:
            db = _connect()
        cursor = db.cursor()
        cursor.execute(sql, params or ())
    except psycopg2.Error:
        try:
            db.rollback()
        except psycopg2.Error:
            pass
        if not db.closed:
            raise
        db = _connect()
        cursor = db.cursor()
        cursor.execute(sql, params or ())


_ensure_schema()

_HASH_ALGORITHM = "pbkdf2_sha256"
_HASH_ITERATIONS = 260_000


def _hash_password(password):
    salt = _secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _HASH_ITERATIONS)
    return "$".join((
        _HASH_ALGORITHM,
        str(_HASH_ITERATIONS),
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    ))


def _verify_password(password, stored):
    try:
        algorithm, iterations, salt_text, digest_text = stored.split("$", 3)
        if algorithm != _HASH_ALGORITHM:
            return False
        salt = base64.b64decode(salt_text.encode("ascii"))
        expected = base64.b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def create_user(email, phone, password):
    _execute(
        "INSERT INTO users(email, phone, password) VALUES (%s, %s, %s)",
        (email, phone, _hash_password(password)),
    )
    db.commit()


def get_user(email):
    _execute("SELECT * FROM users WHERE email=%s", (email,))
    return cursor.fetchone()


def update_preferences(user_id, languages, start_year, end_year, genres, favourite_movies):
    _execute(
        """UPDATE users SET languages=%s, start_year=%s, end_year=%s,
           genres=%s, favourite_movies=%s WHERE user_id=%s""",
        (languages, start_year, end_year, genres, favourite_movies, user_id),
    )
    db.commit()


def load_preferences(user_id):
    _execute(
        """SELECT languages, start_year, end_year, genres, favourite_movies
           FROM users WHERE user_id=%s""",
        (user_id,),
    )
    return cursor.fetchone()


def save_favourite(user_id, movie):
    _execute(
        "INSERT INTO favourites(user_id, movie_id, movie_title) VALUES (%s, %s, %s) "
        "ON CONFLICT (user_id, movie_id) DO NOTHING",
        (user_id, movie["id"], movie["title"]),
    )
    db.commit()


def load_favourites(user_id):
    _execute(
        "SELECT movie_id, movie_title FROM favourites WHERE user_id=%s",
        (user_id,),
    )
    return cursor.fetchall()


def login_user(email, password):
    _execute("SELECT user_id, email, password FROM users WHERE email=%s", (email,))
    user = cursor.fetchone()
    if user and _verify_password(password, user[2]):
        return {"user_id": user[0], "email": user[1]}
    return None


def favourite_exists(user_id, movie_id):
    _execute(
        "SELECT 1 FROM favourites WHERE user_id=%s AND movie_id=%s",
        (user_id, movie_id),
    )
    return cursor.fetchone() is not None


def remove_favourite(user_id, movie_id):
    _execute(
        "DELETE FROM favourites WHERE user_id=%s AND movie_id=%s",
        (user_id, movie_id),
    )
    db.commit()


def favourite_count(movie_id):
    _execute(
        "SELECT COUNT(DISTINCT user_id) FROM favourites WHERE movie_id=%s",
        (movie_id,),
    )
    return cursor.fetchone()[0]
