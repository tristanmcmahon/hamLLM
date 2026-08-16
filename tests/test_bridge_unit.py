import json
import base64
from pathlib import Path
import pytest
from hamllm import bridge
from hamllm.state import State


def test_parse_subject_ok():
    assert bridge.parse_subject('HELIX-TASK abc123') == 'abc123'


def test_parse_subject_fail():
    assert bridge.parse_subject('HELIX TASK abc') is None


def test_extract_plain_text():
    from hamllm.gmail import GmailClient
    payload = {'mimeType':'multipart/alternative', 'parts':[{'mimeType':'text/plain', 'body':{'data': base64.urlsafe_b64encode(b'hello').decode()}}]}
    g = GmailClient('/nonexistent')
    assert g.extract_plain_text(payload) == 'hello'


def test_state_roundtrip(tmp_path):
    p = tmp_path / 'state.json'
    s = State(p)
    assert not s.is_processed('x')
    s.mark_processed('x')
    assert s.is_processed('x')
    # reload
    s2 = State(p)
    assert s2.is_processed('x')
