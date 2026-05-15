from fastapi import FastAPI, File, UploadFile, Form
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from typing import List, Optional, Dict, Any
from PIL import Image
import uvicorn
import shutil
import os
import datetime
import database
import asyncio
import logging
from config import config
from mahjong_state_tracker import MahjongStateTracker
from mahjong.tile import TilesConverter
from efficiency_engine import EfficiencyEngine, format_suggestions
from stt_service import STTService
from llm_service import LLMService
from vision_service import VisionService, draw_bounding_boxes
from schemas import (
    StartSessionRequest, 
    AnalyzeResponse, 
    PlayerData,
    EndSessionRequest, 
    ProcessAudioResponse
)

# Configure Logging
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global Session Trackers
SESSION_TRACKERS: Dict[str, MahjongStateTracker] = {}
EFFICIENCY_ENGINE = EfficiencyEngine()

# Initialize Services
# Note: Ensure OPENAI_API_KEY is set in environment or pass it here
STT_SERVICE = STTService()
# STT_SERVICE = None
LLM_SERVICE = LLMService(
    base_url=config.LLM_BASE_URL,
    api_key=config.LLM_API_KEY,
    model=config.LLM_MODEL
)
VISION_SERVICE = VisionService(
    model_path=config.YOLO_MODEL_PATH,
    class_names_path=config.YOLO_CLASS_NAMES_PATH,
    confidence_threshold=config.YOLO_CONF_THRESHOLD,
    iou_threshold=config.YOLO_IOU_THRESHOLD
)

# Initialize Database
database.init_db()

# YOLO Class to MPSZ Notation Mapping
YOLO_TO_MPSZ_MAPPING = {
    # --- Bamboo (s) ---
    '1B': '1s', '2B': '2s', '3B': '3s',
    '4B': '4s', '5B': '5s', '6B': '6s',
    '7B': '7s', '8B': '8s', '9B': '9s',

    # --- Characters (m) ---
    '1C': '1m', '2C': '2m', '3C': '3m',
    '4C': '4m', '5C': '5m', '6C': '6m',
    '7C': '7m', '8C': '8m', '9C': '9m',

    # --- Dots (p) ---
    '1D': '1p', '2D': '2p', '3D': '3p',
    '4D': '4p', '5D': '5p', '6D': '6p',
    '7D': '7p', '8D': '8p', '9D': '9p',

    # --- Winds (z 1-4) ---
    'EW': '1z', # East
    'SW': '2z', # South
    'WW': '3z', # West
    'NW': '4z', # North

    # --- Dragons (z 5-7) ---
    'WD': '5z', # White
    'GD': '6z', # Green
    'RD': '7z', # Red

    # --- Flowers/Seasons (Bonus) ---
    '1F': 'f1', '2F': 'f2', '3F': 'f3', '4F': 'f4',
    '1S': 's1', '2S': 's2', '3S': 's3', '4S': 's4',
}

def convert_to_mpsz(yolo_classes: List[str]):
    """
    Convert YOLO classes to MPSZ notation.
    Returns a tuple (hand_tiles, bonus_tiles).
    """
    hand_tiles = []
    bonus_tiles = []
    
    for cls in yolo_classes:
        mpsz = YOLO_TO_MPSZ_MAPPING.get(cls)
        if mpsz:
            if mpsz.startswith('f') or mpsz.startswith('s'):
                bonus_tiles.append(mpsz)
            else:
                hand_tiles.append(mpsz)
        else:
            hand_tiles.append(cls)
            
    return hand_tiles, bonus_tiles


