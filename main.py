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
    ticks = "`" * 3
    cleaned = text.replace(ticks + "json", "").replace(ticks, "").strip()
    return json.loads(cleaned)

def call_gemini_with_retry(image_bytes: bytes, content_type: str):
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            image_parts = [{"mime_type": content_type, "data": image_bytes}]
            response = model.generate_content([PROMPT, image_parts[0]])
            return response.text
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    raise last_error

# ==========================================
# 3. API ENDPOINTLAR
# ==========================================

@app.post("/save-profile")
def save_profile(profile: UserProfile, db: Session = Depends(get_db)):
    user = db.query(DBUser).filter(DBUser.telegram_id == profile.telegram_id).first()
    if user:
        user.gender = profile.gender
        user.age = profile.age
        user.height = profile.height
        user.weight = profile.weight
        user.activity_level = profile.activity_level
        user.goal = profile.goal
        user.tdee = profile.tdee
        message = "Profil yangilandi"
    else:
        new_user = DBUser(**profile.dict())
        db.add(new_user)
        message = "Yangi profil yaratildi"
    db.commit()
    return {"status": "success", "message": message}

@app.post("/analyze-food")
async def analyze_food(file: UploadFile = File(...)):
    if not file:
        raise HTTPException(status_code=400, detail="Rasm fayli yuklanmadi.")
    
    content_type = file.content_type or "image/jpeg"
    image_bytes = await file.read()

    try:
        raw_text = call_gemini_with_retry(image_bytes, content_type)
        result = extract_json(raw_text)
        return result
    except Exception as e:
        print(f"Xatolik yuz berdi: {e}")
        raise HTTPException(
            status_code=503,
            detail="Tizimda vaqtinchalik tirbandlik. Iltimos, birozdan so'ng yana urinib ko'ring 🔄"
        )
