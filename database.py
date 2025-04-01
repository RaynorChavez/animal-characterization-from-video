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

    # Check if the table exists first
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='detected_fish'"
    )
    table_exists = cursor.fetchone()

    if not table_exists:
        # Create the table with all columns if it doesn't exist
        print("Creating new detected_fish table...")
        cursor.execute("""
            CREATE TABLE detected_fish (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                image_filename TEXT UNIQUE NOT NULL,
                video_filename TEXT NOT NULL,
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
        # Add an index for video filename lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_video_filename ON detected_fish (video_filename);
        """)
        conn.commit()
    else:
        # Check if we need to add the video_filename column (for backward compatibility)
        try:
            # Try to select from the column to see if it exists
            cursor.execute("SELECT video_filename FROM detected_fish LIMIT 1")
        except sqlite3.OperationalError:
            # Column doesn't exist, add it
            print("Adding video_filename column to existing database...")
            cursor.execute(
                "ALTER TABLE detected_fish ADD COLUMN video_filename TEXT DEFAULT 'unknown'"
            )
            conn.commit()
            print("Column added successfully")

        # Make sure indexes exist
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_perceptual_hash ON detected_fish (perceptual_hash);
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_video_filename ON detected_fish (video_filename);
        """)
        conn.commit()

    conn.close()


def add_or_update_fish(image_filename, video_filename, timestamp_str, p_hash):
    """Adds a new fish or updates the timestamp list of an existing similar fish."""
    conn = get_db()
    cursor = conn.cursor()

    # Check for existing fish with the same hash (or very similar if needed) from the same video
    cursor.execute(
        "SELECT id, timestamps FROM detected_fish WHERE perceptual_hash = ? AND video_filename = ?",
        (p_hash, video_filename),
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
            f"Updated timestamps for existing fish ID {existing_id} with hash {p_hash} from {video_filename}"
        )
    else:
        timestamps = json.dumps([timestamp_str])
        try:
            cursor.execute(
                """
                INSERT INTO detected_fish (image_filename, video_filename, timestamps, perceptual_hash, status)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    image_filename,
                    video_filename,
                    timestamps,
                    p_hash,
                    "pending_characterization",
                ),
            )
            conn.commit()
            new_entry_id = cursor.lastrowid
            print(
                f"Added new fish ID {new_entry_id} with hash {p_hash} from {video_filename}"
            )
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


def get_all_fish_data(video_filename=None):
    """Gets all fish data, optionally filtered by video filename."""
    conn = get_db()
    cursor = conn.cursor()

    if video_filename:
        cursor.execute(
            "SELECT id, image_filename, video_filename, timestamps, status, taxonomy_json FROM detected_fish "
            "WHERE video_filename = ? ORDER BY first_detected_at DESC",
            (video_filename,),
        )
    else:
        cursor.execute(
            "SELECT id, image_filename, video_filename, timestamps, status, taxonomy_json FROM detected_fish "
            "ORDER BY first_detected_at DESC"
        )

    results = cursor.fetchall()
    conn.close()
    # Convert Row objects to dictionaries for JSON serialization
    return [dict(row) for row in results]


def get_processed_videos():
    """Get a list of all processed video filenames."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT video_filename FROM detected_fish ORDER BY video_filename"
    )
    results = cursor.fetchall()
    conn.close()
    return [row["video_filename"] for row in results]


def delete_fish_entry(fish_id):
    """Delete a specific fish entry by ID."""
    conn = get_db()
    cursor = conn.cursor()

    # First get the image filename so we can delete the file
    cursor.execute("SELECT image_filename FROM detected_fish WHERE id = ?", (fish_id,))
    result = cursor.fetchone()

    if result:
        image_filename = result["image_filename"]

        # Delete the database entry
        cursor.execute("DELETE FROM detected_fish WHERE id = ?", (fish_id,))
        conn.commit()
        conn.close()

        # Return the image filename so the file can be deleted if needed
        return image_filename

    conn.close()
    return None


# Initialize the database on module load
init_db()
