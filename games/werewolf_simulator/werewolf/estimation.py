
import random
import copy
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

from .models import GameState, Role, Faction, PlayerPrivate, WitchState, Player

@dataclass
class FastState:
    """Minimal state for fast simulation."""
    roles: Dict[int, Role]
    alive: Set[int]
    witch_save_used: bool
    witch_poison_used: bool
    seer_checked: Dict[int, bool]  # Target ID -> Is Wolf
    # Track who knows what (simplified)
    # Wolves know each other.
    # Good guys know only public info + their own checks.

    def is_game_over(self) -> Optional[Faction]:
        wolves = [pid for pid in self.alive if self.roles[pid] == Role.WOLF]
        good = [pid for pid in self.alive if self.roles[pid] != Role.WOLF]
        
        if not wolves:
            return Faction.VILLAGE
        if len(wolves) >= len(good):
            return Faction.WOLF
        return None

class FastSimulator:
    """
    A lightweight simulator for Monte Carlo rollouts.
    It assumes 'Rational' play:
    - Wolves kill highest priority targets.
    - Seer checks unknowns.
    - Witch saves/poisons based on simple heuristic rules.
    - Day Vote:
      - If Seer found a wolf, everyone votes for that wolf (Good coordination).
      - If no confirmed wolf, Good votes randomly among suspects.
      - Wolves vote for Good players.
    """
    def __init__(self, state: FastState):
        self.state = state

    def run(self) -> Faction:
        # Prevent infinite loops with a max round counter
        for _ in range(20): # 20 days max
            winner = self.state.is_game_over()
            if winner: return winner

            self._night_phase()
            
            winner = self.state.is_game_over()
            if winner: return winner
            
            self._day_phase()
        
        return Faction.VILLAGE # Draw favors Village? Or random? Let's say Village for now.

    def _night_phase(self):
        # 1. Wolf Kill
        target = self._wolf_choose_target()
        
        # 2. Witch Save
        saved = False
        witch_id = self._find_role(Role.WITCH)
        if witch_id in self.state.alive and not self.state.witch_save_used:
            # Simple heuristic: Save the first person killed (50% chance?)
            # Or always save if self is not target?
            # Let's say Witch saves 80% of the time on Night 1/2.
            if random.random() < 0.8:
                saved = True
                self.state.witch_save_used = True
        
        # 3. Witch Poison
        poison_target = None
        if witch_id in self.state.alive and not self.state.witch_poison_used:
            # Poison if Seer found a wolf and communicated it?
            # In simulation, we simplify: Random poison late game (30%)
            if random.random() < 0.3:
                # Poison a random non-confirmed good
                candidates = self._get_suspects(witch_id)
                if candidates:
                    poison_target = random.choice(candidates)
                    self.state.witch_poison_used = True

        # 4. Seer Check
        seer_id = self._find_role(Role.SEER)
        if seer_id in self.state.alive:
            unknowns = [p for p in self.state.alive if p != seer_id and p not in self.state.seer_checked]
            if unknowns:
                check = random.choice(unknowns)
                is_wolf = (self.state.roles[check] == Role.WOLF)
                self.state.seer_checked[check] = is_wolf

        # Resolve Deaths
        deaths = []
        if not saved and target is not None:
            deaths.append(target)
        if poison_target is not None:
            deaths.append(poison_target)
        
        for d in deaths:
            self.state.alive.discard(d)

    def _day_phase(self):
        # Voting Logic
        # 1. Check if Seer is alive and has found a wolf
        seer_id = self._find_role(Role.SEER)
        known_wolf = None
        
        if seer_id in self.state.alive:
            # Find a checked wolf
            for pid, is_wolf in self.state.seer_checked.items():
                if is_wolf and pid in self.state.alive:
                    known_wolf = pid
                    break
        
        # Vote Targets
        votes = {} # target -> count
        
        wolves = [p for p in self.state.alive if self.state.roles[p] == Role.WOLF]
        good = [p for p in self.state.alive if self.state.roles[p] != Role.WOLF]
        
        # Wolf Strategy: Vote for a random Good player
        # (Unless bus strategy, but let's stick to simple team play)
        wolf_target = random.choice(good) if good else None
        
        for w in wolves:
            if wolf_target:
                votes[wolf_target] = votes.get(wolf_target, 0) + 1
                
        # Good Strategy
        for g in good:
            if known_wolf:
                # If Seer exposed a wolf, vote for it!
                votes[known_wolf] = votes.get(known_wolf, 0) + 1
            else:
                # Vote for a random suspect (someone not known to be good)
                # In simulation, good players don't know roles.
                # Simplification: They vote for a random person who is NOT themselves.
                # (Ideally exclude confirmed good, but we don't track confirmed good fully here)
                candidates = [p for p in self.state.alive if p != g]
                if candidates:
                    vote = random.choice(candidates)
                    votes[vote] = votes.get(vote, 0) + 1
        
        # Tally
        if not votes: return
        
        # Sort by votes
        sorted_votes = sorted(votes.items(), key=lambda x: x[1], reverse=True)
        top_target, top_count = sorted_votes[0]
        
        # Handle Tie (Simple: random among ties, or no death)
        # Let's say max vote dies.
        self.state.alive.discard(top_target)
        
        # Hunter Death Logic (Simplified)
        if self.state.roles.get(top_target) == Role.HUNTER:
             # Shoot a random person
             candidates = [p for p in self.state.alive]
             if candidates:
                 shot = random.choice(candidates)
                 self.state.alive.discard(shot)

    def _wolf_choose_target(self) -> Optional[int]:
        # Priority: Seer > Witch > Villager
        # But Wolves don't know who is who in the real game?
        # WAIT: In the simulation, we are rolling out a "possible world".
        # In this world, roles are assigned.
        # REAL Wolves know roles. So in simulation, Wolf Bots should know roles.
        
        alive = self.state.alive
        good_alive = [p for p in alive if self.state.roles[p] != Role.WOLF]
        if not good_alive: return None
        
        # Try to find Gods
        seer = self._find_role(Role.SEER)
        witch = self._find_role(Role.WITCH)
        
        if seer in alive: return seer
        if witch in alive: return witch
        
        return random.choice(good_alive)

    def _find_role(self, role: Role) -> Optional[int]:
        for pid, r in self.state.roles.items():
            if r == role: return pid
        return None

    def _get_suspects(self, actor_id: int) -> List[int]:
        # Anyone alive except self
        return [p for p in self.state.alive if p != actor_id]


