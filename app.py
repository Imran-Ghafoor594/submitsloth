import io
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from flask import Flask, request, jsonify, send_file
from dotenv import load_dotenv
from werkzeug.exceptions import HTTPException
from submitsloth.core import InputError, inspect_file, validate_requirements, run_checks, archive_path, clean_name
from submitsloth.ai import configuration, extract_requirements

load_dotenv()
app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['MAX_CONTENT_LENGTH'] = 30 * 1024 * 1024
app.config['MAX_FORM_MEMORY_SIZE'] = 256 * 1024

@app.after_request
def headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.errorhandler(InputError)
def bad_input(e): return jsonify(error=str(e)), 400

@app.errorhandler(HTTPException)
def http_error(e): return jsonify(error=e.description), e.code

@app.errorhandler(Exception)
def unexpected(e):
    app.logger.exception('Request failed')
    return jsonify(error='The server could not complete this request. Review the files and try again.'), 500

@app.get('/')
def index(): return app.send_static_file('index.html')

@app.get('/api/status')
def status():
    base, model, _ = configuration()
    return jsonify(ai_configured=bool(base and model), model=model if base and model else None,
                   ocr_available=bool(shutil.which('tesseract')), max_total_mb=30, max_file_mb=12)

@app.post('/api/instructions')
def instructions():
    upload = request.files.get('file')
    if not upload: raise InputError('Choose an instruction file.')
    data = upload.read(12 * 1024 * 1024 + 1)
    info = inspect_file(upload.filename, data)
    text = info['text']
    if Path(info['name']).suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'} and info['valid']:
        if not shutil.which('tesseract'):
            raise InputError('Image OCR is unavailable on this server. Paste the instructions or use a text PDF/DOCX. Docker includes Tesseract.')
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / ('input' + Path(info['name']).suffix)
            source.write_bytes(data)
            try:
                result = subprocess.run(['tesseract', str(source), 'stdout', '-l', 'eng'], capture_output=True, text=True, timeout=25)
                if result.returncode: raise InputError('Image OCR failed. Paste the instructions manually.')
                text = result.stdout
            except subprocess.TimeoutExpired:
                raise InputError('OCR exceeded 25 seconds. Use a smaller image or paste the instructions.') from None
    if not text.strip(): raise InputError(info['warning'] or 'No text found. Paste instructions manually.')
    return jsonify(text=text[:20000], warning=info['warning'])

@app.post('/api/extract')
def extract():
    obj = request.get_json(silent=True) or {}
    text = obj.get('text', '')
    if not isinstance(text, str) or not 10 <= len(text) <= 20000:
        raise InputError('Provide between 10 and 20,000 characters of instructions.')
    if obj.get('consent') is not True:
        raise InputError('Confirm permission to send instruction text to your configured AI provider.')
    return jsonify(requirements=extract_requirements(text), model=configuration()[1])

def parse_submission():
    try:
        metadata = json.loads(request.form.get('metadata', '{}'))
    except ValueError: raise InputError('Invalid submission metadata.') from None
    if not isinstance(metadata, dict): raise InputError('Invalid metadata.')
    requirements = validate_requirements(metadata.get('requirements', []))
    uploads = request.files.getlist('files')
    entries = metadata.get('files', [])
    if not isinstance(entries, list) or not 1 <= len(uploads) <= 60 or len(entries) != len(uploads):
        raise InputError('Upload 1–60 files with matching metadata.')
    files, binaries, seen = [], [], set()
    for upload, entry in zip(uploads, entries):
        if not isinstance(entry, dict): raise InputError('Invalid file metadata.')
        data = upload.read(12 * 1024 * 1024 + 1)
        f = inspect_file(upload.filename, data, entry.get('role'))
        dest = archive_path(entry.get('path', f['name']))
        if dest.casefold() in seen: raise InputError('Duplicate export paths. Give each file a unique destination.')
        seen.add(dest.casefold())
        f['path'] = dest
        files.append(f)
        binaries.append(data)
    return metadata, requirements, files, binaries

@app.post('/api/check')
def check():
    _, requirements, files, _ = parse_submission()
    return jsonify(results=run_checks(requirements, files), files=[{k:v for k,v in f.items() if k != 'text'} for f in files])

@app.post('/api/export')
def export():
    metadata, requirements, files, binaries = parse_submission()
    results = run_checks(requirements, files)
    unresolved = not results or any(r['status'] != 'pass' for r in results) or any(f['warning'] or not f['valid'] for f in files)
    if unresolved and metadata.get('acknowledge') is not True:
        raise InputError('Review unresolved checks/file warnings and explicitly acknowledge them before export.')
    report = {'created_utc': datetime.now(timezone.utc).isoformat(), 'notice': 'Automated structural checks, not grading or certification. Manual requirements remain unresolved.',
              'unresolved_acknowledged': bool(metadata.get('acknowledge')), 'results': results,
              'files': [{k:v for k,v in f.items() if k != 'text'} for f in files]}
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as z:
        for f, data in zip(files, binaries): z.writestr(f['path'], data)
        z.writestr('_submitsloth/review.json', json.dumps(report, indent=2, ensure_ascii=False))
    stream.seek(0)
    name = clean_name(metadata.get('zip_name', 'submission'))
    if not name.lower().endswith('.zip'): name += '.zip'
    return send_file(stream, mimetype='application/zip', as_attachment=True, download_name=name)

if __name__ == '__main__':
    app.run(host=os.getenv('HOST', '127.0.0.1'), port=int(os.getenv('PORT', '5000')), debug=False)
