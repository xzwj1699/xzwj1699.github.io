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
        # Run until game over
        # We need a way to capture step-by-step events for history
        # The original 'run_game' function does everything in one go.
        # Let's refactor run_game logic into this class or use it.
        # For simplicity, we'll adapt the run_game logic here.
        
        state = self.engine.state
        rng = self.engine.rng
        strategy = SimpleStrategy(rng)
        
        # Initial state record
        self.record_history(state)

        while state.phase != Phase.GAME_OVER:
            if state.phase == Phase.NIGHT_WOLF:
                wolf_id = get_first_alive_by_role(state, Role.WOLF)
                if wolf_id is not None:
                    rec = strategy.recommend(state, wolf_id)
                    apply_action(state, rec.action, recommendation=rec)
                else:
                    state.phase = Phase.NIGHT_SEER
            elif state.phase == Phase.NIGHT_SEER:
                seer_id = get_first_alive_by_role(state, Role.SEER)
                if seer_id is not None:
                    rec = strategy.recommend(state, seer_id)
                    apply_action(state, rec.action, recommendation=rec)
                else:
                    state.phase = Phase.NIGHT_WITCH
            elif state.phase == Phase.NIGHT_WITCH:
                witch_id = get_first_by_role(state, Role.WITCH)
                rec = strategy.recommend(state, witch_id)
                apply_action(state, rec.action, recommendation=rec)
                resolve_hunter_shots(state, strategy)
                finalize_after_hunter(state)
                
                # Add status summary event for debugging/logging
                # List Gold Water (Silver Water), Seer Checks, etc.
                if state.day == 1: # Only on first night or every night? Maybe every night.
                    pass 

            elif state.phase == Phase.DAY_DISCUSS:
                # Everyone speaks once in order
                speakers = alive_players(state)
                # Randomize speaker order? Or sequential? Sequential for now.
                for speaker in speakers:
                    if state.phase != Phase.DAY_DISCUSS: break # Check if phase changed (game over?)
                    rec = strategy.recommend(state, speaker.player_id)
                    # Apply action
                    apply_action(state, rec.action, recommendation=rec)
                    # Update beliefs for everyone based on this statement
                    if rec.action.statement:
                         strategy.update_beliefs(state, rec.action.statement)
                
                # End discussion, move to vote
                
                # Debug Info removed (Moved to UI tags)

                state.phase = Phase.DAY_VOTE
            elif state.phase == Phase.DAY_VOTE:
                vote_map = {}
                vote_reasons = {}
                alive_count = 0
                for p in state.players:
                    if p.alive:
                        alive_count += 1
                        vote_target = strategy.choose_vote_target(state, p.player_id)
                        vote_map[str(p.player_id)] = vote_target
                        
                        # Get reason for this vote
                        rec = strategy.recommend(state, p.player_id)
                        # Override target in recommendation to match chosen target (if strategy is consistent)
                        # Actually choose_vote_target and recommend might differ if not synced.
                        # recommend calls choose_vote_target internally for DAY_VOTE.
                        # Let's just use recommend logic to get reason.
                        # But wait, recommend returns a new Action. We need to ensure it's the same target.
                        # strategy.choose_vote_target is used above.
                        # Let's call recommend but force action target to be vote_target to generate reason?
                        # _generate_reason takes an action.
                        
                        action = Action(action_type=ActionType.VOTE, actor_id=p.player_id, target_id=vote_target)
                        reason = strategy._generate_reason(state, p.player_id, action)
                        vote_reasons[str(p.player_id)] = reason

                
                # Count votes
                vote_counts = {}
                for target in vote_map.values():
                    vote_counts[target] = vote_counts.get(target, 0) + 1
                
                # Check majority
                # Rules:
                # 1. Plurality (whoever has most votes).
                #    User requested: "Most votes gets exiled" (relative majority).
                #    So we remove the > 50% threshold.
                #    Only tie at the top prevents exile.
                
                exiled_player = None
                
                # Sort by votes
                sorted_votes = sorted(vote_counts.items(), key=lambda x: x[1], reverse=True)
                
                description = "投票结束"
                
                if sorted_votes:
                    top_target, top_count = sorted_votes[0]
                    # Check for tie at the top
                    is_tie = False
                    if len(sorted_votes) > 1 and sorted_votes[1][1] == top_count:
                        is_tie = True
                        
                    # Condition: Not a tie. No threshold.
                    if not is_tie:
                        exiled_player = top_target
                        description = f"投票结果：放逐玩家 {exiled_player}"
                    else:
                        reason = "平票"
                        description = f"投票结果：{reason}，无人被放逐"
                else:
                     description = "无人投票"



                # Record the VOTE event with details
                # If exiled, include "exiled_player_id" in event or just rely on description/target_id?
                # Target ID is used for exiled player in VOTE event.
                record_event(state, description, target_id=exiled_player, votes=vote_map, vote_reasons=vote_reasons)
                
                # Update trust based on votes
                strategy.update_trust_after_vote(state, vote_map)
                
                if exiled_player is not None:
                    kill_player(state, exiled_player, reason="VOTE")
                    # Mark as exiled in public events? Or just use description.
                    # We need frontend to know this was an exile event.
                    # Frontend checks phase == DAY_VOTE and target_id.
                
                resolve_hunter_shots(state, strategy)
                finalize_after_hunter(state)

                if state.phase != Phase.GAME_OVER:
                    state.day += 1
                    state.phase = Phase.NIGHT_WOLF
            
            pass

        # After game over, populate history from public_events
        self.history = [
            {
                "day": e.day,
                "phase": e.phase.value,
                "description": e.description,
                "actor_id": e.actor_id,
                "target_id": e.target_id,
                "recommendation": {
                    "action_type": e.recommendation.action.action_type.value,
                    "target_id": e.recommendation.action.target_id,
                    "reason": e.recommendation.reason,
                    "win_rate": e.recommendation.win_rate_estimate
                } if e.recommendation else None,
                "statement": {
                    "actor_id": e.statement.actor_id,
                    "content": e.statement.content,
                    "claimed_role": e.statement.claimed_role.value if e.statement.claimed_role else None,
                    "claimed_checks": {k: v for k, v in e.statement.claimed_checks.items()}
                } if e.statement else None,
                "trust_scores": e.trust_scores,
                "votes": e.votes,
                "vote_reasons": e.vote_reasons
            }




            for e in state.public_events
        ]

    def record_history(self, state: GameState):
        pass



