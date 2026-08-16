"""Minimal Gmail client abstraction. Real implementation uses googleapiclient.
In tests this module will be mocked."""
import base64

class GmailClient:
    def __init__(self, token_path):
        self.token_path = token_path

    def available(self):
        from pathlib import Path
        return Path(self.token_path).exists()

    def list_unread(self, subject_prefix):
        # Real impl would call Gmail API; here just return [] in default runtime
        return []

    def get_message(self, msg_id):
        return {}

    def extract_plain_text(self, payload):
        # simple walker
        if not payload:
            return ''
        mime = payload.get('mimeType','')
        if mime.startswith('text/plain') and payload.get('body',{}).get('data'):
            return base64.urlsafe_b64decode(payload['body']['data'].encode()).decode(errors='replace')
        for p in payload.get('parts',[]) or []:
            t = self.extract_plain_text(p)
            if t:
                return t
        return ''

    def has_result(self, task_id):
        return False

    def send_message(self, to, subject, body):
        # real impl would send
        return None
