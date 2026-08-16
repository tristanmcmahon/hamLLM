"""Entry point for hamLLM bridge.
Minimal implementation; imports Gmail/Ollama helpers lazily to allow tests to mock.
"""
import os
import re
import time
import json
from pathlib import Path

SUBJ_RE = re.compile(r"^HELIX-TASK\s+(\S+)$")

def print_stage(s):
    print(s, flush=True)

def parse_subject(subject):
    m = SUBJ_RE.match(subject or "")
    return m.group(1) if m else None

def main(argv=None):
    # Config via env
    trusted_sender = os.environ.get("HAM_TRUSTED_SENDER", "tristan.mcmahon@gmail.com")
    credential_path = os.environ.get("HAM_CREDENTIAL_PATH", os.path.expanduser("~/.config/gwen/gmail_token.json"))
    state_path = os.environ.get("HAM_STATE_PATH", os.path.expanduser("~/.local/state/gwen/processed.json"))
    ollama_url = os.environ.get("HAM_OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
    model = os.environ.get("HAM_MODEL", "helix-qwen:latest")

    print_stage("starting")
    # Lazy imports so tests can mock modules
    from .gmail import GmailClient
    from .state import State
    from .ollama import call_ollama

    svc = GmailClient(credential_path)
    if not svc.available():
        print_stage("no gmail token; exiting")
        return 0

    state = State(Path(state_path))
    msgs = svc.list_unread("HELIX-TASK")
    for mid in msgs:
        print_stage(f"fetching {mid}")
        msg = svc.get_message(mid)
        subject = msg.get('subject')
        frm = msg.get('from')
        # normalize
        frm_addr = frm
        if '<' in frm and '>' in frm:
            frm_addr = frm.split('<',1)[1].split('>',1)[0]
        if frm_addr.strip() != trusted_sender:
            print_stage(f"skipping {mid}: sender mismatch")
            continue
        tid = parse_subject(subject)
        if not tid:
            print_stage(f"skipping {mid}: malformed subject")
            continue
        if state.is_processed(tid):
            print_stage(f"already processed {tid}; skipping")
            continue
        # check existing result
        if svc.has_result(tid):
            print_stage(f"found existing result for {tid}; marking processed")
            state.mark_processed(tid)
            continue
        body = svc.extract_plain_text(msg.get('payload', {}))
        print_stage(f"posting to ollama {tid}")
        resp = call_ollama(ollama_url, model, body)
        # send reply
        subj_out = f"HELIX-RESULT {tid}"
        start = time.time()
        svc.send_message(trusted_sender, subj_out, resp)
        end = time.time()
        state.mark_processed(tid)
        print_stage(f"done {tid}")
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
