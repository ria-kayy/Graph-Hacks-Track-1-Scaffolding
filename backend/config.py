import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    repo: str = os.getenv("TARGET_REPO", "pallets/click")
    ref: str = os.getenv("TARGET_REF", "HEAD")
    graph: str = os.getenv("FALKORDB_GRAPH", "whygraph")
    host: str = os.getenv("FALKORDB_HOST", "localhost")
    port: int = int(os.getenv("FALKORDB_PORT", "6379"))
    password: str | None = os.getenv("FALKORDB_PASSWORD") or None
    mode: str = os.getenv("FALKORDB_MODE", "server")
    lite_path: str = os.getenv("FALKORDB_LITE_PATH", str(ROOT / ".data/falkordb.db"))
    github_token: str = os.getenv("GITHUB_TOKEN", "")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    debug: bool = os.getenv("DEBUG_QUERIES", "false").lower() == "true"
    triage_fork: str = os.getenv("TRIAGE_FORK", "")


settings = Settings()
