from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
from fastapi.middleware.cors import CORSMiddleware

from config import ALLOWED_ORIGINS, HOST, PORT
from routers import agent, devices, disk, integrity, recordings, reports
from utils.exception import VigiTraceException
from utils.logger import logger

app = FastAPI(title="VigiTrace Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agent.router)
app.include_router(devices.router)
app.include_router(recordings.router)
app.include_router(disk.router)
app.include_router(integrity.router)
app.include_router(reports.router)


@app.exception_handler(VigiTraceException)
def handle_vigitrace_exception(_request: Request, exc: VigiTraceException) -> JSONResponse:
    logger.error("VigiTraceException: %s", exc)
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.error_message},
    )


@app.exception_handler(Exception)
def handle_unexpected_exception(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled service error")
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "VigiTrace Service encountered an unexpected error.",
            "error": str(exc),
        },
    )


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
