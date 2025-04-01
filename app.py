from flask import Flask, render_template, request, jsonify, url_for, send_from_directory
import os
import threading
import queue
import time
import json
import csv
import io
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import make_response

from database import get_all_fish_data, init_db, IMAGE_DIR
from detector import detect_and_extract_fish
from llm_handler import get_fish_taxonomy

# --- Flask App Setup ---
app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads/"
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB upload limit
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)  # Ensure image dir exists too

# --- Global Variables for Progress Tracking ---
# Using dictionaries to manage state for potentially multiple uploads (though simple example assumes one at a time)
progress_status = {
    "detection": {"current": 0, "total": 1, "error": False, "message": "Idle"},
    "characterization": {"current": 0, "total": 0, "error": False, "message": "Idle"},
    "processing_active": False,
}
progress_lock = threading.Lock()  # To safely update progress from threads
characterization_queue = queue.Queue()
llm_worker_stop_event = threading.Event()


# --- Background Worker for LLM ---
def llm_worker():
    """Worker thread to process images from the queue using Gemini."""
    print("LLM Worker thread started.")
    total_characterized = 0
    while not llm_worker_stop_event.is_set():
        try:
            # Get task from queue, wait up to 1 second if empty
            task = characterization_queue.get(timeout=1)
            fish_id = task["id"]
            image_filename = task["filename"]

            print(f"LLM Worker processing task for fish ID: {fish_id}")
            get_fish_taxonomy(
                fish_id, image_filename
            )  # This function handles DB updates and rate limits

            total_characterized += 1
            with progress_lock:
                # Update characterization progress *after* successful processing
                # Note: 'total' might still be increasing if detection is ongoing
                progress_status["characterization"]["current"] = total_characterized
                progress_status["characterization"]["message"] = (
                    f"Characterized {total_characterized}/{progress_status['characterization']['total']}..."
                )

            characterization_queue.task_done()  # Signal task completion

        except queue.Empty:
            # Queue is empty, check if processing is still active
            with progress_lock:
                if (
                    not progress_status["processing_active"]
                    and characterization_queue.empty()
                ):
                    print("LLM Worker: Queue empty and processing inactive. Exiting.")
                    break  # Exit loop if main processing is done and queue is empty
            continue  # Go back to waiting if processing might still add items
        except Exception as e:
            print(f"Error in LLM worker: {e}")
            # Optionally mark the specific task as error in DB if possible
            characterization_queue.task_done()  # Still need to mark task done

    print("LLM Worker thread finished.")


# --- Progress Update Callback ---
def update_detection_progress(current_frame, total_frames, error_occurred):
    """Callback function for the detector thread to update progress."""
    with progress_lock:
        progress_status["detection"]["current"] = current_frame
        progress_status["detection"]["total"] = total_frames
        progress_status["detection"]["error"] = error_occurred
        if error_occurred:
            progress_status["detection"]["message"] = "Error during detection."
        elif current_frame >= total_frames:
            progress_status["detection"]["message"] = (
                f"Detection complete ({characterization_queue.qsize()} items queued)."
            )
            # Update total characterization count *once* detection is done
            progress_status["characterization"]["total"] = (
                characterization_queue.qsize()
            )
            if progress_status["characterization"]["total"] == 0:
                progress_status["characterization"]["message"] = (
                    "No fish found to characterize."
                )
            else:
                progress_status["characterization"]["message"] = (
                    f"Waiting to characterize {progress_status['characterization']['total']} fish..."
                )

        else:
            progress_status["detection"]["message"] = (
                f"Detecting... frame {current_frame}/{total_frames}"
            )