class WinRateEstimator:
    def __init__(self, num_simulations: int = 50):
        self.num_simulations = num_simulations

    def estimate(self, state: GameState, actor_id: int) -> float:
        """
        Estimate win rate for the faction of actor_id using Monte Carlo simulation.
        """
        my_role = state.players[actor_id].role if actor_id < len(state.players) else Role.VILLAGER
        # Use Engine's role_of logic if available, but here we access direct
        # Actually state.players is a list of Player objects.
        # Find player object
        my_player = next((p for p in state.players if p.player_id == actor_id), None)
        if not my_player: return 0.5
        
        my_role = my_player.role
        my_faction = Faction.WOLF if my_role == Role.WOLF else Faction.VILLAGE
        
        wins = 0
        
        # 1. Identify Fixed Information (Constraints)
        fixed_roles = {}
        fixed_roles[actor_id] = my_role
        
        # If I am Wolf, I know all teammates
        if my_role == Role.WOLF:
            for p in state.players:
                if p.role == Role.WOLF:
                    fixed_roles[p.player_id] = Role.WOLF
        
        # If I am Seer, I know my checks
        if my_role == Role.SEER:
            private = state.private_info.get(actor_id)
            if private:
                for target, is_wolf in private.seer_results.items():
                    fixed_roles[target] = Role.WOLF if is_wolf else Role.VILLAGER # Simplified Good
                    # Note: Seer sees "Good", doesn't know exact role (Villager vs Witch).
                    # But for simulation consistency, we need to assign exact roles.
                    # We will handle this in sampling.
        
        # If I am Witch, I might know Silver Water (but not role)
        # We ignore this for now to keep sampling simple.
        
        # Dead players: If death reveals role (e.g. game setting), fix it.
        # Assuming standard rules: Death = Role revealed?
        # The simulator usually prints "Player X died".
        # Let's assume for this estimator: We treat dead players as "Known" if we want,
        # or we just ignore them since they don't impact future win rate (except for balancing counts).
        # Actually, dead player roles matter for "what roles are left".
        # Let's assume we know the roles of dead players (Standard Open Cards).
        for p in state.players:
            if not p.alive:
                 # In many rules, role is revealed on death.
                 fixed_roles[p.player_id] = p.role

        # 2. Prepare Pool for Unknowns
        # Total roles in the game
        all_roles_list = []
        for p in state.players:
            all_roles_list.append(p.role)
            
        # Remove fixed roles from the pool
        pool = list(all_roles_list)
        for pid, role in fixed_roles.items():
            if role in pool:
                pool.remove(role)
            elif role == Role.VILLAGER and Role.VILLAGER not in pool:
                 # Seer saw a "Good" (Villager/God). We assigned Villager in fixed_roles as placeholder?
                 # Wait, Seer check result is boolean.
                 # If I am Seer and checked X is Good. X could be Witch, Hunter, Villager.
                 # This makes sampling harder.
                 # Simplification: If Seer sees Good, we treat it as "Constraint: X is not Wolf".
                 pass
        
        # Refined Sampling:
        # We need to assign roles to unknown players such that constraints are met.
        # Constraints:
        # 1. fixed_roles (Exact matches)
        # 2. partial_constraints (e.g. X is NOT Wolf)
        
        unknown_players = [p.player_id for p in state.players if p.player_id not in fixed_roles]
        
        # Special handling for Seer's "Good" checks (which are not in fixed_roles yet)
        known_good_ids = set()
        if my_role == Role.SEER:
            private = state.private_info.get(actor_id)
            if private:
                 for target, is_wolf in private.seer_results.items():
                     if not is_wolf:
                         known_good_ids.add(target)
        
        # Filter pool to ensure we can satisfy known_goods
        # The pool must contain enough non-wolf roles for known_good_ids that are in unknown_players
        
        # 3. Run Simulations
        for _ in range(self.num_simulations):
            # Sample a world
            current_pool = list(pool)
            random.shuffle(current_pool)
            
            # Assign roles
            temp_roles = dict(fixed_roles)
            
            # Check if assignment is valid regarding Known Goods
            # We need to assign Non-Wolf to Known Goods
            
            # Split unknown players into "Must be Good" and "Any"
            must_be_good = [uid for uid in unknown_players if uid in known_good_ids]
            others = [uid for uid in unknown_players if uid not in known_good_ids]
            
            # Try to assign
            # This is a bit complex if pool doesn't have enough goods (logic error elsewhere).
            # Simple approach: Re-shuffle until valid (Rejection Sampling).
            
            valid_assignment = False
            attempt_limit = 10
            
            assigned_map = {}
            
            for attempt in range(attempt_limit):
                random.shuffle(current_pool)
                # Try to pop goods for must_be_good
                temp_pool = list(current_pool)
                current_assignment = {}
                
                possible = True
                for mg in must_be_good:
                    # Find a non-wolf in temp_pool
                    # Prefer Villager/God
                    found = False
                    for i, r in enumerate(temp_pool):
                        if r != Role.WOLF:
                            current_assignment[mg] = temp_pool.pop(i)
                            found = True
                            break
                    if not found:
                        possible = False
                        break
                
                if possible:
                    # Assign rest
                    for o in others:
                        current_assignment[o] = temp_pool.pop(0)
                    assigned_map = current_assignment
                    valid_assignment = True
                    break
            
            if not valid_assignment:
                # Fallback: Just random assign (ignore Seer info to avoid crash)
                # This dilutes accuracy but keeps robustness
                random.shuffle(current_pool)
                for i, uid in enumerate(unknown_players):
                    assigned_map[uid] = current_pool[i]

            temp_roles.update(assigned_map)
            
            # Build FastState
            # Witch State?
            # If I am Witch, I know my state.
            # If I am not, I assume Witch state is default (fresh) unless public info says otherwise.
            # (Simplification: Assume fresh)
            
            w_save = False
            w_poison = False
            
            # Check if Witch is already dead?
            # If Witch is dead, effectively powers are gone.
            # FastSimulator handles alive check.
            
            # If I am Witch, use my actual state
            if my_role == Role.WITCH and actor_id in state.private_info:
                w_state = state.private_info[actor_id].witch_state
                w_save = w_state.save_used
                w_poison = w_state.poison_used

            sim_state = FastState(
                roles=temp_roles,
                alive={p.player_id for p in state.players if p.alive},
                witch_save_used=w_save,
                witch_poison_used=w_poison,
                seer_checked={} # Reset check memory for simulation Seer
            )
            
            # If I am Seer, the simulation Seer should know what I know?
            # Yes, pre-fill seer_checked
            if my_role == Role.SEER and actor_id in state.private_info:
                sim_state.seer_checked = dict(state.private_info[actor_id].seer_results)

            simulator = FastSimulator(sim_state)
            winner = simulator.run()
            
            if winner == my_faction:
                wins += 1
                
        return wins / self.num_simulations
