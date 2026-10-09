# MediaMatcher

A Streamlit movie discovery and recommendation app using TMDB and MySQL.

## Files

- `app.py` — Streamlit interface and recommendation logic
- `database.py` — MySQL helpers; reads credentials from Streamlit secrets and hashes new account passwords
- `schema.sql` — database tables required by the app
- `requirements.txt` — Python dependencies

## Security notes

- Never commit `.streamlit/secrets.toml`, `.env`, database credentials, or API keys.
- Rotate any database password or TMDB key that has ever appeared in a source file or report.
- This deployment version hashes passwords for new accounts. It does not accept old plaintext-password records. Use a fresh hosted database or migrate/reset existing users safely.
- The app needs a hosted MySQL instance accessible from Streamlit Community Cloud. `localhost` will refer to the cloud app container, not your own computer.

## Set up the database

1. Create a hosted MySQL service and database, for example using Aiven for MySQL.
2. Copy the database hostname, port, username, password, and database name from the provider's connection details.
3. Run `schema.sql` in that database using the provider's SQL console or a MySQL client.
4. If the provider requires TLS certificate verification, download its CA certificate and configure `ssl_ca` to the certificate file path. Do not disable certificate verification to work around connection errors.

## Local development

1. Install Python 3.10 or newer.
2. Install dependencies: `pip install -r requirements.txt`.
3. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in your real TMDB key and hosted MySQL credentials.
4. Run `streamlit run app.py`.

Keep `.streamlit/secrets.toml` out of Git. `.gitignore` already excludes it.

## Deploy on Streamlit Community Cloud

1. Push this folder to a GitHub repository.
2. Open https://share.streamlit.io/ and sign in with GitHub.
3. Create an app and select your repository, branch (`main`), and main file path (`app.py`).
4. In Advanced settings / Secrets, paste TOML content with your rotated API key and hosted database connection details, following `.streamlit/secrets.toml.example`.
5. Deploy and check the app logs if startup fails.

## Streamlit secrets format

```toml
TMDB_API_KEY = "your_rotated_tmdb_api_key"

[mysql]
host = "your-hostname"
port = 3306
user = "your-db-user"
password = "your-new-db-password"
database = "movie_recommender"
# ssl_ca = "ca.pem" # if your provider supplies a CA certificate
```
