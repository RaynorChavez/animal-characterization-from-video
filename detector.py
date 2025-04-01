import cv2
from ultralytics import YOLO
import os
import uuid
import time
from PIL import Image
import imagehash  # For perceptual hashing
from database import add_or_update_fish, IMAGE_DIR
from dotenv import load_dotenv
import threading  # Added for stop event support
import pathlib  # For handling file paths
import shutil  # For file operations

# Load environment variables
load_dotenv()

# --- Configuration ---
MODEL_PATH = "yolov8s.pt"  # Or yolov8n.pt for smaller/faster, yolov8m/l/x for more accurate but slower/larger
CONFIDENCE_THRESHOLD = 0.4  # Minimum confidence for detection
# FRAMES_TO_SKIP = 15  # Process every Nth frame (adjust based on video speed/needs)
SECONDS_BETWEEN_FRAMES = float(
    os.getenv("SECONDS_BETWEEN_FRAMES", "5.0")
)  # Process a frame every X seconds (from .env or default to 5.0)
HASH_SIZE = 8  # Perceptual hash size (higher = more detail, slower)
HASH_SIMILARITY_THRESHOLD = (
    5  # How different hashes can be to be considered the same fish (lower = stricter)
)

# --- Load Model ---
# Ensure you have downloaded the model weights (it might download automatically first time)
try:
    print(
        f"Loading YOLO model '{MODEL_PATH}'... This may take a moment on first run as the model needs to be downloaded."
    )
    start_time = time.time()

    # Check if the model file exists locally before loading
    if not os.path.exists(MODEL_PATH):
        print(
            f"YOLO model file '{MODEL_PATH}' not found locally. It will be downloaded automatically (20-30MB)."
        )
        print("Downloading model. Please wait...")

    model = YOLO(MODEL_PATH)
    load_time = time.time() - start_time

    print(f"YOLO model '{MODEL_PATH}' loaded successfully in {load_time:.2f} seconds.")
    print(
        f"Using time-based frame sampling: processing a frame every {SECONDS_BETWEEN_FRAMES} seconds"
    )
except Exception as e:
    print(f"Error loading YOLO model: {e}")
    model = None


