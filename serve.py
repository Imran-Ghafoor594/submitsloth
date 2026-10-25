"""Production WSGI entry point (works on Windows and Linux)."""
import os
from waitress import serve
from app import app
if __name__ == '__main__':
    serve(app, host='0.0.0.0', port=int(os.getenv('PORT', '5000')), threads=4, max_request_body_size=30 * 1024 * 1024)
