from flask import Flask, request, render_template, send_file
from compare_docs import load_document, compare_textbook_notes, validate_homework, save_to_docx
from dotenv import load_dotenv
import os

# ✅ Load environment variables
load_dotenv()

app = Flask(__name__)

# ✅ Upload folder
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ✅ Port configuration (Render uses PORT 10000 by default)
PORT = int(os.getenv("PORT", 10000))

@app.route('/', methods=['GET', 'POST'])
def index():
    results = ""
    notes_path, homework_path = None, None

    if request.method == 'POST':
        # ✅ Get uploaded files
        textbook = request.files.get('textbook')
        notes = request.files.get('notes')
        homework = request.files.get('homework')

        if not (textbook and notes and homework):
            results = "Please upload all three files: textbook, notes, and homework."
        else:
            # ✅ Save uploaded files
            textbook_path = os.path.join(UPLOAD_FOLDER, textbook.filename)
            notes_path = os.path.join(UPLOAD_FOLDER, notes.filename)
            homework_path = os.path.join(UPLOAD_FOLDER, homework.filename)

            textbook.save(textbook_path)
            notes.save(notes_path)
            homework.save(homework_path)

            try:
                # ✅ Load document content
                textbook_text = load_document(textbook_path)
                notes_text = load_document(notes_path)
                homework_text = load_document(homework_path)

                # ✅ Process notes comparison
                corrected_notes = compare_textbook_notes(textbook_text, notes_text)
                corrected_notes_path = os.path.join(UPLOAD_FOLDER, "Corrected_Notes.docx")
                save_to_docx(corrected_notes, corrected_notes_path)

                # ✅ Process homework validation
                corrected_homework = validate_homework(textbook_text, notes_text, homework_text)
                corrected_homework_path = os.path.join(UPLOAD_FOLDER, "Corrected_Homework.docx")
                save_to_docx(corrected_homework, corrected_homework_path)

                results = "✅ Notes and Homework have been corrected!"
                notes_path = corrected_notes_path
                homework_path = corrected_homework_path

            except Exception as e:
                results = f"An error occurred: {str(e)}"

    return render_template('index.html', results=results, notes_path=notes_path, homework_path=homework_path)


@app.route('/download')
def download():
    """Route to download the corrected documents."""
    file_path = request.args.get('path')
    if file_path and os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    else:
        return "File not found."


# ✅ Production-ready configuration for Render
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=False)