def get_first_alive_by_role(state: GameState, role: Role) -> Optional[int]:
    for p in state.players:
        if p.role == role and p.alive:
            return p.player_id
    return None


def get_first_by_role(state: GameState, role: Role) -> int:
    for p in state.players:
        if p.role == role:
            return p.player_id
    return state.players[0].player_id


def get_first_alive_player_id(state: GameState) -> int:
    for p in state.players:
        if p.alive:
            return p.player_id
    return state.players[0].player_id


def resolve_votes(state: GameState, strategy: SimpleStrategy) -> int:
    vote_counts = {}
    for p in state.players:
        if not p.alive:
            continue
        target_id = strategy.choose_vote_target(state, p.player_id)
        vote_counts[target_id] = vote_counts.get(target_id, 0) + 1
    max_votes = max(vote_counts.values())
    top_targets = [pid for pid, count in vote_counts.items() if count == max_votes]
    return strategy.rng.choice(top_targets)


def resolve_hunter_shots(state: GameState, strategy: SimpleStrategy) -> None:
    while True:
        unshot = get_unshot_dead_hunters(state)
        if not unshot:
            break
        for hunter in unshot:
            target_id = strategy.choose_hunter_shot(state, hunter.player_id)
            record_event(state, "猎人开枪", actor_id=hunter.player_id, target_id=target_id)
            if target_id is not None:
                kill_player(state, target_id, reason="HUNTER")


def finalize_after_hunter(state: GameState) -> None:
    if state.phase == Phase.GAME_OVER:
        return
    winner = check_winner(state)
    if winner is not None:
        state.winner = winner
        state.phase = Phase.GAME_OVER
        record_event(state, "游戏结束")
        return


def get_view(state: GameState, player_id: int) -> dict:
    return get_player_view(state, player_id)
