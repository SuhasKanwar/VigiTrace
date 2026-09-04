import os

from dotenv import load_dotenv

SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(SERVICE_DIR, ".env"))

PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
VIGITRACE_SERVER_URL = os.getenv("VIGITRACE_SERVER_URL", "http://localhost:9000")

# Acquired evidence is written here. Derived artifacts are kept separate from
# any source media so the original is never modified in place.
EVIDENCE_DIR = os.getenv("EVIDENCE_DIR", os.path.join(SERVICE_DIR, "evidence"))

# Optional AI assistance. Absent keys degrade analysis to a clear
# "not configured" state rather than failing the pipeline.
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
AI_ENABLED = bool(GROQ_API_KEY or NVIDIA_API_KEY)

