import google.generativeai as genai
from dotenv import load_dotenv
import os

# Load API key
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

# Configure Gemini
genai.configure(api_key=API_KEY)

# AI modification function
def modify_document(diff_summary):
    """Use Gemini to modify document based on differences."""
    model = genai.GenerativeModel('gemini-pro')

    prompt = f"""
    Here are the differences between two documents:
    {diff_summary}
    
    Generate a modified version with the improvements applied.
    """
    
    response = model.generate_content(prompt)
    return response.text
