from flask import Flask, request, render_template, send_file, jsonify
from compare_docs import (
    load_document, 
    compare_textbook_notes, 
    validate_homework, 
    generate_homework,
    save_to_docx,
    generate_custom_homework,
    analyze_notes_for_daily_topics
)
from dotenv import load_dotenv
import os
import google.generativeai as genai
import json
import traceback
import time

# Load environment variables
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("❌ CRITICAL ERROR: GEMINI_API_KEY not found in .env file!")

genai.configure(api_key=API_KEY)

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "default-secret-key")

# Configure file paths
UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "outputs"
ALLOWED_EXTENSIONS = {'docx', 'txt', 'pdf'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/check', methods=['POST'])
def check_homework():
    try:
        if 'textbook' not in request.files or 'notes' not in request.files or 'homework' not in request.files:
            return jsonify({"error": "Missing file parts in request"}), 400
            
        textbook_file = request.files['textbook']
        notes_file = request.files['notes']
        homework_file = request.files['homework']

        if not all([f.filename != '' for f in [textbook_file, notes_file, homework_file]]):
            return jsonify({"error": "Empty filename detected!"}), 400

        if not all([allowed_file(f.filename) for f in [textbook_file, notes_file, homework_file]]):
            return jsonify({"error": "Invalid file type! Allowed: .docx, .txt, .pdf"}), 400

        # FIX 1: Use full paths for all files
        textbook_path = os.path.join(app.config['UPLOAD_FOLDER'], "textbook.docx")
        notes_path = os.path.join(app.config['UPLOAD_FOLDER'], "notes.docx")
        homework_path = os.path.join(app.config['UPLOAD_FOLDER'], "homework.docx")

        textbook_file.save(textbook_path)
        notes_file.save(notes_path)
        homework_file.save(homework_path)

        # FIX 2: Load using full paths
        textbook_text = load_document(textbook_path)
        notes_text = load_document(notes_path)
        homework_text = load_document(homework_path)

        daily_topics = analyze_notes_for_daily_topics(notes_text)
        if not daily_topics or len(daily_topics) == 0:
            return jsonify({
                "error": "Daily topic extraction failed",
                "hint": "Ensure notes contain dated entries with clear topics"
            }), 400

        corrected_homework = validate_homework(textbook_text, daily_topics, homework_text)
        output_path = save_to_docx(
            corrected_homework, 
            app.config['OUTPUT_FOLDER'], 
            "corrected_homework.docx"
        )
        
        return jsonify({
            "message": "Homework validation complete!",
            "download_link": f"/download/{os.path.basename(output_path)}",
            "status": "success"
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "error": f"Unexpected server error: {str(e)}",
            "status": "critical"
        }), 500

@app.route('/create', methods=['POST'])
def create_homework():
    try:
        if 'textbook' not in request.files or 'notes' not in request.files:
            return jsonify({"error": "Missing required files"}), 400
            
        textbook_file = request.files['textbook']
        notes_file = request.files['notes']

        timestamp = str(int(time.time()))
        
        # FIX 3: Full paths with upload folder
        textbook_path = os.path.join(app.config['UPLOAD_FOLDER'], f"textbook_{timestamp}.docx")
        notes_path = os.path.join(app.config['UPLOAD_FOLDER'], f"notes_{timestamp}.docx")
        
        textbook_file.save(textbook_path)
        notes_file.save(notes_path)

        # FIX 4: Use full paths for loading
        textbook_text = load_document(textbook_path)
        notes_text = load_document(notes_path)
        
        daily_topics = analyze_notes_for_daily_topics(notes_text)

        new_homework = generate_homework(textbook_text, daily_topics)
        output_path = save_to_docx(
            new_homework,
            app.config['OUTPUT_FOLDER'],
            f"generated_hw_{timestamp}.docx"
        )
        
        return jsonify({
            "message": "Homework generated successfully",
            "download_link": f"/download/{os.path.basename(output_path)}",
            "generated_at": timestamp
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "error": f"Generation pipeline failed: {str(e)}",
            "stage": "unknown"
        }), 500

@app.route('/generate-custom', methods=['POST'])
def handle_custom_generation():
    try:
        if 'textbook' not in request.files or 'notes' not in request.files:
            return jsonify({"error": "Missing textbook or notes"}), 400

        textbook_file = request.files['textbook']
        notes_file = request.files['notes']
        custom_instructions = request.form.get('custom_instructions', '')

        if not custom_instructions:
            return jsonify({"error": "Please enter custom instructions"}), 400

        timestamp = str(int(time.time()))
        textbook_path = os.path.join(app.config['UPLOAD_FOLDER'], f"textbook_{timestamp}.docx")
        notes_path = os.path.join(app.config['UPLOAD_FOLDER'], f"notes_{timestamp}.docx")
        
        textbook_file.save(textbook_path)
        notes_file.save(notes_path)

        textbook_text = load_document(textbook_path)
        notes_text = load_document(notes_path)
        daily_topics = analyze_notes_for_daily_topics(notes_text)

        custom_hw = generate_custom_homework(
            textbook_text,
            daily_topics,
            custom_instructions
        )

        output_filename = f"custom_hw_{timestamp}.docx"
        output_path = save_to_docx(custom_hw, app.config['OUTPUT_FOLDER'], output_filename)
        
        return jsonify({
            "message": "Custom homework generated!",
            "download_link": f"/download/{output_filename}"
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({
            "error": f"Generation failed: {str(e)}",
            "hint": "Check your files and try again"
        }), 500

@app.route('/download/<filename>')
def download(filename):
    try:
        if '..' in filename or filename.startswith('/'):
            return "Invalid filename", 400
            
        path = os.path.join(app.config['OUTPUT_FOLDER'], filename)
        
        if not os.path.isfile(path):
            return "File not found", 404
            
        return send_file(
            path,
            as_attachment=True,
            download_name=f"revised_{filename}",
            mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/prompt', methods=['POST'])
def prompt_handler():
    try:
        # Check for required files and prompt
        if 'textbook' not in request.files or 'notes' not in request.files:
            return jsonify({"error": "Textbook and notes files are required"}), 400
            
        textbook_file = request.files['textbook']
        notes_file = request.files['notes']
        data = request.form
        prompt_text = data.get('prompt', '').strip()
        
        if not prompt_text:
            return jsonify({"error": "Please enter a question or prompt"}), 400

        # Save files temporarily
        timestamp = str(int(time.time()))
        textbook_path = os.path.join(app.config['UPLOAD_FOLDER'], f"textbook_{timestamp}.docx")
        notes_path = os.path.join(app.config['UPLOAD_FOLDER'], f"notes_{timestamp}.docx")
        
        textbook_file.save(textbook_path)
        notes_file.save(notes_path)

        # Load document contents
        textbook_text = load_document(textbook_path)
        notes_text = load_document(notes_path)

        # Enhanced prompt with context
        enhanced_prompt = f"""
        You are an AI teaching assistant helping a student with their studies.
        You have access to:
        1. Textbook content (below)
        2. Student's notes (below)
        
        TEXTBOOK CONTENT:
        {textbook_text[:10000]}  # Limiting to first 10k chars for context
        
        STUDENT NOTES:
        {notes_text[:5000]}  # Limiting to first 5k chars for context
        
        STUDENT'S QUESTION:
        {prompt_text}
        
        INSTRUCTIONS:
        - Answer the question using the textbook as the primary source
        - Reference the notes when relevant to the question
        - If the question is about the notes content, focus on that
        - Be concise but thorough
        - For "what's in my notes" questions, summarize key points
        - Format your response clearly with headings if needed
        """

        model = genai.GenerativeModel("models/gemini-1.5-pro-latest")
        response = model.generate_content(enhanced_prompt)
        
        # Clean up temporary files
        try:
            os.remove(textbook_path)
            os.remove(notes_path)
        except:
            pass
        
        return jsonify({
            "response": response.text,
            "status": "success"
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(
        host='0.0.0.0',
        port=port,
        debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    )