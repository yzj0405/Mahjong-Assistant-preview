from pydantic import BaseModel
from typing import List, Optional, Dict, Any


class PlayerData(BaseModel):
    """Single player state in the 4-player game."""
    seat: int  # 0=自家, 1=下家(right), 2=对家(opposite), 3=上家(left)
    wind: str = ""  # Seat wind: 'E','S','W','N'
    hand: List[str] = []  # Only populated for self (seat=0)
    melds: List[str] = []
    discards: List[str] = []


class StartSessionRequest(BaseModel):
    session_id: str


class EndSessionRequest(BaseModel):
    session_id: str


class AnalyzeResponse(BaseModel):
    # Backward-compatible fields
    user_hand: List[str]
    melded_tiles: List[str]
    river_tiles: List[str] = []
    suggested_play: str
    annotated_image_path: Optional[str] = None
    action_detected: Optional[str] = None
    warning: Optional[str] = None
    is_stable: bool = True
    # 4-player extended fields
    players: List[PlayerData] = []
    current_turn: int = -1
    current_turn_label: str = ""


class ProcessAudioResponse(BaseModel):
    transcript: str
    events: List[Dict[str, Any]]
    updated_visible_tiles_count: int
    details: List[str]
