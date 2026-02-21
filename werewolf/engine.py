from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple
import random

from .models import (
    Action,
    ActionType,
    Event,
    Faction,
    GameConfig,
    GameState,
    Phase,
    Player,
    PlayerPrivate,
    Role,
    Recommendation,
    Statement
)


@dataclass
class GameEngine:
    roles: Dict[int, Role]
    config: Optional[GameConfig] = None
    state: GameState = field(init=False)
    rng: random.Random = field(default_factory=random.Random)
    
    def __post_init__(self):
        players = [Player(player_id=pid, role=role) for pid, role in self.roles.items()]
        private_info = {p.player_id: PlayerPrivate() for p in players}
        
        # Initialize trust scores
        for p_obs in players:
            p_obs_private = private_info[p_obs.player_id]
            for p_target in players:
                if p_obs.player_id == p_target.player_id:
                    continue
                
                # Default trust: 0.5 (Neutral)
                trust = 0.5
                
                # Wolf Logic: Know teammates
                if p_obs.role == Role.WOLF:
                    if p_target.role == Role.WOLF:
                        trust = 1.0 # Trust teammate
                    else:
                        trust = 0.0 # Know they are good (enemy)
                
                p_obs_private.trust_scores[p_target.player_id] = trust

        # Create default config if not provided
        if self.config is None:
            # Infer from roles length or default to 6-player standard
            # This is fallback.
            self.config = GameConfig(
                player_count=len(players),
                roles={r: list(self.roles.values()).count(r) for r in set(self.roles.values())},
                victory_condition="side_slaughter" if len(players) >= 9 else "side_slaughter" # Simplified
            )

        self.state = GameState(players=players, day=1, phase=Phase.NIGHT_WOLF, private_info=private_info, config=self.config)

def create_default_game(seed: Optional[int] = None, player_count: int = 6) -> Tuple[GameState, random.Random]:
    rng = random.Random(seed)
    
    # Configuration Logic
    roles_list = []
    victory_condition = "side_slaughter"
    
    if player_count == 6:
        # 2 Wolves, 2 Villagers, 1 Seer, 1 Witch
        roles_list = [Role.WOLF]*2 + [Role.VILLAGER]*2 + [Role.SEER, Role.WITCH]
        victory_condition = "city_slaughter" # Usually kill all villagers or all gods (but here simplified)
    elif player_count == 9:
        # 3 Wolves, 3 Villagers, 3 Gods (Seer, Witch, Hunter)
        roles_list = [Role.WOLF]*3 + [Role.VILLAGER]*3 + [Role.SEER, Role.WITCH, Role.HUNTER]
        victory_condition = "side_slaughter"
    elif player_count == 12:
        # 4 Wolves, 4 Villagers, 4 Gods (Seer, Witch, Hunter, Guard/Villager)
        # For MVP, let's use 4 Villagers + Seer, Witch, Hunter, Hunter (or another Villager)
        # Standard: Seer, Witch, Hunter, Idiot/Guard. We don't have Guard yet. Use Villager as placeholder or add Guard later.
        # Let's use 5 Villagers for now.
        roles_list = [Role.WOLF]*4 + [Role.VILLAGER]*5 + [Role.SEER, Role.WITCH, Role.HUNTER]
        victory_condition = "side_slaughter"
    elif player_count == 15:
        # 5 Wolves, 5 Villagers, 5 Gods
        roles_list = [Role.WOLF]*5 + [Role.VILLAGER]*5 + [Role.SEER, Role.WITCH, Role.HUNTER, Role.VILLAGER, Role.VILLAGER]
        victory_condition = "side_slaughter"
    else:
        # Fallback to 6
        roles_list = [Role.WOLF]*2 + [Role.VILLAGER]*2 + [Role.SEER, Role.WITCH]

    rng.shuffle(roles_list)
    roles = {i: role for i, role in enumerate(roles_list)}
    
    config = GameConfig(
        player_count=player_count,
        roles={r: roles_list.count(r) for r in set(roles_list)},
        victory_condition=victory_condition
    )
    
    # Use GameEngine to ensure consistent initialization
    engine = GameEngine(roles, config=config)
    engine.rng = rng # Use provided rng
    return engine.state, rng





def alive_players(state: GameState) -> List[Player]:
    return [p for p in state.players if p.alive]


def get_player(state: GameState, player_id: int) -> Player:
    return next(p for p in state.players if p.player_id == player_id)


def role_of(state: GameState, player_id: int) -> Role:
    return get_player(state, player_id).role


def faction_of(role: Role) -> Faction:
    return Faction.WOLF if role == Role.WOLF else Faction.VILLAGE


def check_winner(state: GameState) -> Optional[Faction]:
    alive = alive_players(state)
    wolves = [p for p in alive if p.role == Role.WOLF]
    villagers = [p for p in alive if p.role != Role.WOLF]
    if not wolves:
        return Faction.VILLAGE
    if len(wolves) >= len(villagers):
        return Faction.WOLF
    return None


