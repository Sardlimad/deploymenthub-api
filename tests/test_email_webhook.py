import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.config import Settings
from app.notifications.email import EmailSender


def _serve(received: list, reply: bytes):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            received.append(json.loads(self.rfile.read(length)))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *args):  # silencio
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_webhook_envia_json_con_secreto():
    received: list = []
    server = _serve(received, b'{"ok":true}')
    try:
        settings = Settings(
            email_webhook_url=f"http://127.0.0.1:{server.server_port}/exec", email_webhook_secret="clave",
            _env_file=None,
        )
        EmailSender(settings).send("a@b.com", "Asunto", "Cuerpo", "<p>Hola</p>")
    finally:
        server.shutdown()
    assert received == [{"secret": "clave", "to": "a@b.com", "subject": "Asunto", "body": "Cuerpo", "html": "<p>Hola</p>"}]


def test_webhook_caido_no_lanza_excepcion():
    settings = Settings(email_webhook_url="http://127.0.0.1:9/exec", _env_file=None)
    EmailSender(settings).send("a@b.com", "Asunto", "Cuerpo")  # absorbe el fallo
