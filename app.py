from collections import Counter
from datetime import date
import random
import re
import requests
from requests.adapters import HTTPAdapter
import streamlit as st
from streamlit_option_menu import option_menu
from urllib3.util import Retry

from database import (
    create_user,
    favourite_count,
    favourite_exists,
    load_favourites,
    load_preferences,
    login_user,
    remove_favourite,
    save_favourite,
    update_preferences,
)

session = requests.Session()
retry = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry)
session.mount("https://", adapter)
session.mount("http://", adapter)


API_KEY = st.secrets["TMDB_API_KEY"]
BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

st.set_page_config(page_title="MediaMatcher | Discover your next favourite", page_icon="🎬", layout="wide", initial_sidebar_state="expanded")


if "preferences" not in st.session_state:
    st.session_state.preferences = {
        "languages": [],
        "start_year": None,
        "end_year": None,
        "genres": [],
        "favorite_movies": [],
    }

if "favourites" not in st.session_state:
    st.session_state.favourites = []

if "finder_results" not in st.session_state:
    st.session_state.finder_results = []

if "route" not in st.session_state:
    st.session_state.route = "Home"

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "user_id" not in st.session_state:
    st.session_state.user_id = None

if "user_email" not in st.session_state:
    st.session_state.user_email = ""


@st.cache_data(ttl=3600)
def tmdb_get(path, parameters=None):
    if parameters is None:
        parameters = {}

    user_preferences = st.session_state.get("preferences", {})
    languages = user_preferences.get("languages", [])
    api_language = languages[0] if languages else "en-US"

    parameters = dict(parameters)
    parameters["api_key"] = API_KEY
    parameters["language"] = api_language
    parameters.setdefault(
        "primary_release_date.gte",
        f"{user_preferences.get('start_year', 1885)}-01-01",
    )

    if path == "/discover/movie":

        parameters.setdefault(
            "primary_release_date.lte",
            f"{user_preferences.get('end_year', 2026)}-12-31",
        )

    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = session.get(
            f"{BASE_URL}{path}",
            params=parameters,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"TMDB request failed: {path}\n{e}")
        return {"results": [], "genres": []}


@st.cache_data
def get_genres():
    data = tmdb_get("/genre/movie/list")
    print(data)
    return {g["name"]: g["id"] for g in data.get("genres", [])}

GENRES_MAP = get_genres()
ANIMATION_ID = GENRES_MAP.get("Animation")


def respects_preferences(movie):
    user_preferences = st.session_state.preferences
    allowed_languages = user_preferences.get("languages", [])
    start_year = user_preferences.get("start_year", 1885)
    end_year = user_preferences.get("end_year", 2026)

    if (
        allowed_languages
        and movie.get("original_language") not in allowed_languages
    ):
        return False

    if movie.get("release_date"):
        try:
            year = int(movie["release_date"].split("-")[0])
            if not (start_year <= year <= end_year):
                return False
        except ValueError:
            pass

    selected_genres = user_preferences.get("genres", [])
    selected_genre_ids = [
        GENRES_MAP[genre] for genre in selected_genres if genre in GENRES_MAP
    ]
    movie_genres = set(movie.get("genre_ids", []))

    if ANIMATION_ID in movie_genres and ANIMATION_ID not in selected_genre_ids:
        return False

    return True


def search_movies(query):
    return tmdb_get("/search/movie", {"query": query}).get("results", [])


def get_similar_movies(movie_id):
    similar_movies = tmdb_get(f"/movie/{movie_id}/similar").get("results", [])
    return [m for m in similar_movies if respects_preferences(m)]


def valid_email(email):
    pattern = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
    return re.match(pattern, email) is not None


def get_movie(movie_id):
    return tmdb_get(f"/movie/{movie_id}")


def is_preferences_complete(user_preferences):
    return (
        user_preferences
        and user_preferences.get("languages")
        and user_preferences.get("start_year") is not None
        and user_preferences.get("end_year") is not None
        and len(user_preferences.get("genres", [])) == 4
        and len(user_preferences.get("favorite_movies", [])) == 3
    )


@st.cache_data(ttl=86400)
def cached_similar(movie_id):
    return get_similar_movies(movie_id)


