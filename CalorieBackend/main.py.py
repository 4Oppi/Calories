import os
import json
import re
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
# Railway'dagi DATABASE_URL ni olamiz
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db") # Agar topa olmasa vaqtinchalik sqlite yaratadi
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# User Modeli (Bazadagi jadval tuzilishi)
class DBUser(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True) # Mijozning noyob ID si
    gender = Column(String)
    age = Column(Integer)
    height = Column(Integer)
    weight = Column(Float)
    activity_level = Column(Float)
    goal = Column(String)
    tdee = Column(Integer)

# Jadvallarni yaratish
Base.metadata.create_all(bind=engine)

# Bazaga ulanish sessiyasini ochish
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Frontend'dan keladigan JSON formatni tekshirish uchun Pydantic modeli
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
# 2. GEMINI AI SOZLAMALARI
# ==========================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "BU_YERGA_API_KALITNI_YOZING")
genai.configure(api_key=GEMINI_API_KEY)

def extract_json(text: str) -> dict:
    cleaned = re.sub(r"
http://googleusercontent.com/immersive_entry_chip/0

Ishni **Backend'ni Railway'ga yangilashdan** boshlaymiz. Qilib bo'lgach, menga ayting, keyin darrov `index.html` dagi o'sha `saveProfile()` JS funksiyasini yangi bazamizga ma'lumot yuboradigan qilib o'zgartirib beraman! Qani, olg'a!