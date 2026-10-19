"""Evidence store: content-addressed bodies + one JSON line per fetch (the metadata sidecar).

Bodies: data/raw/bodies/<sha[:2]>/<sha>.gz  (sha256 of the *uncompressed* bytes)
Homepages go to data/raw/homepage/ (git-ignored; shipped as Actions artifacts).
Fetch records: data/raw/fetches/<snapshot>.jsonl
"""

from __future__ import annotations

import gzip
import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

RAW = Path("data/raw")


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class FetchRecord:
    domain: str
    host: str
    snapshot: str
    resource: str  # robots|robots_apex|ads|homepage|homepage_rendered|host|dns|meta_docs|gtm
    source: str  # live_direct|live_playwright|wayback|doh
    requested_url: str
    final_url: str | None = None
    redirect_chain: list[str] = field(default_factory=list)
    http_status: int | None = None
    fetch_status: str | None = None
    content_type: str | None = None
    bytes: int = 0
    truncated: bool = False
    sha256: str | None = None
    body_path: str | None = None
    wayback_ts: str | None = None
    age_days: float | None = None
    challenge_detected: bool = False
    robots_redirected_cross_host: bool = False
    fetched_at: str = field(default_factory=now_iso)
    engine_credits: int = 0
    error: str | None = None
    fetch_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])


def save_body(body: bytes, kind: str = "bodies", root: Path = RAW) -> tuple[str, str]:
    sha = hashlib.sha256(body).hexdigest()
    p = root / kind / sha[:2] / f"{sha}.gz"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        with gzip.GzipFile(tmp, "wb", compresslevel=9, mtime=0) as f:
            f.write(body)
        tmp.replace(p)
    return sha, str(p)


def load_body(path: str | None) -> bytes | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    with gzip.open(p, "rb") as f:
        return f.read()


class FetchLog:
    def __init__(self, snapshot: str, root: Path = RAW):
        self.path = root / "fetches" / f"{snapshot}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, rec: FetchRecord) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def done_keys(self) -> set[tuple[str, str]]:
        """(domain, resource) pairs already recorded — makes runs resumable."""
        return {(r["domain"], r["resource"]) for r in self.read()}
