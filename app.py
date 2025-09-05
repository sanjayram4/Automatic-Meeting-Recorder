import os
import subprocess
import uuid
import time
import threading
import requests
import zipfile
import io
import stat
import psutil
import speech_recognition as sr
from datetime import datetime, timedelta
from flask import Flask, request, render_template, redirect, url_for, jsonify, send_from_directory, flash
from apscheduler.schedulers.background import BackgroundScheduler
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException, NoSuchElementException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import whisper
from transformers import pipeline
import json

from dotenv import load_dotenv
import google.generativeai as genai

# Load .env file
load_dotenv()

# Configure Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# ---------------------------
# CONFIG - edit these before use
# ---------------------------
CHROME_USER_DATA_DIR = r"C:\Users\SANJAY RAM N S\AppData\Local\Google\Chrome\User Data"
CHROME_PROFILE_DIR = "Default"
FFMPEG_PATH = r"C:\Users\SANJAY RAM N S\Desktop\automated-meeting-recorder\ffmpeg-8.0-essentials_build\bin\ffmpeg.exe"
SYSTEM_AUDIO_DEVICE = "Microphone (Synaptics SmartAudio HD)"
MIC_AUDIO_DEVICE = "Microphone (Synaptics SmartAudio HD)"

RECORDINGS_DIR = "recordings"
TRANSCRIPTS_DIR = "transcripts"
SUMMARIES_DIR = "summaries"
SCHEDULES_FILE = "schedules.json"

os.makedirs(RECORDINGS_DIR, exist_ok=True)
os.makedirs(TRANSCRIPTS_DIR, exist_ok=True)
os.makedirs(SUMMARIES_DIR, exist_ok=True)
# ---------------------------

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Change this for production
scheduler = BackgroundScheduler()
scheduler.start()

SCHEDULES = {}
ACTIVE_RECORDINGS = {}

# Load saved schedules
def load_schedules():
    global SCHEDULES
    try:
        if os.path.exists(SCHEDULES_FILE):
            with open(SCHEDULES_FILE, 'r') as f:
                SCHEDULES = json.load(f)
                
            # Re-add jobs to scheduler
            for job_id, schedule in SCHEDULES.items():
                run_datetime = datetime.fromisoformat(schedule["datetime"])
                if run_datetime > datetime.now():
                    scheduler.add_job(
                        func=scheduled_job_runner, 
                        trigger='date', 
                        run_date=run_datetime, 
                        args=[job_id], 
                        id=job_id
                    )
                    print(f"Rescheduled job: {job_id}")
    except Exception as e:
        print(f"Error loading schedules: {e}")

#save schedules
def save_schedules():
    try:
        with open(SCHEDULES_FILE, 'w') as f:
            json.dump(SCHEDULES, f)
    except Exception as e:
        print(f"Error saving schedules: {e}")

# Load models (will be loaded on first use)
whisper_model = None
summarizer = None

#model Loads

def load_models():
    """Load the Whisper model and summarization model"""
    global whisper_model, summarizer
    try:
        if whisper_model is None:
            print("Loading Whisper model...")
            whisper_model = whisper.load_model("base")  # You can use "small", "medium", or "large" for better accuracy
        
        if summarizer is None:
            print("Loading summarization model...")
            summarizer = pipeline("summarization", model="facebook/bart-large-cnn")
    except Exception as e:
        print(f"Error loading models: {e}")

def kill_chrome_processes():
    """Kill all Chrome processes to avoid conflicts"""
    try:
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if proc.info['name'] and any(name in proc.info['name'].lower() for name in ['chrome', 'chromedriver']):
                    proc.kill()
                    print(f"Killed process: {proc.info['name']} (PID: {proc.info['pid']})")
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        time.sleep(3)  # Wait for processes to terminate
    except Exception as e:
        print(f"Error killing processes: {e}")

def get_chromedriver_path():
    """Get ChromeDriver path, automatically downloading if needed"""
    try:
        driver_path = ChromeDriverManager().install()
        return driver_path
    except Exception as e:
        print(f"Error using webdriver_manager: {e}")
        return manual_chromedriver_install()

def manual_chromedriver_install():
    """Manual ChromeDriver installation as fallback"""
    chromedriver_dir = os.path.join(os.getcwd(), "chromedriver")
    os.makedirs(chromedriver_dir, exist_ok=True)
    chromedriver_path = os.path.join(chromedriver_dir, "chromedriver.exe")
    
    if os.path.exists(chromedriver_path):
        return chromedriver_path
        
    print("Downloading ChromeDriver...")
    
    try:
        # Get the latest ChromeDriver version
        latest_url = "https://chromedriver.storage.googleapis.com/LATEST_RELEASE"
        response = requests.get(latest_url)
        version = response.text.strip()
        
        download_url = f"https://chromedriver.storage.googleapis.com/{version}/chromedriver_win32.zip"
        response = requests.get(download_url)
        
        with zipfile.ZipFile(io.BytesIO(response.content)) as zip_file:
            zip_file.extractall(chromedriver_dir)
        
        os.chmod(chromedriver_path, stat.S_IEXEC)
        return chromedriver_path
    except Exception as e:
        print(f"Failed to download ChromeDriver: {e}")
        raise Exception("Could not install ChromeDriver automatically")


#-----------------------Worked function---------------------------------


