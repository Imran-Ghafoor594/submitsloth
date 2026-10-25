import io
import json
import os
import unittest
import zipfile
from unittest.mock import patch
from pypdf import PdfWriter
from PIL import Image
from app import app
from submitsloth.core import archive_path, InputError
from submitsloth.ai import extract_requirements

def pdf(pages):
    w=PdfWriter()
    for _ in range(pages):w.add_blank_page(width=300,height=300)
    b=io.BytesIO();w.write(b);return b.getvalue()

def png():
    b=io.BytesIO();Image.new('RGB',(8,8),'blue').save(b,'PNG');return b.getvalue()

def req(kind,value='',target='report'):
    return {'label':'Test requirement','kind':kind,'target':target,'value':value}

class WorkflowTests(unittest.TestCase):
    def setUp(self):self.client=app.test_client()
    def submit(self,endpoint='/api/check',requirements=None,entries=None,files=None,**kwargs):
        files=files or [('report.pdf',pdf(2))]
        entries=entries or [{'role':'report','path':'report/'+n} for n,_ in files]
        metadata={'requirements':requirements or [req('max_pages','2')],'files':entries,**kwargs}
        return self.client.post(endpoint,data={'metadata':json.dumps(metadata),'files':[(io.BytesIO(b),n) for n,b in files]},content_type='multipart/form-data')
    def test_home_and_status(self):
        with self.client.get('/') as response: self.assertEqual(response.status_code,200)
        self.assertIn('ai_configured',self.client.get('/api/status').json)
    def test_page_limit_pass_and_fail(self):
        self.assertEqual(self.submit().json['results'][0]['status'],'pass')
        self.assertEqual(self.submit(files=[('report.pdf',pdf(3))]).json['results'][0]['status'],'fail')
    def test_missing_screenshots(self):
        r=self.submit(requirements=[req('min_count','3','screenshot')],files=[('a.png',png()),('b.png',png())],entries=[{'role':'screenshot','path':'a.png'},{'role':'screenshot','path':'b.png'}])
        self.assertEqual(r.json['results'][0]['status'],'fail')
    def test_corrupt_pdf_needs_review(self):
        r=self.submit(files=[('report.pdf',b'garbage')]);self.assertEqual(r.json['results'][0]['status'],'review');self.assertFalse(r.json['files'][0]['valid'])
    def test_literal_text_match(self):
        r=self.submit(requirements=[req('contains','Student Example')],files=[('report.txt',b'Name: Student Example')]);self.assertEqual(r.json['results'][0]['status'],'pass')
    def test_missing_text_not_claimed_failed(self):
        self.assertEqual(self.submit(requirements=[req('contains','Student Example')]).json['results'][0]['status'],'review')
    def test_docx_page_count_unknown(self):
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:z.writestr('word/document.xml','<document><t>Example</t></document>')
        self.assertEqual(self.submit(files=[('report.docx',b.getvalue())]).json['results'][0]['status'],'review')
    def test_export_unresolved_requires_acknowledgment(self):
        self.assertEqual(self.submit('/api/export',requirements=[req('manual')]).status_code,400)
        self.assertEqual(self.submit('/api/export',requirements=[req('manual')],acknowledge=True).status_code,200)
    def test_zip_preserves_bytes_and_report(self):
        original=pdf(2);r=self.submit('/api/export',files=[('report.pdf',original)],acknowledge=True,zip_name='Team07.zip');self.assertEqual(r.status_code,200)
        with zipfile.ZipFile(io.BytesIO(r.data)) as z:
            self.assertEqual(z.read('report/report.pdf'),original)
            self.assertEqual(json.loads(z.read('_submitsloth/review.json'))['results'][0]['status'],'pass')
    def test_traversal_and_reserved_path_rejected(self):
        for path in ['../bad','/etc/file','a/../../bad','a\\bad','a//b','_submitsloth/review.json']:
            with self.assertRaises(InputError):archive_path(path)
    def test_duplicate_paths_rejected(self):
        r=self.submit(files=[('a.txt',b'a'),('b.txt',b'b')],entries=[{'role':'other','path':'same.txt'},{'role':'other','path':'SAME.txt'}]);self.assertEqual(r.status_code,400)
    def test_bad_numeric_requirement_rejected(self):
        self.assertEqual(self.submit(requirements=[req('max_pages','-1')]).status_code,400)
    def test_original_filename_not_export_path(self):
        r=self.submit(requirements=[req('filename','renamed.pdf')],entries=[{'role':'report','path':'renamed.pdf'}]);self.assertEqual(r.json['results'][0]['status'],'fail')
    def test_instruction_import(self):
        r=self.client.post('/api/instructions',data={'file':(io.BytesIO(b'Submit a report of 2 pages.'),'brief.txt')});self.assertEqual(r.json['text'],'Submit a report of 2 pages.')
    def test_ai_without_config_and_without_consent(self):
        with patch.dict(os.environ,{'AI_BASE_URL':'','AI_MODEL':''}):
            r=self.client.post('/api/extract',json={'text':'Submit a two page report.','consent':True});self.assertEqual(r.status_code,400)
        self.assertEqual(self.client.post('/api/extract',json={'text':'Submit a two page report.'}).status_code,400)
    def test_ai_response_validation_mocked(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,*args):return json.dumps({'choices':[{'message':{'content':json.dumps({'requirements':[dict(req('max_pages','2'),source_quote='invented text')]})}}]}).encode()
        with patch.dict(os.environ,{'AI_BASE_URL':'http://localhost:11434/v1','AI_MODEL':'test'}),patch('urllib.request.urlopen',return_value=Response()):
            self.assertEqual(extract_requirements('Submit a report.')[0]['kind'],'manual')

if __name__=='__main__':unittest.main()
