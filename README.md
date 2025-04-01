# Fish Video Species Detection

A web application that automatically detects fish in underwater videos, extracts and catalogs them, and uses Google's Gemini API to identify their species.

## Features

- Upload and process underwater videos
- Automatic fish detection using YOLOv8
- Time-based frame sampling (process frames at regular time intervals)
- Perceptual hashing to avoid duplicate fish entries
- Integration with Google's Gemini AI for species identification
- Real-time progress tracking with dual progress bars
- Interactive results display with timestamps and taxonomic classifications
- CSV export of detection data for further analysis
- Clickable fish images with maximized view for detailed inspection
- Stop button to halt processing at any time

## Project Structure

```
fish-identifier-app/
│
├── app.py                   # Main Flask application logic
├── requirements.txt         # Python dependencies
├── database.py              # Database interaction functions
├── llm_handler.py           # Gemini API interaction logic
├── detector.py              # Fish detection logic using YOLO
│
├── uploads/                 # Temp storage for uploaded videos
├── detected_fish/           # Storage for cropped fish images
│
├── templates/
│   └── index.html           # Frontend HTML
│
└── static/
    └── css/
    │   └── style.css        # CSS styling
    └── js/
        └── script.js        # Additional JavaScript functionality
```

## Prerequisites

- Python 3.8 or higher
- A Gemini API key from Google AI Studio

## Installation

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/fish-video-species-detection.git
   cd fish-video-species-detection
   ```

2. Install the dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Set up your environment variables:
   - Rename `.env.example` to `.env` (or create a new `.env` file)
   - Add your Gemini API key and customize settings:
     ```
     GEMINI_API_KEY=your_api_key_here
     GEMINI_RPM=60
     SECONDS_BETWEEN_FRAMES=5.0
     ```

## Usage

1. Start the Flask application:
   ```
   python app.py
   ```

2. Open your web browser and navigate to:
   ```
   http://localhost:8000
   ```

3. Upload an underwater video file using the drag-and-drop interface.

4. The application will:
   - Process the video at regular time intervals (default: every 5 seconds)
   - Detect fish using YOLOv8
   - Extract unique fish images
   - Send the images to Gemini for species identification
   - Display results in a table with timestamps and taxonomic information

5. Control and interact with results:
   - Use the "Stop Processing" button if you want to halt the detection or characterization at any point
   - Click on any fish image to view it in a larger size
   - Download all detection data as a CSV file using the "Download CSV" button

## Technical Details

- **Fish Detection**: Uses YOLOv8 to detect objects in video frames. By default, it captures all detected objects for Gemini to evaluate.
- **Frame Sampling**: Processes frames at regular time intervals (default: every 5 seconds) instead of processing every frame, significantly reducing processing time.
- **Duplicate Handling**: Uses perceptual hashing (pHash) to identify similar fish appearances across frames.
- **Database**: Uses SQLite to store detected fish, their timestamps, and taxonomic information.
- **API Usage**: Implements rate limiting for Gemini API calls to stay within usage limits.
- **Data Export**: Provides CSV download functionality for further analysis in spreadsheet software or data science tools.
- **Process Control**: Allows stopping the processing pipeline at any point while keeping already processed results.

## Customization via Environment Variables

You can adjust several parameters by setting environment variables in the `.env` file:

- `SECONDS_BETWEEN_FRAMES`: How many seconds to wait between processing frames (higher = faster but might miss fish)
- `CONFIDENCE_THRESHOLD`: Minimum confidence score for YOLO detections
- `GEMINI_RPM`: Rate limit for Gemini API requests per minute

## License

[MIT License](LICENSE)

## Acknowledgments

- YOLOv8 by Ultralytics
- Google's Gemini API for species identification
- Flask for the web framework 