def tmdb_get_keywords(movie_id, api_key):
    try:
        print(f"Fetching keywords for movie {movie_id}")
        response = session.get(
            f"{BASE_URL}/movie/{movie_id}/keywords",
            params={"api_key": api_key},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return {
            keyword["name"].lower() for keyword in data.get("keywords", [])
        }
    except requests.exceptions.RequestException as e:
        print(f"Keyword request failed for movie {movie_id}: {e}")
        return set()


@st.cache_data(ttl=86400)
def cached_keywords(movie_id):
    return tmdb_get_keywords(movie_id, API_KEY)


pages = [
    "Home",
    "Finder",
    "Favourites",
    "Recommended",
    "Upcoming",
    "Preferences",
    "Accounts",
]
default_index = (
    pages.index(st.session_state.route)
    if st.session_state.route in pages
    else 0
)

with st.sidebar:
    st.markdown("## 🎬 MediaMatcher")
    st.caption("Find your next favourite")
    if not st.session_state.logged_in:
        # Keep account access separate and always visible before authentication.
        selected_page = option_menu(
            menu_title="GET STARTED",
            options=["Accounts"],
            icons=["person-circle"],
            default_index=0,
            key="guest_navigation",
        )
        st.session_state.route = "Accounts"
        st.info("Log in or create an account to explore your personal movie space.")
    else:
        selected_page = option_menu(
            menu_title="YOUR CINEMA",
            options=pages,
            icons=["house", "search", "heart", "stars", "calendar-event", "sliders", "person-circle"],
            default_index=default_index,
            key="member_navigation",
        )
        st.session_state.route = selected_page

if (
    st.session_state.logged_in
    and not is_preferences_complete(st.session_state.preferences)
    and st.session_state.route not in ["Preferences", "Accounts"]
):
    st.session_state.route = "Preferences"
    st.warning("Please complete your Preferences before using the app.")
    st.rerun()


def recommend_from_viewed(favourites, candidates, api_key):
    if not favourites:
        return []

    genre_counter = Counter()
    viewed_keywords = set()
    viewed_years = []

    for movie in favourites:
        genre_counter.update(movie.get("genre_ids", [])[:4])
        if movie.get("release_date"):
            try:
                viewed_years.append(int(movie["release_date"].split("-")[0]))
            except ValueError:
                pass
        viewed_keywords.update(cached_keywords(movie["id"]))

    top_genres = set(genre for genre, _ in genre_counter.most_common(4))
    preferences = st.session_state.preferences
    allowed_languages = preferences.get("languages", [])
    start_year = preferences.get("start_year", 1885)
    end_year = preferences.get("end_year", 2026)

    scored_movies = []
    for movie in candidates:
        language_ok = (not allowed_languages) or (
            movie.get("original_language") in allowed_languages
        )
        year_ok = True
        release_year = None

        if movie.get("release_date"):
            try:
                release_year = int(movie["release_date"].split("-")[0])
                year_ok = start_year <= release_year <= end_year
            except ValueError:
                pass

        if not (language_ok and year_ok):
            continue

        score = 0
        candidate_genres = set(movie.get("genre_ids", [])[:4])
        genre_overlap = top_genres.intersection(candidate_genres)
        score += len(genre_overlap) * 1.5

        preferred_genres = {
            GENRES_MAP[g]
            for g in preferences.get("genres", [])
            if g in GENRES_MAP
        }
        score += len(candidate_genres & preferred_genres) * 0.75

        if release_year:
            for viewed_year in viewed_years:
                difference = abs(release_year - viewed_year)
                if difference <= 20:
                    score += 1
                elif difference > 55:
                    score -= 1

            if release_year < 1965:
                score -= 2.5
            elif release_year < 1980:
                score -= 1.5
            elif release_year > 2000:
                score += 1.5

        rating = movie.get("vote_average", 0)
        if rating > 8:
            score += 1.5
        elif 7 <= rating <= 8:
            score += 1.0

        popularity = movie.get("popularity", 0)
        if popularity > 200:
            score += 6
        elif popularity > 30:
            score += 4
        elif popularity < 15:
            score -= 2

        scored_movies.append((movie, score))

    scored_movies.sort(key=lambda item: item[1], reverse=True)
    top_movies = scored_movies[:200]

    final_scores = []
    for movie, score in top_movies:
        keyword_overlap = viewed_keywords.intersection(
            cached_keywords(movie["id"])
        )
        score += len(keyword_overlap) * 0.1
        final_scores.append((movie, round(score, 2)))

    final_scores.sort(key=lambda item: item[1], reverse=True)
    return final_scores[:10]


def rank_against_single_movie(base_movie, candidates, limit=6):
    if not base_movie:
        return []
    seen = set()
    unique = []
    for m in candidates:
        if m["id"] not in seen and respects_preferences(m):
            seen.add(m["id"])
            unique.append(m)
    ranked = recommend_from_viewed(
        favourites=[base_movie], candidates=unique, api_key=API_KEY
    )
    return ranked[:limit]


def build_finder_candidates(
    selected_genres, max_pages=15, min_popularity=7, min_rating=0.01
):
    genres_map = get_genres()
    selected_ids = [genres_map[g] for g in selected_genres if g in genres_map]
    required_matches = 1
    pool = []
    page = 1

    while page <= max_pages:
        data = tmdb_get(
            "/discover/movie",
            {
                "with_genres": ",".join(map(str, selected_ids)),
                "vote_average.gte": min_rating,
                "page": page,
            },
        )
        for m in data.get("results", []):
            movie_genres = set(m.get("genre_ids", []))
            if (
                len(movie_genres & set(selected_ids)) >= required_matches
                and m.get("popularity", 0) >= min_popularity
                and respects_preferences(m)
            ):
                pool.append(m)

        if len(pool) >= 200:
            break
        page += 1

    seen = set()
    unique = []
    for m in pool:
        if m["id"] not in seen:
            seen.add(m["id"])
            unique.append(m)
    return unique


def split_for_recommendation(pool, viewed_size=12):
    if len(pool) <= viewed_size:
        return pool, []
    random.shuffle(pool)
    viewed = pool[:viewed_size]
    candidates = pool[viewed_size:]
    return viewed, candidates


def display_movie_box(
    m,
    score=None,
    show_add_button=False,
    button_key=None,
    show_remove_button=False,
    highlight=False,
):
    poster_html = ""
    if m.get("poster_path"):
        poster_html = f'<div class="poster"><img src="{IMAGE_BASE + m["poster_path"]}" width="120"></div>'

    release = m.get("release_date", "TBA")
    score_text = f"Recommendation Score: {score}" if score is not None else ""
    overview = m.get("overview", "No overview available.")
    saved_count = favourite_count(m["id"]) if "id" in m else 0

    info_html = f"""
    <div class="info">
        <div class="movie-title">{m.get('title', 'Untitled')}</div>
        <div class="movie-header">
            <span>Release: {release}</span>
            <span>{score_text}</span>
        </div>
        <div class="movie-saved">
            Saved as favourite by {saved_count} user{"s" if saved_count != 1 else ""}
        </div>
        <div class="movie-overview">{overview}</div>
    </div>
    """

    card_class = "movie-card recommended" if highlight else "movie-card"
    st.markdown(
        f'<div class="{card_class}">{poster_html}{info_html}</div>',
        unsafe_allow_html=True,
    )

    if show_add_button and button_key:
        if st.button("Add to Favourites", key=button_key):

            already_added = any(
                fav["id"] == m["id"]
                for fav in st.session_state.favourites
            )

            if already_added:
                st.info("This movie is already in your favourites.")
            else:
                st.session_state.favourites.append(m)

                if not favourite_exists(st.session_state.user_id, m["id"]):
                    save_favourite(st.session_state.user_id, m)

                st.success("Added to your favourites!")

    if show_remove_button and button_key:
        if st.button("Remove", key=button_key):

            remove_favourite(st.session_state.user_id, m["id"])

            st.session_state.favourites = [
                fav for fav in st.session_state.favourites
                if fav["id"] != m["id"]
            ]

            st.rerun()

st.markdown(
    """
    <style>
    :root { --ink:#f4f0e8; --muted:#b5b0a7; --accent:#d6a85c; }
    .stApp { background:#101114; color:var(--ink); }
    [data-testid="stHeader"], header[data-testid="stHeader"], .stAppHeader, [data-testid="stToolbar"], [data-testid="stDecoration"] { background:#101114 !important; color:#f4f0e8 !important; }
    [data-testid="stHeader"] { border-bottom:1px solid #292a30; }
    [data-testid="stToolbar"] button, [data-testid="stStatusWidget"] button { color:#f4f0e8 !important; }
    [data-testid="stAppViewContainer"] { background:#101114 !important; }
    [data-testid="stSidebar"] [aria-current="page"], [data-testid="stSidebar"] a[aria-selected="true"] { background:#332b20 !important; border-left:3px solid #d6a85c !important; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2 { color:#f0c879 !important; }
    .stApp::before { content:""; display:block; height:3px; width:100%; background:linear-gradient(90deg,#7b3c42 0%,#d6a85c 52%,#286c68 100%); }
    /* Sidebar: cover Streamlit's current and legacy DOM wrappers. */
    section[data-testid="stSidebar"],
    [data-testid="stSidebar"],
    [data-testid="stSidebar"] > div,
    [data-testid="stSidebar"] > div > div,
    [data-testid="stSidebar"] [data-testid="stSidebarContent"],
    [data-testid="stSidebar"] [data-testid="stSidebarUserContent"],
    [data-testid="stSidebar"] [data-testid="stVerticalBlock"],
    [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"],
    [data-testid="stSidebar"] [data-testid="stElementContainer"],
    [data-testid="stSidebar"] [data-testid="stSidebarNav"],
    [data-testid="stSidebar"] [data-testid="stSidebarNavItems"] {
        background: #17181d !important;
        background-color: #17181d !important;
        color: #f4f0e8 !important;
    }
    [data-testid="stSidebar"]::before,
    [data-testid="stSidebar"]::after { background: #17181d !important; }
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] { background: transparent !important; }
    [data-testid="stSidebar"] .nav,
    [data-testid="stSidebar"] .nav-pills,
    [data-testid="stSidebar"] .nav-item { background: transparent !important; }
    [data-testid="stSidebar"] .nav-link,
    [data-testid="stSidebar"] a.nav-link,
    [data-testid="stSidebar"] button.nav-link {
        background: #202126 !important;
        background-color: #202126 !important;
        color: #d8d2c8 !important;
        border: 1px solid #303137 !important;
        border-radius: 10px !important;
        margin: 3px 0 !important;
    }
    [data-testid="stSidebar"] .nav-link:hover { background: #2a2927 !important; color: #f0c879 !important; border-color: #8c7044 !important; }
    [data-testid="stSidebar"] .nav-link.active,
    [data-testid="stSidebar"] .nav-link[aria-current="page"] { background: #332b20 !important; background-color: #332b20 !important; color: #f0c879 !important; border-left: 3px solid #d6a85c !important; }
    /* Force the option-menu area dark too; its internals vary by package version. */
    [data-testid="stSidebar"] iframe { color-scheme: dark !important; }
    [data-testid="stSidebar"] * { color: #f4f0e8; }
    [data-testid="stSidebar"] .nav-link, [data-testid="stSidebar"] .nav-link * { color: #d8d2c8 !important; }
    [data-testid="stSidebar"] .nav-link.active, [data-testid="stSidebar"] .nav-link.active * { color: #f0c879 !important; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #b5b0a7; }
    [data-testid="stSidebar"] [data-testid="stAlert"] { background:#24252a; border:1px solid #37383e; }
    h1,h2,h3 { letter-spacing:-.04em; color:#f4f0e8; } h1 { font-weight:850 !important; }
    [data-testid="stMarkdownContainer"] p,[data-testid="stMarkdownContainer"] li { color:#c8c3bb; }
    [data-testid="stCaptionContainer"] { color:#a7a29a; }
    [data-testid="stButton"] button { border-radius:11px; border:1px solid #393a40; background:#202126; color:#f4f0e8; font-weight:650; transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease; }
    [data-testid="stButton"] button:hover { border-color:#d6a85c; color:#f0c879; box-shadow:0 7px 22px rgba(0,0,0,.28); transform:translateY(-2px); }
    [data-testid="stButton"] button[kind="primary"] { background:#d6a85c; color:#17130d; border-color:#d6a85c; }
    [data-testid="stTextInput"] input,[data-testid="stTextArea"] textarea,[data-testid="stNumberInput"] input { border-radius:11px; background:#1c1d22; border-color:#393a40; color:#f4f0e8; }
    [data-testid="stTextInput"] input:focus,[data-testid="stTextArea"] textarea:focus { border-color:#d6a85c; box-shadow:0 0 0 1px #d6a85c; }
    [data-testid="stSelectbox"] [data-baseweb="select"],[data-testid="stMultiSelect"] [data-baseweb="select"] { background:#1c1d22; border-radius:11px; }
    [data-testid="stAlert"] { border-radius:13px; }
    [data-testid="stRadio"] label,[data-testid="stCheckbox"] label { color:#eee9e0; }
    .page-hero { position:relative; isolation:isolate; overflow:hidden; border:1px solid #393137; border-radius:24px; padding:clamp(26px,4vw,42px); margin:4px 0 28px; background:radial-gradient(ellipse at 88% 10%,rgba(214,168,92,.18),transparent 31%),linear-gradient(118deg,#211f25 0%,#2b2228 52%,#172426 100%); box-shadow:0 18px 48px rgba(0,0,0,.2); }
    .page-hero:after { content:"✦"; position:absolute; right:5%; top:-28px; font-family:Georgia,serif; font-size:150px; color:rgba(214,168,92,.07); pointer-events:none; }
    .page-hero-title { position:relative; z-index:1; color:#fffaf0; font-family:Georgia,"Times New Roman",serif; font-size:clamp(31px,4.5vw,49px); font-weight:700; line-height:1.08; letter-spacing:-.045em; max-width:760px; margin:0 0 13px; }
    .page-hero-copy { position:relative; z-index:1; color:#d0c8c1 !important; font-size:15px; line-height:1.75; max-width:690px; margin:0; }
    .panel-heading { color:#f4f0e8; font-family:Georgia,"Times New Roman",serif; font-size:25px; font-weight:700; letter-spacing:-.025em; margin:8px 0 5px; }
    .panel-copy { color:#aaa59e !important; font-size:14px; line-height:1.7; margin:0 0 18px; }
    .stat-tile { min-height:112px; padding:17px 18px; margin:8px 0 18px; border-radius:15px; border:1px solid #33343a; background:linear-gradient(145deg,#222329,#191a1e); }
    .stat-label,.detail-label { color:#c69d58; font-size:10px; font-weight:850; letter-spacing:.16em; margin-bottom:9px; }
    .stat-value { color:#fff5e4; font-family:Georgia,"Times New Roman",serif; font-size:27px; font-weight:700; line-height:1.2; }
    .stat-note { color:#9e9992; font-size:12px; margin-top:5px; }
    .detail-panel,.empty-panel { border:1px solid #303137; background:linear-gradient(145deg,#202126,#191a1e); border-radius:16px; padding:22px; margin:10px 0 20px; }
    .detail-label { margin-top:6px; }
    .detail-value { color:#e3ddd4; font-size:15px; line-height:1.8; margin-bottom:17px; }
    .detail-value:last-child { margin-bottom:0; }
    .stat-strip { display:flex; align-items:center; gap:14px; border-bottom:1px solid #303137; padding:0 0 18px; margin:0 0 22px; }
    .stat-strip-number { color:#f0c879; font-family:Georgia,"Times New Roman",serif; font-size:34px; font-weight:700; }
    .stat-strip-label { color:#aaa59e; font-size:10px; font-weight:850; letter-spacing:.17em; }
    .empty-title { color:#fff5e4; font-family:Georgia,"Times New Roman",serif; font-size:24px; font-weight:700; margin-bottom:7px; }
    .hero-banner { position:relative; isolation:isolate; overflow:hidden; border:1px solid #393137; border-radius:26px; padding:clamp(28px,5vw,52px); margin:4px 0 30px; background:radial-gradient(ellipse at 82% 18%,rgba(214,168,92,.23),transparent 30%),linear-gradient(118deg,#242027 0%,#31232a 48%,#172629 100%); color:#fff; box-shadow:0 24px 65px rgba(0,0,0,.26); }
    .hero-banner:before { content:""; position:absolute; z-index:-1; width:330px; height:330px; right:-80px; bottom:-180px; border:1px solid rgba(214,168,92,.28); border-radius:50%; box-shadow:0 0 0 28px rgba(214,168,92,.035),0 0 0 58px rgba(214,168,92,.025); }
    .hero-banner:after { content:"MM"; position:absolute; z-index:-1; right:5%; top:8%; font-family:Georgia,serif; font-size:clamp(100px,17vw,210px); font-weight:900; letter-spacing:-.12em; color:rgba(255,255,255,.035); line-height:1; }
    .hero-eyebrow { color:#f0c879; font-size:11px; font-weight:850; letter-spacing:.2em; text-transform:uppercase; margin-bottom:15px; }
    .hero-title { color:#fffaf0; font-family:Georgia,"Times New Roman",serif; font-size:clamp(34px,5vw,58px); line-height:1.02; font-weight:700; letter-spacing:-.045em; max-width:680px; margin-bottom:17px; }
    .hero-copy { color:#d8d0c9 !important; font-size:16px; line-height:1.75; max-width:600px; margin:0; }
    .section-kicker { color:#e6b966; font-size:10px; font-weight:850; letter-spacing:.2em; text-transform:uppercase; margin:6px 0 7px; }
    .movie-card { background:linear-gradient(145deg,#202126,#191a1e); border:1px solid #303137; border-radius:18px; padding:18px; margin-bottom:15px; display:flex; gap:18px; box-shadow:0 10px 28px rgba(0,0,0,.15); color:#f4f0e8; transition:border-color .2s ease,transform .2s ease,box-shadow .2s ease; }
    .movie-card:hover { border-color:#8c7044; transform:translateY(-3px); box-shadow:0 16px 36px rgba(0,0,0,.27); }
    .movie-card.recommended { background:linear-gradient(135deg,#202a28,#1b1e20); border-color:#3c5a50; border-left:4px solid #d6a85c; }
    .poster { flex:0 0 120px; margin-right:0; } .poster img { border-radius:12px; width:120px; height:auto; box-shadow:0 8px 22px rgba(0,0,0,.38); }
    .info { flex:1; min-width:0; } .movie-title { font-family:Georgia,"Times New Roman",serif; font-size:23px; line-height:1.2; font-weight:700; margin:2px 0 10px; color:#fff7e9; }
    .movie-meta { font-size:14px; color:#b5b0a7; margin-bottom:10px; }
    .movie-overview { color:#c5c0b8; line-height:1.7; -webkit-line-clamp:4; display:-webkit-box; -webkit-box-orient:vertical; overflow:hidden; }
    .movie-header { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; font-size:12px; color:#b5b0a7; margin:2px 0 9px; }
    .movie-saved { font-size:12px; color:#e6b966; margin-bottom:8px; font-weight:650; }
    [data-testid="stForm"] { background:#1a1b20; border:1px solid #303137; border-radius:16px; padding:20px; }
    hr { border-color:#303137 !important; }
    @media (max-width:600px) { .hero-banner { padding:27px 22px; border-radius:19px; } .movie-card { padding:12px; gap:12px; border-radius:14px; } .poster { flex-basis:88px; } .poster img { width:88px; } .movie-title { font-size:19px; } }
    </style>
    """,
    unsafe_allow_html=True,
)




if st.session_state.route == "Preferences":
    st.markdown("""
    <div class="page-hero">
      <div class="hero-eyebrow">YOUR TASTE, YOUR RULES</div>
      <div class="page-hero-title">Build your cinema profile.</div>
      <p class="page-hero-copy">Tune your language, era, and favourite genres so MediaMatcher can find films that feel made for you.</p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('<div class="section-kicker">PERSONALISE YOUR EXPERIENCE</div>', unsafe_allow_html=True)
    if not is_preferences_complete(st.session_state.preferences):
        st.markdown('<div class="panel-heading">Let’s get to know your taste</div><p class="panel-copy">Choose your settings below. We’ll use them to shape your recommendations.</p>', unsafe_allow_html=True)
        lang_map = {
            "English": "en",
            "Hindi": "hi",
            "French": "fr",
            "Spanish": "es",
            "German": "de",
            "Japanese": "ja",
            "Korean": "ko",
        }
        chosen_langs = st.multiselect(
            "Preferred languages", list(lang_map.keys())
        )
        years = st.slider(
            "Release year range", 1885, 2026, (2000, 2026)
        )
        fav_genres = st.multiselect(
            "Your 4 favorite genres",
            list(GENRES_MAP.keys()),
            max_selections=4,
        )
        fav_movies_input = st.text_area(
            "Enter your 3 favorite movies (comma separated)"
        )

        if st.button("Save Preferences"):
            fav_movies = [
                m.strip() for m in fav_movies_input.split(",") if m.strip()
            ]
            if len(chosen_langs) < 1:
                st.warning("Please choose at least one language.")
            elif len(fav_genres) != 4:
                st.warning("Please select exactly 4 favorite genres.")
            elif len(fav_movies) != 3:
                st.warning("Please enter exactly 3 favorite movies.")
            else:
                st.session_state.preferences["languages"] = [
                    lang_map[l] for l in chosen_langs
                ]
                st.session_state.preferences["start_year"] = years[0]
                st.session_state.preferences["end_year"] = years[1]
                st.session_state.preferences["genres"] = fav_genres[:4]
                st.session_state.preferences["favorite_movies"] = fav_movies[
                    :3
                ]

                update_preferences(
                    st.session_state.user_id,
                    ",".join(st.session_state.preferences["languages"]),
                    years[0],
                    years[1],
                    ",".join(fav_genres),
                    ",".join(fav_movies),
                )

                for title in st.session_state.preferences["favorite_movies"]:
                    results = [
                        m
                        for m in search_movies(title)
                        if respects_preferences(m)
                    ]
                    if results:
                        movie = results[0]
                        if movie not in st.session_state.favourites:
                            st.session_state.favourites.append(movie)
                        if not favourite_exists(
                            st.session_state.user_id, movie["id"]
                        ):
                            save_favourite(st.session_state.user_id, movie)

                st.success(
                    "Preferences saved! Your favorite movies have been added to favourites."
                )
                st.session_state.route = "Home"
                st.rerun()
    else:
        prefs = st.session_state.preferences
        st.markdown('<div class="panel-heading">Your current profile</div><p class="panel-copy">Your discovery settings at a glance.</p>', unsafe_allow_html=True)
        p1, p2, p3 = st.columns(3)
        with p1:
            st.markdown(f'<div class="stat-tile"><div class="stat-label">LANGUAGES</div><div class="stat-value">{len(prefs["languages"])}</div><div class="stat-note">selected</div></div>', unsafe_allow_html=True)
        with p2:
            st.markdown(f'<div class="stat-tile"><div class="stat-label">RELEASE ERA</div><div class="stat-value">{prefs["start_year"]}–{prefs["end_year"]}</div><div class="stat-note">your preferred years</div></div>', unsafe_allow_html=True)
        with p3:
            st.markdown(f'<div class="stat-tile"><div class="stat-label">GENRES</div><div class="stat-value">{len(prefs["genres"])}</div><div class="stat-note">of 4 chosen</div></div>', unsafe_allow_html=True)
        st.markdown('<div class="detail-panel"><div class="detail-label">PREFERRED LANGUAGES</div><div class="detail-value">' + ", ".join(prefs["languages"]) + '</div><div class="detail-label">FAVOURITE GENRES</div><div class="detail-value">' + ", ".join(prefs["genres"]) + '</div><div class="detail-label">INSPIRATION FILMS</div><div class="detail-value">' + ", ".join(prefs["favorite_movies"]) + '</div></div>', unsafe_allow_html=True)
        if st.button("Edit Preferences"):
            st.session_state.preferences = {
                "languages": [],
                "start_year": None,
                "end_year": None,
                "genres": [],
                "favorite_movies": [],
            }
            st.rerun()

elif st.session_state.route == "Finder":
    st.markdown("""
    <div class="page-hero">
      <div class="hero-eyebrow">THE DISCOVERY STUDIO</div>
      <div class="page-hero-title">Tell us the mood. We’ll find the movie.</div>
      <p class="page-hero-copy">Blend genres and set a rating threshold to uncover films worth your next evening.</p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('<div class="section-kicker">DESIGN YOUR SEARCH</div>', unsafe_allow_html=True)
    st.markdown('<div class="panel-heading">Set your film criteria</div><p class="panel-copy">Pick up to four genres and a minimum rating. Choose at least two genres to start the search.</p>', unsafe_allow_html=True)
    genres = list(get_genres().keys())
    selected_genres = st.multiselect(
        "Choose genres", genres, max_selections=4
    )
    min_rating = st.slider(
        "Minimum movie rating",
        min_value=0.0,
        max_value=10.0,
        value=7.0,
        step=0.5,
    )

    if st.button("Find Movies"):
        if len(selected_genres) < 2:
            st.warning("Select at least 2 genres.")
        else:
            with st.spinner("Building recommendations..."):
                pool = build_finder_candidates(
                    selected_genres, max_pages=10, min_rating=min_rating
                )
                if len(pool) < 80:
                    pool = build_finder_candidates(
                        selected_genres, max_pages=20, min_rating=min_rating
                    )
                viewed, candidates = split_for_recommendation(pool)
                if not candidates:
                    st.info("Not enough movies found. Try different genres.")
                else:
                    recs = recommend_from_viewed(
                        viewed, candidates, API_KEY
                    )
                    st.session_state.finder_results = recs

    if st.session_state.finder_results:
        st.markdown('<div class="section-kicker">CURATED FOR YOUR SEARCH</div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-heading">Your matches</div><p class="panel-copy">A shortlist built around the genres and rating you selected.</p>', unsafe_allow_html=True)
        for i, (m, score) in enumerate(st.session_state.finder_results[:12]):
            display_movie_box(
                m,
                score=score,
                show_add_button=True,
                button_key=f"finder_{i}",
            )

elif st.session_state.route == "Favourites":
    st.markdown("""
    <div class="page-hero">
      <div class="hero-eyebrow">YOUR PRIVATE COLLECTION</div>
      <div class="page-hero-title">The ones worth keeping.</div>
      <p class="page-hero-copy">Every saved film helps MediaMatcher understand your taste and make smarter suggestions.</p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown(f'<div class="stat-strip"><span class="stat-strip-number">{len(st.session_state.favourites)}</span><span class="stat-strip-label">FILMS IN YOUR COLLECTION</span></div>', unsafe_allow_html=True)
    if not st.session_state.favourites:
        st.markdown('<div class="empty-panel"><div class="empty-title">Your collection starts here.</div><div class="panel-copy">Search for a film you love and save it to build your personal cinema shelf.</div></div>', unsafe_allow_html=True)
    else:
        for i, m in enumerate(st.session_state.favourites):
            display_movie_box(
                m, show_remove_button=True, button_key=f"rm_{i}"
            )

elif st.session_state.route == "Recommended":
    st.markdown("""
    <div class="page-hero">
      <div class="hero-eyebrow">A LITTLE MORE YOU</div>
      <div class="page-hero-title">Your next favourite is out there.</div>
      <p class="page-hero-copy">Recommendations are shaped by your saved films, genre overlap, ratings, and viewing preferences.</p>
    </div>
    """, unsafe_allow_html=True)
    if not st.session_state.favourites:
        st.markdown('<div class="empty-panel"><div class="empty-title">Give us a starting point.</div><div class="panel-copy">Save a few films you love first. We’ll use them to build a more personal set of recommendations.</div></div>', unsafe_allow_html=True)
    else:
        pool = []
        TARGET_POOL_SIZE = 400
        MAX_PAGES = 10

        for m in st.session_state.favourites:
            sims = cached_similar(m["id"])
            for x in sims:
                if x.get("popularity", 0) >= 11 and respects_preferences(x):
                    pool.append(x)

        page = 1
        while len(pool) < TARGET_POOL_SIZE and page <= MAX_PAGES:
            discovered = tmdb_get(
                "/discover/movie",
                {"vote_average.gte": 1, "page": page},
            ).get("results", [])
            for x in discovered:
                if x.get("popularity", 0) >= 11 and respects_preferences(x):
                    pool.append(x)
            page += 1

        seen = set()
        unique = []
        for m in pool:
            if m["id"] not in seen:
                seen.add(m["id"])
                unique.append(m)

        normal_candidates = [
            m
            for m in unique
            if respects_preferences(m) and m.get("vote_average", 0) > 0.01
        ]
        recs = recommend_from_viewed(
            st.session_state.favourites, normal_candidates, API_KEY
        )

        st.markdown('<div class="section-kicker">MATCHED TO YOUR TASTE</div>', unsafe_allow_html=True)
        st.markdown('<div class="panel-heading">Your top 10 picks</div><p class="panel-copy">Ranked to help you discover something new without losing the thread of what you enjoy.</p>', unsafe_allow_html=True)
        if not recs:
            st.info("Not enough data yet. Showing best available matches.")

        for i, (m, score) in enumerate(recs[:10]):
            display_movie_box(
                m,
                score=score,
                show_add_button=True,
                button_key=f"rec_{i}",
                highlight=False,
            )

elif st.session_state.route == "Upcoming":
    st.markdown("""
    <div class="page-hero">
      <div class="hero-eyebrow">COMING SOON TO YOUR WATCHLIST</div>
      <div class="page-hero-title">Make room for what’s next.</div>
      <p class="page-hero-copy">A look ahead at upcoming releases, with picks informed by the films you already enjoy.</p>
    </div>
    """, unsafe_allow_html=True)
    TODAY = date.today()
    pool = []

    for fav in st.session_state.favourites:
        try:
            sims = cached_similar(fav["id"])
            for m in sims:
                if m.get("release_date"):
                    try:
                        rd = date.fromisoformat(m["release_date"])
                        if rd > TODAY:
                            pool.append(m)
                    except ValueError:
                        pass
        except Exception:
            pass

    if len(pool) < 10:
        page = 1
        while page <= 5 and len(pool) < 40:
            data = tmdb_get("/movie/upcoming", {"page": page})
            for m in data.get("results", []):
                if m.get("release_date"):
                    try:
                        rd = date.fromisoformat(m["release_date"])
                        if rd > TODAY:
                            pool.append(m)
                    except ValueError:
                        pass
            page += 1

    seen = set()
    unique = []
    for m in pool:
        if m.get("id") and m["id"] not in seen:
            seen.add(m["id"])
            unique.append(m)

    ranked = recommend_from_viewed(st.session_state.favourites, unique, API_KEY)
    if len(ranked) < 3:
        ranked = [(m, 0.0) for m in unique[:3]]

    st.markdown('<div class="section-kicker">ON THE HORIZON</div>', unsafe_allow_html=True)
    st.markdown('<div class="panel-heading">Upcoming picks for you</div><p class="panel-copy">Release dates can change, so check the latest listings before planning a premiere night.</p>', unsafe_allow_html=True)
    for i, (m, score) in enumerate(ranked[:3]):
        display_movie_box(
            m,
            score=score,
            show_add_button=True,
            button_key=f"upcoming_{i}",
        )

elif st.session_state.route == "Accounts":
    st.markdown("""
    <div class="page-hero account-hero">
      <div class="hero-eyebrow">WELCOME TO MEDIAMATCHER</div>
      <div class="page-hero-title">Your next great watch starts here.</div>
      <p class="page-hero-copy">Sign in to return to your collection, or create an account to start building a cinema profile that’s yours.</p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('<div class="section-kicker">YOUR ACCOUNT</div>', unsafe_allow_html=True)
    st.markdown(
        "Welcome! Please log in to an existing account or create a new "
        "one to save your preferences and favourites."
    )
    option = st.radio(
        "Choose option", ["Login", "Create Account"], horizontal=True
    )
    st.markdown("---")

    if option == "Login":
        st.subheader("Login")
        email = st.text_input("Email Address", key="login_email")
        password = st.text_input(
            "Password", type="password", key="login_password"
        )

        if st.button("Login", use_container_width=True):
            if email == "" or password == "":
                st.error("Please fill in all fields.")
            else:
                user = login_user(email, password)
                if user:
                    st.session_state.logged_in = True
                    st.session_state.user_id = user["user_id"]
                    st.session_state.user_email = user["email"]

                    prefs = load_preferences(user["user_id"])
                    if prefs:
                        st.session_state.preferences = {
                            "languages": prefs[0].split(",") if prefs[0] else [],
                            "start_year": prefs[1],
                            "end_year": prefs[2],
                            "genres": prefs[3].split(",") if prefs[3] else [],
                            "favorite_movies": prefs[4].split(",")
                            if prefs[4]
                            else [],
                        }

                    st.session_state.favourites = []
                    for movie in load_favourites(user["user_id"]):
                        full_movie = get_movie(movie[0])
                        if full_movie:
                            st.session_state.favourites.append(full_movie)

                    st.success("Login successful!")
                    st.session_state.route = "Home"
                    st.rerun()
                else:
                    st.error("Incorrect email or password.")
    else:
        st.subheader("Create Account")
        email = st.text_input("Email Address", key="signup_email")
        phone = st.text_input("Phone Number", key="signup_phone")
        password = st.text_input(
            "Password", type="password", key="signup_password"
        )
        confirm = st.text_input(
            "Confirm Password", type="password", key="signup_confirm"
        )

        if st.button("Create Account", use_container_width=True):
            if "" in [email, phone, password, confirm]:
                st.error("Please fill in all fields.")
            elif not valid_email(email):
                st.error("Please enter a valid email address.")
            elif len(password) < 8:
                st.error("Password must be at least 8 characters long.")
            elif password != confirm:
                st.error("Passwords do not match.")
            else:
                try:
                    create_user(email, phone, password)
                    user = login_user(email, password)
                    if user:
                        st.session_state.logged_in = True
                        st.session_state.user_id = user["user_id"]
                        st.session_state.user_email = user["email"]
                        st.session_state.preferences = {
                            "languages": [],
                            "start_year": None,
                            "end_year": None,
                            "genres": [],
                            "favorite_movies": [],
                        }
                        st.session_state.favourites = []
                        st.success("Account created successfully!")
                        st.session_state.route = "Preferences"
                        st.rerun()
                    else:
                        st.error(
                            "Account was created, but automatic login failed."
                        )
                except Exception as e:
                    st.error(str(e))

else:
    st.markdown(
        """
        <div class="hero-banner">
          <div class="hero-eyebrow">Your personal cinema guide</div>
          <div class="hero-title">A better watch starts with a great match.</div>
          <p class="hero-copy">Find films that fit your taste, save the ones you love, and discover your next favourite from a world of cinema.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="section-kicker">Explore the catalogue</div>', unsafe_allow_html=True)
    st.title("Find your next favourite")
    st.write("Search by title to explore films and get tailored recommendations.")
    query = st.text_input("Search movies", placeholder="Try Dune, Inception, Spirited Away…", label_visibility="collapsed")

    if query:
        results = search_movies(query)
        if not results:
            st.info("No movies found.")
        else:
            results = sorted(
                results,
                key=lambda m: m.get("popularity", 0),
                reverse=True,
            )
            st.subheader("Search Results")
            for i, m in enumerate(results[:10]):
                display_movie_box(
                    m,
                    show_add_button=True,
                    button_key=f"home_add_{i}",
                )

                if st.button("Recommend Similar", key=f"home_rec_{i}"):
                    pool = []
                    TARGET_POOL = 50

                    for x in cached_similar(m["id"]):
                        if x.get("popularity", 0) > 11 and respects_preferences(
                            x
                        ):
                            pool.append(x)

                    page = 1
                    while len(pool) < TARGET_POOL and page <= 6:
                        discovered = tmdb_get(
                            "/discover/movie",
                            {"vote_average.gte": 1, "page": page},
                        ).get("results", [])
                        for x in discovered:
                            if (
                                x.get("popularity", 0) >= 11
                                and respects_preferences(x)
                            ):
                                pool.append(x)
                        page += 1

                    ranked = rank_against_single_movie(m, pool, limit=5)

                    st.markdown(
                        f"""
                        <div style="
                            background-color:#eef6ff;
                            padding:20px;
                            border-radius:12px;
                            margin-top:25px;
                            border-left:6px solid #4a90e2;
                        ">
                        <h3>Recommendations</h3>
                        <p style="color:#555;">Based on <strong>{m.get('title', 'Movie')}</strong></p>
                        """,
                        unsafe_allow_html=True,
                    )
                    for j, (sm, score) in enumerate(ranked[:5]):
                        display_movie_box(
                            sm,
                            score=score,
                            show_add_button=True,
                            button_key=f"home_sim_{i}_{j}",
                            highlight=True,
                        )
                    st.markdown("</div>", unsafe_allow_html=True)