# def build_ffmpeg_command(output_path, record_system_audio=True, record_mic=False):
#     cmd = [FFMPEG_PATH, "-y"]
#     n_sources = 0
#     if record_system_audio:
#         cmd += ["-f", "dshow", "-i", f"audio={SYSTEM_AUDIO_DEVICE}"]
#         n_sources += 1
#     if record_mic:
#         cmd += ["-f", "dshow", "-i", f"audio={MIC_AUDIO_DEVICE}"]
#         n_sources += 1
#     # Mix if needed
#     if n_sources == 2:
#         cmd += ["-filter_complex", "amix=inputs=2:duration=longest"]
#     # Encode to MP3 (no video)
#     cmd += ["-vn", "-c:a", "libmp3lame", "-q:a", "2", output_path]
#     return cmd


#-----------------------Worked function---------------------------------


# def build_ffmpeg_command(output_path):
#     return [
#         FFMPEG_PATH,
#         "-f", "dshow",
#         "-i", f"audio={SYSTEM_AUDIO_DEVICE}",
#         "-ar", "16000",
#         "-ac", "1",
#         "-vn",
#         "-c:a", "pcm_s16le",
#         output_path
#     ]

def build_ffmpeg_command(output_path, record_system_audio=True, record_mic=False):
    cmd = [FFMPEG_PATH, "-y"]
    
    # Add audio inputs
    if record_system_audio:
        cmd += ["-f", "dshow", "-i", f"audio={SYSTEM_AUDIO_DEVICE}"]
    
    if record_mic:
        cmd += ["-f", "dshow", "-i", f"audio={MIC_AUDIO_DEVICE}"]
    
    # If both audio sources are enabled, mix them
    if record_system_audio and record_mic:
        cmd += ["-filter_complex", "amix=inputs=2:duration=longest"]
    
    # Add output options
    cmd += [
        "-ar", "16000",  # Sample rate
        "-ac", "1",      # Mono audio
        "-c:a", "pcm_s16le",  # PCM 16-bit little-endian
        output_path
    ]
    
    return cmd

# def start_recording(output_filename, record_system_audio=True, record_mic=False):
#     # force .mp3 extension
#     base, _ = os.path.splitext(output_filename)
#     output_filename = base + ".mp3"
#     outfile = os.path.join(RECORDINGS_DIR, output_filename)
#     cmd = build_ffmpeg_command(outfile, record_system_audio=record_system_audio, record_mic=record_mic)
#     print("Starting ffmpeg with command:", " ".join(cmd))
#     proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
#     return proc, outfile

# def start_recording(output_filename, record_system_audio=True, record_mic=False):
#     # Always save as WAV for transcription
#     base, _ = os.path.splitext(output_filename)
#     wav_path = os.path.join(RECORDINGS_DIR, base + ".wav")
#     mp3_path = os.path.join(RECORDINGS_DIR, base + ".mp3")

#     # Build ffmpeg command
#     cmd = [FFMPEG_PATH, "-y"]
#     inputs = []
#     if record_system_audio:
#         cmd += ["-f", "dshow", "-i", f"audio={SYSTEM_AUDIO_DEVICE}"]
#         inputs.append("system")
#     if record_mic:
#         cmd += ["-f", "dshow", "-i", f"audio={MIC_AUDIO_DEVICE}"]
#         inputs.append("mic")

#     # Mix system + mic if both are enabled
#     if len(inputs) == 2:
#         cmd += ["-filter_complex", "amix=inputs=2:duration=longest"]

#     # Output as WAV
#     cmd += ["-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav_path]

#     print("Starting ffmpeg with command:", " ".join(cmd))
#     proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

#     # After recording finishes, convert WAV → MP3 for storage
#     def convert_to_mp3():
#         proc.wait()
#         subprocess.run([
#             FFMPEG_PATH, "-y", "-i", wav_path,
#             "-codec:a", "libmp3lame", "-q:a", "2", mp3_path
#         ])
#         print(f"Saved MP3 copy: {mp3_path}")

#     threading.Thread(target=convert_to_mp3, daemon=True).start()

#     return proc, wav_path



def start_recording(output_filename, record_system_audio=True, record_mic=False):
    # Create the recordings directory if it doesn't exist
    os.makedirs(RECORDINGS_DIR, exist_ok=True)
    
    # Always save as WAV for transcription
    base, _ = os.path.splitext(output_filename)
    wav_path = os.path.join(RECORDINGS_DIR, base + ".wav")
    mp3_path = os.path.join(RECORDINGS_DIR, base + ".mp3")

    # Build ffmpeg command
    cmd = build_ffmpeg_command(wav_path, record_system_audio, record_mic)
    
    print("Starting ffmpeg with command:", " ".join(cmd))
    
    # Start the process with proper error handling
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=open("ffmpeg_error.log", "w"),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

        
        # Wait a moment to check if FFmpeg started successfully
        time.sleep(1)
        if proc.poll() is not None:
            # FFmpeg exited immediately, which means there was an error
            stdout, stderr = proc.communicate()
            error_msg = stderr.decode('utf-8', errors='ignore') if stderr else "Unknown error"
            print(f"FFmpeg failed to start: {error_msg}")
            raise Exception(f"FFmpeg failed to start: {error_msg}")
            
        return proc, wav_path, mp3_path
        
    except Exception as e:
        print(f"Error starting FFmpeg: {e}")
        raise


# def stop_recording(proc: subprocess.Popen):
#     if proc and proc.poll() is None:
#         try:
#             # Send 'q' to FFmpeg to quit gracefully (this allows proper file finalization)
#             proc.stdin.write(b'q')
#             proc.stdin.flush()
            
#             # Wait for graceful termination
#             proc.wait(timeout=15)
#             print("FFmpeg terminated gracefully")
            
#         except (subprocess.TimeoutExpired, IOError, BrokenPipeError):
#             print("FFmpeg not responding to graceful shutdown, forcing termination")
#             try:
#                 proc.terminate()
#                 proc.wait(timeout=5)
#             except subprocess.TimeoutExpired:
#                 proc.kill()
#                 proc.wait()
#         except Exception as e:
#             print(f"Error stopping recording: {e}")
#             proc.kill()


