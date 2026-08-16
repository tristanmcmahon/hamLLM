import json
from pathlib import Path

def atomic_write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(sorted(list(data)), f)
        f.flush(); import os; os.fsync(f.fileno())
    tmp.rename(path)

class State:
    def __init__(self, path: Path):
        self.path = path
        self._set = set()
        if path.exists():
            try:
                self._set = set(json.loads(path.read_text(encoding='utf-8')))
            except Exception:
                self._set = set()

    def is_processed(self, tid: str) -> bool:
        return tid in self._set

    def mark_processed(self, tid: str):
        self._set.add(tid)
        atomic_write(self.path, self._set)