def record_event(state: GameState, description: str, actor_id: Optional[int] = None, target_id: Optional[int] = None, recommendation: Optional[Recommendation] = None, statement: Optional[Statement] = None, votes: Optional[Dict[str, int]] = None, vote_reasons: Optional[Dict[str, str]] = None) -> None:
    # Capture trust scores snapshot
    trust_snapshot = {}
    for pid, p_info in state.private_info.items():
        trust_snapshot[pid] = dict(p_info.trust_scores)
    
    state.public_events.append(Event(day=state.day, phase=state.phase, description=description, actor_id=actor_id, target_id=target_id, recommendation=recommendation, statement=statement, votes=votes, vote_reasons=vote_reasons, trust_scores=trust_snapshot))



def apply_action(state: GameState, action: Action, recommendation: Optional[Recommendation] = None) -> None:
    if state.phase == Phase.NIGHT_WOLF and action.action_type == ActionType.KILL:
        state.pending_kill = action.target_id
        record_event(state, "狼人选择了目标", actor_id=action.actor_id, target_id=action.target_id, recommendation=recommendation)
        state.phase = Phase.NIGHT_SEER
        return
    if state.phase == Phase.NIGHT_SEER and action.action_type == ActionType.CHECK:
        target_role = role_of(state, action.target_id)
        state.private_info[action.actor_id].seer_results[action.target_id] = target_role == Role.WOLF
        record_event(state, "预言家查验了目标", actor_id=action.actor_id, target_id=action.target_id, recommendation=recommendation)
        state.phase = Phase.NIGHT_WITCH
        return
    if state.phase == Phase.NIGHT_WITCH:
        if action.action_type == ActionType.SAVE and action.target_id is not None:
            state.private_info[action.actor_id].witch_state.save_used = True
            state.private_info[action.actor_id].witch_state.saved_player_id = action.target_id
            record_event(state, "女巫使用了解药", actor_id=action.actor_id, target_id=action.target_id, recommendation=recommendation)
            if state.pending_kill == action.target_id:
                state.pending_kill = None
        if action.action_type == ActionType.POISON and action.target_id is not None:
            state.private_info[action.actor_id].witch_state.poison_used = True
            record_event(state, "女巫使用了毒药", actor_id=action.actor_id, target_id=action.target_id, recommendation=recommendation)
            kill_player(state, action.target_id, reason="WITCH")
        if action.action_type == ActionType.PASS:
            record_event(state, "女巫选择了不使用药水", actor_id=action.actor_id, recommendation=recommendation)
        resolve_night(state)
        return
    if state.phase == Phase.DAY_DISCUSS and action.action_type == ActionType.SPEAK:
        record_event(state, "玩家发言", actor_id=action.actor_id, recommendation=recommendation, statement=action.statement)
        return
    if state.phase == Phase.DAY_VOTE and action.action_type == ActionType.VOTE:

        kill_player(state, action.target_id, reason="VOTE")
        record_event(state, "放逐了玩家", actor_id=action.actor_id, target_id=action.target_id, recommendation=recommendation)
        resolve_day(state)
        return


def resolve_night(state: GameState) -> None:
    if state.pending_kill is not None:
        kill_player(state, state.pending_kill, reason="WOLF")
        record_event(state, "夜晚击杀生效", target_id=state.pending_kill)
        state.pending_kill = None
    winner = check_winner(state)
    if winner is not None:
        state.winner = winner
        state.phase = Phase.GAME_OVER
        record_event(state, "游戏结束")
        return
    state.phase = Phase.DAY_DISCUSS



def resolve_day(state: GameState) -> None:
    winner = check_winner(state)
    if winner is not None:
        state.winner = winner
        state.phase = Phase.GAME_OVER
        record_event(state, "游戏结束")
        return
    state.day += 1
    state.phase = Phase.NIGHT_WOLF


def kill_player(state: GameState, target_id: Optional[int], reason: str = "UNKNOWN") -> None:
    if target_id is None:
        return
    # Modify the player object in the list directly
    for p in state.players:
        if p.player_id == target_id:
            p.alive = False
            p.death_reason = reason
            break


def get_unshot_dead_hunters(state: GameState) -> List[Player]:
    dead_hunters = [p for p in state.players if p.role == Role.HUNTER and not p.alive]
    return [h for h in dead_hunters if not any(e.description == "猎人开枪" and e.actor_id == h.player_id for e in state.public_events)]


def get_player_view(state: GameState, player_id: int) -> Dict:
    player = get_player(state, player_id)
    private = state.private_info[player_id]
    return {
        "player_id": player_id,
        "role": player.role.value,
        "alive": player.alive,
        "day": state.day,
        "phase": state.phase.value,
        "seer_results": dict(private.seer_results),
        "witch_state": {
            "save_used": private.witch_state.save_used,
            "poison_used": private.witch_state.poison_used,
        },
        "public_events": [
            {
                "day": e.day,
                "phase": e.phase.value,
                "description": e.description,
                "actor_id": e.actor_id,
                "target_id": e.target_id,
            }
            for e in state.public_events
        ],
        "alive_players": [p.player_id for p in alive_players(state)],
        "all_players_state": {
            p.player_id: {
                "alive": p.alive,
                "role": p.role.value,
                "death_reason": p.death_reason
            } for p in state.players
        }
    }
