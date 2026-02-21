from typing import List, Dict
import os
from datetime import datetime
from .models import GameState, Role

class GameLogger:
    @staticmethod
    def format_log(state: GameState, history: List[Dict]) -> str:
        lines = []
        lines.append("=" * 50)
        lines.append(f"Werewolf Game Log - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 50)
        lines.append("\n[Player Configuration]")
        
        # Sort players by ID
        sorted_players = sorted(state.players, key=lambda p: p.player_id)
        for p in sorted_players:
            lines.append(f"Player {p.player_id}: {p.role.value}")
            
        lines.append("\n" + "=" * 50)
        lines.append("[Game Events]")
        lines.append("=" * 50)
        
        for i, event in enumerate(history):
            day = event['day']
            phase = event['phase']
            desc = event['description']
            actor = event['actor_id']
            target = event['target_id']
            stmt = event.get('statement')
            votes = event.get('votes')
            reasons = event.get('vote_reasons')
            
            lines.append(f"\nStep {i+1}: Day {day} - {phase}")
            lines.append(f"Event: {desc}")
            
            if actor is not None:
                lines.append(f"  Actor: Player {actor}")
            if target is not None:
                lines.append(f"  Target: Player {target}")
                
            if stmt:
                lines.append(f"  Statement: \"{stmt['content']}\"")
                if stmt['claimed_role']:
                    lines.append(f"  Claimed Role: {stmt['claimed_role']}")
            
            if votes:
                lines.append("  Votes:")
                # Invert votes: Target -> [Voters]
                vote_map = {}
                for voter, tgt in votes.items():
                    if tgt not in vote_map: vote_map[tgt] = []
                    vote_map[tgt].append(voter)
                
                for tgt, voters in vote_map.items():
                    voter_list = ", ".join(voters)
                    lines.append(f"    Target Player {tgt} received {len(voters)} votes from: {voter_list}")
                    
            if reasons:
                lines.append("  Vote Reasons:")
                for voter, reason in reasons.items():
                    lines.append(f"    Player {voter}: {reason}")
                    
        lines.append("\n" + "=" * 50)
        lines.append(f"Game Over. Winner: {state.winner.value if state.winner else 'None'}")
        lines.append("=" * 50)
        
        return "\n".join(lines)

    @staticmethod
    def save_log(state: GameState, history: List[Dict], filename: str = None) -> str:
        if filename is None:
            # Ensure logs directory exists
            log_dir = "game_logs"
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = os.path.join(log_dir, f"game_{timestamp}.txt")
            
        content = GameLogger.format_log(state, history)
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
            
        return filename
