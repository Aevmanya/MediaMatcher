-- Run this in the hosted MySQL database selected for MediaMatcher.
-- This schema is intended for the deployment-ready database.py, which hashes passwords.

CREATE TABLE IF NOT EXISTS users (
    user_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    phone VARCHAR(32) NOT NULL,
    password VARCHAR(255) NOT NULL,
    languages TEXT NULL,
    start_year SMALLINT NULL,
    end_year SMALLINT NULL,
    genres TEXT NULL,
    favourite_movies TEXT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS favourites (
    favourite_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    movie_id BIGINT NOT NULL,
    movie_title VARCHAR(512) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_movie (user_id, movie_id),
    CONSTRAINT fk_favourites_user FOREIGN KEY (user_id)
        REFERENCES users(user_id) ON DELETE CASCADE
);
