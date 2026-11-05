import os
import google.generativeai as genai
from dotenv import load_dotenv
from docx import Document
from unstructured.partition.docx import partition_docx
import json
from typing import List, Dict

# Load API Key
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)

def load_document(file_path):
    """Load a DOCX file and extract text."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    print(f"📖 Loading {os.path.basename(file_path)}...")
    elements = partition_docx(filename=file_path)
    doc_content = "\n".join([str(el) for el in elements])
    return doc_content

def compare_textbook_notes(textbook_text, notes_text):
    """Compare notes with textbook and rewrite irrelevant content."""
    print("🔍 Checking notes against textbook...")
    
    prompt = f"""
    You are an AI that reviews student notes based on a given textbook. 
    The textbook contains the main content, and the notes should closely follow it.
    
    TASK:
    - Compare the notes to the textbook.
    - Identify and rewrite any incorrect or irrelevant sections in the notes.
    - Ensure that the revised notes align with the textbook content.
    
    TEXTBOOK CONTENT:
    {textbook_text[:3000]}
    
    STUDENT NOTES:
    {notes_text[:3000]}
    
    OUTPUT:
    Provide the improved version of the notes.
    """

    model = genai.GenerativeModel("models/gemini-1.5-pro-latest")
    response = model.generate_content(prompt)

    revised_notes = response.text.strip() if response and response.text else notes_text
    print("✅ Notes comparison completed!")
    return revised_notes

def analyze_notes_for_daily_topics(notes_text):
    """Enhanced analysis with better error handling"""
    print("🔍 Starting note analysis...")
    try:
        prompt = f"""
        Analyze these class notes and extract daily topics in strict JSON format.
        If dates aren't available, use "Unknown" as the date.
        
        NOTES:
        {notes_text[:5000]}

        Required JSON format:
        {{
            "date": "YYYY-MM-DD",
            "topics": ["topic1", "topic2"]
        }}

        Return ONLY the JSON array.
        """
        
        model = genai.GenerativeModel("models/gemini-1.5-pro-latest")
        response = model.generate_content(prompt)
        
        # More robust JSON extraction
        raw_text = response.text.strip()
        json_start = raw_text.find('[')
        json_end = raw_text.rfind(']') + 1
        json_str = raw_text[json_start:json_end]
        
        parsed = json.loads(json_str)
        print("📅 Topics analysis successful")
        return parsed
        
    except Exception as e:
        print(f"❌ Analysis failed, using fallback: {str(e)}")
        return [{"date": "Unknown", "topics": ["General Topics"]}]




def validate_homework(textbook_text, daily_topics, homework_text):
    """Check homework relevance to daily topics and textbook."""
    print("✅ Checking homework relevance...")
    
    prompt = f"""
    Validate homework questions based on:
    - Textbook content (20 pages)
    - Daily topics covered in class
    
    DAILY TOPICS:
    {json.dumps(daily_topics)}
    
    TEXTBOOK CONTENT:
    {textbook_text[:5000]}
    
    HOMEWORK:
    {homework_text}
    
    TASKS:
    1. Identify questions not related to daily topics/textbook
    2. Replace irrelevant questions with new relevant ones
    3. Maintain question count
    4. Return only the corrected homework
    """
    
    model = genai.GenerativeModel("models/gemini-1.5-pro-latest")
    response = model.generate_content(prompt)
    print("🔍 Homework validation complete!")
    return response.text

def generate_homework(textbook_text, daily_topics, custom_instructions=None):
    """Generate homework with optional custom instructions."""
    prompt = f"""
    Generate homework based on:
    - Textbook: {textbook_text[:5000]}
    - Topics: {json.dumps(daily_topics)}
    {f"- CUSTOM REQUIREMENTS: {custom_instructions}" if custom_instructions else ""}
    """
    model = genai.GenerativeModel("models/gemini-1.5-pro-latest")
    response = model.generate_content(prompt)
    return response.text


def generate_custom_homework(textbook_text, daily_topics, custom_instructions):
    """Generate homework based on user's custom requirements."""
    print("✨ Generating custom homework...")
    
    prompt = f"""
    Create a homework assignment based on the following requirements:
    {custom_instructions}

    CONTEXT:
    - Textbook content: {textbook_text[:5000]}
    - Daily topics: {json.dumps(daily_topics)}

    REQUIREMENTS:
    1. Follow the instructions EXACTLY
    2. Ensure questions match the topics
    3. Return only the generated homework
    """
    
    model = genai.GenerativeModel("models/gemini-1.5-pro-latest")
    response = model.generate_content(prompt)
    return response.text

def save_to_docx(content, output_folder, filename):
    """Save content to a DOCX file."""
    print(f"💾 Saving {filename}...")
    doc = Document()
    doc.add_paragraph(content)
    file_path = os.path.join(output_folder, filename)
    doc.save(file_path)
    print(f"🎉 Successfully saved to {file_path}")
    return file_path