import os
import time
import base64
import requests
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

TOKEN_URL = "https://accounts.spotify.com/api/token"
SEARCH_URL = "https://api.spotify.com/v1/search"
PLAYLIST_TRACKS_URL = "https://api.spotify.com/v1/playlists/{playlist_id}/tracks"

_cached_token: Optional[str] = None
_token_expiry_ts: float = 0.0

import re

_ML = re.compile(r"[\u0D00-\u0D7F]")  # Malayalam
_TA = re.compile(r"[\u0B80-\u0BFF]")  # Tamil
_HI = re.compile(r"[\u0900-\u097F]")  # Hindi (Devanagari)
_TE = re.compile(r"[\u0C00-\u0C7F]")  # Telugu

_LANG_ARTISTS = {
    "malayalam": {"sushin shyam", "jakes bejoy", "gopi sundar", "rex vijayan", "vineeth sreenivasan", "bijibal", "sooraj santhosh"},
    "tamil": {"anirudh", "a.r. rahman", "yuvan", "harris jayaraj", "gv prakash", "hiphop tamizha"},
    "hindi": {"pritam", "arijit", "amit trivedi", "vishal-shekhar", "jubin nautiyal",
              "yo yo honey singh", "sachin-jigar", "vishal mishra", "himesh reshammiya", "dhanda nyoliwala",
              "anand raj anand", "aastha gill", "sanju rathod", "ajay-atul", "badshah", "neha kakkar",
              "pav dharia", "karan aujla", "meet bros anjjan", "zack knight", "shashwat sachdev"},
    "telugu": {"devi sri prasad", "thaman", "mickey j meyer"},
}


# romanised Hindi keywords that frequently appear in titles
_ROMAN_HINDI_WORDS = re.compile(r"\b(kiya|kamariya|sundari|patola|diggy|bom|na ja|tauba|baby doll|laal pari|baby doll|dhurandhar)\b", re.I)

def is_track_in_language(title: str, artist: str, lang: str) -> bool:
    lang = (lang or "").lower().strip()
    # treat empty as english (no filtering)
    if lang in ("", "english"):
        # still reject any track that clearly belongs to another supported language
        joined = f"{title or ""} {artist or ""}".lower()
        # obvious scripts = non-English
        if _ML.search(joined) or _TA.search(joined) or _HI.search(joined) or _TE.search(joined):
            return False
        # obvious romanised hindi keywords
        if _ROMAN_HINDI_WORDS.search(joined):
            return False
        # if artist appears in any of the non-english artist lists, reject
        for other in ("malayalam", "tamil", "hindi", "telugu"):
            for ar in _LANG_ARTISTS.get(other, set()):
                if ar in joined:
                    return False
        return True

    t = title or ""
    a = artist or ""
    joined = f"{t} {a}".lower()

    # helper to check known artists for a language
    def _check_artists(target: str) -> bool:
        for ar in _LANG_ARTISTS.get(target, set()):
            if ar in joined:
                return True
        return False

    if lang == "malayalam":
        # first prefer native script detection
        if _ML.search(t) or _ML.search(a):
            return True
        # then known Malayalam artists
        if _check_artists("malayalam"):
            return True
        # romanized Malayalam keywords may appear in titles/albums
        mal_keywords = ["mollywood", "malayalam"]
        if any(k in joined for k in mal_keywords):
            return True
        # filter out obvious global english hits
        obvious_global = ["taylor swift", "the weeknd", "lady gaga", "drake",
                          "ed sheeran", "ariana grande", "bts"]
        if any(x in joined for x in obvious_global):
            return False
        # otherwise we don't have good evidence it's Malayalam
        return False
    elif lang == "tamil":
        if _TA.search(t) or _TA.search(a) or _check_artists("tamil"):
            return True
    elif lang == "hindi":
        if _HI.search(t) or _HI.search(a) or _check_artists("hindi"):
            return True
        # drop obvious global english songs
        obvious_global = ["taylor swift", "the weeknd", "lady gaga", "drake",
                          "ed sheeran", "ariana grande", "bts"]
        if any(x in joined for x in obvious_global):
            return False
        return False
    elif lang == "telugu":
        if _TE.search(t) or _TE.search(a) or _check_artists("telugu"):
            return True

    # Fall through: no clues
    return False


def _clamp_int(value: Any, default: int, lo: int, hi: int) -> int:
    """
    Convert to int safely and clamp to [lo, hi].
    Prevents Spotify 400 "Invalid limit".
    """
    try:
        v = int(str(value).strip())
    except Exception:
        v = int(default)
    if v < lo:
        v = lo
    if v > hi:
        v = hi
    return v


