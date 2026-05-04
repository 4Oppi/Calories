# 🍔 Food Calorie Analyzer — Backend

FastAPI asosida yozilgan, ovqat rasmidan kaloriya va ozuqa moddalarini aniqlash uchun backend API.

---

## 📁 Loyiha tuzilishi

```
food-calorie-bot/
├── main.py           # Asosiy FastAPI ilovasi
├── requirements.txt  # Python kutubxonalari
├── .env.example      # Muhit o'zgaruvchilari namunasi
├── .env              # Sizning maxfiy kalitlaringiz (git'ga qo'shmang!)
└── README.md
```

---

## ⚙️ O'rnatish va ishga tushirish

### 1-qadam: Loyihani klonlash yoki fayllarni joylashtirish

```bash
mkdir food-calorie-bot && cd food-calorie-bot
# Barcha fayllarni shu papkaga ko'chiring
```

### 2-qadam: Virtual muhit yaratish (tavsiya etiladi)

```bash
python -m venv venv

# Windows:
venv\Scripts\activate

# macOS / Linux:
source venv/bin/activate
```

### 3-qadam: Kutubxonalarni o'rnatish

```bash
pip install -r requirements.txt
```

### 4-qadam: `.env` faylini sozlash

```bash
cp .env.example .env
```

`.env` faylini oching va API kalitingizni kiriting:
```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx
```

> API kalitni https://console.anthropic.com/ saytidan olishingiz mumkin.

### 5-qadam: Serverni ishga tushirish

```bash
uvicorn main:app --reload --port 8000
```

Server muvaffaqiyatli ishga tushsa, terminalda quyidagini ko'rasiz:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

---

## 🧪 API'ni sinab ko'rish

### Variant 1: Swagger UI (eng qulay)

Brauzerda oching: **http://127.0.0.1:8000/docs**

1. `/analyze-food` bo'limini oching
2. "Try it out" tugmasini bosing
3. Ovqat rasmini yuklang
4. "Execute" tugmasini bosing

### Variant 2: `curl` buyrug'i bilan (terminal)

```bash
curl -X POST "http://127.0.0.1:8000/analyze-food" \
  -H "accept: application/json" \
  -F "file=@/path/to/your/food_image.jpg"
```

### Variant 3: Python script bilan

```python
import requests

with open("pizza.jpg", "rb") as f:
    response = requests.post(
        "http://127.0.0.1:8000/analyze-food",
        files={"file": ("pizza.jpg", f, "image/jpeg")}
    )

print(response.json())
```

---

## 📤 Javob formati

Muvaffaqiyatli so'rovga javob:

```json
{
  "food_name": "Pepperoni Pizza",
  "calories": 285.0,
  "protein": 12.0,
  "fat": 10.0,
  "carbs": 36.0
}
```

---

## ⚠️ Muhim eslatmalar

- `.env` faylini hech qachon GitHub'ga push qilmang
- `.gitignore` fayliga `.env` ni qo'shing:
  ```
  echo ".env" >> .gitignore
  ```
- Production'da `allow_origins=["*"]` ni Telegram Mini App domeningiz bilan almashtiring
