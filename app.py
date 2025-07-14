import os
import uuid
import traceback
import torch
import librosa
from flask import Flask, request, render_template
from werkzeug.utils import secure_filename
from moviepy.editor import VideoFileClip
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor, pipeline
from yt_dlp import YoutubeDL

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['TEMP_FOLDER'] = 'temp'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max upload

# Ensure folders exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['TEMP_FOLDER'], exist_ok=True)

# Device config
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Load models
asr_processor = Wav2Vec2Processor.from_pretrained("facebook/wav2vec2-base-960h")
asr_model = Wav2Vec2ForCTC.from_pretrained("facebook/wav2vec2-base-960h").to(device)
summarizer = pipeline("summarization", model="facebook/bart-large-cnn")

def extract_audio(video_path, output_path):
    """Extract audio track from video file and save as WAV."""
    video = VideoFileClip(video_path)
    video.audio.write_audiofile(output_path, verbose=False, logger=None)
    return output_path

def transcribe_audio(audio_path):
    """Load audio, resample to 16kHz, and transcribe speech to text."""
    speech, _ = librosa.load(audio_path, sr=16000)
    inputs = asr_processor(speech, sampling_rate=16000, return_tensors="pt", padding=True)
    with torch.no_grad():
        logits = asr_model(inputs.input_values.to(device)).logits
    predicted_ids = torch.argmax(logits, dim=-1)
    transcription = asr_processor.batch_decode(predicted_ids)[0]
    return transcription.strip()

def summarize_text(text):
    """Summarize text using BART."""
    if len(text.split()) < 20:
        return "Transcript too short to summarize."
    result = summarizer(text, max_length=130, min_length=40, do_sample=False)
    return result[0]["summary_text"]

def get_youtube_description(url):
    """Fetch YouTube video description using yt-dlp."""
    ydl_opts = {}
    with YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(url, download=False)
        description = info_dict.get('description', '')
    return description

@app.route("/", methods=["GET", "POST"])
def index():
    transcript = ""
    summary = ""
    error = ""

    if request.method == "POST":
        file = request.files.get("video")
        youtube_url = request.form.get("url", "").strip()

        try:
            # If YouTube URL provided
            if youtube_url:
                try:
                    transcript = get_youtube_description(youtube_url)
                    if not transcript:
                        transcript = "No description available for this video."
                    summary = summarize_text(transcript)
                except Exception as e:
                    traceback.print_exc()
                    error = f"❌ Failed to fetch YouTube data: {str(e)}"

            # Else if video file uploaded
            elif file and file.filename != "":
                filename = secure_filename(file.filename)
                video_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                file.save(video_path)

                audio_filename = f"{uuid.uuid4()}.wav"
                audio_path = os.path.join(app.config["TEMP_FOLDER"], audio_filename)

                extract_audio(video_path, audio_path)
                transcript = transcribe_audio(audio_path)
                summary = summarize_text(transcript)

            else:
                error = "⚠️ Please upload a video file or enter a YouTube URL."

        except Exception as e:
            traceback.print_exc()
            error = f"❌ Error processing video: {str(e)}"

    return render_template("index.html", transcript=transcript, summary=summary, error=error)

if __name__ == "__main__":
    app.run(debug=True)