def _infer_region(
    image_path: str,
    region: List[float],
    vision_service: VisionService,
    base_path: str,
    region_name: str
) -> List[Dict[str, Any]]:
    """
    Crop a region from an image and run YOLO inference.
    Returns predictions with coordinates adjusted to full-image space.
    """
    x1f, y1f, x2f, y2f = region

    with Image.open(image_path) as img:
        width, height = img.size
        x1 = int(width * x1f)
        y1 = int(height * y1f)
        x2 = int(width * x2f)
        y2 = int(height * y2f)
        cropped = img.crop((x1, y1, x2, y2))
        temp_path = f"{base_path}_{region_name}.jpg"
        cropped.save(temp_path)

    preds = vision_service.detect_objects(temp_path)

    for p in preds:
        p['x'] = p.get('x', 0) + x1
        p['y'] = p.get('y', 0) + y1

    if os.path.exists(temp_path):
        os.remove(temp_path)

    return preds

app = FastAPI()

# Add CORS to allow requests from anywhere (helpful for dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define Base Directory and Static Directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Ensure uploads directory exists
UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def read_root():
    return FileResponse(os.path.join(STATIC_DIR, "dashboard.html"))

@app.post("/api/start-session")
async def start_session(request: StartSessionRequest):
    logger.info(f"Received Start Session request: session_id={request.session_id}")
    database.create_or_update_session(request.session_id)
    # Initialize Tracker
    SESSION_TRACKERS[request.session_id] = MahjongStateTracker()
    return {"status": "success", "session_id": request.session_id}

