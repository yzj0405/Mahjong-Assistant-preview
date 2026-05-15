import os
import json
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Static Paths
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    STATIC_DIR = os.path.join(BASE_DIR, "static")
    UPLOAD_DIR = os.path.join(STATIC_DIR, "uploads")

    # LLM Configuration
    LLM_API_KEY = os.getenv("LLM_API_KEY", "lm-studio")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://127.0.0.1:1234/v1")
    LLM_MODEL = os.getenv("LLM_MODEL", "qwen/qwen3-4b-2507")

    # Local YOLO Model Configuration
    YOLO_MODEL_PATH = os.path.join(BASE_DIR, "models/yolo/weights.onnx")
    YOLO_CLASS_NAMES_PATH = os.path.join(BASE_DIR, "models/yolo/class_names.txt")
    YOLO_CONF_THRESHOLD = float(os.getenv("YOLO_CONF_THRESHOLD", 0.54))
    YOLO_IOU_THRESHOLD = float(os.getenv("YOLO_IOU_THRESHOLD", 0.85))

    # Application Settings
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # --- 4-Player Layout Configuration ---
    # Self's seat wind (default South for 南京麻将)
    SELF_WIND = os.getenv("SELF_WIND", "S")
    WIND_ORDER = ['E', 'S', 'W', 'N']

    # Image layout regions for 腾讯欢乐麻将 (portrait mode)
    # Format: [x1, y1, x2, y2] as fractions of image width/height
    # Override entire layout via LAYOUT_JSON env var
    IMAGE_LAYOUT = {
        # Self (seat 0, bottom)
        'self_hand':      [0.00, 0.80, 1.00, 1.00],
        'self_melds':     [0.00, 0.68, 1.00, 0.80],
        'self_discards':  [0.20, 0.55, 0.80, 0.68],
        # Right / 下家 (seat 1)
        'right_melds':    [0.82, 0.15, 1.00, 0.55],
        'right_discards': [0.55, 0.30, 0.82, 0.55],
        # Opposite / 对家 (seat 2)
        'opposite_melds':    [0.20, 0.02, 0.80, 0.12],
        'opposite_discards': [0.20, 0.12, 0.80, 0.30],
        # Left / 上家 (seat 3)
        'left_melds':    [0.00, 0.15, 0.18, 0.55],
        'left_discards': [0.18, 0.30, 0.45, 0.55],
    }

    _layout_json = os.getenv("LAYOUT_JSON")
    if _layout_json:
        try:
            IMAGE_LAYOUT = json.loads(_layout_json)
        except json.JSONDecodeError:
            pass

    # Region name → (player_seat, data_field)
    REGION_MAP = {
        'self_hand':      (0, 'hand'),
        'self_melds':     (0, 'melds'),
        'self_discards':  (0, 'discards'),
        'right_melds':    (1, 'melds'),
        'right_discards': (1, 'discards'),
        'opposite_melds':    (2, 'melds'),
        'opposite_discards': (2, 'discards'),
        'left_melds':    (3, 'melds'),
        'left_discards': (3, 'discards'),
    }

    @classmethod
    def get_seat_wind(cls, seat: int) -> str:
        self_idx = cls.WIND_ORDER.index(cls.SELF_WIND) if cls.SELF_WIND in cls.WIND_ORDER else 1
        return cls.WIND_ORDER[(self_idx + seat) % 4]

    @classmethod
    def get_seat_name(cls, seat: int) -> str:
        names = ['自家', '下家', '对家', '上家']
        return names[seat] if 0 <= seat < 4 else '未知'

config = Config()
