import sys
import subprocess

# Kutubxona yo'q bo'lsa, avtomatik o'rnatish mantiqi
try:
    import google.generativeai
except ImportError:
    print("google.generativeai topilmadi! O'rnatilmoqda...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "google-generativeai"])
    import google.generativeai

# Qolgan barcha kodlaringiz shu yerdan pastga tushadi...
import os
import json
import re
import time
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
# ... va hokazo ...
