from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .engine import (
    GameEngine,
    apply_action,
    check_winner,
    create_default_game,
    get_player,
    get_player_view,
    get_unshot_dead_hunters,
    record_event,
    alive_players,
    kill_player
)
from .models import Action, ActionType, Faction, GameState, Phase, Role
from .strategy import SimpleStrategy


@dataclass
class GameSimulator:
    engine: GameEngine
    history: List[Dict] = field(default_factory=list)
    
    def run(self) -> None:
        self.history = []
        state = self.engine.state
        rng = self.engine.rng
        strategy = SimpleStrategy(rng)
        
        # Initial state record
        self.record_history(state)

        while state.phase != Phase.GAME_OVER:
            # Safety break for infinite loops
            if state.day > 100:
                break

            if state.phase == Phase.NIGHT_WOLF:
                wolf_id = self.get_first_alive_by_role(state, Role.WOLF)
                if wolf_id is not None:
                    rec = strategy.recommend(state, wolf_id)
                    apply_action(state, rec.action, recommendation=rec)
                else:
                    state.phase = Phase.NIGHT_SEER
            elif state.phase == Phase.NIGHT_SEER:
                seer_id = self.get_first_alive_by_role(state, Role.SEER)
                if seer_id is not None:
                    rec = strategy.recommend(state, seer_id)
                    apply_action(state, rec.action, recommendation=rec)
                else:
                    state.phase = Phase.NIGHT_WITCH
            elif state.phase == Phase.NIGHT_WITCH:
                witch_id = self.get_first_by_role(state, Role.WITCH)
                if witch_id is not None:
                    rec = strategy.recommend(state, witch_id)
                    apply_action(state, rec.action, recommendation=rec)
                
                self.resolve_hunter_shots(state, strategy)
                self.finalize_after_hunter(state)
                
                if state.phase != Phase.GAME_OVER:
                    state.phase = Phase.DAY_DISCUSS

            elif state.phase == Phase.DAY_DISCUSS:
                # Everyone speaks once in order
                speakers = alive_players(state)
                for speaker in speakers:
                    if state.phase == Phase.GAME_OVER: break
                    rec = strategy.recommend(state, speaker.player_id)
                    apply_action(state, rec.action, recommendation=rec)
                
                if state.phase != Phase.GAME_OVER:
                    state.phase = Phase.DAY_VOTE
                    
            elif state.phase == Phase.DAY_VOTE:
                vote_map = {}
                vote_reasons = {}
                
                # Collect votes
                for p in alive_players(state):
                    vote_target = strategy.choose_vote_target(state, p.player_id)
                    if vote_target is not None:
                        vote_map[p.player_id] = vote_target
                        # Get reason
                        action = Action(action_type=ActionType.VOTE, actor_id=p.player_id, target_id=vote_target)
                        reason = strategy._generate_reason(state, p.player_id, action)
                        vote_reasons[p.player_id] = reason
                
                # Tally votes
                vote_counts = {}
                for target in vote_map.values():
                    vote_counts[target] = vote_counts.get(target, 0) + 1
                
                description = "投票结束"
                exiled_player = None
                
                if vote_counts:
                    sorted_votes = sorted(vote_counts.items(), key=lambda x: x[1], reverse=True)
                    top_target, top_count = sorted_votes[0]
                    
                    # Check tie
                    is_tie = False
                    if len(sorted_votes) > 1 and sorted_votes[1][1] == top_count:
                        is_tie = True
                    
                    if not is_tie:
                        exiled_player = top_target
                        description = f"投票结果：放逐玩家 {exiled_player}"
                    else:
                        description = "投票结果：平票，无人被放逐"
                else:
                    description = "无人投票"
                
                # Record VOTE event
                # Convert keys to int for event record if needed, but they are ints
                record_event(state, description, target_id=exiled_player, votes=vote_map, vote_reasons=vote_reasons)
                
                # Execute Exile
                if exiled_player is not None:
                    kill_player(state, exiled_player, reason="VOTE")
                
                self.resolve_hunter_shots(state, strategy)
                self.finalize_after_hunter(state)

                if state.phase != Phase.GAME_OVER:
                    state.day += 1
                    state.phase = Phase.NIGHT_WOLF

        # Populate history
        self.history = []
        for e in state.public_events:
            rec_data = None
            if e.recommendation:
                rec_data = {
                    "win_rate": e.recommendation.win_rate_estimate,
                    "reason": e.recommendation.reason
                }
            
            self.history.append({
                "day": e.day,
                "phase": e.phase.value,
                "description": e.description,
                "actor_id": e.actor_id,
                "target_id": e.target_id,
                "votes": e.votes,
                "recommendation": rec_data
            })

    def record_history(self, state: GameState):
        pass

    def get_first_alive_by_role(self, state: GameState, role: Role) -> Optional[int]:
        for p in state.players:
            if p.role == role and p.alive:
                return p.player_id
        return None

    def get_first_by_role(self, state: GameState, role: Role) -> Optional[int]:
        for p in state.players:
            if p.role == role:
                return p.player_id
        return None

    def resolve_hunter_shots(self, state: GameState, strategy: SimpleStrategy) -> None:
        while True:
            unshot = get_unshot_dead_hunters(state)
            if not unshot:
                break
            for hunter in unshot:
                target_id = strategy.choose_hunter_shot(state, hunter.player_id)
                record_event(state, "猎人开枪", actor_id=hunter.player_id, target_id=target_id)
                if target_id is not None:
                    kill_player(state, target_id, reason="HUNTER")
    
    def finalize_after_hunter(self, state: GameState) -> None:
        if state.phase == Phase.GAME_OVER:
            return
        winner = check_winner(state)
        if winner is not None:
            state.winner = winner
            state.phase = Phase.GAME_OVER
            record_event(state, "游戏结束")


def run_game(seed: int = None, player_count: int = 9) -> GameState:
    state, rng = create_default_game(seed=seed, player_count=player_count)
    roles = {p.player_id: p.role for p in state.players}
    engine = GameEngine(roles, config=state.config)
    engine.rng = rng
    engine.state = state
    
    simulator = GameSimulator(engine)
    simulator.run()
    return state

def get_view(state: GameState, player_id: int) -> dict:
    return get_player_view(state, player_id)
