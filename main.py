import anthropic
import base64
import json
import re

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI(title="Food Calorie Analyzer API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Production'da o'zgartiring
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_FILE_SIZE_MB = 5


class FoodAnalysisResult(BaseModel):
    food_name: str
    calories: float
    protein: float
    fat: float
    carbs: float


SYSTEM_PROMPT = """You are a professional nutritionist and food recognition expert.
When given an image of food, you MUST respond with ONLY a valid JSON object.
No extra text, no markdown, no code blocks — just raw JSON.

The JSON must follow this exact schema:
{
  "food_name": "<name of the food in English>",
  "calories": <number: kcal per serving shown>,
  "protein": <number: grams>,
  "fat": <number: grams>,
  "carbs": <number: grams>
}

Rules:
- All numeric values must be numbers (not strings).
- Estimate values based on a typical serving size if the portion is unclear.
- If multiple foods are present, analyze the whole plate as one meal.
- If the image does not contain food, return: {"food_name": "unknown", "calories": 0, "protein": 0, "fat": 0, "carbs": 0}
"""


@app.get("/")
async def root():
    return {"status": "ok", "message": "Food Calorie Analyzer API is running"}


@app.post("/analyze-food", response_model=FoodAnalysisResult)
async def analyze_food(file: UploadFile = File(...)):
    # 1. Fayl turini tekshirish
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Allowed: JPEG, PNG, GIF, WEBP",
        )

    # 2. Fayl o'lchamini tekshirish
    image_bytes = await file.read()
    if len(image_bytes) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE_MB}MB",
        )

    # 3. Rasmni base64 formatiga o'tkazish
    image_base64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    # 4. Claude Vision API ga yuborish
    try:
        message = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": file.content_type,
                                "data": image_base64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Analyze this food image and return the nutritional information as JSON.",
                        },
                    ],
                }
            ],
        )
    except anthropic.APIConnectionError:
        raise HTTPException(status_code=503, detail="Failed to connect to AI service")
    except anthropic.RateLimitError:
        raise HTTPException(status_code=429, detail="AI service rate limit exceeded. Try again later.")
    except anthropic.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"AI service error: {e.message}")

    # 5. Javobni JSON formatiga o'tkazish
    raw_text = message.content[0].text.strip()

    # Agar model markdown code block qaytargan bo'lsa, tozalash
    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
    raw_text = re.sub(r"\s*```$", "", raw_text)

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="AI returned an invalid response format. Please try again.",
        )

    # 6. Natijani qaytarish
    try:
        return FoodAnalysisResult(
            food_name=str(data["food_name"]),
            calories=float(data["calories"]),
            protein=float(data["protein"]),
            fat=float(data["fat"]),
            carbs=float(data["carbs"]),
        )
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"AI response missing required fields: {str(e)}",
        )
