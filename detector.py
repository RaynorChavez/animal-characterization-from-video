import cv2
from ultralytics import YOLO
import os
import uuid
from PIL import Image
import imagehash  # For perceptual hashing
from database import add_or_update_fish, IMAGE_DIR

# --- Configuration ---
MODEL_PATH = "yolov8s.pt"  # Or yolov8n.pt for smaller/faster, yolov8m/l/x for more accurate but slower/larger
CONFIDENCE_THRESHOLD = 0.4  # Minimum confidence for detection
FRAMES_TO_SKIP = 15  # Process every Nth frame (adjust based on video speed/needs)
HASH_SIZE = 8  # Perceptual hash size (higher = more detail, slower)
HASH_SIMILARITY_THRESHOLD = (
    5  # How different hashes can be to be considered the same fish (lower = stricter)
)

# --- Load Model ---
# Ensure you have downloaded the model weights (it might download automatically first time)
try:
    model = YOLO(MODEL_PATH)
    # The COCO dataset (which yolov8 is pre-trained on) usually has 'fish' as class 78,
    # but it's safer to get the class index dynamically if possible, or confirm it.
    # For standard COCO pre-trained models, 'fish' might not be a default class.
    # It *does* detect broader categories like 'animal'.
    # Let's assume for now we look for *any* detected object and rely on Gemini.
    # OR, if 'fish' *is* a class:
    # fish_class_id = -1
    # for i, name in model.names.items():
    #     if name.lower() == 'fish':
    #         fish_class_id = i
    #         break
    # if fish_class_id == -1:
    #     print("Warning: 'fish' class not found in model names. Detecting all objects.")
    # else:
    #     print(f"Found 'fish' class with ID: {fish_class_id}")

    print(f"YOLO model '{MODEL_PATH}' loaded successfully.")
except Exception as e:
    print(f"Error loading YOLO model: {e}")
    model = None


def detect_and_extract_fish(video_path, detection_queue, progress_callback):
    """
    Opens a video, detects fish frame by frame, extracts, hashes, saves,
    and adds new unique fish to the database and queue.
    """
    if not model:
        print("Detection cannot proceed: YOLO model not loaded.")
        progress_callback(0, 0, True)  # Signal error
        return

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

    while True:
        ret, frame = cap.read()
        if not ret:
            break  # End of video

        frame_count += 1

        # Process only every Nth frame
        if frame_count % FRAMES_TO_SKIP != 0:
            continue

        processed_frame_count += 1
        timestamp_msec = cap.get(cv2.CAP_PROP_POS_MSEC)
        timestamp_sec = timestamp_msec / 1000.0
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
                    save_path = os.path.join(IMAGE_DIR, image_filename)
                    cv2.imwrite(save_path, cropped_fish)

                    # Add to DB or update timestamp; get ID if it's a *new* unique fish
                    new_fish_id = add_or_update_fish(
                        image_filename, timestamp_str, p_hash
                    )

                    if new_fish_id:
                        detected_count += 1
                        # Add the *ID* and filename to the queue for LLM processing
                        detection_queue.put(
                            {"id": new_fish_id, "filename": image_filename}
                        )
                        print(f"Queued new fish ID {new_fish_id} for characterization.")
                    else:
                        # It was an update to an existing hash, don't requeue, maybe log differently?
                        # print(f"Updated existing fish with hash {p_hash} at {timestamp_str}")
                        # If we just updated, we don't increment detected_count as it's not 'new'
                        pass

                except Exception as e:
                    print(f"Error processing detection at frame {frame_count}: {e}")

        # Update progress periodically
        if processed_frame_count % 10 == 0:  # Update progress every 10 processed frames
            progress_callback(frame_count, total_frames, False)

    cap.release()
    print(
        f"Video processing complete. Processed {processed_frame_count} frames. Found {detected_count} unique new fish."
    )
    # Final progress update
    progress_callback(total_frames, total_frames, False)