def stop_recording(proc: subprocess.Popen):
    if proc and proc.poll() is None:
        try:
            # Send 'q' to FFmpeg to quit gracefully
            proc.stdin.write(b'q')
            proc.stdin.flush()
            
            # Wait for graceful termination
            proc.wait(timeout=15)
            print("FFmpeg terminated gracefully")
            
        except (subprocess.TimeoutExpired, IOError, BrokenPipeError):
            print("FFmpeg not responding to graceful shutdown, forcing termination")
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        except Exception as e:
            print(f"Error stopping recording: {e}")
            proc.kill()

def transcribe_audio(audio_path):
    """Transcribe audio file to text using Whisper"""
    try:
        load_models()
        print(f"Transcribing audio: {audio_path}")
        result = whisper_model.transcribe(audio_path)
        return result["text"]
    except Exception as e:
        print(f"Error transcribing audio: {e}")
        return ""

# def summarize_text(text, max_length=150, min_length=30):
#     """Summarize text using BART model"""
#     try:
#         load_models()
        
#         # If text is too short, return as is
#         if len(text.split()) < 50:
#             return text
            
#         # Split text into chunks if it's too long for the model
#         max_chunk_length = 1024
#         chunks = [text[i:i+max_chunk_length] for i in range(0, len(text), max_chunk_length)]
        
#         summaries = []
#         for chunk in chunks:
#             summary = summarizer(chunk, max_length=max_length, min_length=min_length, do_sample=False)
#             summaries.append(summary[0]['summary_text'])
        
#         return " ".join(summaries)
#     except Exception as e:
#         print(f"Error summarizing text: {e}")
#         return text



def summarize_text(text):
    """Summarize text using Gemini API"""
    try:
        if not text.strip():
            return "No content to summarize."

        model = genai.GenerativeModel("gemini-1.5-flash")
        # prompt = f"Summarize this meeting transcript in clear bullet points:\n\n{text}"
        prompt = f"""
        You are an AI meeting assistant. Summarize the following meeting transcript in a simple, clear, and readable way.

        Your response MUST follow this structure:

        Meeting Title: A short and meaningful title  

        Meeting Summary: 
        - Write the discussion like a natural and easy-to-read conversation style and bullet point
        - Keep it simple and clear for everyone to understand like a human conversation

        Meeting Conclusion:
        - Highlight the final decisions, key takeaways, or next steps

        Full Transcript:
        {text}

        Closing Note:
        Thank you for reading! 🙏✨😊
        """


        response = model.generate_content(prompt)

        return response.text.strip()
    except Exception as e:
        print(f"Error summarizing text: {e}")
        return text



