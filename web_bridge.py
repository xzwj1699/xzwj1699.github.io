import json
import random
from werewolf.engine import GameEngine, create_default_game
from werewolf.simulator import GameSimulator
from werewolf.models import Role, Phase

# Global state
class GameStore:
    def __init__(self):
        self.simulator = None
        self.game_history = []
        self.roles = {}

store = GameStore()

def new_game(seed, player_count):
    try:
        seed = int(seed) if seed is not None else random.randint(0, 10000)
        player_count = int(player_count)
        
        state, rng = create_default_game(seed, player_count)
        
        # Reconstruct engine
        roles = {p.player_id: p.role for p in state.players}
        engine = GameEngine(roles, config=state.config)
        engine.rng = rng
        engine.state = state
        
        store.simulator = GameSimulator(engine)
        random.seed(seed)
        store.simulator.run()
        
        store.game_history = store.simulator.history
        store.roles = {pid: role.value for pid, role in roles.items()}
        
        winner = store.simulator.engine.state.winner.value if store.simulator.engine.state.winner else None
        
        return {
            "seed": seed,
            "total_steps": len(store.game_history),
            "roles": store.roles,
            "winner": winner
        }
    except Exception as e:
        return {"error": str(e)}

def get_game_step(step_index, view_player_id=None):
    try:
        step_index = int(step_index)
        if not store.simulator or not store.game_history:
            return {"error": "Game not initialized"}
            
        if step_index < 0 or step_index >= len(store.game_history):
            return {"error": "Step index out of range"}
            
        current_event = store.game_history[step_index]
        
        # Calculate alive status
        player_states = {pid: {"alive": True, "death_reason": None, "tags": []} for pid in store.roles.keys()}
        
        for i in range(step_index + 1):
            evt = store.game_history[i]
            # Check for death events
            if evt.get('target_id') is not None:
                tid = evt['target_id']
                desc = evt.get('description', '')
                
                reason = None
                if desc == "猎人开枪":
                    reason = "HUNTER"
                elif desc.startswith("投票结果：放逐玩家") or desc == "放逐了玩家":
                    reason = "VOTE"
                elif desc == "夜晚击杀生效":
                    reason = "WOLF"
                elif desc == "女巫使用了毒药":
                    reason = "WITCH"
                
                if reason:
                    # In history, target_id is int
                    # player_states keys are int
                    if tid in player_states:
                        player_states[tid]["alive"] = False
                        player_states[tid]["death_reason"] = reason
            
            # Check for Claims
            stmt = evt.get('statement')
            if stmt:
                actor_id = stmt.get('actor_id')
                
                claimed_role = stmt.get('claimed_role')
                claimed_checks = stmt.get('claimed_checks', {})
                content = stmt.get('content', "")
                
                # Enum handling if needed (unlikely if history is serialized, but safe to check)
                if isinstance(claimed_role, dict):
                     claimed_role = claimed_role.get('value', claimed_role)
                elif hasattr(claimed_role, 'value'):
                     claimed_role = claimed_role.value

                # Seer Claims
                if claimed_role == "SEER" and claimed_checks:
                    for target, is_wolf in claimed_checks.items():
                        tag_type = "查杀" if is_wolf else "金水"
                        tag = f"{tag_type}({actor_id})"
                        target_id = int(target)
                        if target_id in player_states and tag not in player_states[target_id]["tags"]:
                            player_states[target_id]["tags"].append(tag)
                
                # Witch Claims
                if claimed_role == "WITCH":
                    import re
                    match_save = re.search(r"救了\s*(\d+)", content)
                    if match_save:
                        target = int(match_save.group(1))
                        tag = f"银水({actor_id})"
                        if target in player_states and tag not in player_states[target]["tags"]:
                            player_states[target]["tags"].append(tag)
        
        # Determine visibility
        visible_event = filter_event_for_player(current_event, view_player_id)
        
        # Filter roles based on view
        visible_roles = {}
        if view_player_id is None or view_player_id == -1:
            visible_roles = store.roles
        else:
            visible_roles[view_player_id] = store.roles[view_player_id]
            my_role = store.roles[view_player_id]
            if my_role == Role.WOLF.value:
                for pid, role in store.roles.items():
                    if role == Role.WOLF.value:
                        visible_roles[pid] = role
            
        return {
            "step_index": step_index,
            "event": visible_event,
            "total_steps": len(store.game_history),
            "roles": visible_roles,
            "player_states": player_states
        }
    except Exception as e:
        return {"error": str(e)}

def filter_event_for_player(event, player_id):
    if player_id is None or player_id == -1:
        return event
        
    phase = event.get('phase')
    actor = event.get('actor_id')
    
    is_visible = False
    
    # Public phases
    if phase in [Phase.DAY_VOTE.value, Phase.DAY_DISCUSS.value, Phase.GAME_OVER.value]:
        is_visible = True
    elif actor == player_id:
        is_visible = True
    else:
        my_role = store.roles.get(player_id)
        actor_role = store.roles.get(actor) if actor is not None else None
        if my_role == Role.WOLF.value and actor_role == Role.WOLF.value:
            is_visible = True

    if not is_visible:
         return {
            "day": event["day"],
            "phase": phase,
            "description": "夜晚发生了某些事情...",
            "actor_id": None,
            "target_id": None,
            "is_hidden": True,
            "recommendation": None
        }

    rec = None
    if event.get('recommendation'):
        if player_id is None or player_id == -1 or actor == player_id:
            rec = event['recommendation']

    return {
        "day": event["day"],
        "phase": event["phase"],
        "description": event["description"],
        "actor_id": event["actor_id"],
        "target_id": event["target_id"],
        "is_hidden": False,
        "recommendation": rec,
        "statement": event.get('statement'),
        "trust_scores": event.get('trust_scores'),
        "votes": event.get('votes')
    }
