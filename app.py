from flask import Flask, request, jsonify
from dotenv import load_dotenv
from flask_cors import CORS
import os
import requests
from datetime import datetime, timezone, timedelta
from google import genai
from google.genai import errors

from mood_detector import detect_mood
from transition_engine import get_target_mood
from spotify_query import build_queries_for_languages
from spotify_client import recommend_continuous_from_playlists, is_track_in_language, search_spotify_tracks_multi

from models import db, User, Session, SongPlayed, MoodTransition, Preference, SongPlayLog, MoodSessionLog

load_dotenv()

# Configure Gemini
_gemini_client = None
_gemini_key = os.getenv("GEMINI_API_KEY", "")
if _gemini_key:
    _gemini_client = genai.Client(api_key=_gemini_key)

app = Flask(__name__)
basedir = os.path.abspath(os.path.dirname(__file__))
instance_path = os.path.join(basedir, 'instance')
if not os.path.exists(instance_path):
    os.makedirs(instance_path)

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(instance_path, 'mooduplift.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

with app.app_context():
    db.create_all()

CORS(app)  # allow browser requests (dev)

# Auth Routes
@app.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    password = data.get("password")
    name = data.get("name")
    
    if not email or not password or not name:
        return jsonify({"error": "email, password, and name are required"}), 400
        
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "User already exists"}), 400
        
    user = User(
        email=email,
        name=name,
        dob=data.get("dob"),
        age=data.get("age"),
        gender=data.get("gender")
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    
    return jsonify({"message": "User registered successfully", "user": {"email": email, "name": name}}), 201

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    password = data.get("password")
    
    if not email or not password:
        return jsonify({"error": "email and password are required"}), 400
        
    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        return jsonify({"error": "Invalid email or password"}), 401

    # Log user login to admin activity
    try:
        from models import AdminLog as _AdminLog
        log = _AdminLog(action="user_login", detail=f"User {email} logged in",
                        ip_address=request.remote_addr)
        db.session.add(log)
        db.session.commit()
    except Exception:
        pass
        
    return jsonify({
        "message": "Login successful",
        "user": {
            "email": user.email,
            "name": user.name,
            "dob": user.dob,
            "age": user.age,
            "gender": user.gender
        }
    }), 200

# Sync Routes
@app.route("/sync-history", methods=["POST"])
def sync_history():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    history = data.get("history") or []
    
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
        
    for s in user.sessions:
        db.session.delete(s)
        
    for item in history:
        new_session = Session(
            user_id=user.id,
            date_str=item.get("date"),
            start_mood=item.get("start_mood"),
            target_mood=item.get("target_mood"),
            end_mood=item.get("end_mood"),
            intensity=item.get("intensity"),
            duration=item.get("duration"),
            intensities_raw=",".join(map(str, item.get("intensities") or [])),
            is_live=item.get("isLive", False)
        )
        db.session.add(new_session)
        db.session.flush()
        
        for s in item.get("songs") or []:
            db.session.add(SongPlayed(
                session_id=new_session.id,
                title=s.get("title"),
                artist=s.get("artist"),
                youtube_search_query=s.get("youtube_search_query"),
                played_in_mood=s.get("played_in_mood")
            ))
            
        for t in item.get("transitions") or []:
            db.session.add(MoodTransition(
                session_id=new_session.id,
                from_mood=t.get("from"),
                to_mood=t.get("to"),
                time_str=t.get("time"),
                intensity=t.get("intensity")
            ))
            
    db.session.commit()
    return jsonify({"message": "History synced successfully"}), 200

@app.route("/get-history", methods=["POST"])
def get_history_api():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
        
    history = []
    for s in user.sessions:
        history.append({
            "date": s.date_str,
            "start_mood": s.start_mood,
            "target_mood": s.target_mood,
            "end_mood": s.end_mood,
            "intensity": s.intensity,
            "duration": s.duration,
            "intensities": [int(x) for x in s.intensities_raw.split(",")] if s.intensities_raw else [],
            "isLive": s.is_live,
            "songs": [{
                "title": sp.title,
                "artist": sp.artist,
                "youtube_search_query": sp.youtube_search_query,
                "played_in_mood": sp.played_in_mood
            } for sp in s.songs_played],
            "transitions": [{
                "from": mt.from_mood,
                "to": mt.to_mood,
                "time": mt.time_str,
                "intensity": mt.intensity
            } for mt in s.transitions]
        })
        
    return jsonify({"history": history}), 200

@app.route("/sync-preferences", methods=["POST"])
def sync_preferences():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    blocked = data.get("blocked") or []
    liked = data.get("liked") or []
    
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
        
    Preference.query.filter_by(user_id=user.id).delete()
    
    for b in blocked:
        db.session.add(Preference(user_id=user.id, title=b.get("title"), artist=b.get("artist"), pref_type='block'))
    for l in liked:
        db.session.add(Preference(user_id=user.id, title=l.get("title"), artist=l.get("artist"), pref_type='like'))
        
    db.session.commit()
    return jsonify({"message": "Preferences synced successfully"}), 200

@app.route("/get-preferences", methods=["POST"])
def get_preferences_api():
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
        
    blocked = [{"title": p.title, "artist": p.artist} for p in user.preferences if p.pref_type == 'block']
    liked = [{"title": p.title, "artist": p.artist} for p in user.preferences if p.pref_type == 'like']
    
    return jsonify({"blocked": blocked, "liked": liked}), 200

# ✅ Add this helper BELOW app = Flask(__name__)
def _song_key(title: str, artist: str) -> tuple[str, str]:
    return (title.strip().lower(), artist.strip().lower())


@app.route("/youtube-search", methods=["POST"])
def youtube_search_api():
    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400

    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        return jsonify({"error": "YOUTUBE_API_KEY missing in .env"}), 500

    # 1) Search multiple results, prefer embeddable/syndicated
    search_url = "https://www.googleapis.com/youtube/v3/search"
    search_params = {
        "part": "snippet",
        "type": "video",
        "maxResults": 8,  # fetch more to filter
        "q": query,
        "key": api_key,
        "safeSearch": "none",
        "videoEmbeddable": "true",
        "videoSyndicated": "true"
    }

    sr = requests.get(search_url, params=search_params, timeout=10)
    if sr.status_code != 200:
        return jsonify({"error": "YouTube search failed", "details": sr.text}), 502

    items = (sr.json().get("items") or [])
    if not items:
        return jsonify({"videoId": None, "query": query, "reason": "no_results"}), 200

    # 2) Heuristic filter: avoid edits/shorts/etc.
    bad_words = [
        "edit", "status", "whatsapp", "shorts", "reel", "amv",
        "slowed", "reverb", "sped up", "8d", "nightcore", "remix",
        "cover", "karaoke", "mashup"
    ]

    def looks_bad(title: str) -> bool:
        t = (title or "").lower()
        return any(w in t for w in bad_words)

    candidates = []
    for it in items:
        vid = ((it.get("id") or {}).get("videoId"))
        title = ((it.get("snippet") or {}).get("title") or "")
        if not vid:
            continue
        if looks_bad(title):
            continue
        candidates.append(vid)

    # fallback: if everything filtered out, use raw list
    if not candidates:
        candidates = [((it.get("id") or {}).get("videoId")) for it in items if (it.get("id") or {}).get("videoId")]

    # 3) Validate embeddable + public using Videos API
    videos_url = "https://www.googleapis.com/youtube/v3/videos"
    vids = ",".join(candidates[:10]) # type: ignore
    vr = requests.get(videos_url, params={
        "part": "status,snippet,contentDetails",
        "id": vids,
        "key": api_key
    }, timeout=10)

    if vr.status_code != 200:
        # if validation fails, just return first candidate
        return jsonify({"videoId": candidates[0], "query": query, "note": "validation_failed"}), 200

    vitems = vr.json().get("items") or []

    USER_REGION = "IN"  # change if needed
    for v in vitems:
        status = v.get("status") or {}
        if status.get("privacyStatus") != "public":
            continue
        if status.get("embeddable") is not True:
            continue

        cd = v.get("contentDetails") or {}
        rr = cd.get("regionRestriction") or {}
        blocked = set(rr.get("blocked") or [])
        allowed = set(rr.get("allowed") or [])

        # If allowed list exists and user's region isn't in it, skip
        if allowed and USER_REGION not in allowed:
            continue
        # If blocked list contains user's region, skip
        if USER_REGION in blocked:
            continue

        return jsonify({"videoId": v.get("id"), "query": query}), 200

    # if none embeddable/public, return first candidate anyway
    return jsonify({"videoId": candidates[0] if candidates else None, "query": query, "reason": "no_embeddable_found"}), 200




@app.route("/detect-mood", methods=["POST"])
def detect_mood_api():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()

    if not text:
        return jsonify({"error": "text is required"}), 400

    result = detect_mood(text)
    return jsonify(result)


@app.route("/get-song", methods=["POST"])
def get_song_api():
    data = request.get_json(silent=True) or {}

    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "text is required"}), 400

    # languages list (optional)
    languages = data.get("languages")
    if not isinstance(languages, list) or not languages:
        languages = ["malayalam", "hindi", "tamil", "telugu", "english"]
    else:
        languages = [str(x).strip().lower() for x in languages if str(x).strip()]

    # ✅ always return 10 songs (minimum)
    limit = int(data.get("limit", 10) or 10)
    limit = max(limit, 10)
    limit = min(limit, 200)

    # ✅ Parse blocked list (songs user skipped/disliked)
    blocked = data.get("blocked") or []
    blocked_set = set()
    if isinstance(blocked, list):
        for item in blocked:
            if isinstance(item, dict):
                bt = item.get("title", "")
                ba = item.get("artist", "")
                if bt and ba:
                    blocked_set.add(_song_key(bt, ba))

    # ✅ Parse liked list (songs user liked)
    liked = data.get("liked") or []
    liked_set = set()
    if isinstance(liked, list):
        for item in liked:
            if isinstance(item, dict):
                lt = item.get("title", "")
                la = item.get("artist", "")
                if lt and la:
                    liked_set.add(_song_key(lt, la))


    state = detect_mood(text)
    current_mood = state.get("mood", "Neutral")
    intensity = int(state.get("intensity", 40))

    # ✅ Build played_set from database (server-side) using email + detected mood
    # This ONLY excludes songs that were ACTUALLY played (skipped songs are allowed to replay)
    email = (data.get("email") or "").strip().lower()
    played_set = set()
    if email:
        user_obj = User.query.filter_by(email=email).first()
        if user_obj:
            # Normalize mood string matching for the query
            logs = SongPlayLog.query.filter_by(
                user_id=user_obj.id, 
                mood=current_mood.strip(), 
                action='played'
            ).all()
            for log in logs:
                played_set.add(_song_key(log.title, log.artist))

    # 2) transition engine
    target_mood = get_target_mood(current_mood, intensity)

    # 3) build multi-language queries
    queries = build_queries_for_languages(target_mood, intensity, languages, current_mood=current_mood)

    # 4) spotify search (merged)
    try:
        tracks = recommend_continuous_from_playlists(
            queries,
            playlists_per_query=20,
            final_limit=100,
            market="IN"
        )
    except Exception as e:
        print(f"DEBUG: Spotify error, using fallbacks. Error: {e}")
        # High-quality fallback songs (varied moods)
        tracks = [
            {"title": "Levitating", "artist": "Dua Lipa", "popularity": 90, "spotify_url": ""},
            {"title": "Blinding Lights", "artist": "The Weeknd", "popularity": 95, "spotify_url": ""},
            {"title": "Sunflower", "artist": "Post Malone", "popularity": 88, "spotify_url": ""},
            {"title": "Stay", "artist": "The Kid LAROI", "popularity": 92, "spotify_url": ""},
            {"title": "Heat Waves", "artist": "Glass Animals", "popularity": 91, "spotify_url": ""},
        ]

    # ✅ fallback top-up if playlists give too few
    if len(tracks) < limit:
        try:
            more = search_spotify_tracks_multi(queries, per_query_limit=50)
            seen_keys = {(t["title"].strip().lower(), t["artist"].strip().lower()) for t in tracks}
            for t in more:
                k = (t["title"].strip().lower(), t["artist"].strip().lower())
                if k in seen_keys:
                    continue
                tracks.append(t)
                seen_keys.add(k)
                if len(tracks) >= limit:
                    break
        except Exception as e:
            print(f"DEBUG: Secondary search failed, proceeding with current tracks. Error: {e}")

    # ✅ This ensures pick_index actually moves through unique songs.
    #filtered_tracks = []
    songs = []
    seen = set()
    for t in tracks:
        k = _song_key(t["title"], t["artist"])
        if k in blocked_set:
            continue
        if k in seen:
            continue
        # ✅ Skip songs played/skipped previously for this same mood,
        # UNLESS the song is liked (exception for liked songs)
        if k in played_set and k not in liked_set:
            continue
        seen.add(k)
        #filtered_tracks.append(t)

        '''# Pick 1 best song'''
        '''if filtered_tracks:
        # Automatically pick based on how many songs the user already blocked
            pick_index = len(blocked_set)
        # Keep index within available range
            pick_index = min(pick_index, len(filtered_tracks) - 1)
            best = filtered_tracks[pick_index]
        else:
            best = {"title": "Let It Be", "artist": "The Beatles"}'''

        requested_lang = languages[0] if languages else ""

        title = t["title"]
        artist = t["artist"]

        # ✅ filter by chosen language
        if requested_lang and not is_track_in_language(title, artist, requested_lang):
            continue

        songs.append({
            "title": title,
            "artist": artist,
            "youtube_search_query": f"{title} {artist} audio"
        })

        if len(songs) >= limit:
            break


    return jsonify({
        "blocked_count": len(blocked_set),
        "current_mood": current_mood,
        "intensity": intensity,
        "languages": languages,
        "spotify_queries": queries,
        "target_mood": target_mood,
        "songs": songs
    })

