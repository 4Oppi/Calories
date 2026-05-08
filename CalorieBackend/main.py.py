from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import google.generativeai as genai
import json
import os
import re

app = FastAPI(title="CalorieScan Backend")

# WebApp (Frontend) ruxsatnoma olishi uchun CORS sozlamasi
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gemini API kalitini o'rnatish
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyDE7gAvw0m-NRaolJU0iir0cigYVT3ZIQU")
genai.configure(api_key=GEMINI_API_KEY)

def extract_json(text: str) -> dict:
    cleaned = re.sub(r"
http://googleusercontent.com/immersive_entry_chip/0

Mana shu 2 ta faylni yangi papkaga saqlang. Undan keyin shu qutini (papkani) GitHub'ga yuklab, Railway orqali osmonga uchirib yuboravering! Ssilka chiqqach menga xabar qiling. 🚀