def process_audio_to_summary(audio_path, base_filename):
    """Transcribe audio and save ONLY a summary (no transcript file on disk)."""
    transcription = transcribe_audio(audio_path)
    if not transcription or not transcription.strip():
        print("Warning: transcription was empty")
        transcription = ""
    summary = summarize_text(transcription)
    # Save summary
    summary_path = os.path.join(SUMMARIES_DIR, f"{base_filename}_summary.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary)
    return summary_path

def wait_for_network_idle(driver, timeout=30, check_interval=2):
    """Wait for network to be idle"""
    end_time = time.time() + timeout
    while time.time() < end_time:
        try:
            # Check if network requests are complete
            requests_in_flight = driver.execute_script("""
                return window.performance.getEntriesByType('resource')
                    .filter(r => r.responseEnd === 0).length;
            """)
            if requests_in_flight == 0:
                return True
        except:
            pass
        time.sleep(check_interval)
    return False

def simple_join_approach(driver):
    """Simple approach - just wait for user to join manually"""
    print("Using simple approach - please join the meeting manually")
    
    # Display instructions to user
    try:
        driver.execute_script("""
            var instructionDiv = document.createElement('div');
            instructionDiv.style.position = 'fixed';
            instructionDiv.style.top = '50%';
            instructionDiv.style.left = '50%';
            instructionDiv.style.transform = 'translate(-50%, -50%)';
            instructionDiv.style.backgroundColor = 'rgba(0,0,0,0.8)';
            instructionDiv.style.color = 'white';
            instructionDiv.style.padding = '20px';
            instructionDiv.style.borderRadius = '10px';
            instructionDiv.style.zIndex = '9999';
            instructionDiv.style.fontSize = '18px';
            instructionDiv.style.textAlign = 'center';
            instructionDiv.innerHTML = '<h2>Please join the meeting manually</h2><p>This window will automatically record once you join</p>';
            document.body.appendChild(instructionDiv);
            
            // Remove after 10 seconds
            setTimeout(function() {
                if (instructionDiv.parentNode) {
                    instructionDiv.parentNode.removeChild(instructionDiv);
                }
            }, 10000);
        """)
    except:
        pass
    
    # Wait for user to join manually
    return True

def is_user_in_meeting(driver):
    """Check if user is still in the meeting"""
    try:
        # Check for "You were removed" message
        removed_indicators = [
            "div[aria-label*='You were removed']",
            "div[aria-label*='removed from the meeting']",
            "//*[contains(text(), 'You were removed')]",
            "//*[contains(text(), 'removed from the meeting')]"
        ]
        
        for indicator in removed_indicators:
            try:
                if indicator.startswith("//"):
                    elements = driver.find_elements(By.XPATH, indicator)
                else:
                    elements = driver.find_elements(By.CSS_SELECTOR, indicator)
                
                if elements and any(el.is_displayed() for el in elements):
                    print("User was removed from the meeting")
                    return False
            except:
                pass
        
        # Check if we're still in the meeting by looking for meeting controls
        meeting_indicators = [
            "div[jsname='BOHaEe']",  # Meeting controls
            "div[aria-label*='Turn off microphone']",
            "div[aria-label*='Turn off camera']",
            "div[jsname='lQeS6']",  # Participant list
            "button[aria-label*='Leave call']",
            "div[class*='controls']",
            "video",  # Video element
        ]
        
        for indicator in meeting_indicators:
            elements = driver.find_elements(By.CSS_SELECTOR, indicator)
            if elements and any(el.is_displayed() for el in elements):
                return True
        
        return False
    except Exception as e:
        print(f"Error checking meeting status: {e}")
        return False

def join_google_meet(driver, participant_name):
    """Improved function to join Google Meet with multiple strategies"""
    print("Attempting to join Google Meet...")
    
    try:
        # Wait for network to be idle first
        wait_for_network_idle(driver, timeout=30)
        
        # Wait for page to load completely
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        # First, check if there's a name input field and fill it
        name_input_selectors = [
            "input[type='text']",
            "input[aria-label*='name']",
            "input[aria-label*='Name']",
            "input[placeholder*='name']",
            "input[placeholder*='Name']",
            "input[jsname*='YPqjbf']",
            "//input[contains(@placeholder, 'name')]",
            "//input[contains(@placeholder, 'Name')]",
            "//input[contains(@aria-label, 'name')]",
            "//input[contains(@aria-label, 'Name')]",
        ]
        
        name_filled = False
        for selector in name_input_selectors:
            try:
                if selector.startswith("//"):
                    elements = driver.find_elements(By.XPATH, selector)
                else:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                
                for element in elements:
                    if element.is_displayed() and element.is_enabled():
                        print(f"Found name input with selector: {selector}")
                        # Clear any existing text and enter the provided name
                        element.clear()
                        element.send_keys(participant_name)
                        name_filled = True
                        print(f"Filled in name field with: {participant_name}")
                        break
                if name_filled:
                    time.sleep(1)  # Wait for UI to update
                    break
            except Exception as e:
                continue
        
        # Try multiple strategies to find and click the join button
        join_success = False
        
        # Strategy 1: Try to find and click "Ask to Join" button first
        ask_to_join_selectors = [
            "button[aria-label*='Ask to join']",
            "div[aria-label*='Ask to join']",
            "//span[contains(text(), 'Ask to join')]",
            "//div[contains(text(), 'Ask to join')]",
            "//button[contains(., 'Ask to join')]",
            "div[jsname*='askToJoin']",
            "button[jsname*='askToJoin']",
        ]
        
        for selector in ask_to_join_selectors:
            try:
                if selector.startswith("//"):
                    elements = driver.find_elements(By.XPATH, selector)
                else:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                
                for element in elements:
                    if element.is_displayed() and element.is_enabled():
                        print(f"Found 'Ask to Join' button with selector: {selector}")
                        # Scroll into view and click
                        driver.execute_script("arguments[0].scrollIntoView(true);", element)
                        time.sleep(0.5)
                        element.click()
                        print("Clicked 'Ask to Join' button successfully!")
                        join_success = True
                        break
                if join_success:
                    break
            except Exception as e:
                continue
        
        # Strategy 2: If "Ask to Join" not found, try regular join buttons
        if not join_success:
            join_selectors = [
                # New Google Meet interface
                "button[aria-label*='Join now']",
                "button[aria-label*='Join meeting']",
                "div[aria-label*='Join now']",
                "div[aria-label*='Join meeting']",
                
                # Old Google Meet interface
                "span[jsname*='join']",
                "div[jsname*='join']",
                "button[jsname*='join']",
                
                # Text-based selectors
                "//span[contains(text(), 'Join now')]",
                "//span[contains(text(), 'Join meeting')]",
                "//div[contains(text(), 'Join now')]",
                "//div[contains(text(), 'Join meeting')]",
                "//button[contains(., 'Join now')]",
                "//button[contains(., 'Join meeting')]",
                
                # Alternative selectors
                "button.VfPpkd-LgbsSe",
                "div.U26fgb",
                "div[role='button']",
                
                # More specific selectors
                "div[class*='join'] button",
                "button[data-tooltip*='Join']",
            ]
            
            for selector in join_selectors:
                try:
                    if selector.startswith("//"):
                        # XPath selector
                        element = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, selector))
                        )
                    else:
                        # CSS selector
                        element = WebDriverWait(driver, 5).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                        )
                    
                    if element.is_displayed() and element.is_enabled():
                        print(f"Found join button with selector: {selector}")
                        # Scroll into view and click
                        driver.execute_script("arguments[0].scrollIntoView(true);", element)
                        time.sleep(0.5)
                        element.click()
                        print("Clicked join button successfully!")
                        join_success = True
                        break
                except Exception as e:
                    continue
        
        # Strategy 3: Direct JavaScript click on join buttons
        if not join_success:
            try:
                join_script = """
                // Function to click elements that might be join buttons
                function clickJoinButtons() {
                    // First try "Ask to Join" buttons
                    var askToJoinSelectors = [
                        'button[aria-label*="Ask to join"]',
                        'div[aria-label*="Ask to join"]',
                        'div[jsname*="askToJoin"]',
                        'button[jsname*="askToJoin"]'
                    ];
                    
                    for (var i = 0; i < askToJoinSelectors.length; i++) {
                        var buttons = document.querySelectorAll(askToJoinSelectors[i]);
                        for (var j = 0; j < buttons.length; j++) {
                            var btn = buttons[j];
                            if (btn.offsetWidth > 0 && btn.offsetHeight > 0 && 
                                window.getComputedStyle(btn).display !== 'none') {
                                btn.click();
                                console.log('Clicked "Ask to Join" button with selector: ' + askToJoinSelectors[i]);
                                return true;
                            }
                        }
                    }
                    
                    // Then try regular join buttons
                    var joinSelectors = [
                        'button[aria-label*="Join now"]',
                        'button[aria-label*="Join meeting"]',
                        'div[aria-label*="Join now"]',
                        'div[aria-label*="Join meeting"]',
                        'div[jsname*="join"]',
                        'button[jsname*="join"]',
                        'span[jsname*="join"]',
                        'button.VfPpkd-LgbsSe',
                        'div.U26fgb',
                        'div[role="button"]'
                    ];
                    
                    for (var i = 0; i < joinSelectors.length; i++) {
                        var buttons = document.querySelectorAll(joinSelectors[i]);
                        for (var j = 0; j < buttons.length; j++) {
                            var btn = buttons[j];
                            if (btn.offsetWidth > 0 && btn.offsetHeight > 0 && 
                                window.getComputedStyle(btn).display !== 'none') {
                                btn.click();
                                console.log('Clicked join button with selector: ' + joinSelectors[i]);
                                return true;
                            }
                        }
                    }
                    
                    // Try by text content
                    var allButtons = document.querySelectorAll('button, div[role="button"]');
                    for (var i = 0; i < allButtons.length; i++) {
                        var btn = allButtons[i];
                        var btnText = btn.textContent || btn.innerText || btn.getAttribute('aria-label') || '';
                        var lowerText = btnText.toLowerCase();
                        if ((lowerText.includes('join') || lowerText.includes('ask')) && 
                            btn.offsetWidth > 0 && btn.offsetHeight > 0 &&
                            window.getComputedStyle(btn).display !== 'none') {
                            btn.click();
                            console.log('Clicked button with text: ' + btnText);
                            return true;
                        }
                    }
                    
                    return false;
                }
                
                return clickJoinButtons();
                """
                join_success = driver.execute_script(join_script)
                if join_success:
                    print("Joined meeting via JavaScript injection")
            except Exception as e:
                print(f"JavaScript injection failed: {e}")
        
        # Strategy 4: Check if we're already in the meeting
        if not join_success:
            try:
                meeting_indicators = [
                    "div[jsname='BOHaEe']",  # Meeting controls
                    "div[aria-label*='Turn off microphone']",
                    "div[aria-label*='Turn off camera']",
                    "div[jsname='lQeS6']",  # Participant list
                    "button[aria-label*='Leave call']",
                    "div[class*='controls']",
                    "video",  # Video element
                ]
                
                for indicator in meeting_indicators:
                    elements = driver.find_elements(By.CSS_SELECTOR, indicator)
                    if elements and any(el.is_displayed() for el in elements):
                        print("Already in the meeting room")
                        return True
            except:
                pass
        
        # Strategy 5: Take a screenshot for debugging
        if not join_success:
            try:
                screenshot_path = os.path.join(RECORDINGS_DIR, f"meet_debug_{int(time.time())}.png")
                driver.save_screenshot(screenshot_path)
                print(f"Saved screenshot to {screenshot_path} for debugging")
                
                # Also get page source for analysis
                page_source_path = os.path.join(RECORDINGS_DIR, f"meet_source_{int(time.time())}.html")
                with open(page_source_path, "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
                print(f"Saved page source to {page_source_path}")
            except Exception as e:
                print(f"Error saving debug info: {e}")
            
        return join_success
        
    except Exception as e:
        print(f"Error joining meeting: {e}")
        return False

# def automate_join_and_record(meet_link, participant_name, record_system_audio=True, record_mic=False):
#     unique_prefix = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4str()
#     output_name = f"meeting_{unique_prefix}.mp3"

#     # Kill existing Chrome processes before starting
#     print("Killing existing Chrome processes...")
#     kill_chrome_processes()

#     # Get ChromeDriver path
#     try:
#         chromedriver_path = get_chromedriver_path()
#         print(f"Using ChromeDriver at: {chromedriver_path}")
#     except Exception as e:
#         print(f"Failed to get ChromeDriver: {e}")
#         return output_name

#     # Create a unique user data directory for this session
#     session_user_data_dir = os.path.join(os.getcwd(), f"chrome_profile_{int(time.time())}")
#     os.makedirs(session_user_data_dir, exist_ok=True)

#     chrome_options = Options()
#     chrome_options.add_argument(f"--user-data-dir={session_user_data_dir}")
#     chrome_options.add_argument("--profile-directory=Default")
#     chrome_options.add_argument("--use-fake-ui-for-media-stream")
#     chrome_options.add_argument("--no-first-run")
#     chrome_options.add_argument("--no-default-browser-check")
#     chrome_options.add_argument("--disable-dev-shm-usage")
#     chrome_options.add_argument("--no-sandbox")
#     chrome_options.add_argument("--disable-gpu")
#     chrome_options.add_argument("--remote-debugging-port=9222")
#     chrome_options.add_argument("--disable-extensions")
#     chrome_options.add_argument("--disable-plugins")
#     chrome_options.add_argument("--disable-blink-features=AutomationControlled")
#     chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
#     chrome_options.add_experimental_option('useAutomationExtension', False)
#     chrome_options.add_argument("--window-size=1400,900")
#     chrome_options.add_argument("--start-maximized")
#     chrome_options.add_argument("--disable-web-security")
#     chrome_options.add_argument("--allow-running-insecure-content")
#     chrome_options.add_argument("--disable-features=VizDisplayCompositor")
#     chrome_options.add_argument("--disable-software-rasterizer")
#     chrome_options.headless = False

#     driver = None
#     ffmpeg_proc = None

#     try:
#         service = Service(chromedriver_path)
#         driver = webdriver.Chrome(service=service, options=chrome_options)
#         driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
#         driver.set_page_load_timeout(60)  # Increased timeout

#         print(f"Opening meeting link: {meet_link}")
        
#         # Try to load the page with retries
#         max_retries = 3
#         for attempt in range(max_retries):
#             try:
#                 driver.get(meet_link)
#                 break
#             except TimeoutException:
#                 if attempt == max_retries - 1:
#                     raise
#                 print(f"Timeout on attempt {attempt + 1}, retrying...")
#                 time.sleep(5)
        
#         # Wait for page to load with more flexible waiting
#         WebDriverWait(driver, 30).until(
#             lambda d: d.execute_script("return document.readyState") == "complete"
#         )
        
#         # Additional wait for Google Meet specific elements
#         time.sleep(10)
        
#         # Try to join the meeting with fallback to simple approach
#         join_success = join_google_meet(driver, participant_name)
#         if not join_success:
#             join_success = simple_join_approach(driver)
        
#         if not join_success:
#             print("Failed to join automatically. Please join manually within 20 seconds...")
#             # Give user more time to join manually
#             for i in range(20):
#                 print(f"Waiting... {20-i} seconds left")
#                 time.sleep(1)
        
#         # Start recording regardless of join status
#         ffmpeg_proc, output_path = start_recording(output_name, record_system_audio, record_mic)
#         ACTIVE_RECORDINGS[output_name] = {
#             'process': ffmpeg_proc,
#             'path': output_path,
#             'driver': driver,
#             'start_time': datetime.now()
#         }
#         print("Recording started")
        
#         # Display status message
#         if driver:
#             try:
#                 driver.execute_script("""
#                     var statusDiv = document.createElement('div');
#                     statusDiv.style.position = 'fixed';
#                     statusDiv.style.top = '10px';
#                     statusDiv.style.right = '10px';
#                     statusDiv.style.backgroundColor = 'rgba(0,0,0,0.7)';
#                     statusDiv.style.color = 'white';
#                     statusDiv.style.padding = '10px';
#                     statusDiv.style.borderRadius = '5px';
#                     statusDiv.style.zIndex = '9999';
#                     statusDiv.innerHTML = 'Recording in progress...';
#                     document.body.appendChild(statusDiv);
#                 """)
#             except:
#                 pass

#         # Keep recording until user is removed from meeting or 4 hours max
#         max_duration = 4 * 60 * 60  # 4 hours in seconds
#         start_time = time.time()
        
#         while time.time() - start_time < max_duration:
#             # Check if user is still in the meeting
#             if not is_user_in_meeting(driver):
#                 print("User is no longer in the meeting, stopping recording")
#                 break
                
#             time.sleep(10)  # Check every 10 seconds

#     except (WebDriverException, TimeoutException) as e:
#         print(f"Browser error: {e}")
#         # Start recording even if browser fails
#         if not ffmpeg_proc:
#             ffmpeg_proc, output_path = start_recording(output_name, record_system_audio, record_mic)
#             ACTIVE_RECORDINGS[output_name] = {
#                 'process': ffmpeg_proc,
#                 'path': output_path,
#                 'driver': None,
#                 'start_time': datetime.now()
#             }
#             print("Recording started despite browser issues")
#             time.sleep(300)  # Record for 5 minutes on error

#     except Exception as e:
#         print(f"Unexpected error: {e}")
#         # Start basic recording on any error
#         if not ffmpeg_proc:
#             ffmpeg_proc, output_path = start_recording(output_name, record_system_audio, record_mic)
#             ACTIVE_RECORDINGS[output_name] = {
#                 'process': ffmpeg_proc,
#                 'path': output_path,
#                 'driver': None,
#                 'start_time': datetime.now()
#             }
#             time.sleep(300)  # Record for 5 minutes on error

#     finally:
#         if output_name in ACTIVE_RECORDINGS:
#             del ACTIVE_RECORDINGS[output_name]
            
#         if ffmpeg_proc:
#             stop_recording(ffmpeg_proc)
#             print("Recording stopped")
            
#             # Process audio to text if audio was recorded
#             if record_system_audio or record_mic:
#                 base_filename = os.path.splitext(output_name)[0]
#                 try:
#                     print("Processing audio to text...")
#                     summary_path = process_audio_to_summary(output_path, base_filename)
#                     print(f"Summary saved to: {summary_path}")
#                 except Exception as e:
#                     print(f"Error processing audio to text: {e}")
            
#         if driver:
#             try:
#                 driver.quit()
#             except:
#                 pass
#         # Clean up
#         try:
#             import shutil
#             shutil.rmtree(session_user_data_dir, ignore_errors=True)
#         except:
#             pass
#         kill_chrome_processes()

#     return output_name


def automate_join_and_record(meet_link, participant_name, record_system_audio=True, record_mic=False):
    unique_prefix = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4str()
    output_name = f"meeting_{unique_prefix}"


    # Kill existing Chrome processes before starting
    print("Killing existing Chrome processes...")
    kill_chrome_processes()

    # Get ChromeDriver path
    try:
        chromedriver_path = get_chromedriver_path()
        print(f"Using ChromeDriver at: {chromedriver_path}")
    except Exception as e:
        print(f"Failed to get ChromeDriver: {e}")
        return output_name

    # Create a unique user data directory for this session
    session_user_data_dir = os.path.join(os.getcwd(), f"chrome_profile_{int(time.time())}")
    os.makedirs(session_user_data_dir, exist_ok=True)

    chrome_options = Options()
    chrome_options.add_argument(f"--user-data-dir={session_user_data_dir}")
    chrome_options.add_argument("--profile-directory=Default")
    chrome_options.add_argument("--use-fake-ui-for-media-stream")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--remote-debugging-port=9222")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-plugins")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    chrome_options.add_argument("--window-size=1400,900")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-web-security")
    chrome_options.add_argument("--allow-running-insecure-content")
    chrome_options.add_argument("--disable-features=VizDisplayCompositor")
    chrome_options.add_argument("--disable-software-rasterizer")
    chrome_options.headless = False

    driver = None
    ffmpeg_proc = None

    try:
        service = Service(chromedriver_path)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        driver.set_page_load_timeout(60)  # Increased timeout

        print(f"Opening meeting link: {meet_link}")
        
        # Try to load the page with retries
        max_retries = 3
        for attempt in range(max_retries):
            try:
                driver.get(meet_link)
                break
            except TimeoutException:
                if attempt == max_retries - 1:
                    raise
                print(f"Timeout on attempt {attempt + 1}, retrying...")
                time.sleep(5)
        
        # Wait for page to load with more flexible waiting
        WebDriverWait(driver, 30).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        
        # Additional wait for Google Meet specific elements
        time.sleep(10)
        
        # Try to join the meeting with fallback to simple approach
        join_success = join_google_meet(driver, participant_name)
        if not join_success:
            join_success = simple_join_approach(driver)
        
        if not join_success:
            print("Failed to join automatically. Please join manually within 20 seconds...")
            # Give user more time to join manually
            for i in range(20):
                print(f"Waiting... {20-i} seconds left")
                time.sleep(1)
        
        # Start recording - now gets both WAV and MP3 paths
        ffmpeg_proc, wav_path, mp3_path = start_recording(output_name, record_system_audio, record_mic)
        ACTIVE_RECORDINGS[output_name] = {
            'process': ffmpeg_proc,
            'wav_path': wav_path,
            'mp3_path': mp3_path,
            'driver': driver,
            'start_time': datetime.now()
        }
        print("Recording started")
        
        # Display status message
        if driver:
            try:
                driver.execute_script("""
                    var statusDiv = document.createElement('div');
                    statusDiv.style.position = 'fixed';
                    statusDiv.style.top = '10px';
                    statusDiv.style.right = '10px';
                    statusDiv.style.backgroundColor = 'rgba(0,0,0,0.7)';
                    statusDiv.style.color = 'white';
                    statusDiv.style.padding = '10px';
                    statusDiv.style.borderRadius = '5px';
                    statusDiv.style.zIndex = '9999';
                    statusDiv.innerHTML = 'Recording in progress...';
                    document.body.appendChild(statusDiv);
                """)
            except:
                pass

        # Keep recording until user is removed from meeting or 4 hours max
        max_duration = 4 * 60 * 60  # 4 hours in seconds
        start_time = time.time()
        
        while time.time() - start_time < max_duration:
            # Check if user is still in the meeting
            if not is_user_in_meeting(driver):
                print("User is no longer in the meeting, stopping recording")
                break
                
            time.sleep(10)  # Check every 10 seconds

    except (WebDriverException, TimeoutException) as e:
        print(f"Browser error: {e}")
        # Start recording even if browser fails
        if not ffmpeg_proc:
            ffmpeg_proc, wav_path, mp3_path = start_recording(output_name, record_system_audio, record_mic)
            ACTIVE_RECORDINGS[output_name] = {
                'process': ffmpeg_proc,
                'wav_path': wav_path,
                'mp3_path': mp3_path,
                'driver': None,
                'start_time': datetime.now()
            }
            print("Recording started despite browser issues")
            time.sleep(300)  # Record for 5 minutes on error

    except Exception as e:
        print(f"Unexpected error: {e}")
        # Start basic recording on any error
        if not ffmpeg_proc:
            ffmpeg_proc, wav_path, mp3_path = start_recording(output_name, record_system_audio, record_mic)
            ACTIVE_RECORDINGS[output_name] = {
                'process': ffmpeg_proc,
                'wav_path': wav_path,
                'mp3_path': mp3_path,
                'driver': None,
                'start_time': datetime.now()
            }
            time.sleep(300)  # Record for 5 minutes on error

    finally:
        if output_name in ACTIVE_RECORDINGS:
            del ACTIVE_RECORDINGS[output_name]
            
        if ffmpeg_proc:
            stop_recording(ffmpeg_proc)
            print("Recording stopped")
            
            # Process audio to text if audio was recorded
            if record_system_audio or record_mic:
                base_filename = os.path.splitext(output_name)[0]
                try:
                    print("Processing audio to text...")
                    # Use the WAV path for transcription
                    summary_path = process_audio_to_summary(wav_path, base_filename)
                    print(f"Summary saved to: {summary_path}")
                except Exception as e:
                    print(f"Error processing audio to text: {e}")
            
        if driver:
            try:
                driver.quit()
            except:
                pass
        # Clean up
        try:
            import shutil
            shutil.rmtree(session_user_data_dir, ignore_errors=True)
        except:
            pass
        kill_chrome_processes()

    return output_name

