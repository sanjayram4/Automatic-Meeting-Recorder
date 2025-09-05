# Automatic Meeting Agent 🎥🤖

An AI-powered Flask web app that can **automatically join online meetings (Google Meet, Zoom, MS Teams, etc.)**, record audio, transcribe it into text, and generate **meeting summaries** using **Whisper + Gemini AI**.  

The app also supports **scheduling meetings**, managing **recordings & summaries**, and provides a **beautiful Bootstrap-based dashboard**.

---

## ✨ Features

- 📅 **Schedule Meetings** → Automatically join and record at the scheduled time  
- ⚡ **Start Now** → Instantly join a meeting and start recording  
- 🎙️ **Record Audio** → Captures system/mic audio using FFmpeg  
- 📝 **Transcribe with Whisper** → Converts speech into text  
- 🤖 **Summarize with Gemini AI** → Generates clear, human-like meeting summaries  
- 📂 **Dashboard** → View, play, download, and delete recordings & summaries  
- 🗑️ **Manage Data** → Cancel schedules, delete recordings/summaries easily  

---

## 📂 Project Structure

```
.
├── app.py                 # Flask backend (main application logic)
├── templates/
│   └── index.html         # Frontend (Bootstrap UI for scheduling, recordings, summaries)
├── static/
│   └── style.css          # Custom CSS
├── recordings/            # Saved audio recordings (WAV/MP3)
├── summaries/             # Saved meeting summaries
├── transcripts/           # (Optional) raw transcripts if needed
├── schedules.json         # Stores scheduled jobs
├── requirements.txt       # Python dependencies
└── README.md              # Project documentation
```

---

## ⚙️ Installation

### 1️⃣ Clone the repository
```bash
git clone https://github.com/your-username/automatic-meeting-agent.git
cd automatic-meeting-agent
```

### 2️⃣ Create a virtual environment
```bash
python -m venv venv
source venv/bin/activate   # Mac/Linux
venv\Scripts\activate      # Windows
```

### 3️⃣ Install dependencies
```bash
pip install -r requirements.txt
```

### 4️⃣ Install FFmpeg
- Download from [FFmpeg official builds](https://www.gyan.dev/ffmpeg/builds/)  
- Update `FFMPEG_PATH` in `app.py` with your installed ffmpeg.exe path.  

### 5️⃣ Setup Chrome & ChromeDriver
- Install Google Chrome  
- ChromeDriver is automatically managed by `webdriver-manager`.  

### 6️⃣ Setup API Key (Gemini AI)
Create a `.env` file in the project root:
```
GEMINI_API_KEY=your_google_gemini_api_key_here
```

---

## ▶️ Running the Project

```bash
python app.py
```

Then open in browser:  
👉 `http://127.0.0.1:5000`

---

## 🖥️ How It Works (Flow)

1. **Frontend (index.html)**  
   - Schedule a meeting (title, link, date, time, participant name)  
   - Or start a meeting immediately  

2. **Backend (app.py)**  
   - Uses **Selenium** to open Chrome & join the meeting  
   - Starts **FFmpeg** to record system/mic audio  
   - Saves recordings into `/recordings`  

3. **Processing**  
   - Whisper → Transcribes speech → text  
   - Gemini AI → Summarizes transcript into clear notes  

4. **Dashboard**  
   - Play recordings inside the page  
   - Download or delete recordings & summaries  
   - Manage upcoming scheduled meetings  

---

## 📦 Requirements (requirements.txt)

```
Flask
apscheduler
selenium
webdriver-manager
psutil
requests
whisper
transformers
torch
google-generativeai
python-dotenv
```

---

## 🚀 Example Usage

- **Schedule a Meeting**  
  Enter details → App will join automatically at the given date & time  

- **Start Now**  
  Paste meeting link → App joins & starts recording immediately  

- **After Meeting**  
  - 🎧 Recording available in the dashboard  
  - 📑 Auto-generated summary saved in `/summaries`  

---

## 🛡️ Security Notes

- Replace `app.secret_key` in `app.py` with a secure random value before production  
- Ensure API keys are stored in `.env` (never commit to GitHub)  
- FFmpeg requires access to system audio devices → check correct device names in config  

---

## 📸 Screenshots (Optional)
(Add here if you want: dashboard, recording list, summary output, etc.)

---

## 🤝 Contribution

Feel free to fork, improve, and submit PRs.  

---

## 📜 License

MIT License © 2025  
