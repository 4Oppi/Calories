import os
import json
import time
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import google.generativeai as genai
from sqlalchemy import create_engine, Column, Integer, String, Float, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

app = FastAPI(title="CalorieScan Backend V2")

# CORS — set your Vercel domain here in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# DATABASE
# ==========================================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./caloriescan.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class DBUser(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True)
    name = Column(String, default="")
    gender = Column(String)
    age = Column(Integer)
    height = Column(Integer)
    weight = Column(Float)
    activity_level = Column(String)
    goal = Column(String)
    tdee = Column(Integer)

class DBMeal(Base):
    __tablename__ = "meals"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, index=True)
    food_name = Column(String)
    calories = Column(Float)
    protein = Column(Float)
    carbs = Column(Float)
    fat = Column(Float)
    date = Column(String)      # YYYY-MM-DD
    created_at = Column(String)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ==========================================
# PYDANTIC MODELS
# ==========================================
class UserProfile(BaseModel):
    telegram_id: int
    name: str = ""
    gender: str
    age: int
    height: int
    weight: float
    activity_level: str
    goal: str
    tdee: int

class MealCreate(BaseModel):
    telegram_id: int
    food_name: str
    calories: float
    protein: float
    carbs: float
    fat: float

class MealOut(BaseModel):
    id: int
    telegram_id: int
    food_name: str
    calories: float
    protein: float
    carbs: float
    fat: float
    date: str
    created_at: str

    class Config:
        from_attributes = True

# ==========================================
# GEMINI AI
# ==========================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY environment variable not set. AI scanning will fail.")
    GEMINI_API_KEY = ""

genai.configure(api_key=GEMINI_API_KEY)

PROMPT = (
    "You are the world's top nutrition expert. Analyze the food in this image deeply. "
    "Estimate calories and macronutrients based on USDA data. "
    "Respond ONLY in this exact JSON format, no extra text, no markdown:\n"
    '{\"food_name\": \"Food name (English)\", \"calories\": 0, \"protein\": 0, \"fat\": 0, \"carbs\": 0}'
)

MAX_RETRIES = 3
RETRY_DELAY = 2

def extract_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```", 2)
        text = parts[-1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    return json.loads(text)

def call_gemini_with_retry(image_bytes: bytes, content_type: str):
    if not GEMINI_API_KEY:
        raise Exception("Gemini API key not configured")
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content([
                PROMPT,
                {"mime_type": content_type, "data": image_bytes}
            ])
            return response.text
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    raise last_error

# ==========================================
# API ENDPOINTS
# ==========================================

@app.get("/")
def root():
    return {"status": "CalorieScan API is running"}

@app.get("/profile/{telegram_id}")
def get_profile(telegram_id: int, db: Session = Depends(get_db)):
    user = db.query(DBUser).filter(DBUser.telegram_id == telegram_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {
        "telegram_id": user.telegram_id,
        "name": user.name,
        "gender": user.gender,
        "age": user.age,
        "height": user.height,
        "weight": user.weight,
        "activity_level": user.activity_level,
        "goal": user.goal,
        "tdee": user.tdee
    }

@app.post("/save-profile")
def save_profile(profile: UserProfile, db: Session = Depends(get_db)):
    user = db.query(DBUser).filter(DBUser.telegram_id == profile.telegram_id).first()
    if user:
        user.name = profile.name
        user.gender = profile.gender
        user.age = profile.age
        user.height = profile.height
        user.weight = profile.weight
        user.activity_level = profile.activity_level
        user.goal = profile.goal
        user.tdee = profile.tdee
        msg = "Profile updated"
    else:
        db.add(DBUser(**profile.dict()))
        msg = "Profile created"
    db.commit()
    return {"status": "success", "message": msg}

@app.post("/analyze-food")
async def analyze_food(file: UploadFile = File(...)):
    if not file:
        raise HTTPException(status_code=400, detail="No image uploaded")
    content_type = file.content_type or "image/jpeg"
    image_bytes = await file.read()
    try:
        raw_text = call_gemini_with_retry(image_bytes, content_type)
        result = extract_json(raw_text)
        for key in ["food_name", "calories", "protein", "fat", "carbs"]:
            if key not in result:
                result[key] = 0 if key != "food_name" else "Unknown food"
        return result
    except Exception as e:
        print(f"Analysis error: {e}")
        raise HTTPException(status_code=503, detail="AI analysis failed. Please try again.")

@app.post("/meals")
def create_meal(meal: MealCreate, db: Session = Depends(get_db)):
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().isoformat()
    db_meal = DBMeal(
        telegram_id=meal.telegram_id,
        food_name=meal.food_name,
        calories=meal.calories,
        protein=meal.protein,
        carbs=meal.carbs,
        fat=meal.fat,
        date=today,
        created_at=now
    )
    db.add(db_meal)
    db.commit()
    db.refresh(db_meal)
    return {"status": "success", "meal": MealOut.from_orm(db_meal)}

@app.get("/meals/{telegram_id}")
def get_meals(telegram_id: int, date: str = None, db: Session = Depends(get_db)):
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    meals = db.query(DBMeal).filter(
        DBMeal.telegram_id == telegram_id,
        DBMeal.date == date
    ).order_by(DBMeal.created_at.desc()).all()
    return {"meals": [MealOut.from_orm(m) for m in meals]}

@app.get("/daily-summary/{telegram_id}")
def get_summary(telegram_id: int, date: str = None, db: Session = Depends(get_db)):
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    meals = db.query(DBMeal).filter(
        DBMeal.telegram_id == telegram_id,
        DBMeal.date == date
    ).all()
    return {
        "date": date,
        "calories": round(sum(m.calories for m in meals), 1),
        "protein": round(sum(m.protein for m in meals), 1),
        "carbs": round(sum(m.carbs for m in meals), 1),
        "fat": round(sum(m.fat for m in meals), 1),
        "meal_count": len(meals)
    }

@app.delete("/meals/{meal_id}")
def delete_meal(meal_id: int, db: Session = Depends(get_db)):
    meal = db.query(DBMeal).filter(DBMeal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    db.delete(meal)
    db.commit()
    return {"status": "success"}
