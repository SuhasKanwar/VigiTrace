import os

from dotenv import load_dotenv

SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(SERVICE_DIR, ".env"))

PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
VIGITRACE_SERVER_URL = os.getenv("VIGITRACE_SERVER_URL", "http://localhost:9000")

# Acquired evidence is written here. Derived artifacts are kept separate from
# any source media so the original is never modified in place.
EVIDENCE_DIR = os.getenv("EVIDENCE_DIR", os.path.join(SERVICE_DIR, "evidence"))

# Optional AI assistance via NVIDIA NIM, whose API is OpenAI-compatible. An
# absent key degrades narration to a clear "not configured" state rather than
# failing the pipeline; deterministic findings are produced either way.
#
# The model is configurable because NIM entitlements are per-account: a model
# can appear in /v1/models and still return 404 for a given key, so the default
# is one verified as reachable rather than the largest on the menu.
NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "mistralai/mistral-nemotron")
AI_ENABLED = bool(NVIDIA_API_KEY)

