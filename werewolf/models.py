from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class Role(str, Enum):
    WOLF = "WOLF"
    SEER = "SEER"
    WITCH = "WITCH"
    HUNTER = "HUNTER"
    VILLAGER = "VILLAGER"


class Faction(str, Enum):
    WOLF = "WOLF"
    VILLAGE = "VILLAGE"


class Phase(str, Enum):
    NIGHT_WOLF = "NIGHT_WOLF"
    NIGHT_SEER = "NIGHT_SEER"
    NIGHT_WITCH = "NIGHT_WITCH"
    DAY_DISCUSS = "DAY_DISCUSS"
    DAY_VOTE = "DAY_VOTE"
    GAME_OVER = "GAME_OVER"


class ActionType(str, Enum):
    KILL = "KILL"
    CHECK = "CHECK"
    SAVE = "SAVE"
    POISON = "POISON"
    VOTE = "VOTE"
    SHOOT = "SHOOT"
    PASS = "PASS"
    SPEAK = "SPEAK"


@dataclass
class Player:
    player_id: int
    role: Role
    alive: bool = True
    death_reason: Optional[str] = None # "VOTE", "WOLF", "WITCH", "HUNTER"


@dataclass
class WitchState:
    save_used: bool = False
    poison_used: bool = False
    saved_player_id: Optional[int] = None # Remember who I saved


@dataclass
class PlayerPrivate:
    seer_results: Dict[int, bool] = field(default_factory=dict)
    witch_state: WitchState = field(default_factory=WitchState)
    trust_scores: Dict[int, float] = field(default_factory=dict)
    known_seers: List[int] = field(default_factory=list)
    known_witches: List[int] = field(default_factory=list)
    believed_silver_water: Optional[int] = None # The player I believe is Silver Water (based on Witch claim)


@dataclass
class Statement:
    actor_id: int
    content: str
    claimed_role: Optional[Role] = None
    claimed_checks: Dict[int, bool] = field(default_factory=dict)


@dataclass
class Recommendation:
    action: Action
    reason: str
    win_rate_estimate: Optional[float] = None
    alternatives: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class Event:
    day: int
    phase: Phase
    description: str
    actor_id: Optional[int] = None
    target_id: Optional[int] = None
    recommendation: Optional[Recommendation] = None
    statement: Optional[Statement] = None
    votes: Optional[Dict[str, int]] = None  # Mapping: voter_id -> target_id
    vote_reasons: Optional[Dict[str, str]] = None # Mapping: voter_id -> reason
    trust_scores: Optional[Dict[int, Dict[int, float]]] = None # Snapshot of trust scores: {observer_id: {target_id: score}}


@dataclass
class Action:
    action_type: ActionType
    actor_id: int
    target_id: Optional[int] = None
    statement: Optional[Statement] = None


@dataclass
class GameConfig:
    player_count: int
    roles: Dict[Role, int]
    victory_condition: str = "side_slaughter" # "side_slaughter" or "city_slaughter"

@dataclass
class GameState:
    players: List[Player]
    day: int
    phase: Phase
    config: GameConfig
    pending_kill: Optional[int] = None
    public_events: List[Event] = field(default_factory=list)
    private_info: Dict[int, PlayerPrivate] = field(default_factory=dict)
    winner: Optional[Faction] = None

