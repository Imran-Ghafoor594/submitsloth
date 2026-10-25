"""Deterministic inspection and packaging. Uploaded code is never executed."""
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath
from pypdf import PdfReader
from PIL import Image

ROLES = {'report', 'code', 'screenshot', 'other'}
KINDS = {'exists', 'max_pages', 'min_count', 'contains', 'filename', 'manual'}
CODE_EXTS = {'.py', '.js', '.ts', '.tsx', '.jsx', '.java', '.cpp', '.c', '.h', '.html', '.css', '.ipynb', '.sql', '.r', '.m', '.go', '.rs'}
MAX_FILE = 12 * 1024 * 1024

class InputError(ValueError):
    pass

def clean_name(name):
    name = str(name).replace('\\', '/').split('/')[-1]
    name = re.sub(r'[^\w.() -]', '_', name, flags=re.UNICODE).strip(' .')[:120]
    return name or 'unnamed'

def archive_path(path):
    if not isinstance(path, str) or len(path) > 220 or '\\' in path or path.startswith('/'):
        raise InputError('Invalid export path.')
    parts = path.split('/')
    if any(p in {'', '.', '..'} or ':' in p or clean_name(p) != p for p in parts):
        raise InputError('Use ordinary folder/file names without traversal or special characters.')
    if parts[0].lower() == '_submitsloth':
        raise InputError('The _submitsloth folder is reserved for the review manifest.')
    return str(PurePosixPath(path))

def validate_requirements(items):
    if not isinstance(items, list) or len(items) > 50:
        raise InputError('Provide up to 50 checklist requirements.')
    out = []
    for i, r in enumerate(items):
        if not isinstance(r, dict):
            raise InputError('Invalid checklist row.')
        kind, target = r.get('kind', 'manual'), r.get('target', 'report')
        if kind not in KINDS or target not in ROLES | {'any'}:
            raise InputError('Unknown check type or file group.')
        label = str(r.get('label', '')).strip()[:300]
        if not label:
            raise InputError('Every requirement needs a description.')
        value = str(r.get('value', '')).strip()[:300]
        if kind in {'max_pages', 'min_count'}:
            if not value.isdigit() or not 1 <= int(value) <= 1000:
                raise InputError('Page/count limits must be whole numbers from 1 to 1000.')
        if kind in {'contains', 'filename'} and not value:
            raise InputError('Text and filename checks need a value.')
        out.append({'id': str(i + 1), 'label': label, 'kind': kind, 'target': target,
                    'value': value, 'source_quote': str(r.get('source_quote', ''))[:700]})
    return out

def guess_role(name):
    ext = PurePosixPath(name).suffix.lower()
    if ext == '.pdf' or ext == '.docx': return 'report'
    if ext in CODE_EXTS: return 'code'
    if ext in {'.png', '.jpg', '.jpeg', '.webp'}: return 'screenshot'
    return 'other'

def docx_text(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if sum(x.file_size for x in z.infolist()) > 25 * 1024 * 1024:
            raise InputError('DOCX uncompressed size exceeds 25 MB.')
        xml = z.read('word/document.xml')
        root = ET.fromstring(xml)
        return ' '.join(x.text or '' for x in root.iter() if x.tag.endswith('}t'))

def inspect_file(name, data, role=None):
    if not data: raise InputError(f'{name}: empty file.')
    if len(data) > MAX_FILE: raise InputError(f'{name}: exceeds 12 MB.')
    name = clean_name(name)
    role = role or guess_role(name)
    if role not in ROLES: raise InputError('Invalid file role.')
    f = {'name': name, 'size': len(data), 'role': role, 'pages': None, 'text': '', 'warning': '', 'valid': True}
    ext = PurePosixPath(name).suffix.lower()
    try:
        if ext == '.pdf':
            reader = PdfReader(io.BytesIO(data), strict=False)
            if reader.is_encrypted: raise ValueError('Encrypted PDF')
            f['pages'] = len(reader.pages)
            if len(reader.pages) > 100:
                f['warning'] = 'Text extraction limited to the first 100 pages.'
            f['text'] = '\n'.join((p.extract_text() or '') for p in list(reader.pages)[:100])[:200000]
            if not f['text'].strip(): f['warning'] = 'No selectable text. Scanned PDF needs manual review; automatic PDF OCR is not included.'
        elif ext == '.docx':
            f['text'] = docx_text(data)[:200000]
            f['warning'] = 'DOCX page count depends on rendering. Export to PDF to check the page limit.'
        elif ext in {'.png', '.jpg', '.jpeg', '.webp'}:
            with Image.open(io.BytesIO(data)) as im:
                if im.width * im.height > 20000000: raise ValueError('Image is larger than 20 megapixels')
                im.verify()
        elif ext in CODE_EXTS | {'.txt', '.md', '.csv', '.json', '.yaml', '.yml'}:
            f['text'] = data.decode('utf-8')[:200000]
        elif ext == '.zip':
            f['warning'] = 'Archive contents are not inspected. Upload source files individually for code checks.'
        else:
            f['warning'] = 'File format is not inspected; presence only.'
    except Exception:
        f['valid'] = False
        f['warning'] = 'Could not read this file safely. It may be corrupt, encrypted, too large to inspect, or have the wrong extension.'
    return f

def run_checks(requirements, files):
    results = []
    for r in requirements:
        selected = [f for f in files if r['target'] == 'any' or f['role'] == r['target']]
        valid = [f for f in selected if f['valid']]
        status, evidence = 'review', 'This requirement needs human judgment.'
        kind, value = r['kind'], r['value']
        if kind == 'exists':
            status = 'pass' if valid else ('review' if selected else 'fail')
            evidence = f'{len(valid)} readable file(s) assigned to {r["target"]}. Presence only; content quality is not assessed.'
        elif kind == 'min_count':
            n = int(value)
            status = 'pass' if len(valid) >= n else ('review' if len(selected) >= n else 'fail')
            evidence = f'{len(valid)} readable file(s); at least {n} required. File roles are user-confirmed.'
        elif kind == 'max_pages':
            known = [f for f in valid if f['pages'] is not None]
            exceeds = [f for f in known if f['pages'] > int(value)]
            if not selected: status, evidence = 'fail', 'No file in the selected group.'
            elif exceeds: status, evidence = 'fail', '; '.join(f'{f["name"]}: {f["pages"]} pages (limit {value})' for f in exceeds)
            elif len(known) != len(selected): evidence = 'Page count is only verified for readable PDFs. Convert other documents to PDF.'
            else: status, evidence = 'pass', '; '.join(f'{f["name"]}: {f["pages"]} pages ≤ {value}' for f in known)
        elif kind == 'contains':
            match = next((f for f in valid if value.casefold() in f['text'].casefold()), None)
            if match:
                at = match['text'].casefold().find(value.casefold())
                status, evidence = 'pass', f'{match["name"]}: “…{match["text"][max(0, at-40):at+len(value)+70]}…” (literal match only)'
            elif not selected: status, evidence = 'fail', 'No file in the selected group.'
            else: evidence = 'Exact text was not found in extracted content. Check spelling, images, or formatting manually.'
        elif kind == 'filename':
            # Check original uploaded names, never silently claim export naming is already applied.
            match = next((f for f in selected if f['name'] == value), None)
            status = 'pass' if match else 'fail'
            evidence = f'Original filename {value!r} ' + ('found.' if match else 'not found. Export renaming does not change this check.')
        results.append({**r, 'status': status, 'evidence': evidence})
    return results
