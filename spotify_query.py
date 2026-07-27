# spotify_query.py

LANGUAGE_TAGS = {
    "malayalam": ["malayalam", "mollywood"],
    "tamil": ["tamil", "kollywood"],
    "hindi": ["hindi", "bollywood"],
    "telugu": ["telugu", "tollywood"],
    "english": ["pop"],
}

MOOD_KEYWORDS = {
    "Calm": ["melody", "calm", "soothing", "acoustic"],
    "Neutral": ["hits", "popular"],
    "Happy": ["happy", "feel good", "cheerful"],
    "Energised": ["party", "dance", "upbeat"],
}

CURRENT_MOOD_KEYWORDS = {
    "Sad": ["sad", "emotional", "heartbreak"],
    "Stressed": ["chill", "relaxing"],
    "Anxious": ["calm", "peaceful"],
    "Neutral": ["light"],
    "Happy": ["cheerful"],
    "Energised": ["high energy"],
}

def build_queries_for_languages(
    target_mood: str,
    intensity: int,
    languages: list[str],
    current_mood: str = "Neutral",
) -> list[str]:

    target_mood = (target_mood or "Neutral").strip().title()
    current_mood = (current_mood or "Neutral").strip().title()
    intensity = max(0, min(int(intensity), 100))

    base_mood_terms = MOOD_KEYWORDS.get(target_mood, MOOD_KEYWORDS["Neutral"])
    current_terms = CURRENT_MOOD_KEYWORDS.get(current_mood, ["hits"])

    # If very intense negative mood, push calmer keywords
    strong_negative = (current_mood in {"Sad", "Stressed", "Anxious"} and intensity >= 70)
    if strong_negative:
        target_mood = "Calm"  # force calmer search intent

    queries: list[str] = []

    for lang in languages:
        lk = (lang or "").strip().lower()
        tags = LANGUAGE_TAGS.get(lk, [lk])

        # ---------------- Indian languages ----------------
        if lk in {"malayalam", "tamil", "hindi", "telugu"}:
            main_tag = tags[0]  # tamil/malayalam/...
            industry = tags[1] if len(tags) > 1 else main_tag

            # ✅ CALM MODE: avoid "hit songs" (brings energetic/trending)
            if target_mood == "Calm":
                # Make queries playlist-search friendly and calm-specific
                queries.append(f"{main_tag} melody songs")
                queries.append(f"{main_tag} sad melody songs")
                queries.append(f"{main_tag} acoustic songs")
                queries.append(f"{main_tag} love melody songs")

                # optional: industry-based but still calm (not hits)
                queries.append(f"{industry} melody songs")

            # ✅ HAPPY MODE: balanced (not too generic)
            elif target_mood == "Happy":
                queries.append(f"{main_tag} feel good songs")
                queries.append(f"{main_tag} happy songs")
                queries.append(f"{industry} feel good songs")

            # ✅ ENERGISED MODE: ok to use hits/party
            elif target_mood == "Energised":
                queries.append(f"{main_tag} dance songs")
                queries.append(f"{main_tag} happy songs")
                queries.append(f"{industry} mass songs")

            # ✅ NEUTRAL MODE: general popular / hits
            else:
                queries.append(f"{main_tag} movie songs")
                queries.append(f"{main_tag} popular songs")
                queries.append(f"{industry} hit songs")

        # ---------------- English ----------------
        else:
            # keep queries short; filtering later will catch non-English tracks
            if target_mood == "Calm":
                queries.append("english calm pop")
                queries.append("english acoustic pop")
                queries.append("english soft pop")
                queries.append("english sad pop")
            elif target_mood == "Happy":
                queries.append("english happy pop")
                queries.append("english feel good pop")
                queries.append("english cheerful pop")
            elif target_mood == "Energised":
                queries.append("english party pop")
                queries.append("english dance pop")
                queries.append("english workout pop")
            else:
                queries.append("english popular pop")
                queries.append("english top pop")

    # Remove duplicates but keep order
    seen = set()
    out = []
    for q in queries:
        q2 = " ".join(q.split()).strip().lower()
        if q2 and q2 not in seen:
            seen.add(q2)
            out.append(q)

    return out