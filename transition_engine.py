# transition_engine.py

TRANSITION_NEXT = {
    "Sad": "Calm",
    "Stressed": "Calm",
    "Anxious": "Calm",
    "Calm": "Neutral",
    "Neutral": "Happy",
    "Happy": "Energised",
    "Energised": "Energised"
}

def get_target_mood(current_mood: str, intensity: int) -> str:
    # safety defaults
    current_mood = (current_mood or "Neutral").strip().title()
    if current_mood not in TRANSITION_NEXT:
        current_mood = "Neutral"

    # slow transition if intensity is high (one step)
    target = TRANSITION_NEXT[current_mood]

    # faster transition if intensity is low (two steps), but only for negative moods
    # jumping from Neutral directly to Energised is too jarring.
    negative_moods = ["Sad", "Stressed", "Anxious", "Calm"]
    if intensity < 50 and current_mood in negative_moods:
        target = TRANSITION_NEXT.get(target, target)

    return target
