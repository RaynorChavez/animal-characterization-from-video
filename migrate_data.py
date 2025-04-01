#!/usr/bin/env python3
"""
Migration script to move existing fish images into video-specific directories
and update the database entries.
Run this script once after upgrading to the new version with video-specific organization.
"""

import os
import sqlite3
import shutil
import pathlib
from database import DATABASE_NAME, IMAGE_DIR


def migrate_images_to_video_folders():
    """
    Migrates existing fish images to video-specific folders and updates database records.
    """
    print("\n=== Fish Detection Data Migration Tool ===")
    print(
        "This tool will organize your existing detected fish images into video-specific folders."
    )
    print("Please make sure you have a backup of your data before proceeding.\n")

    # Confirm with user
    response = input("Do you want to proceed with the migration? (y/n): ")
    if response.lower() != "y":
        print("Migration cancelled.")
        return

    conn = sqlite3.connect(DATABASE_NAME)
    # Enable row_factory to get results as dictionaries
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Check if the database has the video_filename column
    try:
        cursor.execute("SELECT video_filename FROM detected_fish LIMIT 1")
    except sqlite3.OperationalError:
        print(
            "The database doesn't have a video_filename column. Please run the app once to upgrade the database schema."
        )
        conn.close()
        return

    # Get all fish data
    cursor.execute("SELECT id, image_filename, video_filename FROM detected_fish")
    fish_records = cursor.fetchall()

    print(f"Found {len(fish_records)} fish records to process.")

    # Get all unique video filenames
    cursor.execute("SELECT DISTINCT video_filename FROM detected_fish")
    videos = [row["video_filename"] for row in cursor.fetchall()]

    print(f"Found {len(videos)} unique videos.")

    # Create video-specific directories
    for video in videos:
        if video == "unknown":
            # Skip 'unknown' video entries for now
            continue

        # Create a safe directory name
        video_dirname = pathlib.Path(video).stem
        video_dirname = "".join(
            c if c.isalnum() or c in "-_" else "_" for c in video_dirname
        )
        video_dir = os.path.join(IMAGE_DIR, video_dirname)

        # Create the directory if it doesn't exist
        if not os.path.exists(video_dir):
            os.makedirs(video_dir, exist_ok=True)
            print(f"Created directory: {video_dir}")

    # Move files and update database records
    migrated_count = 0
    skipped_count = 0
    errors_count = 0

    for fish in fish_records:
        try:
            fish_id = fish["id"]
            image_filename = fish["image_filename"]
            video_filename = fish["video_filename"]

            # Skip if image_filename already contains a directory separator (already migrated)
            if os.path.dirname(image_filename):
                skipped_count += 1
                continue

            # Skip entries with unknown video
            if video_filename == "unknown":
                skipped_count += 1
                continue

            # Create the source and destination paths
            src_path = os.path.join(IMAGE_DIR, image_filename)

            # Create safe video directory name
            video_dirname = pathlib.Path(video_filename).stem
            video_dirname = "".join(
                c if c.isalnum() or c in "-_" else "_" for c in video_dirname
            )

            # New relative path (for database)
            new_rel_path = os.path.join(video_dirname, image_filename)

            # Destination path (for file system)
            dst_path = os.path.join(IMAGE_DIR, new_rel_path)

            # Check if the source file exists
            if not os.path.exists(src_path):
                print(
                    f"Warning: Source file not found: {src_path} (Fish ID: {fish_id})"
                )
                skipped_count += 1
                continue

            # Copy the file to the new location
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(src_path, dst_path)

            # Update the database with the new path
            cursor.execute(
                "UPDATE detected_fish SET image_filename = ? WHERE id = ?",
                (new_rel_path, fish_id),
            )

            migrated_count += 1

            # Print progress every 10 files
            if migrated_count % 10 == 0:
                print(f"Migrated {migrated_count} files so far...")

        except Exception as e:
            print(f"Error processing fish ID {fish['id']}: {e}")
            errors_count += 1

    # Commit changes to database
    conn.commit()
    conn.close()

    print("\n=== Migration Summary ===")
    print(f"Total records processed: {len(fish_records)}")
    print(f"Successfully migrated: {migrated_count}")
    print(f"Skipped (already migrated or unknown video): {skipped_count}")
    print(f"Errors: {errors_count}")

    if migrated_count > 0:
        print("\nMigration completed successfully!")
        print("Note: The original files were not deleted to ensure data safety.")
        print(
            "You can manually delete them from the main 'detected_fish' directory after verifying everything works."
        )
    else:
        print(
            "\nNo files were migrated. Either all files were already migrated or there were errors."
        )

    print(
        "\nIf you encounter any issues, please restore from your backup and try again."
    )


if __name__ == "__main__":
    migrate_images_to_video_folders()
