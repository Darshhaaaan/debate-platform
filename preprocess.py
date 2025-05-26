import os
import numpy as np
import soundfile as sf
import whisper
from kokoro import KPipeline
import google.generativeai as genai
from flask import Flask, request, send_file
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

class VoiceBot:
    def __init__(self, api_key: str, output_dir: str = "output", system_prompt: str = "YOU ARE A DEBATOR"):
        self.audio_model = whisper.load_model("base", device="cpu")
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        genai.configure(api_key=api_key)
        self.chat = genai.GenerativeModel("gemini-1.5-flash").start_chat(history=[])
        self.pipeline = KPipeline(lang_code='a', repo_id='hexgrad/Kokoro-82M')

    def generate_response(self, query: str):
        response = self.chat.send_message(query)
        print("DEBATOR RESPONSE: ", response.text)
        return response.text

    def generate_audio(self, query: str, output_file="audio.wav"):
        generator = self.pipeline(query, voice='af_heart', speed=1)
        full_audio = [audio for _, _, audio in generator]
        final_audio = np.concatenate(full_audio)
        audio_path = os.path.join(self.output_dir, output_file)
        sf.write(audio_path, final_audio, 24000)
        return audio_path

    def generate_text(self, audio_path):
        response = self.audio_model.transcribe(audio_path)
        print("TRANSCRIBED TEXT:", response['text'])
        return response['text']


API_KEY = os.getenv("GEMINI_API_KEY")  
bot = VoiceBot(api_key=API_KEY, system_prompt="YOU ARE A DEBATOR")



if __name__ == "__main__":
    app.run(debug=True)