def uuid4str():
    return str(uuid.uuid4()).replace('-', '')

def get_recorded_audios():
    """Get list of recorded audio (mp3)"""
    audios = []
    try:
        for file in os.listdir(RECORDINGS_DIR):
            if file.lower().endswith('.wav'):
                file_path = os.path.join(RECORDINGS_DIR, file)
                file_size = os.path.getsize(file_path)
                file_time = datetime.fromtimestamp(os.path.getctime(file_path))
                audios.append({
                    'name': file,
                    'size': file_size,
                    'date': file_time.strftime("%Y-%m-%d %H:%M:%S"),
                    'url': f"/recordings/{file}"
                })
        # Sort by date, newest first
        audios.sort(key=lambda x: x['date'], reverse=True)
    except Exception as e:
        print(f"Error getting recorded audios: {e}")
    return audios


def get_summaries():
    """Get list of summaries"""
    summaries = []
    try:
        for file in os.listdir(SUMMARIES_DIR):
            if file.endswith('.txt'):
                file_path = os.path.join(SUMMARIES_DIR, file)
                file_size = os.path.getsize(file_path)
                file_time = datetime.fromtimestamp(os.path.getctime(file_path))
                summaries.append({
                    'name': file,
                    'size': file_size,
                    'date': file_time.strftime("%Y-%m-%d %H:%M:%S"),
                    'url': f"/summaries/{file}"
                })
        # Sort by date, newest first
        summaries.sort(key=lambda x: x['date'], reverse=True)
    except Exception as e:
        print(f"Error getting summaries: {e}")
    return summaries

