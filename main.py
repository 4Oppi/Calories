import os
import json
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from google import genai
from google.genai import types

# .env faylidan API kalitni yuklash
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY topilmadi! .env faylini tekshiring.")

# Yangi rasmiy kutubxona orqali mijozni (client) sozlash
client = genai.Client(api_key=GEMINI_API_KEY)

app = FastAPI(title="Food Calorie Analyzer API")

# CORS sozlamalari
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROMPT = """
Siz ovqat ekspertisiz. Quyidagi rasmda ko'rsatilgan taomni tahlil qiling.
Faqat quyidagi JSON formatida javob bering, boshqa hech narsa yozmang:

{"food_name": "taom nomi (faqat o'zbek tilida, masalan: Qovurilgan tovuq va kartoshka)", "calories": 000, "protein": 00, "fat": 00, "carbs": 00}
"""
@app.post("/analyze-food")
async def analyze_food(file: UploadFile = File(...)):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Faqat rasm fayllari qabul qilinadi.")

    try:
        image_bytes = await file.read()

        # Rasmni yangi tizim formatiga o'tkazish
        image_part = types.Part.from_bytes(
            data=image_bytes,
            mime_type=file.content_type,
        )

      # Gemini 2.5 Flash modeliga so'rov yuborish
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[PROMPT, image_part]
        )

        raw_text = response.text.strip()

        # Model yuborgan Markdown/JSON qoldiqlarini tozalash
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        result = json.loads(raw_text)

        return {
            "success": True,
            "data": result
        }

    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Model noto'g'ri JSON qaytardi.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"API Xatosi: {str(e)}")