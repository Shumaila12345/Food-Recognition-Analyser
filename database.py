import sqlite3
from datetime import datetime

DB_NAME = "food_history.db"


def init_db():
    """Creates the database and table if they don't already exist.
    Safe to call every time the app starts — won't erase existing data."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS analysis_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_food TEXT,
            confidence REAL,
            serving_size REAL,
            calories REAL,
            protein REAL,
            carbs REAL,
            fat REAL,
            fiber REAL,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_analysis(food_name, confidence, serving_size, nutrition):
    """Saves one detected food + its nutrition info as a row in the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO analysis_history 
        (detected_food, confidence, serving_size, calories, protein, carbs, fat, fiber, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        food_name,
        confidence,
        serving_size,
        nutrition.get("calories", 0),
        nutrition.get("protein", 0),
        nutrition.get("carbs", 0),
        nutrition.get("fat", 0),
        nutrition.get("fiber", 0),
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ))
    conn.commit()
    conn.close()


def get_all_history():
    """Retrieves every saved analysis, most recent first."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM analysis_history ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return rows


def delete_history_item(item_id):
    """Deletes one specific history entry by its id."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM analysis_history WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()


def clear_all_history():
    """Deletes ALL history entries."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM analysis_history")
    conn.commit()
    conn.close()