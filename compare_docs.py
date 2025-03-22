import os
import google.generativeai as genai
from dotenv import load_dotenv
from docx import Document
from unstructured.partition.docx import partition_docx

# ✅ Load API Key
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)


def load_document(file_path):
    """Load a DOCX file and extract text."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

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
    {textbook_text[:3000]}  # Limit for processing
    
    STUDENT NOTES:
    {notes_text[:3000]}  # Limit for processing
    
    OUTPUT:
    Provide the improved version of the notes.
    """

    # ✅ Use the correct Gemini model
    model = genai.GenerativeModel("models/gemini-1.5-pro-latest")  # 👈 Updated model ID
    response = model.generate_content(prompt)

    revised_notes = response.text.strip() if response and response.text else notes_text
    return revised_notes


def validate_homework(textbook_text, notes_text, homework_text):
    """Check if homework questions are relevant and rewrite irrelevant ones."""
    print("📌 Validating homework questions...")

    prompt = f"""
    You are an AI that reviews homework questions for relevance to a given textbook and student notes. 
    The textbook is the primary source, and the notes are additional reference material.
    
    TASK:
    - Check each homework question against the textbook and notes.
    - If a question is irrelevant, replace it with a new, relevant question.
    - Ensure all final questions are aligned with the textbook concepts.
    
    TEXTBOOK CONTENT:
    {textbook_text[:3000]}
    
    STUDENT NOTES:
    {notes_text[:3000]}
    
    HOMEWORK QUESTIONS:
    {homework_text[:2000]}
    
    OUTPUT:
    Provide the corrected homework questions.
    """

    # ✅ Use the correct Gemini model
    model = genai.GenerativeModel("models/gemini-1.5-pro-latest")  # 👈 Updated model ID
    response = model.generate_content(prompt)

    revised_homework = response.text.strip() if response and response.text else homework_text
    return revised_homework


def save_to_docx(content, filename):
    """Save text content to a DOCX file."""
    doc = Document()
    doc.add_paragraph(content)
    doc.save(filename)
    return filename