def detect_and_extract_fish(
    video_path, detection_queue, progress_callback, stop_event=None
):
    """
    Opens a video, detects fish frame by frame, extracts, hashes, saves,
    and adds new unique fish to the database and queue.

    Args:
        video_path: Path to the video file
        detection_queue: Queue for adding detected fish
        progress_callback: Callback function to report progress
        stop_event: Optional threading.Event to signal stopping the process
    """
    if not model:
        print("Detection cannot proceed: YOLO model not loaded.")
        progress_callback(0, 0, True)  # Signal error
        return

    # If no stop_event provided, create a dummy one that's never set
    if stop_event is None:
        stop_event = threading.Event()

    # Extract video filename from path
    video_filename = os.path.basename(video_path)

    # Create a safe directory name from the video filename
    video_dirname = pathlib.Path(video_filename).stem  # Remove the extension
    # Remove any special characters that might cause issues in directory names
    video_dirname = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in video_dirname
    )

    # Create video-specific directory for detected fish
    video_image_dir = os.path.join(IMAGE_DIR, video_dirname)
    os.makedirs(video_image_dir, exist_ok=True)

    print(f"Processing video: {video_filename}")
    print(f"Storing detected fish images in: {video_image_dir}")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Could not open video file {video_path}")
        progress_callback(0, 0, True)  # Signal error
        return

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = 0
    detected_count = 0
    processed_frame_count = 0  # Frames actually processed by YOLO

    # Calculate frames to skip based on time interval and FPS
    frames_to_skip = int(SECONDS_BETWEEN_FRAMES * fps)
    if frames_to_skip < 1:
        frames_to_skip = 1  # Ensure at least 1 frame is skipped

    print(
        f"Video FPS: {fps}, processing every {frames_to_skip} frames (about every {SECONDS_BETWEEN_FRAMES} seconds)"
    )

    last_processed_time = -float(
        "inf"
    )  # Initialize to negative infinity to ensure first frame is processed

    while not stop_event.is_set():
        ret, frame = cap.read()
        if not ret:
            break  # End of video

        frame_count += 1

        # Get current timestamp in seconds
        timestamp_msec = cap.get(cv2.CAP_PROP_POS_MSEC)
        timestamp_sec = timestamp_msec / 1000.0

        # Process only if enough time has passed since the last processed frame
        if timestamp_sec - last_processed_time < SECONDS_BETWEEN_FRAMES:
            # Check stop event more frequently
            if frame_count % 10 == 0 and stop_event.is_set():
                print("Stopping detection process as requested.")
                break
            continue

        # Check if stop requested before processing this frame
        if stop_event.is_set():
            print("Stopping detection process as requested.")
            break

        # Update the last processed time
        last_processed_time = timestamp_sec

        processed_frame_count += 1
        # Format timestamp (e.g., 00:01:23.456)
        minutes, seconds = divmod(timestamp_sec, 60)
        hours, minutes = divmod(minutes, 60)
        timestamp_str = f"{int(hours):02d}:{int(minutes):02d}:{seconds:06.3f}"

        # Run YOLO detection
        results = model.predict(
            frame, conf=CONFIDENCE_THRESHOLD, verbose=False
        )  # verbose=False reduces console spam

        # Process results
        for result in results:
            boxes = result.boxes
            for box in boxes.xyxy:  # Bounding boxes in xyxy format
                # Check stop event during processing
                if stop_event.is_set():
                    print("Stopping detection during result processing.")
                    break

                x1, y1, x2, y2 = map(int, box)

                # --- Optional: Filter by Class ID ---
                # current_class_id = int(boxes.cls[boxes.xyxy.tolist().index(box.tolist())])
                # if fish_class_id != -1 and current_class_id != fish_class_id:
                #      continue # Skip if not the fish class ID

                # Crop the detected fish
                cropped_fish = frame[y1:y2, x1:x2]

                # Ensure crop is valid
                if cropped_fish.size == 0:
                    print(
                        f"Warning: Empty crop at frame {frame_count}, timestamp {timestamp_str}. Skipping."
                    )
                    continue

                try:
                    # Convert to PIL Image for hashing
                    pil_image = Image.fromarray(
                        cv2.cvtColor(cropped_fish, cv2.COLOR_BGR2RGB)
                    )

                    # Calculate perceptual hash
                    p_hash = str(imagehash.phash(pil_image, hash_size=HASH_SIZE))

                    # --- Check for Similarity (More Advanced - Optional) ---
                    # Instead of exact hash match in DB, query for hashes within threshold
                    # This requires a different DB query approach (potentially slower)
                    # For simplicity, we'll use exact hash matching first. If too many duplicates
                    # are missed, this is the place to implement hamming distance check.

                    # Save the cropped image with a unique name
                    image_filename = f"fish_{uuid.uuid4()}.png"
                    save_path = os.path.join(video_image_dir, image_filename)
                    cv2.imwrite(save_path, cropped_fish)

                    # Store image path relative to IMAGE_DIR to preserve video folder organization
                    rel_image_path = os.path.join(video_dirname, image_filename)

                    # Add to DB or update timestamp; get ID if it's a *new* unique fish
                    new_fish_id = add_or_update_fish(
                        rel_image_path, video_filename, timestamp_str, p_hash
                    )

                    if new_fish_id:
                        detected_count += 1
                        # Add the *ID* and filename to the queue for LLM processing
                        detection_queue.put(
                            {"id": new_fish_id, "filename": rel_image_path}
                        )
                        print(f"Queued new fish ID {new_fish_id} for characterization.")
                    else:
                        # It was an update to an existing hash, don't requeue, maybe log differently?
                        # print(f"Updated existing fish with hash {p_hash} at {timestamp_str}")
                        # If we just updated, we don't increment detected_count as it's not 'new'
                        pass

                except Exception as e:
                    print(f"Error processing detection at frame {frame_count}: {e}")

            # Check if we need to stop after processing this batch of results
            if stop_event.is_set():
                break

        # Update progress periodically
        if processed_frame_count % 10 == 0:  # Update progress every 10 processed frames
            progress_callback(frame_count, total_frames, False)

    # If we exited because of stop_event
    if stop_event.is_set():
        print(
            f"Detection stopped by user. Processed {processed_frame_count} frames. Found {detected_count} unique new fish."
        )
        progress_callback(frame_count, total_frames, False)
    else:
        # We exited normally (end of video)
        cap.release()
        print(
            f"Video processing complete. Processed {processed_frame_count} frames. Found {detected_count} unique new fish."
        )
        # Final progress update
        progress_callback(total_frames, total_frames, False)