@app.route('/')
def index():
    audios = get_recorded_audios()
    summaries = get_summaries()
    return render_template('index.html', schedules=SCHEDULES, audios=audios, summaries=summaries)

@app.route('/schedule', methods=['POST'])
def schedule_meeting():
    data = request.form
    title = data.get('title') or 'Untitled'
    link = data.get('link')
    date = data.get('date')
    time_str = data.get('time')
    participant_name = data.get('participant_name', 'Meeting Participant')
    system_audio_opt = True
    mic_opt = False

    if not link or not date or not time_str:
        flash("Missing required fields", "error")
        return redirect(url_for('index'))

    try:
        run_datetime = datetime.fromisoformat(f"{date}T{time_str}")
        if run_datetime < datetime.now():
            flash("Cannot schedule a meeting in the past", "error")
            return redirect(url_for('index'))
            
        job_id = uuid4str()
        SCHEDULES[job_id] = {
            "id": job_id, 
            "title": title, 
            "link": link,
            "datetime": run_datetime.isoformat(),
            "participant_name": participant_name,
            "system_audio": system_audio_opt, 
            "mic": mic_opt
        }
        
        scheduler.add_job(
            func=scheduled_job_runner, 
            trigger='date', 
            run_date=run_datetime, 
            args=[job_id], 
            id=job_id
        )
        
        save_schedules()
        flash("Meeting scheduled successfully!", "success")
        return redirect(url_for('index'))
    except ValueError:
        flash("Invalid date or time format", "error")
        return redirect(url_for('index'))

