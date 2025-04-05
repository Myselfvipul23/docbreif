import os
import sqlite3
from datetime import datetime
from werkzeug.utils import secure_filename
import google.generativeai as genai
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, Response
import PyPDF2
import docx
from werkzeug.exceptions import RequestEntityTooLarge

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your_secret_key'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB limit
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'txt', 'docx'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

GEMINI_API_KEY = "AIzaSyCzAGEaPAVEuOeUazu6Q_1RGZlkL5kkU58"
genai.configure(api_key=GEMINI_API_KEY)

def get_db_connection():
    conn = sqlite3.connect('docbrief.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()

    # Create the table if it doesn't exist
    conn.execute('''
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            upload_date TIMESTAMP NOT NULL,
            summary TEXT,
            important_clauses TEXT
        )
    ''')

    # Check if 'language' column exists
    existing_columns = [col['name'] for col in conn.execute("PRAGMA table_info(documents)").fetchall()]
    if 'language' not in existing_columns:
        conn.execute("ALTER TABLE documents ADD COLUMN language TEXT DEFAULT 'English'")

    conn.commit()
    conn.close()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def extract_text(file_path):
    file_extension = file_path.rsplit('.', 1)[1].lower()

    try:
        if file_extension == 'txt':
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()

        elif file_extension == 'pdf':
            text = ""
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text
            return text or "No text could be extracted from the PDF."

        elif file_extension == 'docx':
            doc = docx.Document(file_path)
            return "\n".join([paragraph.text for paragraph in doc.paragraphs]) or "No text found in DOCX."

    except Exception as e:
        print(f"[ERROR] File reading failed: {str(e)}")
        return "Error reading the file."

    return "Unsupported file type."

def analyze_document(text, target_language="English"):
    SUPPORTED_LANGUAGES = ['English', 'Hindi', 'Spanish', 'French', 'German',
                           'Japanese', 'Chinese', 'Arabic', 'Portuguese']

    if target_language not in SUPPORTED_LANGUAGES:
        target_language = "English"
        flash("Language not supported. Defaulting to English.", "warning")

    prompt = f"""Analyze this legal document in {target_language}:
    {text[:10000]}

    Provide:
    1. Plain language summary in {target_language}
    2. Important clauses in {target_language}

    Format response in {target_language} with headings:
    [SUMMARY]
    <text>

    [CLAUSES]
    <text>
    """

    summary = f"Summary not available in {target_language}"
    important_clauses = f"Clauses not identified in {target_language}"

    try:
        model = genai.GenerativeModel('gemini-2.0-flash')
        response = model.generate_content(prompt)

        if "[SUMMARY]" in response.text and "[CLAUSES]" in response.text:
            parts = response.text.split("[CLAUSES]")
            summary = parts[0].replace("[SUMMARY]", "").strip()
            important_clauses = parts[1].strip()
        else:
            summary = response.text.split("Important Clauses")[0].strip()
            important_clauses = "Important Clauses" + response.text.split("Important Clauses")[1] if "Important Clauses" in response.text else ""

        summary = summary.replace('\n', '<br>').replace('```', '')
        important_clauses = f"<h4>Important Clauses</h4>" + important_clauses.replace('\n', '<br>').replace('```', '')

    except Exception as e:
        print(f"Gemini API error: {str(e)}")
        flash("Failed to analyze document. Please try again later.", "danger")

    return summary, important_clauses

@app.context_processor
def inject_current_year():
    return {'current_year': datetime.now().year}

@app.route('/set_language')
def set_language():
    lang = request.args.get('lang', 'en')
    session['language'] = lang
    return redirect(request.referrer or url_for('index'))

@app.route('/')
def index():
    conn = get_db_connection()
    documents = conn.execute('SELECT * FROM documents ORDER BY upload_date DESC').fetchall()
    conn.close()

    documents = [dict(doc) for doc in documents]
    return render_template('index.html', documents=documents)

@app.route('/upload', methods=['POST'])
def upload_document():
    if 'document' not in request.files:
        flash('No file part in the request.', 'danger')
        return redirect(request.url)

    file = request.files['document']
    target_language = request.form.get('language', 'English')

    if file.filename == '':
        flash('No selected file.', 'warning')
        return redirect(request.url)

    if file and allowed_file(file.filename):
        original_filename = file.filename
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        unique_filename = f"{timestamp}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)

        text = extract_text(file_path)
        summary, important_clauses = analyze_document(text, target_language)

        conn = get_db_connection()
        conn.execute(
            '''INSERT INTO documents 
            (filename, original_filename, upload_date, summary, important_clauses, language) 
            VALUES (?, ?, ?, ?, ?, ?)''',
            (unique_filename, original_filename, datetime.now(), summary, important_clauses, target_language)
        )
        conn.commit()
        conn.close()

        flash(f'Document analyzed successfully in {target_language}!', 'success')
        return redirect(url_for('index'))
    else:
        flash('File type not allowed. Please upload PDF, TXT, or DOCX.', 'danger')
        return redirect(request.url)

@app.route('/download_summary/<int:doc_id>')
def download_summary(doc_id):
    conn = get_db_connection()
    document = conn.execute('SELECT * FROM documents WHERE id = ?', (doc_id,)).fetchone()
    conn.close()

    if not document:
        flash('Document not found', 'danger')
        return redirect(url_for('index'))

    document = dict(document)
    original_filename = document['original_filename']
    base_name = original_filename.rsplit('.', 1)[0]
    language = document.get('language', 'English')
    summary_filename = f"{base_name}_summary_{language}.txt"

    import re
    summary_text = re.sub('<.*?>', '', document['summary']).replace('<br>', '\n').replace('&nbsp;', ' ')
    important_clauses_text = re.sub('<.*?>', '', document['important_clauses']).replace('<br>', '\n').replace('&nbsp;', ' ')

    content = f"""DOCUMENT ANALYSIS FOR: {original_filename}
Language: {language}
Generated by DocBrief on {document['upload_date']}

=============================================
PLAIN LANGUAGE SUMMARY
=============================================
{summary_text}

=============================================
IMPORTANT CLAUSES
=============================================
{important_clauses_text}
"""

    response = Response(
        content,
        mimetype="text/plain",
        headers={"Content-Disposition": f"attachment;filename={summary_filename}"}
    )
    return response

@app.route('/document/<int:doc_id>')
def view_document(doc_id):
    conn = get_db_connection()
    document = conn.execute('SELECT * FROM documents WHERE id = ?', (doc_id,)).fetchone()
    conn.close()

    if document:
        return render_template('document.html', document=dict(document))

    flash('Document not found', 'danger')
    return redirect(url_for('index'))

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    flash('File is too large. Maximum size allowed is 16MB.', 'danger')
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
