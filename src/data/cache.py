"""Download cache: data/raw/ with a SHA256 manifest. Skips files already present unless refresh=True."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
MANIFEST = RAW / "manifest.json"
UA = {"User-Agent": "Mozilla/5.0 (CarbonScope-India research ingest; +https://github.com)"}
REFRESH = os.environ.get("CARBONSCOPE_REFRESH") == "1"
_LOCK = threading.Lock()


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str | list[str], dest: Path, refresh: bool | None = None, retries: int = 3, data: dict | None = None) -> Path:
    """Download url (or first working mirror) to dest. Records sha256; logs when a refresh changed the file.
    `data` switches to a form POST (used by IMD's gridded-data endpoints)."""
    refresh = REFRESH if refresh is None else refresh
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0 and not refresh:
        return dest
    urls = [url] if isinstance(url, str) else url
    err: Exception | None = None
    for u in urls:
        for attempt in range(retries):
            try:
                req = requests.post(u, data=data, headers=UA, timeout=300, stream=True) if data else \
                    requests.get(u, headers=UA, timeout=120, stream=True)
                with req as r:
                    r.raise_for_status()
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    with open(tmp, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                digest = sha256(tmp)
                with _LOCK:
                    m = _manifest()
                    old = m.get(str(dest.relative_to(RAW)), {}).get("sha256")
                    if old == digest and dest.exists():
                        tmp.unlink()  # unchanged upstream
                    else:
                        tmp.replace(dest)
                    m[str(dest.relative_to(RAW))] = {"url": u, "sha256": digest, "fetched": time.strftime("%Y-%m-%d")}
                    MANIFEST.write_text(json.dumps(m, indent=1, sort_keys=True))
                if old and old != digest:
                    print(f"  [cache] upstream changed: {dest.name}")
                return dest
            except Exception as e:  # noqa: BLE001
                err = e
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"download failed for {urls}: {err}")