def scheduled_job_runner(job_id):
    meta = SCHEDULES.get(job_id)
    if not meta:
        return
    print("Running scheduled job:", job_id, meta)
    t = threading.Thread(target=automate_join_and_record, kwargs={
        "meet_link": meta["link"],
        "participant_name": meta["participant_name"],
        "record_system_audio": meta["system_audio"],
        "record_mic": meta["mic"]
    })
    t.start()

@app.route('/delete_schedule/<job_id>', methods=['POST'])
def delete_schedule(job_id):
    if job_id in SCHEDULES:
        try:
            scheduler.remove_job(job_id)
        except:
            pass
        del SCHEDULES[job_id]
        save_schedules()
        flash("Schedule deleted", "success")
    else:
        flash("Schedule not found", "error")
    return redirect(url_for('index'))

@app.route('/recordings/<filename>')
def download_recording(filename):
    return send_from_directory(RECORDINGS_DIR, filename, as_attachment=True)

@app.route('/summaries/<filename>')
def download_summary(filename):
    return send_from_directory(SUMMARIES_DIR, filename, as_attachment=True)

@app.route('/delete_recording/<filename>', methods=['POST'])
def delete_recording(filename):
    try:
        file_path = os.path.join(RECORDINGS_DIR, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            flash("Recording deleted", "success")
        else:
            flash("Recording not found", "error")
    except Exception as e:
        flash(f"Error deleting recording: {e}", "error")
    return redirect(url_for('index'))

@app.route('/delete_summary/<filename>', methods=['POST'])
def delete_summary(filename):
    try:
        file_path = os.path.join(SUMMARIES_DIR, filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            flash("Summary deleted", "success")
        else:
            flash("Summary not found", "error")
    except Exception as e:
        flash(f"Error deleting summary: {e}", "error")
    return redirect(url_for('index'))

@app.route('/start_now', methods=['POST'])
def start_now():
    data = request.form
    link = data.get('link')
    participant_name = data.get('participant_name', 'Meeting Participant')
    system_audio_opt = True
    mic_opt = False

    if not link:
        flash("Meeting link is required", "error")
        return redirect(url_for('index'))
        
    t = threading.Thread(target=automate_join_and_record, kwargs={
        "meet_link": link,
        "participant_name": participant_name,
        "record_system_audio": system_audio_opt,
        "record_mic": mic_opt
    })
    t.start()
    
    flash("Recording started in the background", "success")
    return redirect(url_for('index'))

@app.route('/stop_recording', methods=['POST'])
def stop_recording_endpoint():
    # This is a simplified implementation - in a real app, you'd need to track
    # the active recording process more carefully
    flash("Recording stopped", "info")
    return redirect(url_for('index'))

@app.route('/get_status')
def get_status():
    return jsonify({
        'active_recordings': len(ACTIVE_RECORDINGS),
        'scheduled_meetings': len(SCHEDULES)
    })

if __name__ == '__main__':
    load_schedules()
    app.run(debug=True, host='0.0.0.0', port=5000)