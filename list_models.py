import google.generativeai as genai
from dotenv import load_dotenv
import os

# ✅ Load Gemini API Key
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)

# ✅ List available models
models = genai.list_models()
print("\n--- Available Gemini Models ---")
for model in models:
    print(f"Model ID: {model.name}")
    print(f"Description: {model.description}")
    print("-" * 40)
