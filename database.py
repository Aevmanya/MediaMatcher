"""Database helpers for MediaMatcher.

Configure connection details in .streamlit/secrets.toml locally and in your
Streamlit Community Cloud app settings when deployed. Never commit secrets.
"""

import base64
import hashlib
import hmac
import os
import secrets as _secrets

import mysql.connector
import streamlit as st


def _read_mysql_config():
    """Read DB settings from Streamlit secrets, with environment fallbacks."""
    try:
        section = st.secrets.get("mysql", {})
    except (FileNotFoundError, RuntimeError):
        section = {}

    def value(key, env_key=None, default=None):
        env_key = env_key or f"MYSQL_{key.upper()}"
        return section.get(key, os.environ.get(env_key, default))

    config = {
        "host": value("host"),
        "user": value("user"),
        "password": value("password"),
        "database": value("database", default="movie_recommender"),
        "port": int(value("port", default=3306)),
    }
    missing = [key for key in ("host", "user", "password", "database") if not config[key]]
    if missing:
        raise RuntimeError(
            "MySQL configuration is missing: " + ", ".join(missing) +
            ". Add a [mysql] section to .streamlit/secrets.toml or configure "
            "the corresponding MYSQL_* environment variables."
        )

    # If your database provider supplies a CA certificate, put its path in the
    # ssl_ca setting and enable certificate/hostname verification.
    ssl_ca = value("ssl_ca", default=None)
    if ssl_ca:
        config["ssl_ca"] = ssl_ca
        config["ssl_verify_cert"] = True
        config["ssl_verify_identity"] = True
    return config


db = mysql.connector.connect(**_read_mysql_config(), connection_timeout=10)
cursor = db.cursor()


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
        # Legacy plaintext passwords are intentionally not accepted by this
        # deployment-ready version. Use a fresh hosted database or reset users.
        return False


def create_user(email, phone, password):
    sql = "INSERT INTO users(email, phone, password) VALUES (%s, %s, %s)"
    cursor.execute(sql, (email, phone, _hash_password(password)))
    db.commit()


def get_user(email):
    cursor.execute("SELECT * FROM users WHERE email=%s", (email,))
    return cursor.fetchone()


def update_preferences(user_id, languages, start_year, end_year, genres, favourite_movies):
    sql = """UPDATE users SET languages=%s, start_year=%s, end_year=%s,
             genres=%s, favourite_movies=%s WHERE user_id=%s"""
    cursor.execute(sql, (languages, start_year, end_year, genres, favourite_movies, user_id))
    db.commit()


def load_preferences(user_id):
    cursor.execute(
        """SELECT languages, start_year, end_year, genres, favourite_movies
           FROM users WHERE user_id=%s""",
        (user_id,),
    )
    return cursor.fetchone()


def save_favourite(user_id, movie):
    cursor.execute(
        "INSERT INTO favourites(user_id, movie_id, movie_title) VALUES (%s, %s, %s)",
        (user_id, movie["id"], movie["title"]),
    )
    db.commit()


def load_favourites(user_id):
    cursor.execute(
        "SELECT movie_id, movie_title FROM favourites WHERE user_id=%s",
        (user_id,),
    )
    return cursor.fetchall()


def login_user(email, password):
    cursor.execute("SELECT user_id, email, password FROM users WHERE email=%s", (email,))
    user = cursor.fetchone()
    if user and _verify_password(password, user[2]):
        return {"user_id": user[0], "email": user[1]}
    return None


def favourite_exists(user_id, movie_id):
    cursor.execute(
        "SELECT 1 FROM favourites WHERE user_id=%s AND movie_id=%s",
        (user_id, movie_id),
    )
    return cursor.fetchone() is not None


def remove_favourite(user_id, movie_id):
    cursor.execute(
        "DELETE FROM favourites WHERE user_id=%s AND movie_id=%s",
        (user_id, movie_id),
    )
    db.commit()


def favourite_count(movie_id):
    cursor.execute(
        "SELECT COUNT(DISTINCT user_id) FROM favourites WHERE movie_id=%s",
        (movie_id,),
    )
    return cursor.fetchone()[0]
