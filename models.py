from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    dob = db.Column(db.String(20))
    age = db.Column(db.String(10))
    gender = db.Column(db.String(20))
    last_active = db.Column(db.DateTime)
    
    sessions = db.relationship('Session', backref='user', lazy=True, cascade="all, delete-orphan")
    preferences = db.relationship('Preference', backref='user', lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Session(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date_str = db.Column(db.String(100)) # e.g. "3/3/2026 • 14:44"
    start_mood = db.Column(db.String(50))
    target_mood = db.Column(db.String(50))
    end_mood = db.Column(db.String(50))
    intensity = db.Column(db.Integer)
    duration = db.Column(db.String(50))
    intensities_raw = db.Column(db.Text) # comma separated list
    is_live = db.Column(db.Boolean, default=False)
    
    songs_played = db.relationship('SongPlayed', backref='session', lazy=True, cascade="all, delete-orphan")
    transitions = db.relationship('MoodTransition', backref='session', lazy=True, cascade="all, delete-orphan")

class SongPlayed(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=False)
    title = db.Column(db.String(200))
    artist = db.Column(db.String(200))
    youtube_search_query = db.Column(db.String(500))
    played_in_mood = db.Column(db.String(50))

class MoodTransition(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('session.id'), nullable=False)
    from_mood = db.Column(db.String(50))
    to_mood = db.Column(db.String(50))
    time_str = db.Column(db.String(50))
    intensity = db.Column(db.Integer)

class Preference(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200))
    artist = db.Column(db.String(200))
    pref_type = db.Column(db.String(20)) # 'like' or 'block'

class SongPlayLog(db.Model):
    """Tracks every played or skipped song per user per detected mood."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    mood = db.Column(db.String(50), nullable=False)   # detected mood
    title = db.Column(db.String(200), nullable=False)
    artist = db.Column(db.String(200), nullable=False)
    action = db.Column(db.String(10), nullable=False)  # 'played' or 'skipped'
    logged_at = db.Column(db.DateTime, server_default=db.func.now())

class MoodSessionLog(db.Model):
    """Rich per-session behavioral log used by the AI insights engine.
    One row is written per completed session via /log-session-outcome."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    session_date = db.Column(db.DateTime, nullable=False)  # full timestamp (date + time of day)
    start_mood = db.Column(db.String(50), nullable=False)  # detected mood at session start
    end_mood = db.Column(db.String(50))                    # mood at end (may be same or higher)
    start_intensity = db.Column(db.Integer)                # 0-100
    end_intensity = db.Column(db.Integer)                  # 0-100, nullable
    songs_played_count = db.Column(db.Integer, default=0)
    songs_skipped_count = db.Column(db.Integer, default=0)
    liked_songs_count = db.Column(db.Integer, default=0)
    mood_improved = db.Column(db.Boolean)                  # True/False/None
    session_duration_secs = db.Column(db.Integer, default=0)

class AdminLog(db.Model):
    """Records admin actions: who logged in, created/deleted users, etc."""
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(100), nullable=False)   # e.g. 'login', 'delete_user'
    detail = db.Column(db.Text)                          # e.g. 'Deleted user foo@bar.com'
    ip_address = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime, server_default=db.func.now())

class AiRequestLog(db.Model):
    """Records every Gemini AI prompt/response pair for admin review."""
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String(120))
    endpoint = db.Column(db.String(50))                  # e.g. 'get-song', 'get-ai-insights'
    user_mood = db.Column(db.String(50))
    prompt_snippet = db.Column(db.Text)                  # first 500 chars of prompt
    response_snippet = db.Column(db.Text)                # first 500 chars of response
    timestamp = db.Column(db.DateTime, server_default=db.func.now())
