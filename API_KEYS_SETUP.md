# API Keys Setup Guide

This guide explains how to get the necessary API keys to run MUMS.ai locally. 

---

## 1. Spotify API Keys (Client ID & Secret)

These keys are used for the Python backend to fetch music recommendations and playback URLs.

**Quick Steps:**
1. **Go to**: [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/)
2. **Log in** with your Spotify account.
3. **Create an App**:
   - Click **Create app**.
   - App Name: "MUMS.ai" (or anything similar)
   - App Description: "AI Mood Music App"
   - Redirect URI: `http://localhost:8888/callback` (or any local URL, though it's mainly for OAuth if used)
   - Check the required agreement boxes and click **Save**.
4. **Copy your API keys**:
   - Go to your newly created app's settings.
   - You will see the **Client ID**.
   - Click **View Client Secret** to reveal the secret.
5. **Update your `.env` file**:
   ```env
   SPOTIFY_CLIENT_ID=your_client_id_here
   SPOTIFY_CLIENT_SECRET=your_client_secret_here
   SPOTIFY_MARKET=IN
   ```

---

## 2. YouTube API Key

This key is used for searching and playing music videos within the Flutter app using `youtube_player_flutter`.

**Quick Steps:**
1. **Go to**: [Google Cloud Console](https://console.cloud.google.com/)
2. **Sign in** with your Google account.
3. **Create a new project**:
   - Click the project dropdown at the top and select **New Project**.
   - Name it "MUMSai-YouTube" and click **Create**.
4. **Enable the YouTube Data API v3**:
   - Go to **APIs & Services** > **Library**.
   - Search for "YouTube Data API v3".
   - Click it and select **Enable**.
5. **Create Credentials**:
   - Go to **APIs & Services** > **Credentials**.
   - Click **Create Credentials** > **API Key**.
6. **Copy your API key** (it usually starts with `AIza...`).
7. **Update your `.env` file**:
   ```env
   YOUTUBE_API_KEY=your_youtube_key_here
   ```

---

## 3. Gemini API Key

This key is used to analyze mood input and generate therapeutic insights using Google's generative AI models.

**Quick Steps:**
1. **Go to**: [Google AI Studio](https://aistudio.google.com/app/apikey)
2. **Sign in** with your Google account.
3. **Create API Key**:
   - Click the **Get API key** button.
   - Select **Create API key in new project**.
4. **Copy your API key** (it usually starts with `AIza...`).
5. **Update your `.env` file**:
   ```env
   GEMINI_API_KEY=your_gemini_key_here
   ```

---

## Final Step: Restart your application

Once you have updated your `.env` file with all the new keys, make sure to restart your Python backend and the Flutter app to load the new environment variables.

**Backend (Python)**
```bash
python app.py
```

**Frontend (Flutter)**
```bash
flutter run
```
