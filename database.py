import sqlite3
import os
import hashlib
from datetime import datetime

DB_NAME = "food_history.db"


def get_connection():
    return sqlite3.connect(DB_NAME)


def init_db():
    """Creates the users table and analysis_history table if they don't
    already exist, and migrates older databases safely (adds columns that
    didn't exist in earlier versions of this app, without losing data)."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS analysis_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            detected_food TEXT,
            confidence REAL,
            serving_size REAL,
            calories REAL,
            protein REAL,
            carbs REAL,
            fat REAL,
            fiber REAL,
            sugar REAL,
            image_path TEXT,
            created_at TEXT
        )
    """)

    # Migrations for databases created before user_id / image_path / sugar
    # existed. NOTE: SQLite always appends ALTER TABLE columns at the
    # physical end of the table, regardless of the CREATE TABLE order above.
    # That's fine here because every query below names its columns
    # explicitly instead of using SELECT * — so column order on disk never
    # matters, unlike the bug we hit earlier with image_path.
    for column, col_type in [
        ("image_path", "TEXT"),
        ("user_id", "INTEGER"),
        ("sugar", "REAL"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE analysis_history ADD COLUMN {column} {col_type}")
        except sqlite3.OperationalError:
            pass  # column already exists, nothing to do

    conn.commit()
    conn.close()


# ---------- PASSWORD HASHING ----------

def _hash_password(password, salt):
    """PBKDF2-HMAC-SHA256 with 100,000 iterations and a random per-user
    salt. Uses only Python's built-in hashlib — no extra packages needed.
    Never store or compare raw passwords directly."""
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    ).hex()


# ---------- USER ACCOUNTS ----------

def create_user(username, password):
    """Creates a new user account. Returns True on success, or False if the
    username is already taken."""
    username = username.strip()
    salt = os.urandom(16).hex()
    password_hash = _hash_password(password, salt)

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
            (username, password_hash, salt, datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False  # username already exists
    finally:
        conn.close()


def verify_login(username, password):
    """Checks a username/password pair. Returns the user's id on success,
    or None if the username doesn't exist or the password is wrong."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, password_hash, salt FROM users WHERE username = ?",
        (username.strip(),),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    user_id, stored_hash, salt = row
    if _hash_password(password, salt) == stored_hash:
        return user_id
    return None


# ---------- ANALYSIS HISTORY (per user) ----------

def save_analysis(user_id, food_name, confidence, serving_size, nutrition, image_path=None):
    """Saves one detected food + its nutrition info as a row, tied to the
    logged-in user. image_path (optional) points to the saved copy of the
    uploaded photo."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO analysis_history
        (user_id, detected_food, confidence, serving_size, calories, protein, carbs, fat, fiber, sugar, image_path, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        food_name,
        confidence,
        serving_size,
        nutrition.get("calories", 0),
        nutrition.get("protein", 0),
        nutrition.get("carbs", 0),
        nutrition.get("fat", 0),
        nutrition.get("fiber", 0),
        nutrition.get("sugar", 0),
        image_path,
        datetime.now().strftime("%Y-%m-%d %H:%M"),
    ))
    conn.commit()
    conn.close()


def get_all_history(user_id):
    """Retrieves every saved analysis for ONE user only, most recent first.
    Columns are named explicitly so row order never depends on the
    physical on-disk column order."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, detected_food, confidence, serving_size, calories,
               protein, carbs, fat, fiber, sugar, image_path, created_at
        FROM analysis_history
        WHERE user_id = ?
        ORDER BY created_at DESC
    """, (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def delete_history_item(item_id, user_id):
    """Deletes one specific history entry, but only if it belongs to this
    user — prevents one user deleting another user's entry by guessing ids."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM analysis_history WHERE id = ? AND user_id = ?",
        (item_id, user_id),
    )
    conn.commit()
    conn.close()


def clear_all_history(user_id):
    """Deletes ALL history entries belonging to this user only."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM analysis_history WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()