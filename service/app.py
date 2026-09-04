from fastapi import FastAPI
import uvicorn
from fastapi.middleware.cors import CORSMiddleware

from config import ALLOWED_ORIGINS, HOST, PORT
from routers import agent

app = FastAPI(title="VigiTrace Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agent.router)

@app.get("/", tags=["Root"])
def root() -> dict:
    return {
        "success": True,
        "message": "Welcome to VigiTrace Service. Visit /docs for API documentation."
    }

@app.get("/health", tags=["Health"])
def health() -> dict:
    return {
        "success": True,
        "message": "VigiTrace Service is healthy and running successfully."
    }

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