def _get_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing environment variable: {name}")
    return v


def get_spotify_token(force_refresh: bool = False) -> str:
    """
    Fetch cached token or refresh using Client Credentials flow.
    """
    global _cached_token, _token_expiry_ts

    if (not force_refresh) and _cached_token and time.time() < (_token_expiry_ts - 30):
        return _cached_token

    client_id = _get_env("SPOTIFY_CLIENT_ID")
    client_secret = _get_env("SPOTIFY_CLIENT_SECRET")

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("utf-8")
    headers = {
        "Authorization": f"Basic {basic}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"grant_type": "client_credentials"}

    resp = requests.post(TOKEN_URL, headers=headers, data=data, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Spotify token error {resp.status_code}: {resp.text}")

    payload = resp.json()
    _cached_token = payload["access_token"]
    expires_in = _clamp_int(payload.get("expires_in", 3600), 3600, 60, 24 * 3600)
    _token_expiry_ts = time.time() + expires_in
    return _cached_token  # type: ignore


def _is_bad_title(title: str) -> bool:
    t = (title or "").lower()

    bad_keywords = [
        "music for", "relaxing music", "calming music", "study music",
        "sleep music", "stress relief", "relief music",
        "healing music", "deep sleep", "white noise",
        "binaural", "asmr",
        "soundscape", "soundscapes",
        "ambient", "nature", "waves", "thunder", "forest", "rain", "raindrops",
        "meditation", "sleep", "study", "focus"
    ]
    bad_exact = ["karaoke"]  # minimal change

    if any(k in t for k in bad_keywords):
        return True
    if any(k in t for k in bad_exact):
        return True
    return False


def _spotify_get(url: str, headers: dict, params: dict, timeout: int = 25) -> requests.Response:
    """
    Minimal robustness:
    - Retries on ReadTimeout (up to 2 times)
    - Refresh token once if 401
    - Retry-after handling for 429 (once)
    """
    max_retries = 2
    resp = None

    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
            
            # ✅ Retry on 5xx errors (Bad Gateway, Service Unavailable, Gateway Timeout)
            if resp.status_code in (502, 503, 504) and attempt < max_retries:
                time.sleep(2.0 * (attempt + 1))  # exponential backoff
                continue
                
            break
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            if attempt < max_retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            else:
                raise RuntimeError(f"Spotify API connection failed after {max_retries} retries: {e}")

    if resp.status_code == 401:
        token = get_spotify_token(force_refresh=True)
        headers = {**headers, "Authorization": f"Bearer {token}"}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
            pass # We will return the previous resp or it will raise later

    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After")
        wait_s = 2
        try:
            if retry_after is not None:
                wait_s = max(2, int(retry_after))
        except Exception:
            wait_s = 2
        time.sleep(wait_s)
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
            pass

    return resp


# -------------------- TRACK SEARCH (UNCHANGED) --------------------

def search_spotify_tracks(
    query: str,
    limit: int = 3,
    market: str | None = None,
    strict_movie: bool = True,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Spotify Search API:
      - limit MUST be 1..50
      - offset must be >=0 (Spotify supports up to 1000 commonly)
    """

    if not query or not query.strip():
        return []

    token = get_spotify_token()
    market = market or os.getenv("SPOTIFY_MARKET", "IN")
    headers = {"Authorization": f"Bearer {token}"}

    limit_i = _clamp_int(limit, default=3, lo=1, hi=50)
    offset_i = _clamp_int(offset, default=0, lo=0, hi=1000)

    params = {
        "q": query,
        "type": "track",
        "limit": str(limit_i),
        "offset": str(offset_i),
        "market": market,
    }

    resp = _spotify_get(SEARCH_URL, headers=headers, params=params, timeout=25)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Spotify search error {resp.status_code}: {resp.text} | params={params}"
        )

    items = resp.json().get("tracks", {}).get("items", [])
    results: List[Dict[str, Any]] = []

    def _looks_non_target_language(it: dict, target_lang: str) -> bool:
        target_lang = (target_lang or "").lower()
        if target_lang in ("english", ""):
            return False

        title = (it.get("name") or "").lower()
        album = (it.get("album") or {})
        album_name = (album.get("name") or "").lower()

        if "from " in title or "from " in album_name:
            return False

        joined = f"{title} {album_name}"
        if target_lang in joined:
            return False

        return True

    qlow = query.lower()

    for it in items:
        title = it.get("name", "")
        if not title:
            continue
        if _is_bad_title(title):
            continue

        if "tollywood" in qlow or "telugu" in qlow:
            if _looks_non_target_language(it, "telugu"):
                continue
        elif "kollywood" in qlow or "tamil" in qlow:
            if _looks_non_target_language(it, "tamil"):
                continue
        elif "bollywood" in qlow or "hindi" in qlow:
            if _looks_non_target_language(it, "hindi"):
                continue
        elif "mollywood" in qlow or "malayalam" in qlow:
            if _looks_non_target_language(it, "malayalam"):
                continue

        if strict_movie:
            album = it.get("album", {}) or {}
            album_name = (album.get("name") or "").lower()
            movie_markers = ["soundtrack", "ost", "motion picture", "from the"]
            is_movie_album = any(m in album_name for m in movie_markers)
            if not is_movie_album:
                continue

        artists = it.get("artists", [])
        artist_name = artists[0].get("name", "") if artists else ""
        if not artist_name or len(artist_name.strip()) < 2:
            continue

        popularity = it.get("popularity", 0)
        min_pop = 20 if "pop" in qlow or "english" in qlow else 30
        if popularity < min_pop:
            continue

        url = (it.get("external_urls") or {}).get("spotify", "")

        results.append({
            "title": title,
            "artist": artist_name,
            "popularity": popularity,
            "spotify_url": url,
        })

    results.sort(key=lambda x: x.get("popularity", 0), reverse=True)
    return results


def search_spotify_tracks_multi(queries: List[str], per_query_limit: int = 50) -> List[Dict[str, Any]]:
    """
    Collect up to per_query_limit results PER query using pagination.
    """
    merged: List[Dict[str, Any]] = []
    seen = set()

    per_query_limit_i = _clamp_int(per_query_limit, default=25, lo=1, hi=500)

    for q in queries:
        if not q or not q.strip():
            continue

        collected: List[Dict[str, Any]] = []
        offset = 0

        page_size = min(50, per_query_limit_i)

        while len(collected) < per_query_limit_i:
            batch = search_spotify_tracks(
                q,
                limit=page_size,
                strict_movie=False,
                offset=offset
            )

            if not batch:
                break

            collected.extend(batch)
            offset += page_size

            if len(batch) < page_size:
                break

            if offset >= 1000:
                break

        for t in collected[:per_query_limit_i]:
            key = (t["title"].lower().strip(), t["artist"].lower().strip())
            if key in seen:
                continue
            seen.add(key)
            merged.append(t)

    merged.sort(key=lambda x: x.get("popularity", 0), reverse=True)
    return merged


# -------------------- NEW: PLAYLIST MODE (MINIMAL ADD) --------------------

def _extract_playlist_id(pl: dict) -> str:
    pid = (pl.get("id") or "").strip()
    if pid:
        return pid

    url = ((pl.get("external_urls") or {}).get("spotify") or "").strip()
    if not url:
        return ""

    parts = urlparse(url).path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "playlist":
        return parts[1]
    return ""


def search_spotify_playlists(
    query: str,
    limit: int = 10,
    market: str | None = None,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Search Spotify playlists using Search API.
    """
    if not query or not query.strip():
        return []

    token = get_spotify_token()
    market = market or os.getenv("SPOTIFY_MARKET", "IN")
    headers = {"Authorization": f"Bearer {token}"}

    limit_i = _clamp_int(limit, default=10, lo=1, hi=50)
    offset_i = _clamp_int(offset, default=0, lo=0, hi=1000)

    params = {
        "q": query,
        "type": "playlist",
        "limit": str(limit_i),
        "offset": str(offset_i),
        "market": market,
    }

    resp = _spotify_get(SEARCH_URL, headers=headers, params=params, timeout=25)
    if resp.status_code != 200:
        raise RuntimeError(f"Spotify playlist search error {resp.status_code}: {resp.text} | params={params}")

    items = resp.json().get("playlists", {}).get("items", []) or []
    out: List[Dict[str, Any]] = []
    for pl in items:
        if not isinstance(pl, dict):
            continue  # ✅ skip None or unexpected values

        pid = _extract_playlist_id(pl)
        if not pid:
            continue
        
        out.append({
            "id": pid,
            "name": (pl.get("name") or ""),
            "tracks_total": ((pl.get("tracks") or {}).get("total") or 0),
            "url": ((pl.get("external_urls") or {}).get("spotify") or ""),
        })
    return out


def get_playlist_tracks(
    playlist_id: str,
    limit: int = 100,
    offset: int = 0,
    market: str | None = None
) -> List[Dict[str, Any]]:
    """
    Get tracks from a playlist.
    limit max = 100
    """
    if not playlist_id:
        return []

    token = get_spotify_token()
    market = market or os.getenv("SPOTIFY_MARKET", "IN")
    headers = {"Authorization": f"Bearer {token}"}

    limit_i = _clamp_int(limit, default=100, lo=1, hi=100)
    offset_i = _clamp_int(offset, default=0, lo=0, hi=10000)

    url = PLAYLIST_TRACKS_URL.format(playlist_id=playlist_id)

    params = {
        "limit": str(limit_i),
        "offset": str(offset_i),
        "market": market,
        # small response for speed
        "fields": "items(track(name,artists(name),popularity,external_urls(spotify))),next",
    }

    resp = _spotify_get(url, headers=headers, params=params, timeout=25)
    if resp.status_code != 200:
        raise RuntimeError(f"Spotify playlist tracks error {resp.status_code}: {resp.text} | playlist_id={playlist_id}")

    items = resp.json().get("items", []) or []
    tracks: List[Dict[str, Any]] = []

    for it in items:
        tr = (it.get("track") or {})
        if not tr:
            continue

        title = (tr.get("name") or "").strip()
        if not title:
            continue

        artists = tr.get("artists") or []
        artist_name = (artists[0].get("name") if artists else "") or ""
        popularity = int(tr.get("popularity") or 0)
        url_sp = ((tr.get("external_urls") or {}).get("spotify") or "")

        tracks.append({
            "title": title,
            "artist": artist_name,
            "popularity": popularity,
            "spotify_url": url_sp,
        })

    return tracks


def recommend_continuous_from_playlists(
    queries: List[str],
    playlists_per_query: int = 6,
    final_limit: int = 50,
    market: str | None = None
) -> List[Dict[str, Any]]:
    """
    Your requested logic:
    - Search playlists from queries (multiple)
    - Pull tracks playlist1 -> playlist2 -> ... sequentially
    - Avoid duplicates across playlists
    - Return as one continued set
    """
    playlists_per_query_i = _clamp_int(playlists_per_query, default=6, lo=1, hi=20)
    final_limit_i = _clamp_int(final_limit, default=50, lo=5, hi=200)

    # 1) Build playlist queue (ordered)
    queue: List[Dict[str, Any]] = []
    seen_pl = set()

    for q in queries:
        pls = search_spotify_playlists(q, limit=playlists_per_query_i, market=market)
        for pl in pls:
            pid = pl["id"]
            if pid in seen_pl:
                continue
            seen_pl.add(pid)
            queue.append(pl)

    if not queue:
        return []

    # 2) Sequentially fetch tracks from each playlist until we have enough unique songs
    offsets: Dict[str, int] = {pl["id"]: 0 for pl in queue}
    exhausted = set()
    seen_tracks = set()
    out: List[Dict[str, Any]] = []

    while len(out) < final_limit_i:
        progressed = False

        for pl in queue:
            pid = pl["id"]
            if pid in exhausted:
                continue

            offset = offsets[pid]
            batch = get_playlist_tracks(pid, limit=100, offset=offset, market=market)

            if not batch:
                exhausted.add(pid)
                continue

            offsets[pid] = offset + 100
            progressed = True

            # Apply your existing filters (minimal reuse)
            for t in batch:
                title = t.get("title", "")
                artist = t.get("artist", "")
                pop = int(t.get("popularity", 0) or 0)

                if not title or not artist:
                    continue
                if _is_bad_title(title):
                    continue

                # same popularity logic as your search (simple + consistent)
                qlow = " ".join(queries).lower()
                min_pop = 20 if ("pop" in qlow or "english" in qlow) else 30
                if pop < min_pop:
                    continue

                key = (title.lower().strip(), artist.lower().strip())
                if key in seen_tracks:
                    continue
                seen_tracks.add(key)

                out.append({
                    "title": title,
                    "artist": artist,
                    "popularity": pop,
                    "spotify_url": t.get("spotify_url", ""),
                    "source_playlist": pl.get("name", ""),
                })

                if len(out) >= final_limit_i:
                    break

            if len(out) >= final_limit_i:
                break

        if not progressed or len(exhausted) == len(queue):
            break

    # Keep popularity order (optional). If you want strict "playlist order", comment this out.
    out.sort(key=lambda x: x.get("popularity", 0), reverse=True)
    return out