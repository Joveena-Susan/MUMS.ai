from email.mime import text
from transformers import pipeline

classifier = pipeline(
    "text-classification", # type: ignore
    model="j-hartmann/emotion-english-distilroberta-base",
    top_k=None
)

mood_mapping = {
    "sadness": "Sad",
    "anger": "Stressed",
    "fear": "Anxious",
    "joy": "Happy",
    "neutral": "Neutral",
    "surprise": "Energised",
    "disgust": "Stressed" 
}

def detect_mood(text):
    text = text.strip()

    if len(text) < 5:
        return {"mood": "Neutral", "intensity": 30}

    outputs = classifier(text)[0]
    outputs = sorted(outputs, key=lambda x: x["score"], reverse=True) # type: ignore

    primary = outputs[0]
    label = primary["label"]  # type: ignore
    score = primary["score"] # type: ignore

    # If confidence is low, treat as Neutral (safe)
    if score < 0.4: # type: ignore
        mood = "Neutral"
        intensity = 40
    else:
        # Map model label into one of your 6 moods (no crashes)
        mood = mood_mapping.get(label, "Neutral")
        intensity = int(score * 100)

    lower = text.lower()
    # ✅ Energetic override
    energetic_phrases = [
        "excited", "pumped", "energetic", "hyped", "full of energy", 
        "let's go", "lets go", "energised", "active", "lively", 
        "vitality", "on top of the world", "unstoppable", "productive",
        "adrenaline", "rushing", "pumping", "can't sit still", "cant sit still"
    ]
    if any(p in lower for p in energetic_phrases):
        mood = "Energised"
        intensity = max(intensity, 80)

    # ✅ Sad override (Breakups, etc.)
    sad_phrases = ["breakup", "thinking about her", "thinking about him", "heartbroken", "not okay", "not ok"]
    if any(p in lower for p in sad_phrases):
        mood = "Sad"
        intensity = max(intensity, 70)

    # ✅ Neutral override for "mild/okay" statements
    ok_phrases = [
        "it's okay", "its okay", "i'm okay", "im okay", "am okay", "not bad", "fine",
        "not great but", "not the best but", "not terrible", "could be worse",
        "not the worst"
    ]
    # Ensure it's not a negated okay like "not okay" unless it's "not bad"
    is_ok = any(p in lower for p in ok_phrases) and "not okay" not in lower and "not ok" not in lower
    if is_ok:
        mood = "Neutral"
        intensity = min(intensity, 55)


    import re
    fb_match = re.search(r'i feel (sad|neutral|better|happy|energised) with intensity (\d+)', lower)
    if fb_match:
        base_mood = fb_match.group(1)
        val = int(fb_match.group(2)) * 10
        
        mapping = {
            "sad": "Sad",
            "neutral": "Neutral",
            "better": "Happy",
            "happy": "Happy",
            "energised": "Energised"
        }
        mood = mapping.get(base_mood, "Neutral")
        intensity = val

    # Clamp intensity (Neutral shouldn't be extremely high)
    if mood == "Neutral":
        intensity = max(30, min(intensity, 60))
    else:
        intensity = max(30, min(intensity, 90))

    return {"mood": mood, "intensity": intensity}

'''if __name__ == "__main__":
    text = input("Enter how you feel today:\n> ")
    result = detect_mood(text)

    print("\nDetected Mood:")
    print(result)'''
