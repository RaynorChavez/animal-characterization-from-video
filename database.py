import sqlite3
import json
import os
from datetime import datetime

DATABASE_NAME = "fish_database.db"
IMAGE_DIR = "detected_fish"

# Ensure the directory for storing images exists
os.makedirs(IMAGE_DIR, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row  # Return rows as dictionary-like objects
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS detected_fish (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_filename TEXT UNIQUE NOT NULL,
            timestamps TEXT NOT NULL, -- JSON list of timestamp strings
            perceptual_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending_characterization', -- pending_characterization, characterizing, characterized, error
            taxonomy_json TEXT,
            first_detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Add an index for faster hash lookups
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_perceptual_hash ON detected_fish (perceptual_hash);
    """)
    conn.commit()
    conn.close()


def add_or_update_fish(image_filename, timestamp_str, p_hash):
    """Adds a new fish or updates the timestamp list of an existing similar fish."""
    conn = get_db()
    cursor = conn.cursor()

    # Check for existing fish with the same hash (or very similar if needed)
    cursor.execute(
        "SELECT id, timestamps FROM detected_fish WHERE perceptual_hash = ?", (p_hash,)
    )
    existing = cursor.fetchone()

    new_entry_id = None
    updated_existing = False

    if existing:
        existing_id = existing["id"]
        timestamps = json.loads(existing["timestamps"])
        if (
            timestamp_str not in timestamps
        ):  # Avoid duplicate timestamps for the same fish
            timestamps.append(timestamp_str)
            timestamps.sort()  # Keep them ordered
            cursor.execute(
                "UPDATE detected_fish SET timestamps = ? WHERE id = ?",
                (json.dumps(timestamps), existing_id),
            )
            conn.commit()
        updated_existing = True
        print(
            f"Updated timestamps for existing fish ID {existing_id} with hash {p_hash}"
        )
    else:
        timestamps = json.dumps([timestamp_str])
        try:
            cursor.execute(
                """
                INSERT INTO detected_fish (image_filename, timestamps, perceptual_hash, status)
                VALUES (?, ?, ?, ?)
            """,
                (image_filename, timestamps, p_hash, "pending_characterization"),
            )
            conn.commit()
            new_entry_id = cursor.lastrowid
            print(f"Added new fish ID {new_entry_id} with hash {p_hash}")
        except sqlite3.IntegrityError:
            print(
                f"Warning: Attempted to insert duplicate image filename {image_filename} or hash {p_hash}. Skipping."
            )
            # This might happen in rare race conditions or if hashing isn't perfectly unique,
            # though filename should be unique (UUID).

    conn.close()
    # Return the ID if it's a new entry needing characterization, and whether it was an update
    return new_entry_id if not updated_existing else None


def get_pending_fish():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, image_filename FROM detected_fish WHERE status = 'pending_characterization'"
    )
    pending = cursor.fetchall()
    conn.close()
    return pending


def update_fish_status(fish_id, status, taxonomy_json=None):
    conn = get_db()
    cursor = conn.cursor()
    if taxonomy_json:
        cursor.execute(
            "UPDATE detected_fish SET status = ?, taxonomy_json = ? WHERE id = ?",
            (status, taxonomy_json, fish_id),
        )
    else:
        cursor.execute(
            "UPDATE detected_fish SET status = ? WHERE id = ?", (status, fish_id)
        )
    conn.commit()
    conn.close()


def get_all_fish_data():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, image_filename, timestamps, status, taxonomy_json FROM detected_fish ORDER BY first_detected_at DESC"
    )
    results = cursor.fetchall()
    conn.close()
    # Convert Row objects to dictionaries for JSON serialization
    return [dict(row) for row in results]


# Initialize the database on module load
init_db()
