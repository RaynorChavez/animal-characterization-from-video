import google.generativeai as genai
import os
import time
import json
from PIL import Image
import io
from database import update_fish_status, IMAGE_DIR
from dotenv import load_dotenv

load_dotenv()

# Configure Gemini model
try:
    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    # Using gemini-1.5-flash for potential better vision capabilities and speed
    model = genai.GenerativeModel("gemini-2.0-flash")
    print("Gemini Model configured.")
except Exception as e:
    print(f"Error configuring Gemini: {e}")
    model = None

# Rate limiting (requests per minute)
RPM = int(os.getenv("GEMINI_RPM", 60))  # Default to 60 RPM
REQUEST_INTERVAL = 60.0 / RPM if RPM > 0 else 0


def extract_json_from_text(text):
    """Safely extracts JSON object from Gemini response text."""
    try:
        # Find the start and end of the JSON block
        json_start = text.find("{")
        json_end = text.rfind("}") + 1
        if json_start != -1 and json_end != -1:
            json_str = text[json_start:json_end]
            # Remove potential markdown fences ```json ... ```
            json_str = json_str.strip()
            if json_str.startswith("```json"):
                json_str = json_str[7:].strip()
            elif json_str.startswith("```"):
                json_str = json_str[3:].strip()
            if json_str.endswith("```"):
                json_str = json_str[:-3].strip()

            # Gemini might sometimes wrap in {{ }} - handle this
            if json_str.startswith("{{") and json_str.endswith("}}"):
                json_str = json_str[1:-1]

            return json.loads(json_str)
        else:
            print("⚠️ JSON object not found in text.")
            return None
    except json.JSONDecodeError as e:
        print(f"⚠️ Failed to parse JSON: {e}")
        print(f"--- Raw Text Start --- \n{text}\n--- Raw Text End ---")
        return None
    except Exception as e:
        print(f"⚠️ An unexpected error occurred during JSON extraction: {e}")
        return None


def get_fish_taxonomy(fish_id, image_filename):
    """Sends image to Gemini and updates database with taxonomy."""
    if not model:
        print("LLM Model not available.")
        update_fish_status(fish_id, "error")
        return

    image_path = os.path.join(IMAGE_DIR, image_filename)
    print(f"Characterizing fish ID {fish_id} from {image_path}...")
    update_fish_status(fish_id, "characterizing")

    try:
        # Check if the image exists in the expected path
        if not os.path.exists(image_path):
            print(f"⚠️ Image file not found at {image_path}")
            update_fish_status(fish_id, "error")
            return

        img = Image.open(image_path)

        # Convert image to bytes if needed by the library/model version
        # img_byte_arr = io.BytesIO()
        # img.save(img_byte_arr, format='PNG') # Or JPEG
        # img_bytes = img_byte_arr.getvalue()

        prompt = """Identify the most likely species, genus, family, order, class, phylum, and kingdom of the animal in this image.
Output the result *only* as a JSON object in the following format, with no other commentary, introductions, or explanations:

{
  "Kingdom": "...",
  "Phylum": "...",
  "Class": "...",
  "Order": "...",
  "Family": "...",
  "Genus": "...",
  "Species": "..."
}

If you cannot confidently identify the animal or its classifications, use "Unknown" for the respective fields.
"""

        # Note: Sending the PIL Image object directly is often supported.
        # If not, uncomment the byte conversion above and send img_bytes.
        response = model.generate_content(
            [prompt, img], stream=False
        )  # Use stream=False for simpler response handling here

        # Make sure to handle potential safety blocks or empty responses
        if not response.parts:
            print(
                f"⚠️ Gemini response for {fish_id} contained no parts (possibly blocked)."
            )
            update_fish_status(fish_id, "error")
            return

        text = response.text
        # print(f"--- Gemini Raw Response for {fish_id} ---")
        # print(text)
        # print("--- End Gemini Raw Response ---")

        json_data = extract_json_from_text(text)

        if json_data:
            print(
                f"Successfully characterized fish ID {fish_id}: {json_data.get('Species', 'N/A')}"
            )
            update_fish_status(
                fish_id, "characterized", taxonomy_json=json.dumps(json_data)
            )
        else:
            print(f"⚠️ Failed to extract JSON for fish ID {fish_id}. Marking as error.")
            update_fish_status(fish_id, "error")

    except genai.types.BlockedPromptException as e:
        print(f"🚫 Gemini blocked the prompt or response for {fish_id}: {e}")
        update_fish_status(fish_id, "error")
    except Exception as e:
        print(f"❌ Error during Gemini API call for fish ID {fish_id}: {e}")
        update_fish_status(fish_id, "error")

    # Apply rate limiting delay AFTER the request
    if REQUEST_INTERVAL > 0:
        # print(f"Rate limiting: sleeping for {REQUEST_INTERVAL:.2f} seconds")
        time.sleep(REQUEST_INTERVAL)
