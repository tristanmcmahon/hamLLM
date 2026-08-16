import requests

def call_ollama(url, model, prompt):
    payload = {"model": model, "prompt": prompt, "stream": False}
    r = requests.post(url, json=payload, timeout=90)
    r.raise_for_status()
    try:
        return r.json().get('response') or r.text
    except Exception:
        return r.text