@app.route("/log-song", methods=["POST"])
def log_song():
    """Log a played or skipped song for the current user and mood."""
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    mood = (data.get("mood") or "Neutral").strip()
    title = data.get("title")
    artist = data.get("artist")
    action = data.get("action")  # 'played' or 'skipped'

    if not all([email, mood, title, artist, action]):
        return jsonify({"error": "email, mood, title, artist, and action are required"}), 400
    if action not in ("played", "skipped"):
        return jsonify({"error": "action must be 'played' or 'skipped'"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Avoid duplicate log entries for the same song+mood+action
    existing = SongPlayLog.query.filter_by(
        user_id=user.id, mood=mood, title=title, artist=artist
    ).first()
    if existing:
        # Update action if it changed (e.g., was skipped, now played)
        existing.action = action
    else:
        db.session.add(SongPlayLog(
            user_id=user.id,
            mood=mood,
            title=title,
            artist=artist,
            action=action
        ))
    db.session.commit()
    return jsonify({"message": "Song logged successfully"}), 200


@app.route("/get-played-songs", methods=["POST"])
def get_played_songs():
    """Return all played/skipped songs for a given user and mood."""
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    mood = data.get("mood")

    if not email or not mood:
        return jsonify({"error": "email and mood are required"}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    logs = SongPlayLog.query.filter_by(user_id=user.id, mood=mood).all()
    return jsonify({
        "played": [
            {"title": l.title, "artist": l.artist, "action": l.action}
            for l in logs
        ]
    }), 200


@app.route("/clear-played-songs", methods=["POST"])
def clear_played_songs():
    """Delete all played/skipped song logs for a given user (used by 'Clear Played History' button)."""
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    if not email:
        return jsonify({"error": "email is required"}), 400
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
    SongPlayLog.query.filter_by(user_id=user.id).delete()
    db.session.commit()
    return jsonify({"message": "Played song history cleared"}), 200

@app.route("/unlog-songs", methods=["POST"])
def unlog_songs():
    """Remove specific songs from SongPlayLog so they can be recommended again."""
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    songs = data.get("songs") or []
    
    if not email:
        return jsonify({"error": "email is required"}), 400
        
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404
        
    count = 0
    for s in songs:
        title = s.get("title")
        artist = s.get("artist")
        if title and artist:
            deleted = SongPlayLog.query.filter_by(
                user_id=user.id, title=title, artist=artist
            ).delete()
            count += deleted
            
    db.session.commit()
    return jsonify({"message": f"{count} song logs removed"}), 200

# ── AI Personalization Routes ──────────────────────────────────────────────────

@app.route("/log-session-outcome", methods=["POST"])
def log_session_outcome():
    """Log rich session behavior data used by the AI insights engine.
    Called from the Flutter app when a session ends (finalizeLiveSession)."""
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    if not email:
        return jsonify({"error": "email is required"}), 400
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Parse session_date from ISO string or default to now
    raw_date = data.get("session_date")
    try:
        session_date = datetime.fromisoformat(raw_date) if raw_date else datetime.utcnow()
    except Exception:
        session_date = datetime.utcnow()

    log = MoodSessionLog(
        user_id=user.id,
        session_date=session_date,
        start_mood=data.get("start_mood", ""),
        end_mood=data.get("end_mood"),
        start_intensity=data.get("start_intensity"),
        end_intensity=data.get("end_intensity"),
        songs_played_count=int(data.get("songs_played_count", 0)),
        songs_skipped_count=int(data.get("songs_skipped_count", 0)),
        liked_songs_count=int(data.get("liked_songs_count", 0)),
        mood_improved=data.get("mood_improved"),
        session_duration_secs=int(data.get("session_duration_secs", 0)),
    )
    db.session.add(log)
    db.session.commit()
    return jsonify({"message": "Session outcome logged"}), 200


@app.route("/get-ai-insights", methods=["POST"])
def get_ai_insights():
    """Generate AI-powered emotional insights for a user.
    Queries MoodSessionLog, SongPlayLog, and Preference tables,
    then calls Google Gemini to produce personalised natural-language insights."""
    data = request.get_json(silent=True) or {}
    email = data.get("email")
    if not email:
        return jsonify({"error": "email is required"}), 400
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    # ── Gather session behavioral data ──
    logs = MoodSessionLog.query.filter_by(user_id=user.id).order_by(
        MoodSessionLog.session_date.desc()
    ).all()

    if not logs:
        return jsonify({"insights": [
            "Start a few sessions so I can learn your mood patterns! 🎵"
        ]}), 200

    # ── Aggregate patterns ──
    total_sessions = len(logs)
    improved_count = sum(1 for l in logs if l.mood_improved is True)
    not_improved_count = sum(1 for l in logs if l.mood_improved is False)
    avg_skips = round(sum(l.songs_skipped_count for l in logs) / total_sessions, 1)
    avg_plays = round(sum(l.songs_played_count for l in logs) / total_sessions, 1)
    avg_likes = round(sum(l.liked_songs_count for l in logs) / total_sessions, 1)

    # Time-of-day buckets
    time_buckets = {"morning": 0, "afternoon": 0, "evening": 0, "night": 0}
    weekday_mood = {}  # {weekday_name: [start_moods]}
    mood_outcome_map = {}  # {start_mood: {improved: N, not_improved: N}}

    for l in logs:
        h = l.session_date.hour
        if 5 <= h < 12:
            time_buckets["morning"] += 1
        elif 12 <= h < 17:
            time_buckets["afternoon"] += 1
        elif 17 <= h < 21:
            time_buckets["evening"] += 1
        else:
            time_buckets["night"] += 1

        wd = l.session_date.strftime("%A")
        weekday_mood.setdefault(wd, []).append(l.start_mood)

        sm = l.start_mood.lower()
        mood_outcome_map.setdefault(sm, {"improved": 0, "not_improved": 0})
        if l.mood_improved is True:
            mood_outcome_map[sm]["improved"] += 1
        elif l.mood_improved is False:
            mood_outcome_map[sm]["not_improved"] += 1

    peak_time = max(time_buckets, key=time_buckets.get)
    low_moods = ["sad", "stressed", "anxious", "angry"]
    stressed_days = {}
    for day, moods in weekday_mood.items():
        stressed_days[day] = sum(1 for m in moods if m.lower() in low_moods)
    peak_stress_day = max(stressed_days, key=stressed_days.get) if stressed_days else None

    # Song play-log for skip rate per mood
    play_logs = SongPlayLog.query.filter_by(user_id=user.id).all()
    skip_by_mood = {}
    play_by_mood = {}
    for pl in play_logs:
        m = pl.mood.lower()
        if pl.action == "skipped":
            skip_by_mood[m] = skip_by_mood.get(m, 0) + 1
        else:
            play_by_mood[m] = play_by_mood.get(m, 0) + 1

    # Liked / blocked songs for preference hints
    liked = [p for p in Preference.query.filter_by(user_id=user.id, pref_type="like").all()]
    blocked = [p for p in Preference.query.filter_by(user_id=user.id, pref_type="block").all()]

    # ── Build Gemini prompt ──
    summary = f"""You are an empathetic music therapy AI inside a mood-lifting app called MoodUplift.
Analyse the following behavioral data for a user and generate exactly 3-4 SHORT, specific,
personalised emotional insights (1-2 sentences each). Be warm, conversational and insightful.
Use second-person ("You"). Focus on patterns, not individual sessions.
Do NOT make up data not present below. Return insights as a JSON array of strings, nothing else.

Data:
- Total sessions: {total_sessions}
- Sessions where mood improved: {improved_count} / {total_sessions}
- Sessions where mood did NOT improve: {not_improved_count}
- Average songs played per session: {avg_plays}
- Average songs skipped per session: {avg_skips}
- Average songs liked per session: {avg_likes}
- Peak usage time of day: {peak_time}
- Time breakdown: {time_buckets}
- Weekday with most low-mood sessions: {peak_stress_day or 'unknown'}
- Weekday mood data: {dict(list(weekday_mood.items())[:7])}
- Mood outcome rates: {mood_outcome_map}
- Skip counts by mood: {skip_by_mood}
- Play counts by mood: {play_by_mood}
- Liked songs count: {len(liked)}
- Blocked songs count: {len(blocked)}

Return ONLY a JSON array like: ["insight 1", "insight 2", "insight 3"]"""

    # ── Call Gemini ──
    if not _gemini_client:
        # Fallback rule-based insights if no API key
        insights = _rule_based_insights(
            total_sessions, improved_count, peak_time,
            avg_skips, avg_plays, peak_stress_day, mood_outcome_map
        )
        return jsonify({"insights": insights}), 200

    try:
        response = _gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=summary
        )
        text = response.text.strip()
        # Strip potential markdown fences
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        import json as _json
        insights = _json.loads(text.strip())
        if not isinstance(insights, list):
            raise ValueError("Not a list")
    except errors.ClientError as e:
        print(f"Gemini API Quota/Client Error: {e}")
        # Graceful fallback to rule-based insights
        insights = _rule_based_insights(
            total_sessions, improved_count, peak_time,
            avg_skips, avg_plays, peak_stress_day, mood_outcome_map
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        # Graceful fallback
        insights = _rule_based_insights(
            total_sessions, improved_count, peak_time,
            avg_skips, avg_plays, peak_stress_day, mood_outcome_map
        )

    # Log this AI request for admin dashboard
    try:
        from models import AiRequestLog as _AiReqLog
        data = request.get_json(silent=True) or {}
        log = _AiReqLog(
            user_email=data.get("email", ""),
            endpoint="get-ai-insights",
            user_mood="",
            prompt_snippet=summary[:500] if 'summary' in dir() else "",
            response_snippet=str(insights[:2])[:500]
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        pass

    return jsonify({"insights": insights}), 200


def _rule_based_insights(total, improved, peak_time, avg_skips,
                          avg_plays, peak_stress_day, mood_outcome_map):
    """Fallback rule-based insights when Gemini API key is not configured."""
    insights = []
    if total >= 2:
        rate = round((improved / total) * 100)
        insights.append(f"Your mood improved in {rate}% of your sessions — music is clearly working for you! 🎵")
    if peak_time:
        insights.append(f"You most often reach for music in the {peak_time}. That's your power hour. ✨")
    if peak_stress_day:
        insights.append(f"You tend to feel low more often on {peak_stress_day}s. A playlist ready on that day might help.")
    if avg_skips > avg_plays * 0.5:
        insights.append("You skip quite a few songs — your taste is specific. The app is learning your preferences! 🎯")
    elif avg_plays > 2:
        insights.append("You tend to listen to songs all the way through — you're patient with music, and it shows.")

    # Mood-specific hints
    for mood, counts in mood_outcome_map.items():
        if counts["not_improved"] > counts["improved"] and counts["not_improved"] >= 2:
            insights.append(f"When you're {mood}, music sometimes takes longer to lift you. Try starting with calmer songs.")
            break

    return insights[:4] if insights else ["Keep listening — I'm learning your patterns! 🎵"]

# ── Public: Feature Toggles for Flutter app ──────────────────────────────────
@app.route("/get-feature-toggles", methods=["GET", "POST"])
def get_feature_toggles():
    """Public endpoint: Flutter fetches this to know which features are enabled."""
    cfg_path = os.path.join(basedir, "admin_config.json")
    try:
        import json as _jm
        with open(cfg_path, "r") as f:
            cfg = _jm.load(f)
        return jsonify(cfg.get("feature_toggles", {})), 200
    except Exception:
        return jsonify({}), 200

# ── Public: Branding for Flutter app ─────────────────────────────────────────
@app.route("/get-branding", methods=["GET", "POST"])
def get_branding():
    """Public endpoint: Flutter fetches this for app name/tagline."""
    cfg_path = os.path.join(basedir, "admin_config.json")
    try:
        import json as _jm
        with open(cfg_path, "r") as f:
            cfg = _jm.load(f)
        return jsonify(cfg.get("branding", {})), 200
    except Exception:
        return jsonify({}), 200


# ═══════════════════════════════════════════════════════════════════════════════
# ADMIN ROUTES  –  protected by X-Admin-Key header (ADMIN_SECRET_KEY in .env)
# ═══════════════════════════════════════════════════════════════════════════════
import json as _json_mod
import functools
from flask import send_from_directory
from models import AdminLog, AiRequestLog

_ADMIN_KEY = os.getenv("ADMIN_SECRET_KEY", "changeme")

def _require_admin(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-Admin-Key", "")
        if key != _ADMIN_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapper

def _log_admin(action, detail=""):
    try:
        entry = AdminLog(action=action, detail=detail,
                         ip_address=request.remote_addr)
        db.session.add(entry)
        db.session.commit()
    except Exception:
        pass

# ── Serve admin SPA ──────────────────────────────────────────────────────────
@app.route("/admin")
@app.route("/admin/")
def admin_page():
    return send_from_directory(basedir, "admin.html")

@app.route("/admin/login", methods=["POST"])
def admin_login():
    data = request.get_json(silent=True) or {}
    if data.get("key") == _ADMIN_KEY:
        _log_admin("login", "Admin logged in")
        return jsonify({"ok": True}), 200
    return jsonify({"error": "Invalid admin key"}), 401

# ── Overview stats ────────────────────────────────────────────────────────────
@app.route("/admin/stats", methods=["POST"])
@_require_admin
def admin_stats():
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC for DB comparisons
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start  = today_start - timedelta(days=7)

    total_users      = User.query.count()
    total_sessions   = MoodSessionLog.query.count()
    # AI requests = only Gemini insights calls
    ai_today         = AiRequestLog.query.filter(
        AiRequestLog.timestamp >= today_start,
        AiRequestLog.endpoint == "get-ai-insights"
    ).count()
    new_this_week    = User.query.count()  # approximate; no created_at on User
    active_users_today = User.query.filter(User.last_active >= today_start).count()
    active_sessions_today = active_users_today # Use active_users_today for this dashboard element

    # Most recent 10 activity log entries
    recent_activity = AdminLog.query.order_by(AdminLog.timestamp.desc()).limit(10).all()

    return jsonify({
        "total_users": total_users,
        "total_mood_entries": total_sessions,
        "ai_requests_today": ai_today,
        "active_sessions_today": active_sessions_today,
        "new_users_this_week": new_this_week,
        "recent_activity": [
            {"action": a.action, "detail": a.detail,
             "timestamp": a.timestamp.isoformat() if a.timestamp else None}
            for a in recent_activity
        ]
    }), 200

# ── User list with search/filter/sort ────────────────────────────────────────
@app.route("/admin/users", methods=["POST"])
@_require_admin
def admin_users():
    data = request.get_json(silent=True) or {}
    search = (data.get("search") or "").strip().lower()
    sort_by = data.get("sort_by", "id")   # id | name | email | last_active | join_date
    order   = data.get("order", "asc")

    q = User.query
    if search:
        q = q.filter(
            db.or_(
                User.name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%")
            )
        )
    if sort_by == "name":
        q = q.order_by(User.name.asc() if order == "asc" else User.name.desc())
    elif sort_by == "email":
        q = q.order_by(User.email.asc() if order == "asc" else User.email.desc())
    elif sort_by == "last_active":
        q = q.order_by(User.last_active.asc() if order == "asc" else User.last_active.desc())
    elif sort_by == "join_date":
        q = q.order_by(User.created_at.asc() if order == "asc" else User.created_at.desc())
    else:
        q = q.order_by(User.id.asc() if order == "asc" else User.id.desc())

    users = q.all()
    result = []
    for u in users:
        la = u.last_active.isoformat() if hasattr(u, 'last_active') and u.last_active else None
        jd = u.created_at.isoformat() if hasattr(u, 'created_at') and u.created_at else None
        session_count = len(u.sessions)
        result.append({
            "id": u.id, "name": u.name, "email": u.email,
            "age": u.age, "gender": u.gender, "dob": u.dob,
            "session_count": session_count,
            "last_active": la,
            "join_date": jd
        })
    return jsonify({"users": result}), 200

# ── Create user ───────────────────────────────────────────────────────────────
@app.route("/admin/users/create", methods=["POST"])
@_require_admin
def admin_create_user():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()
    if not name or not email or not password:
        return jsonify({"error": "name, email and password required"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"error": "User already exists"}), 400
    u = User(name=name, email=email, age=data.get("age"), gender=data.get("gender"))
    u.set_password(password)
    db.session.add(u)
    db.session.commit()
    _log_admin("create_user", f"Created user {email}")
    return jsonify({"ok": True, "id": u.id}), 201

# ── Edit user ─────────────────────────────────────────────────────────────────
@app.route("/admin/users/update", methods=["POST"])
@_require_admin
def admin_update_user():
    data = request.get_json(silent=True) or {}
    uid = data.get("id")
    u = User.query.get(uid)
    if not u:
        return jsonify({"error": "User not found"}), 404
    if data.get("name"):  u.name = data["name"]
    if data.get("email"): u.email = data["email"]
    if data.get("password"): u.set_password(data["password"])
    if data.get("age"):   u.age = data["age"]
    if data.get("gender"): u.gender = data["gender"]
    db.session.commit()
    _log_admin("update_user", f"Updated user id={uid}")
    return jsonify({"ok": True}), 200

# ── Delete user ───────────────────────────────────────────────────────────────
@app.route("/admin/users/delete", methods=["POST"])
@_require_admin
def admin_delete_user():
    data = request.get_json(silent=True) or {}
    uid = data.get("id")
    u = User.query.get(uid)
    if not u:
        return jsonify({"error": "User not found"}), 404
    email = u.email
    # Cascade delete handled by SQLAlchemy relationships
    SongPlayLog.query.filter_by(user_id=uid).delete()
    MoodSessionLog.query.filter_by(user_id=uid).delete()
    AiRequestLog.query.filter_by(user_email=email).delete()
    db.session.delete(u)
    db.session.commit()
    _log_admin("delete_user", f"Deleted user {email}")
    return jsonify({"ok": True}), 200

# ── User detail (mood history, songs, AI interactions) ───────────────────────
@app.route("/admin/user/detail", methods=["POST"])
@_require_admin
def admin_user_detail():
    data = request.get_json(silent=True) or {}
    uid = data.get("id")
    u = User.query.get(uid)
    if not u:
        return jsonify({"error": "User not found"}), 404

    # Mood history
    mood_logs = MoodSessionLog.query.filter_by(user_id=uid)\
        .order_by(MoodSessionLog.session_date.desc()).limit(50).all()
    mood_history = [{
        "date": l.session_date.isoformat() if l.session_date else None,
        "start_mood": l.start_mood, "end_mood": l.end_mood,
        "start_intensity": l.start_intensity, "end_intensity": l.end_intensity,
        "songs_played": l.songs_played_count, "songs_skipped": l.songs_skipped_count,
        "mood_improved": l.mood_improved, "duration_secs": l.session_duration_secs
    } for l in mood_logs]

    # Songs played log
    song_logs = SongPlayLog.query.filter_by(user_id=uid)\
        .order_by(SongPlayLog.logged_at.desc()).limit(50).all()
    songs = [{
        "title": s.title, "artist": s.artist, "mood": s.mood,
        "action": s.action,
        "logged_at": s.logged_at.isoformat() if s.logged_at else None
    } for s in song_logs]

    # AI interactions
    ai_logs = AiRequestLog.query.filter_by(user_email=u.email)\
        .order_by(AiRequestLog.timestamp.desc()).limit(30).all()
    ai_interactions = [{
        "endpoint": a.endpoint, "mood": a.user_mood,
        "prompt": a.prompt_snippet, "response": a.response_snippet,
        "timestamp": a.timestamp.isoformat() if a.timestamp else None
    } for a in ai_logs]

    from sqlalchemy import func
    total_secs = db.session.query(func.sum(MoodSessionLog.session_duration_secs)).filter_by(user_id=uid).scalar() or 0
    total_minutes = total_secs // 60

    liked_songs = [{"title": p.title, "artist": p.artist} for p in Preference.query.filter_by(user_id=uid, pref_type='like').all()]
    blocked_songs = [{"title": p.title, "artist": p.artist} for p in Preference.query.filter_by(user_id=uid, pref_type='block').all()]

    return jsonify({
        "user": {
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "age": u.age,
            "gender": u.gender,
            "last_active": u.last_active.isoformat() if u.last_active else None,
            "total_songs_played": SongPlayLog.query.filter_by(user_id=uid).count(),
            "total_mood_entries": MoodSessionLog.query.filter_by(user_id=uid).count(),
            "total_minutes_played": total_minutes,
            "liked_songs": liked_songs,
            "blocked_songs": blocked_songs
        },
        "mood_history": mood_history,
        "songs": songs,
        "ai_interactions": ai_interactions
    }), 200

# ── Song analytics ────────────────────────────────────────────────────────────
@app.route("/admin/song-analytics", methods=["POST"])
@_require_admin
def admin_song_analytics():
    # Most played songs globally
    from sqlalchemy import func
    top_played = db.session.query(
        SongPlayLog.title, SongPlayLog.artist,
        func.count(SongPlayLog.id).label("play_count")
    ).filter(SongPlayLog.action == "played")\
     .group_by(SongPlayLog.title, SongPlayLog.artist)\
     .order_by(func.count(SongPlayLog.id).desc()).limit(20).all()

    top_skipped = db.session.query(
        SongPlayLog.title, SongPlayLog.artist,
        func.count(SongPlayLog.id).label("skip_count")
    ).filter(SongPlayLog.action == "skipped")\
     .group_by(SongPlayLog.title, SongPlayLog.artist)\
     .order_by(func.count(SongPlayLog.id).desc()).limit(20).all()

    # Mood → song mapping (top song per mood)
    mood_song_map = {}
    moods = ["Sad", "Anxious", "Stressed", "Neutral", "Happy", "Energised"]
    for mood in moods:
        top = db.session.query(
            SongPlayLog.title, SongPlayLog.artist,
            func.count(SongPlayLog.id).label("c")
        ).filter(SongPlayLog.mood == mood, SongPlayLog.action == "played")\
         .group_by(SongPlayLog.title, SongPlayLog.artist)\
         .order_by(func.count(SongPlayLog.id).desc()).first()
        if top:
            mood_song_map[mood] = {"title": top.title, "artist": top.artist, "count": top.c}

    # Skip/replay rates
    total_plays  = SongPlayLog.query.filter_by(action="played").count()
    total_skips  = SongPlayLog.query.filter_by(action="skipped").count()
    total_all    = total_plays + total_skips
    skip_rate    = round((total_skips / total_all * 100) if total_all else 0, 1)
    play_rate    = round((total_plays / total_all * 100) if total_all else 0, 1)

    # Liked songs count & unique global
    total_liked = Preference.query.filter_by(pref_type="like").count()
    all_liked_query = db.session.query(
        Preference.title, Preference.artist, func.count(Preference.id).label("c")
    ).filter_by(pref_type="like").group_by(Preference.title, Preference.artist).order_by(func.count(Preference.id).desc()).all()
    all_liked = [{"title": r.title, "artist": r.artist, "count": r.c} for r in all_liked_query]

    # Blocked songs count & unique global
    total_blocked = Preference.query.filter_by(pref_type="block").count()
    all_blocked_query = db.session.query(
        Preference.title, Preference.artist, func.count(Preference.id).label("c")
    ).filter_by(pref_type="block").group_by(Preference.title, Preference.artist).order_by(func.count(Preference.id).desc()).all()
    all_blocked = [{"title": r.title, "artist": r.artist, "count": r.c} for r in all_blocked_query]

    return jsonify({
        "most_played": [{"title": r.title, "artist": r.artist, "count": r.play_count} for r in top_played],
        "most_skipped": [{"title": r.title, "artist": r.artist, "count": r.skip_count} for r in top_skipped],
        "mood_song_map": mood_song_map,
        "total_plays": total_plays,
        "total_skips": total_skips,
        "skip_rate_pct": skip_rate,
        "play_rate_pct": play_rate,
        "total_liked": total_liked,
        "total_blocked": total_blocked,
        "all_liked": all_liked,
        "all_blocked": all_blocked
    }), 200

# ── Activity log ──────────────────────────────────────────────────────────────
@app.route("/admin/activity-log", methods=["POST"])
@_require_admin
def admin_activity_log():
    data = request.get_json(silent=True) or {}
    limit = min(int(data.get("limit", 100)), 500)
    logs = AdminLog.query.order_by(AdminLog.timestamp.desc()).limit(limit).all()
    return jsonify({
        "logs": [{"action": l.action, "detail": l.detail,
                  "ip": l.ip_address,
                  "timestamp": l.timestamp.isoformat() if l.timestamp else None}
                 for l in logs]
    }), 200

@app.route("/admin/logs/clear", methods=["POST"])
@_require_admin
def admin_logs_clear():
    try:
        db.session.query(AdminLog).delete()
        db.session.commit()
        return jsonify({"ok": True}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# ── Error log (reads from a file if present) ──────────────────────────────────
@app.route("/admin/error-log", methods=["POST"])
@_require_admin
def admin_error_log():
    error_file = os.path.join(basedir, "errors.txt")
    lines = []
    if os.path.exists(error_file):
        with open(error_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-200:]  # last 200 lines
    return jsonify({"errors": [l.rstrip() for l in lines]}), 200

# ── AI responses log ──────────────────────────────────────────────────────────
@app.route("/admin/ai-responses", methods=["POST"])
@_require_admin
def admin_ai_responses():
    data = request.get_json(silent=True) or {}
    limit = min(int(data.get("limit", 50)), 200)
    logs = AiRequestLog.query.order_by(AiRequestLog.timestamp.desc()).limit(limit).all()
    return jsonify({
        "logs": [{
            "user": l.user_email, "endpoint": l.endpoint,
            "mood": l.user_mood, "prompt": l.prompt_snippet,
            "response": l.response_snippet,
            "timestamp": l.timestamp.isoformat() if l.timestamp else None
        } for l in logs]
    }), 200

# ── Feature toggles ───────────────────────────────────────────────────────────
@app.route("/admin/feature-toggles", methods=["POST"])
@_require_admin
def admin_feature_toggles():
    cfg_path = os.path.join(basedir, "admin_config.json")
    data = request.get_json(silent=True) or {}

    if data.get("action") == "set":
        with open(cfg_path, "r") as f:
            cfg = _json_mod.load(f)
        cfg["feature_toggles"].update(data.get("toggles", {}))
        with open(cfg_path, "w") as f:
            _json_mod.dump(cfg, f, indent=2)
        _log_admin("feature_toggle", str(data.get("toggles", {})))
        return jsonify({"ok": True}), 200
    else:
        with open(cfg_path, "r") as f:
            cfg = _json_mod.load(f)
        return jsonify(cfg["feature_toggles"]), 200

# ── Branding ──────────────────────────────────────────────────────────────────
@app.route("/admin/branding", methods=["POST"])
@_require_admin
def admin_branding():
    cfg_path = os.path.join(basedir, "admin_config.json")
    data = request.get_json(silent=True) or {}

    if data.get("action") == "set":
        with open(cfg_path, "r") as f:
            cfg = _json_mod.load(f)
        cfg["branding"].update(data.get("branding", {}))
        with open(cfg_path, "w") as f:
            _json_mod.dump(cfg, f, indent=2)
        _log_admin("branding_update", str(data.get("branding", {})))
        return jsonify({"ok": True}), 200
    else:
        with open(cfg_path, "r") as f:
            cfg = _json_mod.load(f)
        return jsonify(cfg["branding"]), 200

# ── Verify admin key ──────────────────────────────────────────────────────────
@app.route("/admin/verify", methods=["POST"])
def admin_verify():
    data = request.get_json(silent=True) or {}
    if data.get("key") == _ADMIN_KEY:
        return jsonify({"ok": True}), 200
    return jsonify({"error": "Invalid"}), 401


LIVE_SESSIONS = {}

@app.route("/api/lifecycle", methods=["POST"])
def api_lifecycle():
    data = request.json or {}
    email = data.get("email")
    status = data.get("status")
    if not email:
        return jsonify({"error": "missing email"}), 400
    u = User.query.filter_by(email=email).first()
    if u:
        if status == "online":
            LIVE_SESSIONS[u.id] = datetime.now(timezone.utc).timestamp()
            u.last_active = datetime.now(timezone.utc).replace(tzinfo=None)
        elif status == "offline":
            LIVE_SESSIONS.pop(u.id, None)
            u.last_active = datetime.now(timezone.utc).replace(tzinfo=None) # Update to final active time
        db.session.commit()
    return jsonify({"ok": True}), 200

# ── Live users ─────────────────────────────────────
@app.route("/admin/live-users", methods=["POST"])
@_require_admin
def admin_live_users():
    now_ts = datetime.now(timezone.utc).timestamp()
    stale_keys = [uid for uid, ts in LIVE_SESSIONS.items() if now_ts - ts > 20]
    for uid in stale_keys:
        LIVE_SESSIONS.pop(uid, None)
    return jsonify({"live_user_ids": list(LIVE_SESSIONS.keys())}), 200

# ── Liked / blocked songs for all users ──────────────────────────────────────
@app.route("/admin/liked-blocked", methods=["POST"])
@_require_admin
def admin_liked_blocked():
    liked = Preference.query.filter_by(pref_type="like").all()
    blocked = Preference.query.filter_by(pref_type="block").all()
    liked_data = [{"user_id": p.user_id, "title": p.title, "artist": p.artist} for p in liked]
    blocked_data = [{"user_id": p.user_id, "title": p.title, "artist": p.artist} for p in blocked]
    return jsonify({"liked": liked_data, "blocked": blocked_data}), 200


if __name__ == "__main__":
    # app.run(debug=True) (Windows)
    app.run(host="0.0.0.0", port=5000, debug=True)    # (Android)
