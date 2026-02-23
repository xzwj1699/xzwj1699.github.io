from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import random

from .models import Action, ActionType, GameState, Phase, Role, Recommendation, Statement, PlayerPrivate, Faction
from .engine import alive_players, get_player, role_of
from .estimation import WinRateEstimator

@dataclass
class SimpleStrategy:
    rng: random.Random
    estimator: WinRateEstimator = field(default_factory=lambda: WinRateEstimator(num_simulations=50))

    def recommend(self, state: GameState, actor_id: int) -> Recommendation:
        # Wrapper to return Recommendation object
        action = self._choose_action(state, actor_id)
        reason = self._generate_reason(state, actor_id, action)
        win_rate = self.estimator.estimate(state, actor_id)
        return Recommendation(action=action, reason=reason, win_rate_estimate=win_rate)

    def _choose_action(self, state: GameState, actor_id: int) -> Action:
        if state.phase == Phase.NIGHT_WOLF:
            return self.choose_wolf_kill(state, actor_id)
        if state.phase == Phase.NIGHT_SEER:
            return self.choose_seer_check(state, actor_id)
        if state.phase == Phase.NIGHT_WITCH:
            return self.choose_witch_action(state, actor_id)
        if state.phase == Phase.DAY_DISCUSS:
            return self.choose_statement(state, actor_id)
        if state.phase == Phase.DAY_VOTE:
            target_id = self.choose_vote_target(state, actor_id)
            return Action(action_type=ActionType.VOTE, actor_id=actor_id, target_id=target_id)
        return Action(action_type=ActionType.PASS, actor_id=actor_id)

    def _generate_reason(self, state: GameState, actor_id: int, action: Action) -> str:
        if action.action_type == ActionType.KILL:
            return "狼人策略：随机选择一名非狼人玩家进行击杀（基础策略）"
        if action.action_type == ActionType.CHECK:
            return "预言家策略：优先查验未知身份的存活玩家"
        if action.action_type == ActionType.SAVE:
            return "女巫策略：解药可用，发现有人倒牌，决定使用解药救人（银水）"
        if action.action_type == ActionType.POISON:
            return "女巫策略：发现确定的狼人目标，使用毒药"
        if action.action_type == ActionType.SPEAK:
            stmt = action.statement
            if stmt.claimed_role == Role.SEER:
                if role_of(state, actor_id) == Role.WOLF:
                    return "狼人策略（悍跳）：假装预言家，混淆视听，争取抗推位"
                else:
                    return "预言家策略：诚实报告查验结果（金水/查杀），构建逻辑链"
            if stmt.claimed_role == Role.WITCH:
                return "女巫策略：跳身份带队，报告银水信息"
            if stmt.content == "过":
                return "平民策略（深水/隐身）：没有特别信息，选择划水，避免成为焦点"
            return "常规发言"
        if action.action_type == ActionType.VOTE:
            # Check trust scores
            private = state.private_info[actor_id]
            my_role = role_of(state, actor_id)
            
            # Wolf specific reasons
            if my_role == Role.WOLF:
                target_role = role_of(state, action.target_id)
                if target_role in [Role.SEER, Role.WITCH, Role.HUNTER]:
                    return f"狼人策略：目标 {action.target_id} 是神职（{target_role.value}），优先放逐"
                else:
                    return f"狼人策略：目标 {action.target_id} 是好人，试图将其抗推"

            # 1. Vote known wolves (Seer logic)
            known_wolves = [pid for pid, is_wolf in private.seer_results.items() if is_wolf and get_player(state, pid).alive]
            if action.target_id in known_wolves:
                return f"投票理由：目标 {action.target_id} 是已查验的狼人（铁狼）"
            
            # 2. Witch Silver Water Logic
            if my_role == Role.WITCH and private.witch_state.saved_player_id is not None:
                # If voting for someone who is NOT Silver Water, but is attacking Silver Water?
                # Actually if we are voting for X, and X claimed Seer (but is not Silver Water), say it.
                if action.target_id in private.known_seers:
                     saved = private.witch_state.saved_player_id
                     if saved != action.target_id and saved in private.known_seers:
                         return f"女巫策略：银水是 {saved}，目标 {action.target_id} 对跳预言家，定为悍跳狼"

            # 3. Stand-side Logic
            if action.target_id in private.known_seers:
                # If I am voting for a Seer, explain why.
                # If I have a trusted Seer (e.g. Silver Water), and I vote for another.
                if private.believed_silver_water:
                    silver = private.believed_silver_water
                    if silver != action.target_id:
                         # Logic Check: Did the one I support verify Silver Water?
                         # If trusted_seer (supported) verified Silver Water, say it.
                         return f"投票理由：相信女巫的银水 {silver} 是好人，支持验其为好人的预言家，放逐悍跳狼 {action.target_id}"
                
                return f"投票理由：站边逻辑，不相信目标 {action.target_id} 的预言家身份（信赖度低）"

            # 4. Vote lowest trust (Belief logic)
            if action.target_id in private.trust_scores:
                score = private.trust_scores[action.target_id]
                if score < 0.4:
                    return f"投票理由：目标 {action.target_id} 的信赖度极低 ({score:.2f})，怀疑是悍跳狼或倒钩狼"
            
            return "投票理由：没有明确线索，随机投票（避免弃票）"
        return "常规行动"

    def choose_wolf_kill(self, state: GameState, actor_id: int) -> Action:
        # Advanced Logic:
        # 1. Kill confirmed Gods (Seer/Witch) if known.
        # 2. Kill high-trust good players (Gold Water).
        # 3. Avoid killing deep water wolves (obviously).
        
        # Identify targets
        targets = [p.player_id for p in alive_players(state) if p.role != Role.WOLF]
        
        # Check if we know any roles (e.g. from open claims)
        # We need to scan public events for role claims
        known_seers = []
        known_witches = []
        
        for e in state.public_events:
            if e.statement and e.statement.claimed_role:
                claimer = e.statement.actor_id
                if get_player(state, claimer).alive:
                    if e.statement.claimed_role == Role.SEER:
                        known_seers.append(claimer)
                    elif e.statement.claimed_role == Role.WITCH:
                        known_witches.append(claimer)
        
        # Priority: Real Seer > Witch > Random
        # But Wolf doesn't know who is Real Seer if there is a jump.
        # Actually Wolf knows who is NOT wolf. If two people claim Seer, and one is Wolf teammate, the other is Real Seer.
        
        real_seers = [pid for pid in known_seers if role_of(state, pid) != Role.WOLF]
        real_witches = [pid for pid in known_witches if role_of(state, pid) != Role.WOLF]
        
        priority_targets = real_seers + real_witches
        
        if priority_targets:
            target_id = priority_targets[0]
        elif targets:
            target_id = self.rng.choice(targets)
        else:
            return Action(action_type=ActionType.PASS, actor_id=actor_id)
            
        return Action(action_type=ActionType.KILL, actor_id=actor_id, target_id=target_id)

    def choose_seer_check(self, state: GameState, actor_id: int) -> Action:
        private = state.private_info[actor_id]
        
        # Priority:
        # 1. Check active Seer claimers (Counter-Jumpers)
        # 2. Check people with low trust (Suspects)
        # 3. Check random active players (High profile)
        # 4. Random unchecked
        
        candidates = []
        
        # 1. Counter-Jumpers
        for pid in private.known_seers:
            if pid != actor_id and pid not in private.seer_results and get_player(state, pid).alive:
                candidates.append(pid)
        
        if candidates:
            target = self.rng.choice(candidates)
            return Action(action_type=ActionType.CHECK, actor_id=actor_id, target_id=target)
            
        # 2. Low Trust / Suspects
        # Check people who others are suspecting?
        # Or people I distrust.
        suspects = []
        for pid, score in private.trust_scores.items():
            if score < 0.4 and pid not in private.seer_results and get_player(state, pid).alive:
                suspects.append(pid)
        
        if suspects:
            target = self.rng.choice(suspects)
            return Action(action_type=ActionType.CHECK, actor_id=actor_id, target_id=target)
            
        # 3. Random unchecked
        alive = alive_players(state)
        unchecked = [p.player_id for p in alive if p.player_id not in private.seer_results and p.player_id != actor_id]
        
        if unchecked:
            target_id = self.rng.choice(unchecked)
            return Action(action_type=ActionType.CHECK, actor_id=actor_id, target_id=target_id)
            
        return Action(action_type=ActionType.PASS, actor_id=actor_id)

    def choose_witch_action(self, state: GameState, actor_id: int) -> Action:
        private = state.private_info[actor_id]
        
        # 1. Save Logic
        if not private.witch_state.save_used:
            target = state.pending_kill
            if target is not None and target != actor_id: # Cannot save self usually
                # Save!
                private.witch_state.save_used = True
                private.witch_state.saved_player_id = target
                return Action(action_type=ActionType.SAVE, actor_id=actor_id, target_id=target)
                
        # 2. Poison Logic
        if not private.witch_state.poison_used:
            # Poison known Wolf
            # Or if I am dying (pending_kill == actor_id), PANIC POISON!
            
            # Check if I am dying
            am_dying = (state.pending_kill == actor_id)
            if am_dying and not private.witch_state.save_used:
                 # Can I save myself? Usually no.
                 pass
            
            target_to_poison = None
            
            # Priority A: Known Wolves (Seer checked)
            for pid, is_wolf in private.seer_results.items():
                if is_wolf and get_player(state, pid).alive:
                    target_to_poison = pid
                    break
            
            # Priority B: If I am dying, take someone down!
            if target_to_poison is None and am_dying:
                # Find most suspicious person
                # 1. Fake Seer (if any)
                # 2. Lowest trust score
                
                # Check for Fake Seer (Jump Wolf)
                alive_seers = [pid for pid in private.known_seers if get_player(state, pid).alive]
                if alive_seers:
                    # If I have a trusted seer (e.g. Silver Water confirmed), poison the other(s)
                    # Or poison the one with lowest trust
                    alive_seers.sort(key=lambda pid: private.trust_scores.get(pid, 0.5))
                    target_to_poison = alive_seers[0] # Lowest trust seer
                
                # If no Seer candidate or still None, pick lowest trust overall
                if target_to_poison is None:
                    candidates = [p.player_id for p in alive_players(state) if p.player_id != actor_id]
                    candidates.sort(key=lambda pid: private.trust_scores.get(pid, 0.5))
                    if candidates:
                        target_to_poison = candidates[0]
            
            if target_to_poison is not None:
                private.witch_state.poison_used = True
                return Action(action_type=ActionType.POISON, actor_id=actor_id, target_id=target_to_poison)
                
        return Action(action_type=ActionType.PASS, actor_id=actor_id)


    def choose_hunter_shot(self, state: GameState, actor_id: int) -> Optional[int]:
        candidates = [p.player_id for p in alive_players(state) if p.player_id != actor_id]
        if not candidates:
            return None
            
        # Priority:
        # 1. Someone who voted for me in the last vote phase?
        # 2. Someone who claimed Seer and checked me as Wolf (Fake Seer).
        # 3. Lowest trust score.
        
        # Check Public Events for voters/accusers
        enemies = []
        
        for e in state.public_events:
            # Check for votes against me
            if e.votes:
                for voter_str, target_id in e.votes.items():
                    if target_id == actor_id:
                        voter = int(voter_str)
                        if get_player(state, voter).alive:
                            enemies.append(voter)
            
            # Check for false accusations
            if e.statement and e.statement.claimed_role == Role.SEER:
                if actor_id in e.statement.claimed_checks:
                    is_wolf = e.statement.claimed_checks[actor_id]
                    if is_wolf: # They said I am Wolf!
                        speaker = e.statement.actor_id
                        if get_player(state, speaker).alive:
                            enemies.append(speaker)
                            
        if enemies:
            # Prioritize latest enemies? Or most frequent?
            # Just pick random enemy for now.
            return self.rng.choice(enemies)
            
        # Fallback: Lowest trust
        private = state.private_info[actor_id]
        
        # HUNTER SPECIAL: If there is a suspicious Seer (Jump Wolf), shoot him.
        # Especially if I am dying at night (likely Wolf Kill).
        # If I am dying, and there is a "Seer" alive who is distrusted.
        
        # Find alive Seers
        alive_seers = [pid for pid in private.known_seers if get_player(state, pid).alive]
        if len(alive_seers) == 1:
            # Only one Seer left. Is he trusted?
            seer = alive_seers[0]
            if private.trust_scores.get(seer, 0.5) < 0.4:
                return seer # Shoot the fake seer
        elif len(alive_seers) > 1:
             # Multiple seers. Shoot the one I distrust most.
             # Or shoot the one who is NOT Silver Water supported.
             alive_seers.sort(key=lambda pid: private.trust_scores.get(pid, 0.5))
             return alive_seers[0] # Shoot lowest trust
        
        lowest_score = 1.0
        lowest_target = -1
        found_low = False
        
        for cand in candidates:
            score = private.trust_scores.get(cand, 0.5)
            if score < lowest_score:
                lowest_score = score
                lowest_target = cand
                found_low = True
                
        if found_low and lowest_score < 0.4:
            return lowest_target
            
        return self.rng.choice(candidates)

    def choose_statement(self, state: GameState, actor_id: int) -> Action:

        my_role = role_of(state, actor_id)
        private = state.private_info[actor_id]
        
        # 1. Seer Strategy: Always claim Seer and report results
        if my_role == Role.SEER:
            return self._create_seer_statement(state, actor_id, private)
            
        # 2. Witch Strategy: Report saves/poisons
        if my_role == Role.WITCH:
            return self._create_witch_statement(state, actor_id, private)

        # 3. Wolf Strategy: Maybe claim Seer (Jump)
        if my_role == Role.WOLF:
            # Check if any teammate has claimed Seer in the past (History Check)
            teammate_jumped = False
            for e in state.public_events:
                 if e.statement and e.statement.claimed_role == Role.SEER:
                      # Check if the claimer was a wolf teammate
                      if role_of(state, e.statement.actor_id) == Role.WOLF and e.statement.actor_id != actor_id:
                           teammate_jumped = True
                           break
            
            # Strategy Update: Single Jumper Policy
            # If a teammate has already jumped (alive or dead), other wolves should NOT jump.
            # This prevents "chain feeding" where wolves die one by one claiming Seer.
            if not teammate_jumped:
                wolves = [p.player_id for p in alive_players(state) if p.role == Role.WOLF]
                jumper_id = wolves[0] if wolves else -1
                
                if actor_id == jumper_id:
                    return self._create_fake_seer_statement(state, actor_id)
                
        # 4. Hunter Strategy: Reveal if targeted
        if my_role == Role.HUNTER:
             # If I was voted heavily yesterday? Or if I am accused?
             # For now, if trust is low or randomly if game is late.
             # Check if I received votes yesterday? (Need to scan history)
             pass

        # Villager / Hunter (Hidden) / Wolf (Hidden)
        
        # Analyze Trust
        trust_analysis = self._analyze_trust_situation(state, actor_id)
        
        # Chance to speak something useful instead of "Pass"
        # Increase chance if there is something to say (e.g. suspicious people)
        has_something_to_say = False
        speech_content = "过"
        
        if trust_analysis['lowest_trust_score'] < 0.4:
            target = trust_analysis['lowest_trust_target']
            speech_content = f"我觉得 {target} 比较可疑，信赖度很低。"
            has_something_to_say = True
            
        # Hunter Special: If low trust, maybe threaten?
        if my_role == Role.HUNTER and has_something_to_say:
             speech_content += " 我身份比较强，大家注意。"
             
        # Wolf Special: Deep water
        if my_role == Role.WOLF:
            # Maybe agree with current trend or stay quiet
            pass

        # Randomness: 60% chance to speak if has something, else Pass
        if has_something_to_say and self.rng.random() < 0.6:
             return Action(action_type=ActionType.SPEAK, actor_id=actor_id, statement=Statement(actor_id=actor_id, content=speech_content))
             
        return Action(action_type=ActionType.SPEAK, actor_id=actor_id, statement=Statement(actor_id=actor_id, content="过"))

    def _analyze_trust_situation(self, state: GameState, actor_id: int) -> Dict:
        private = state.private_info[actor_id]
        lowest_score = 1.0
        lowest_target = -1
        
        for pid, score in private.trust_scores.items():
            if get_player(state, pid).alive and pid != actor_id:
                if score < lowest_score:
                    lowest_score = score
                    lowest_target = pid
                    
        return {
            'lowest_trust_target': lowest_target,
            'lowest_trust_score': lowest_score
        }

    def _choose_wolf_vote_target(self, state: GameState, actor_id: int) -> int:
        alive = alive_players(state)
        teammates = [p.player_id for p in alive if p.role == Role.WOLF]
        non_wolves = [p.player_id for p in alive if p.role != Role.WOLF]
        
        if not non_wolves: return actor_id # Should not happen
        
        # --- NEW STRATEGY: Coordinate Voting for Wolves ---
        
        # 1. Identify "Jumper Wolf" (Teammate claiming Seer)
        jumper_wolf = -1
        jumper_target = -1
        
        # Scan history for active Seer claim by teammate
        for e in reversed(state.public_events):
            # Check latest claim in current or previous day
            if e.statement and e.statement.claimed_role == Role.SEER:
                speaker = e.statement.actor_id
                if speaker in teammates and get_player(state, speaker).alive:
                    jumper_wolf = speaker
                    # Find who they accused (Kill check) or cleared (Gold Water)
                    # Actually, if they accused someone, we vote that person.
                    # If they cleared someone, we don't vote that person (usually).
                    # But we need a target.
                    # If Jumper accused X, X is priority target.
                    for target, is_wolf in e.statement.claimed_checks.items():
                        if is_wolf and get_player(state, target).alive:
                            jumper_target = target
                            break
                    break
        
        # 2. Identify Real Seer (Enemy Seer)
        enemy_seer = -1
        for e in reversed(state.public_events):
            if e.statement and e.statement.claimed_role == Role.SEER:
                speaker = e.statement.actor_id
                if speaker not in teammates and get_player(state, speaker).alive:
                    enemy_seer = speaker
                    break
        
        # 3. Decision Logic
        
        # Priority A: If Jumper Wolf exists and accused someone, Follow Jumper (Vote Accused).
        # This creates consistency: "I believe Seer (Jumper), so I vote his Wolf".
        if jumper_wolf != -1 and jumper_target != -1:
             return jumper_target
             
        # Priority B: If Jumper Wolf exists but didn't accuse anyone (Gold Water round),
        # Vote for the Enemy Seer (Real Seer) to protect Jumper.
        if jumper_wolf != -1 and enemy_seer != -1:
            return enemy_seer
            
        # Priority C: If no Jumper (or Jumper dead), but Enemy Seer is alive.
        # Vote Enemy Seer (to kill Threat).
        if enemy_seer != -1:
            return enemy_seer
            
        # Priority D: Kill other Gods (Witch/Hunter) if revealed
        known_gods = []
        for e in state.public_events:
            if e.statement and e.statement.claimed_role in [Role.WITCH, Role.HUNTER]:
                claimer = e.statement.actor_id
                if claimer in non_wolves and get_player(state, claimer).alive:
                     known_gods.append(claimer)
        
        if known_gods:
            return known_gods[0]
            
        # Priority E: Consistency with self-speech (if I accused someone)
        for e in reversed(state.public_events):
            if e.day == state.day and e.actor_id == actor_id and e.statement:
                import re
                content = e.statement.content
                match = re.search(r"(我觉得|我怀疑|认出|认为|建议查杀).*?(\d+)", content)
                if not match:
                    match = re.search(r"(\d+).*?(是狼|铁狼|悍跳|可疑)", content)
                
                if match:
                    for group in match.groups():
                        if group.isdigit():
                            suspect = int(group)
                            if get_player(state, suspect).alive:
                                return suspect
                            break

        # Priority F: Random Villager
        return self.rng.choice(non_wolves)

    def _create_witch_statement(self, state: GameState, actor_id: int, private: PlayerPrivate) -> Action:
        content_parts = []
        
        # Check if save was used (look in history for target)
        if private.witch_state.save_used:
            saved_target = None
            save_day = -1
            # Scan history in reverse to find when save was used
            for e in reversed(state.public_events):
                if e.actor_id == actor_id and "使用了解药" in e.description:
                    saved_target = e.target_id
                    save_day = e.day
                    break
            
            if saved_target is not None:
                # Logic: Only report save if it happened last night (Day = current Day) or if I am claiming for the first time?
                # Actually, Witch usually only says "Saved X last night" if it happened last night.
                # If saved earlier, maybe say "Save used on X (Day Y)".
                # The issue was "昨晚救了 1" repeated on Day 2 even if save was on Day 1.
                # state.day is current day. save_day is when it happened.
                
                if save_day == state.day:
                    content_parts.append(f"昨晚救了 {saved_target}")
                else:
                    content_parts.append(f"第 {save_day} 晚救了 {saved_target}")
            else:
                content_parts.append("解药已用")
                
        # Check if poison was used
        if private.witch_state.poison_used:
            poisoned_target = None
            poison_day = -1
            for e in reversed(state.public_events):
                if e.actor_id == actor_id and "使用了毒药" in e.description:
                    poisoned_target = e.target_id
                    poison_day = e.day
                    break
            
            if poisoned_target is not None:
                if poison_day == state.day:
                    content_parts.append(f"昨晚毒了 {poisoned_target}")
                else:
                    content_parts.append(f"第 {poison_day} 晚毒了 {poisoned_target}")
        
        if not content_parts:
             return Action(action_type=ActionType.SPEAK, actor_id=actor_id, statement=Statement(actor_id=actor_id, content="我是女巫，药水还在"))
             
        content = "我是女巫，" + "，".join(content_parts)
        stmt = Statement(actor_id=actor_id, claimed_role=Role.WITCH, content=content)
        return Action(action_type=ActionType.SPEAK, actor_id=actor_id, statement=stmt)


    def _create_seer_statement(self, state: GameState, actor_id: int, private: PlayerPrivate) -> Action:
        # Report all results? Or just latest? 
        # Typically report all history to be convincing.
        content_parts = ["我是预言家"]
        checks = {}
        for pid, is_wolf in private.seer_results.items():
            role_str = "狼人" if is_wolf else "好人"
            content_parts.append(f"验了 {pid} 是 {role_str}")
            checks[pid] = is_wolf
            
        content = "，".join(content_parts)
        stmt = Statement(actor_id=actor_id, claimed_role=Role.SEER, claimed_checks=checks, content=content)
        return Action(action_type=ActionType.SPEAK, actor_id=actor_id, statement=stmt)

    def _create_fake_seer_statement(self, state: GameState, actor_id: int) -> Action:
        # Improved Fake Seer Strategy (User Request Optimized)
        # 1. Avoid accusing known Gods (Witch/Hunter/Silver Water) - unless desperate.
        # 2. Prioritize accusing Unknown players (to push Kill).
        # 3. Or give Gold Water to Teammates (to bond/protect).
        
        alive = alive_players(state)
        teammates = [p.player_id for p in alive if p.role == Role.WOLF]
        
        # History Check: What have I claimed before?
        my_claimed_checks = {}
        for e in state.public_events:
             if e.statement and e.statement.actor_id == actor_id and e.statement.claimed_role == Role.SEER:
                 my_claimed_checks.update(e.statement.claimed_checks)

        # Identify Known Good / Gods to AVOID accusing
        known_good_identities = set()
        for e in state.public_events:
            if e.statement and e.statement.claimed_role in [Role.WITCH, Role.HUNTER]:
                claimer = e.statement.actor_id
                if get_player(state, claimer).alive:
                     known_good_identities.add(claimer)
            if e.statement and e.statement.claimed_role == Role.WITCH:
                 import re
                 match = re.search(r"救了\s*(\d+)", e.statement.content)
                 if match:
                     saved_id = int(match.group(1))
                     known_good_identities.add(saved_id)

        # Filter Unknowns: Alive - Teammates - Known Good - Self - Already Checked
        unknowns = []
        for p in alive:
            pid = p.player_id
            if pid != actor_id and pid not in teammates and pid not in known_good_identities and pid not in my_claimed_checks:
                unknowns.append(pid)
        
        # Decision Logic
        target = -1
        is_wolf = False
        
        can_gold_teammate = len([t for t in teammates if t != actor_id and t not in my_claimed_checks]) > 0
        can_accuse_unknown = len(unknowns) > 0
        
        rand_val = self.rng.random()
        
        # Strategy 1: Gold Water Teammate (40%)
        # "发金水给队友以拉拢支持"
        if can_gold_teammate and (rand_val < 0.4 or not can_accuse_unknown):
            candidates = [t for t in teammates if t != actor_id and t not in my_claimed_checks]
            if candidates:
                target = self.rng.choice(candidates)
                is_wolf = False
        
        # Strategy 2: Accuse Unknown (40%)
        # "查杀一个身份不明的玩家"
        elif can_accuse_unknown and rand_val < 0.8:
            target = self.rng.choice(unknowns)
            is_wolf = True
            
        # Strategy 3: Gold Water Unknown (20%)
        # "或发金水给不明身份玩家（混淆视听）"
        elif can_accuse_unknown:
            target = self.rng.choice(unknowns)
            is_wolf = False
            
        # Fallback: If no unknowns and no unchecked teammates?
        if target == -1:
             # Must check someone. Known Gods? Or Dead people (fake check)?
             # Check a known God as Wolf (last resort)
             candidates = [p.player_id for p in alive if p.player_id != actor_id and p.player_id not in my_claimed_checks]
             if candidates:
                 target = self.rng.choice(candidates)
                 # If they are known good, we must accuse them to have a chance?
                 if target in known_good_identities:
                     is_wolf = True
                 else:
                     is_wolf = True # Aggressive fallback
             else:
                 # Everyone checked?
                 pass

        if target != -1:
            role_str = "狼人" if is_wolf else "好人"
            content = f"我是预言家，昨晚验了 {target} 是 {role_str}"
            checks = {target: is_wolf}
            stmt = Statement(actor_id=actor_id, claimed_role=Role.SEER, claimed_checks=checks, content=content)
            return Action(action_type=ActionType.SPEAK, actor_id=actor_id, statement=stmt)
        else:
             return Action(action_type=ActionType.SPEAK, actor_id=actor_id, statement=Statement(actor_id=actor_id, content="我是预言家，昨晚没验人（出错了）"))

    def update_beliefs(self, state: GameState, statement: Statement):
        # Update trust scores for ALL players based on this statement
        speaker = statement.actor_id
        
        # Initialize trust if empty (0.5 default)
        for p in state.players:
            if p.player_id not in state.private_info: continue
            if speaker not in state.private_info[p.player_id].trust_scores:
                state.private_info[p.player_id].trust_scores[speaker] = 0.5
        
        # 1. If speaker claims Witch and reveals saved person (Silver Water)
        if statement.claimed_role == Role.WITCH:
            # First, update known witches
            for observer in state.players:
                if not observer.alive: continue
                private = state.private_info[observer.player_id]
                if speaker not in private.known_witches:
                    private.known_witches.append(speaker)
            
            # Parse content for "saved X"
            import re
            match = re.search(r"救了\s*(\d+)", statement.content)
            if match:
                saved_target = int(match.group(1))
                
                # Everyone (except Wolves who know truth) should trust the saved person (Silver Water)
                # But only if they trust the Witch claimer?
                # Generally, if someone claims Witch and reports a save that matches the Night history (which they don't know, but they assume), 
                # actually observers don't know who was saved at night.
                # But Silver Water is usually regarded as Good.
                
                for observer in state.players:
                    if not observer.alive: continue
                    observer_id = observer.player_id
                    private = state.private_info[observer_id]
                    
                    # Witch Credibility Logic:
                    # If only one Witch claimer -> High Trust (0.9)
                    # If multiple -> Low Trust (0.4) for all
                    
                    is_believed_witch = False
                    if len(private.known_witches) == 1 and private.known_witches[0] == speaker:
                        is_believed_witch = True
                        private.trust_scores[speaker] = 0.9
                    else:
                        # Conflict
                        for w in private.known_witches:
                            private.trust_scores[w] = 0.4
                    
                    # If I am Wolf, I know if target is good or bad (usually good if Wolves killed them).
                    # If I am Good, I should trust the Silver Water highly.
                    if observer.role != Role.WOLF:
                        if is_believed_witch:
                            # Trust the Silver Water
                            private.trust_scores[saved_target] = 0.9 # Very high trust
                            private.believed_silver_water = saved_target
                            
                            # Also trust the Witch claimer? 
                            # Unless countered by another Witch.
                            # For now, boost Witch trust slightly.
                            if observer_id != speaker:
                                current_witch_trust = private.trust_scores.get(speaker, 0.5)
                                private.trust_scores[speaker] = min(1.0, current_witch_trust + 0.2)

        # If speaker claims Seer


        if statement.claimed_role == Role.SEER:
            for observer in state.players:
                if not observer.alive: continue
                observer_id = observer.player_id
                private = state.private_info[observer_id]
                
                # 1. If I am Seer, Speaker is Wolf (Trust = 0)
                if observer.role == Role.SEER and speaker != observer_id:
                    private.trust_scores[speaker] = 0.0
                    
                # 2. If I am Wolf, I know truth. If Speaker is Wolf teammate, Trust=1. If Good, Trust=0.
                if observer.role == Role.WOLF:
                    if role_of(state, speaker) == Role.WOLF:
                        private.trust_scores[speaker] = 1.0
                    else:
                        private.trust_scores[speaker] = 0.0
                        
                # 3. If I am Villager/Witch/Hunter
                if observer.role in [Role.VILLAGER, Role.WITCH, Role.HUNTER]:
                    # If this is the first Seer claim, tentatively trust (0.6)
                    # If there are multiple Seer claims, reduce trust for all claimants (0.4)
                    
                    # Track known seers
                    if speaker not in private.known_seers:
                        private.known_seers.append(speaker)
                    
                    if len(private.known_seers) == 1:
                        private.trust_scores[speaker] = 0.7 # High trust if only one
                    else:
                        # Conflict! Lower trust for all claimants
                        # But we should try to evaluate based on other info?
                        # For now, default to suspicion for both.
                        for claimer in private.known_seers:
                            private.trust_scores[claimer] = 0.4 # Suspicious
                        
                        # However, if I am Witch, and one of them is my Silver Water, I TRUST HIM.
                        if observer.role == Role.WITCH and private.witch_state.saved_player_id is not None:
                            saved = private.witch_state.saved_player_id
                            if saved in private.known_seers:
                                private.trust_scores[saved] = 0.9 # Trust Silver Water
                                # Distrust the other(s)
                                for claimer in private.known_seers:
                                    if claimer != saved:
                                        private.trust_scores[claimer] = 0.1 # Fake Seer
                        
                        # GENERAL LOGIC: If a Seer candidate checked a known "Silver Water" as Good (and that Silver Water is not themselves),
                        # and another candidate checked Silver Water as Bad (or didn't check),
                        # Trust the one who confirmed Silver Water.
                        
                        if private.believed_silver_water is not None:
                            silver = private.believed_silver_water
                            for claimer in private.known_seers:
                                # Find claimer's statement
                                for e in reversed(state.public_events):
                                    if e.statement and e.statement.actor_id == claimer and e.statement.claimed_role == Role.SEER:
                                        # Did they check silver?
                                        if silver in e.statement.claimed_checks:
                                            is_wolf = e.statement.claimed_checks[silver]
                                            if not is_wolf:
                                                # Validated Silver Water!
                                                private.trust_scores[claimer] = min(1.0, private.trust_scores.get(claimer, 0.5) + 0.4)
                                            else:
                                                # Accused Silver Water! Fake!
                                                private.trust_scores[claimer] = 0.0
                                        break

                            
                # 4. Check Result Logic
                # If speaker says "X is Wolf" and I know X is Good (e.g. X is me), then Speaker is Wolf.
                for target, is_wolf in statement.claimed_checks.items():
                    if target == observer_id:
                        # He checked me!
                        real_me_is_wolf = (observer.role == Role.WOLF)
                        if is_wolf != real_me_is_wolf:
                            # He lied about me!
                            private.trust_scores[speaker] = 0.0

    def update_trust_after_vote(self, state: GameState, votes: Dict[str, int]):
        # votes is mapping: voter_id_str -> target_id_int
        
        for voter_str, target_id in votes.items():
            voter_id = int(voter_str)
            voter = get_player(state, voter_id)
            
            for observer in state.players:
                if not observer.alive: continue
                observer_id = observer.player_id
                if observer_id == voter_id: continue
                
                private = state.private_info[observer_id]
                trust = private.trust_scores.get(voter_id, 0.5)
                
                # Logic 1: Self-Defense
                # If voter voted for me (observer), I trust them less.
                if target_id == observer_id:
                    # If I am good, they are attacking me.
                    if observer.role != Role.WOLF:
                        trust -= 0.3
                    # If I am Wolf, well, they are still attacking me.
                    else:
                        trust -= 0.1 # Less impact as Wolf knows enemies
                        
                # Logic 2: Voting for known Good/Bad
                # Does observer know target's role?
                target_role_known = None
                
                # If target is observer self, role is known
                if target_id == observer_id:
                    target_role_known = observer.role
                # If observer is Wolf, they know teammates
                elif observer.role == Role.WOLF:
                    target_role_known = role_of(state, target_id)
                # If observer is Seer, they might have checked target
                elif observer.role == Role.SEER:
                    if target_id in private.seer_results:
                        is_wolf = private.seer_results[target_id]
                        target_role_known = Role.WOLF if is_wolf else Role.VILLAGER # Generic Good
                
                # Logic 2.1: Voting for Silver Water (Known Good by Witch)
                if observer.role == Role.WITCH and private.witch_state.saved_player_id == target_id:
                    target_role_known = Role.VILLAGER # Silver Water is Good
                
                # Logic 2.2: Voting for known Silver Water (if revealed)
                # If observer trusts Silver Water, and voter votes FOR Silver Water -> Bad.
                if private.believed_silver_water == target_id:
                    target_role_known = Role.VILLAGER
                
                if target_role_known:
                    if target_role_known == Role.WOLF:
                        # Voter voted for known Wolf -> Voter likely Good
                        trust += 0.1
                    else:
                        # Voter voted for known Good -> Voter likely Bad
                        trust -= 0.2
                
                # Logic 3: Attack on Silver Water (General)
                # If someone votes for the Silver Water (and I know who it is), they are suspicious.
                # Already covered by Logic 2.1 and 2.2 if I know Silver Water.
                
                # Logic 4: Follow the Wolf? (If I know X is Wolf, and X votes Y, Y might be Good)
                # If observer knows voter is Wolf
                voter_role_known = None
                if observer.role == Role.SEER and voter_id in private.seer_results:
                    is_wolf = private.seer_results[voter_id]
                    if is_wolf: voter_role_known = Role.WOLF
                
                if voter_role_known == Role.WOLF:
                    # Wolf voting for someone. Target is likely Good.
                    # Increase trust for target (not voter)
                    target_trust = private.trust_scores.get(target_id, 0.5)
                    target_trust += 0.1
                    private.trust_scores[target_id] = min(1.0, target_trust)

                # Clamp trust
                trust = max(0.0, min(1.0, trust))
                private.trust_scores[voter_id] = trust

    def choose_vote_target(self, state: GameState, actor_id: int) -> int:

        private = state.private_info[actor_id]
        my_role = role_of(state, actor_id)
        
        # 1. Trust known facts (Seer results)
        known_wolves = [pid for pid, is_wolf in private.seer_results.items() if is_wolf and get_player(state, pid).alive]
        if known_wolves:
            return known_wolves[0]
            
        # 2. Witch Special: Do NOT vote for Silver Water (Saved person)
        if my_role == Role.WITCH:
            if private.witch_state.saved_player_id is not None:
                pass 

        # 3. Wolf Strategy: Identity-based voting (Plan A)
        if my_role == Role.WOLF:
            return self._choose_wolf_vote_target(state, actor_id)

        # 4. Stand-side Logic (For Villagers/Hunters/Witch)
        # If there are multiple Seers, pick a side.
        
        # Find alive Seer candidates
        alive_seers = [pid for pid in private.known_seers if get_player(state, pid).alive]
        
        if len(alive_seers) > 1:
            # We have a conflict.
            
            # IMPROVEMENT: Use Silver Water Logic if available
            # If one Seer is Silver Water, Trust Him.
            # If one Seer is accused by Witch, Distrust Him.
            
            trusted_seer = None
            distrusted_seer = None
            
            # Check Believed Silver Water
            if private.believed_silver_water is not None:
                silver = private.believed_silver_water
                if silver in alive_seers:
                    trusted_seer = silver
                
                # Check consistency with Silver Water
                for seer in alive_seers:
                    # If this Seer verified Silver Water as Good, trust them more.
                    # Scan history
                    for e in reversed(state.public_events):
                        if e.statement and e.statement.actor_id == seer and e.statement.claimed_role == Role.SEER:
                            if silver in e.statement.claimed_checks:
                                is_wolf = e.statement.claimed_checks[silver]
                                if not is_wolf:
                                    trusted_seer = seer # Found a logical match
                                    break
                    if trusted_seer: break
            
            if trusted_seer:
                # Vote for the OTHER seer(s)
                targets = [s for s in alive_seers if s != trusted_seer]
                if targets:
                    return targets[0]
            
            # Sort by trust
            alive_seers.sort(key=lambda pid: private.trust_scores.get(pid, 0.5))
            
            # Lowest trust is candidate[0]
            best_seer = alive_seers[-1]
            worst_seer = alive_seers[0]
            
            best_trust = private.trust_scores.get(best_seer, 0.5)
            worst_trust = private.trust_scores.get(worst_seer, 0.5)
            
            # If significant difference, vote the worst one
            if best_trust > 0.6 and worst_trust < 0.4:
                return worst_seer
                
        # 5. Trust scores (For Good Guys)
        # Find alive player with lowest trust score
        candidates = [p.player_id for p in alive_players(state) if p.player_id != actor_id]
        
        # Filter candidates for Witch
        if my_role == Role.WITCH and private.witch_state.saved_player_id is not None:
            if private.witch_state.saved_player_id in candidates:
                candidates.remove(private.witch_state.saved_player_id)
        
        if not candidates: return actor_id
        
        lowest_trust = 1.0
        target = self.rng.choice(candidates) # Default random
        
        for cand in candidates:
            # Default trust is 0.5. If I am Witch, I don't know who is Wolf, so 0.5.
            score = private.trust_scores.get(cand, 0.5)
            
            # Special Logic: Gold Water (Good Guy) should not vote for their Seer?
            # If I am Good, and Seer X checked me as Good. I should trust Seer X more.
            # This is handled in update_beliefs (trust Seer who checked me).
            # But here, if I trust someone highly (score > 0.8), I should NOT vote them.
            
            if score < lowest_trust:
                lowest_trust = score
                target = cand
            elif score == lowest_trust:
                if self.rng.random() < 0.5:
                    target = cand
                    
        return target





    def choose_hunter_shot(self, state: GameState, actor_id: int) -> Optional[int]:
        candidates = [p.player_id for p in alive_players(state) if p.player_id != actor_id]
        if not candidates:
            return None
        return self.rng.choice(candidates)

    def recommend_action(self, state: GameState, actor_id: int) -> Action:
        # Deprecated: alias for backward compatibility or direct action use
        return self.recommend(state, actor_id).action

