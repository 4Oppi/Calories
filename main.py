import os
import json
import re
import time

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY topilmadi. Iltimos, .env faylini tekshiring.")

client = genai.Client(api_key=GEMINI_API_KEY)

app = FastAPI(title="CalorieScan V2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROMPT = (
    "Siz dunyodagi eng tajribali ovqatlanish va diyetologiya ekspertisiz. "
    "Quyidagi rasmda ko'rsatilgan taomni chuqur tahlil qiling. "
    "Faqat va faqat quyidagi JSON formatida javob bering, boshqa hech qanday izoh yoki matn yozmang:\n"
    '{"food_name": "taom nomi (faqat o\'zbek tilida)", "calories": 000, "protein": 00, "fat": 00, "carbs": 00}'
)

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


def extract_json(text: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", text).replace("```", "").strip()
    return json.loads(cleaned)


def call_gemini_with_retry(image_bytes: bytes, content_type: str) -> str:
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part.from_bytes(data=image_bytes, mime_type=content_type),
                    PROMPT,
                ],
            )
            return response.text
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    raise last_error


@app.post("/analyze-food")
async def analyze_food(file: UploadFile = File(...)):
    if not file:
        raise HTTPException(status_code=400, detail="Rasm fayli yuklanmadi.")

    content_type = file.content_type or "image/jpeg"
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Faqat rasm fayllari qabul qilinadi.")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Rasm fayli bo'sh.")

    try:
        raw_text = call_gemini_with_retry(image_bytes, content_type)
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Tizimda vaqtinchalik tirbandlik. Iltimos, birozdan so'ng yana urinib ko'ring 🔄",
        )

    try:
        result = extract_json(raw_text)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=422,
            detail="Natijani o'qishda xatolik yuz berdi. Iltimos, boshqa rasm bilan urinib ko'ring.",
        )

    return result
