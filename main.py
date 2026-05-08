import os
import json
import re
import time
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
from sqlalchemy import create_engine, Column, Integer, String, Float, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

app = FastAPI(title="CalorieScan Backend V2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 1. DATABASE (POSTGRESQL) SOZLAMALARI
# ==========================================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class DBUser(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    gender = Column(String)
    age = Column(Integer)
    height = Column(Integer)
    weight = Column(Float)
    activity_level = Column(Float)
    goal = Column(String)
    tdee = Column(Integer)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class UserProfile(BaseModel):
    telegram_id: int
    gender: str
    age: int
    height: int
    weight: float
    activity_level: float
    goal: str
    tdee: int

# ==========================================
# 2. GEMINI AI SOZLAMALARI (RETRY BILAN)
# ==========================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyDE7gAvw0m-NRaolJU0iir0cigYVT3ZIQU")
genai.configure(api_key=GEMINI_API_KEY)

PROMPT = (
    "Siz dunyodagi eng tajribali ovqatlanish va diyetologiya ekspertisiz. "
    "Quyidagi rasmda ko'rsatilgan taomni chuqur tahlil qiling. "
    "1. USDA ma'lumotlar bazasiga asoslanib, kaloriya va makrolarni hisoblang. "
    "Faqat va faqat quyidagi qat'iy JSON formatida javob bering, hech qanday qo'shimcha so'z yozmang:\n"
    '{"food_name": "Taom nomi (O\'zbek tilida)", "calories": 0, "protein": 0, "fat": 0, "carbs": 0}'
)

MAX_RETRIES = 3
RETRY_DELAY = 2

def extract_json(text: str):
    # Bu yerda xato tuzatildi: string to'liq yopildi
    cleaned = re.sub(r"
http://googleusercontent.com/immersive_entry_chip/0

**Nima qilish kerak:**
1.  Ushbu kodni nusxalashda oxirigacha tushganiga e'tibor bering.
2.  `main.py` faylingizni to'liq yangilang.
3.  GitHub'ga yuklab, Railway'da "Deployment Successful" yozuvi chiqishini kuting.

Shu qadamdan keyin "Failed to fetch" xatosi yo'qolishi kerak.