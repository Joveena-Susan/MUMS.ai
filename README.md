# 🎶 MUMS.ai – AI-Powered Mood Uplift & Music Therapy Companion

MUMS.ai is a full-stack mobile application that acts as a personalized music therapy companion. It helps users track their emotional state, discover music tailored to their current mood, receive AI-driven psychological insights, and gradually uplift their emotional well-being through curated audio experiences.

The app combines artificial intelligence, emotion detection, music streaming integrations, and interactive feedback to create a holistic platform designed to enhance mental health and daily emotional balance.

## 📱 Screenshots
Application screenshots are available in the repository in the 'Screenshots' Folder.

## ✨ Features

🤖 **AI Mood Detection & Insights**
- Advanced text and voice-based mood analysis
- Personalized emotional insights and coping suggestions
- Context-aware therapeutic guidance
- Interactive AI-driven feedback loop

🎵 **Smart Music Discovery & Therapy**
- Dynamic music recommendations based on emotional state
- YouTube & Spotify integrations for seamless playback
- Mood-transitioning playlists designed to gently uplift
- Audio therapy tailored to reduce stress and anxiety

🗣️ **Voice & Text Input**
- Express your feelings via text or speech-to-text integration
- Natural language processing for accurate emotional context

📈 **User Progress Tracking**
- Secure user accounts and authentication
- Personal history of mood logs and track interactions
- Data-driven visualization of emotional trends over time

## 🛠 Tech Stack

**Frontend (Mobile App)**
- Flutter
- Dart
- Provider (State Management)
- Speech-to-Text
- YouTube Player Integration

**Backend (API & AI Processing)**
- Python
- Flask / Web Server (app.py)
- Advanced LLM Integrations (AI Insights)

**Database**
- SQLAlchemy

**Integrations**
- Spotify API
- YouTube API

## 🚀 Key Highlights
- Full-stack mobile application (Flutter + Python)
- AI-powered emotion detection and personalized feedback
- Real-time intelligent music curation
- Voice-enabled journaling and mood logging
- Cloud-connected secure architecture
- Modern, accessible, and responsive UI design

## ⚙️ Installation

### Clone the Repository
```bash
git clone https://github.com/JefferyMaju/MUMS.ai.git
cd MUMS.ai
```

### Configure Environment Variables
Create a `.env` file in the root directory for the Python backend:
```env
# Example .env configuration
SPOTIFY_CLIENT_ID=YOUR_SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET=YOUR_SPOTIFY_CLIENT_SECRET
SPOTIFY_MARKET=IN
YOUTUBE_API_KEY=YOUR_YOUTUBE_API_KEY
GEMINI_API_KEY=YOUR_GEMINI_API_KEY
```

### Run Backend
Ensure you have Python installed, then install dependencies and start the server:
```bash
pip install -r requirements.txt
python app.py
```

### Run Mobile Application
Ensure you have Flutter installed and an emulator/device running:
```bash
flutter pub get
flutter run
```

## 🎯 Future Improvements
- Wearable device integration for biometric mood detection (heart rate, HRV)
- Offline mode for downloaded therapy sessions
- Enhanced interactive guided meditations
- Social/community features for shared emotional support
- Extended daily journaling and mood calendar

## 👨‍💻 Author
**Joveena Susan Joby**
- 🌐 GitHub: https://github.com/Joveena-Susan
**Jeffery Maju**
- 🌐 GitHub: [https://github.com/JefferyMaju](https://github.com/JefferyMaju)

⭐ If you found this project interesting, consider giving it a star!