@app.post("/api/analyze-hand", response_model=AnalyzeResponse)
async def analyze_hand(
    image: UploadFile = File(...),
    session_id: str = Form(...),
    incoming_tile: Optional[str] = Form(None)
):
    start_time = datetime.datetime.now()
    steps_log = []
    
    # Step 1: Initialize
    logger.info(f"Received Analyze request: session_id={session_id}, filename={image.filename}")
    steps_log.append(f"[{start_time.strftime('%H:%M:%S')}] Received request: {image.filename}")
    
    # Step 2: Ensure Session Exists
    database.create_or_update_session(session_id)
    steps_log.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Session verified/active")

    # Step 3: Save Image
    timestamp = int(start_time.timestamp() * 1000)
    file_extension = os.path.splitext(image.filename)[1] or ".jpg"
    safe_filename = f"{session_id}_{timestamp}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
        steps_log.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Image saved")
    except Exception as e:
        error_msg = f"Failed to save image: {str(e)}"
        logger.error(error_msg)
        steps_log.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] ERROR: {error_msg}")

    # Step 4: Multi-Region Inference (9 regions for 4 players)
    steps_log.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting 4-player multi-region analysis...")
    
    players_mpsz: Dict[int, Dict[str, List[str]]] = {
        0: {'hand': [], 'melds': [], 'discards': []},
        1: {'hand': [], 'melds': [], 'discards': []},
        2: {'hand': [], 'melds': [], 'discards': []},
        3: {'hand': [], 'melds': [], 'discards': []},
    }
    all_preds: List[Dict[str, Any]] = []
    annotated_path = None
    
    try:
        base_path = os.path.splitext(file_path)[0]
        
        for region_name, region_coords in config.IMAGE_LAYOUT.items():
            seat, field = config.REGION_MAP[region_name]
            
            steps_log.append(
                f"[{datetime.datetime.now().strftime('%H:%M:%S')}] "
                f"Scanning {region_name} -> {config.get_seat_name(seat)}.{field}..."
            )
            
            preds = _infer_region(file_path, region_coords, VISION_SERVICE, base_path, region_name)
            all_preds.extend(preds)
            
            tiles, _ = convert_to_mpsz([p["class"] for p in preds])
            players_mpsz[seat][field] = tiles
        
        # Generate annotated image with all predictions
        annotated_filename = f"{session_id}_{timestamp}_annotated.jpg"
        annotated_full_path = os.path.join(UPLOAD_DIR, annotated_filename)
        
        if draw_bounding_boxes(file_path, all_preds, annotated_full_path):
            annotated_path = f"/static/uploads/{annotated_filename}"
            steps_log.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Annotated image generated")
        
        for seat in range(4):
            pd = players_mpsz[seat]
            steps_log.append(
                f"  {config.get_seat_name(seat)}: "
                f"hand={len(pd['hand'])}, melds={len(pd['melds'])}, discards={len(pd['discards'])}"
            )
        
    except Exception as e:
        error_msg = f"Inference/Processing Error: {str(e)}"
        logger.error(error_msg)
        steps_log.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {error_msg}")

    # Step 5: State Tracking (self only, for action detection)
    steps_log.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Updating state tracker...")
    
    tracker = SESSION_TRACKERS.get(session_id)
    if not tracker:
        tracker = MahjongStateTracker()
        SESSION_TRACKERS[session_id] = tracker
        steps_log.append("Created new tracker for session")

    warning_msg = None
    action_detected = "UNKNOWN"
    user_hand = players_mpsz[0]['hand']
    melded_tiles = players_mpsz[0]['melds']

    try:
        incoming_id = None
        if incoming_tile:
            ids = TilesConverter.one_line_string_to_136_array(incoming_tile)
            if ids:
                incoming_id = ids[0]
        
        update_result = tracker.update_state(user_hand, melded_tiles, incoming_id)
        action_detected = update_result.get("action", "UNKNOWN")
        warning_msg = update_result.get("warning")
        
        steps_log.append(f"State Update: Action={action_detected}")
        if warning_msg:
            steps_log.append(f"WARNING: {warning_msg}")
        
    except Exception as e:
        error_msg = f"Tracker Error: {e}"
        logger.error(error_msg)
        steps_log.append(error_msg)
        warning_msg = f"Internal Error: {e}"

    # Step 6: Sync 4-player visible tiles (full rebuild to avoid drift)
    sync_result = tracker.sync_all_visible_tiles(players_mpsz)
    steps_log.append(f"Visible tiles sync: {sync_result['new_count']} total (delta={sync_result['delta']})")

    # Also sync to EfficiencyEngine
    EFFICIENCY_ENGINE.visible_tiles = list(tracker.visible_tiles)

    # Step 7: Turn Detection
    turn_result = tracker.detect_turn(players_mpsz)
    current_turn = turn_result['current_turn']
    current_turn_label = turn_result['turn_label']
    steps_log.append(f"Turn detected: {current_turn_label} (seat {current_turn})")

    # Step 8: Efficiency / Suggestion Logic
    steps_log.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Analysing optimal move...")
    
    suggested_play = f"Action: {action_detected}"
    shanten = -1
    recommend_comb = []
    is_agari = False
    
    if warning_msg:
        suggested_play = "请重新拍摄确认"
    else:
        try:
            if tracker.current_hidden_hand:
                hidden_count = len(tracker.current_hidden_hand)
                meld_count = sum(len(m.tiles) for m in tracker.meld_history)
                total_tiles = hidden_count + meld_count
                
                # 14, 11, 8, 5, 2 -> My Turn (Discard)
                if total_tiles % 3 == 2: 
                    result = EFFICIENCY_ENGINE.calculate_best_discard(
                        tracker.current_hidden_hand, 
                        tracker.meld_history
                    )
                    suggested_play = format_suggestions(result, "discard")
                    # Extract structured data for mobile client
                    if result:
                        shanten = result.get('shanten', -1)
                        discard_tile = result.get('discard_tile')
                        if discard_tile:
                            recommend_comb = [discard_tile]
                        is_agari = (shanten == -1)
                
                # 13, 10, 7, 4, 1 -> Waiting (Opponent Turn)
                elif total_tiles % 3 == 1: 
                    result = EFFICIENCY_ENGINE.analyze_opportunities(
                        tracker.current_hidden_hand,
                        tracker.meld_history
                    )
                    suggested_play = format_suggestions(result, "opportunity")
                    # Extract structured data for mobile client
                    if result:
                        shanten = result.get('current_shanten', -1)
                        is_agari = (shanten == -1)
                    
        except Exception as e:
            err_msg = f"Efficiency Engine Error: {e}"
            logger.error(err_msg)
            steps_log.append(err_msg)

    # Step 9: Build 4-player response
    river_tiles = []
    for seat in range(4):
        river_tiles.extend(players_mpsz[seat]['discards'])

    players_response: List[PlayerData] = []
    for seat in range(4):
        pd = players_mpsz[seat]
        players_response.append(PlayerData(
            seat=seat,
            wind=config.get_seat_wind(seat),
            hand=pd['hand'] if seat == 0 else [],
            melds=pd['melds'],
            discards=pd['discards']
        ))

    response_data = AnalyzeResponse(
        user_hand=user_hand,
        melded_tiles=melded_tiles,
        river_tiles=river_tiles,
        suggested_play=suggested_play, 
        annotated_image_path=annotated_path,
        action_detected=action_detected,
        warning=warning_msg,
        is_stable=(warning_msg is None),
        shanten=shanten,
        recommend_comb=recommend_comb,
        is_agari=is_agari,
        players=players_response,
        current_turn=current_turn,
        current_turn_label=current_turn_label
    )
    
    steps_log.append(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Analysis complete.")

    # Step 10: Log Interaction to DB
    relative_image_path = f"/static/uploads/{safe_filename}"
    database.log_interaction(
        session_id=session_id,
        image_path=relative_image_path,
        steps=steps_log,
        response=response_data.dict()
    )
    
    logger.info(f"Processed successfully. Response sent.")
    return response_data

@app.post("/api/process-audio", response_model=ProcessAudioResponse)
async def process_audio(
    audio: UploadFile = File(...),
    session_id: str = Form(...)
):
    logger.info(f"Received Audio Processing request: session_id={session_id}")
    
    # Ensure Session Exists
    database.create_or_update_session(session_id)
    if session_id not in SESSION_TRACKERS:
        SESSION_TRACKERS[session_id] = MahjongStateTracker()
        logger.info("Created new tracker for session (from audio)")
    
    # Save Audio
    timestamp = int(datetime.datetime.now().timestamp() * 1000)
    ext = os.path.splitext(audio.filename)[1] or ".wav"
    filename = f"{session_id}_{timestamp}{ext}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(audio.file, buffer)
        logger.info(f"Audio saved to {file_path}")
    except Exception as e:
        logger.error(f"Failed to save audio: {e}")
        return ProcessAudioResponse(
            transcript="",
            events=[],
            updated_visible_tiles_count=0,
            details=[f"Error saving file: {str(e)}"]
        )
        
    # STT
    try:
        transcript = STT_SERVICE.transcribe(file_path)
    except Exception as e:
        logger.error(f"STT failed: {e}")
        return ProcessAudioResponse(
            transcript="",
            events=[],
            updated_visible_tiles_count=0,
            details=[f"STT processing error: {str(e)}"]
        )
    
    # LLM
    events = []
    if transcript:
        events = LLM_SERVICE.analyze_game_events(transcript)
        
    # Update State
    tracker = SESSION_TRACKERS[session_id]
    update_result = tracker.update_visible_tiles(events)
    
    # Log Interaction to DB
    relative_audio_path = f"/static/uploads/{filename}"
    
    response_data = {
        "transcript": transcript,
        "events": events,
        "updated_visible_tiles_count": update_result["updated_count"],
        "details": update_result["details"],
        "visible_tiles_snapshot": tracker.visible_tiles, # Snapshot of current state
        "audio_path": relative_audio_path
    }
    
    steps_log = [
        f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Audio processed",
        f"Transcript: {transcript}",
        f"Events found: {len(events)}",
        f"Visible tiles updated: {update_result['updated_count']}"
    ]
    
    database.log_interaction(
        session_id=session_id,
        image_path=None, # No image for audio interaction
        steps=steps_log,
        response=response_data
    )
    
    return ProcessAudioResponse(
        transcript=transcript,
        events=events,
        updated_visible_tiles_count=update_result["updated_count"],
        details=update_result["details"]
    )

@app.post("/api/end-session")
async def end_session(request: EndSessionRequest):
    logger.info(f"Received End Session request: session_id={request.session_id}")
    database.end_session(request.session_id)
    # Cleanup Tracker
    SESSION_TRACKERS.pop(request.session_id, None)
    return {"status": "success", "message": "Session ended"}

# --- History APIs ---

@app.get("/api/history/sessions")
async def get_history_sessions():
    return database.get_all_sessions()

@app.get("/api/history/details/{session_id}")
async def get_history_details(session_id: str):
    details = database.get_session_details(session_id)
    if not details:
        return {"error": "Session not found"}
    return details

@app.post("/api/debug/yolo")
async def debug_yolo(
    image: UploadFile = File(...),
    conf_threshold: float = Form(0.54),
    iou_threshold: float = Form(0.85)
):
    timestamp = int(datetime.datetime.now().timestamp() * 1000)
    file_extension = os.path.splitext(image.filename)[1] or ".jpg"
    safe_filename = f"debug_{timestamp}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
    except Exception as e:
        return {"error": f"Failed to save image: {str(e)}"}

    # Run detection with custom thresholds
    preds = VISION_SERVICE.detect_objects(
        file_path, 
        conf_threshold=conf_threshold, 
        iou_threshold=iou_threshold
    )
    
    # Sort predictions
    preds.sort(key=lambda p: p.get("x", 0))

    # Generate annotated image
    annotated_filename = f"debug_{timestamp}_annotated.jpg"
    annotated_full_path = os.path.join(UPLOAD_DIR, annotated_filename)
    
    annotated_url = None
    if draw_bounding_boxes(file_path, preds, annotated_full_path):
        annotated_url = f"/static/uploads/{annotated_filename}"
        
    return {
        "predictions": preds,
        "annotated_image_url": annotated_url,
        "original_image_url": f"/static/uploads/{safe_filename}",
        "params": {
            "conf_threshold": conf_threshold,
            "iou_threshold": iou_threshold
        }
    }

@app.post("/api/debug/regions")
async def debug_regions(
    image: UploadFile = File(...)
):
    """Debug endpoint: visualize all layout regions on the uploaded image."""
    timestamp = int(datetime.datetime.now().timestamp() * 1000)
    file_extension = os.path.splitext(image.filename)[1] or ".jpg"
    safe_filename = f"regions_{timestamp}{file_extension}"
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    
    try:
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
    except Exception as e:
        return {"error": f"Failed to save image: {str(e)}"}

    with Image.open(file_path) as im:
        from PIL import ImageDraw
        draw = ImageDraw.Draw(im)
        width, height = im.size
        
        colors = ['red', 'blue', 'green', 'orange', 'purple', 'cyan', 'magenta', 'yellow', 'pink']
        
        for i, (region_name, coords) in enumerate(config.IMAGE_LAYOUT.items()):
            x1f, y1f, x2f, y2f = coords
            x1, y1 = int(width * x1f), int(height * y1f)
            x2, y2 = int(width * x2f), int(height * y2f)
            color = colors[i % len(colors)]
            draw.rectangle([x1, y1, x2, y2], outline=color, width=3)
            draw.text((x1 + 4, y1 + 4), region_name, fill=color)
        
        annotated_filename = f"regions_{timestamp}_annotated.jpg"
        annotated_full_path = os.path.join(UPLOAD_DIR, annotated_filename)
        im.save(annotated_full_path)

    return {
        "annotated_image_url": f"/static/uploads/{annotated_filename}",
        "regions": config.IMAGE_LAYOUT
    }

# --- Background Tasks ---

async def monitor_inactive_sessions():
    """Background task to close inactive sessions every 60 seconds."""
    logger.info("Starting inactive session monitor...")
    while True:
        try:
            await asyncio.sleep(60)
            # Check for sessions inactive for > 300 seconds
            closed_sessions = database.close_inactive_sessions(300)
            if len(closed_sessions) > 0:
                logger.info(f"Monitor: Closed {len(closed_sessions)} inactive sessions.")
                for sid in closed_sessions:
                    SESSION_TRACKERS.pop(sid, None)
        except Exception as e:
            logger.error(f"Monitor Error: {e}")
            await asyncio.sleep(60) # Wait before retrying

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(monitor_inactive_sessions())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