# --- Flask Routes ---
@app.route("/")
def index():
    """Renders the main page."""
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload_video():
    """Handles video upload, starts background processing."""
    global llm_worker_thread  # Make sure we can potentially manage the thread later
    with progress_lock:
        if progress_status["processing_active"]:
            return jsonify({"error": "Processing already in progress."}), 400

    if "videoFile" not in request.files:
        return jsonify({"error": "No video file part"}), 400

    file = request.files["videoFile"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if file:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        try:
            file.save(filepath)
            print(f"Video saved to {filepath}")

            # Reset progress and start processing
            with progress_lock:
                progress_status["detection"] = {
                    "current": 0,
                    "total": 1,
                    "error": False,
                    "message": "Initializing...",
                }
                progress_status["characterization"] = {
                    "current": 0,
                    "total": 0,
                    "error": False,
                    "message": "Waiting for detection...",
                }
                progress_status["processing_active"] = True
                llm_worker_stop_event.clear()  # Ensure stop event is clear for new run

            # Start detection in a background thread
            detection_thread = threading.Thread(
                target=run_detection_and_wait, args=(filepath,), daemon=True
            )
            detection_thread.start()

            # Start LLM worker thread if not already running (or restart if needed)
            # Simple check: if thread is dead or not initialized
            if "llm_worker_thread" not in globals() or not llm_worker_thread.is_alive():
                llm_worker_thread = threading.Thread(target=llm_worker, daemon=True)
                llm_worker_thread.start()
            else:
                print("LLM worker thread already running.")

            return jsonify({"message": "Upload successful, processing started."})

        except Exception as e:
            print(f"Error during file save or processing start: {e}")
            with progress_lock:
                progress_status["processing_active"] = (
                    False  # Ensure processing stops on error
                )
            return jsonify({"error": f"Failed to process video: {e}"}), 500

    return jsonify({"error": "Invalid file."}), 400


def run_detection_and_wait(filepath):
    """Wrapper function to run detection and then signal completion."""
    try:
        detect_and_extract_fish(
            filepath, characterization_queue, update_detection_progress
        )
    except Exception as e:
        print(f"Error in detection thread: {e}")
        update_detection_progress(
            progress_status["detection"]["current"],
            progress_status["detection"]["total"],
            True,
        )  # Signal error
    finally:
        # Signal that the main processing (detection) phase is no longer adding items
        with progress_lock:
            progress_status["processing_active"] = False
        print("Detection thread finished.")
        # The LLM worker will eventually stop itself when the queue is empty and processing_active is False


@app.route("/progress")
def progress():
    """Endpoint for the frontend to poll for progress updates."""
    with progress_lock:
        # Check if LLM worker finished naturally
        char_total = progress_status["characterization"]["total"]
        char_current = progress_status["characterization"]["current"]
        if (
            not progress_status["processing_active"]
            and characterization_queue.empty()
            and char_total > 0
            and char_current == char_total
        ):
            progress_status["characterization"]["message"] = (
                f"Characterization complete ({char_current}/{char_total})."
            )

        return jsonify(progress_status)


@app.route("/results")
def results():
    """Endpoint for the frontend to poll for the latest database results."""
    try:
        data = get_all_fish_data()
        # Add full URL for images
        for item in data:
            item["image_url"] = url_for(
                "static",
                filename=f"{IMAGE_DIR}/{item['image_filename']}",
                _external=False,
            )
            # Parse timestamps string back to list for easier frontend handling
            item["timestamps"] = json.loads(item["timestamps"])
            # Parse taxonomy JSON string if it exists
            if item["taxonomy_json"]:
                item["taxonomy_data"] = json.loads(item["taxonomy_json"])
            else:
                item["taxonomy_data"] = None  # Or an empty dict {}

        return jsonify(data)
    except Exception as e:
        print(f"Error fetching results: {e}")
        return jsonify({"error": "Could not fetch results"}), 500


# Serve static files (like the cropped fish images)
@app.route("/static/detected_fish/<filename>")
def serve_fish_image(filename):
    # Use send_from_directory for security
    return send_from_directory(IMAGE_DIR, filename)


@app.route("/download-csv")
def download_csv():
    """Endpoint to download all fish detection data as a CSV file."""
    try:
        # Get all data from the database
        fish_data = get_all_fish_data()

        # Create a StringIO object to write CSV data
        csv_data = io.StringIO()
        csv_writer = csv.writer(csv_data)

        # Write header row
        csv_writer.writerow(
            [
                "ID",
                "Image Filename",
                "Timestamps",
                "Status",
                "Kingdom",
                "Phylum",
                "Class",
                "Order",
                "Family",
                "Genus",
                "Species",
            ]
        )

        # Write data rows
        for fish in fish_data:
            # Parse taxonomy data if available
            taxonomy = {}
            if fish["taxonomy_json"]:
                taxonomy = json.loads(fish["taxonomy_json"])

            # Write row
            csv_writer.writerow(
                [
                    fish["id"],
                    fish["image_filename"],
                    fish["timestamps"],  # This will be a JSON string
                    fish["status"],
                    taxonomy.get("Kingdom", "Unknown"),
                    taxonomy.get("Phylum", "Unknown"),
                    taxonomy.get("Class", "Unknown"),
                    taxonomy.get("Order", "Unknown"),
                    taxonomy.get("Family", "Unknown"),
                    taxonomy.get("Genus", "Unknown"),
                    taxonomy.get("Species", "Unknown"),
                ]
            )

        # Create response with CSV data
        response = make_response(csv_data.getvalue())
        response.headers["Content-Disposition"] = (
            f"attachment; filename=fish_detections_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        response.headers["Content-type"] = "text/csv"

        return response

    except Exception as e:
        print(f"Error generating CSV: {e}")
        return jsonify({"error": "Could not generate CSV"}), 500


# --- Main Execution ---
if __name__ == "__main__":
    init_db()  # Ensure DB is initialized on startup
    # Start LLM worker thread on app start (can be debated, alternative is starting on first upload)
    # llm_worker_thread = threading.Thread(target=llm_worker, daemon=True)
    # llm_worker_thread.start()
    app.run(debug=True, host="0.0.0.0", port=8000)  # Use debug=False in production
