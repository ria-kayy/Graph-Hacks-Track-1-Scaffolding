import json
import logging
import time
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from backend.api.routes import router
from backend.api.admin import authorized

logging.basicConfig(level=logging.INFO, format="%(message)s")
app = FastAPI(title="WhyGraph", description="Repository memory that remembers why code changed")
app.include_router(router)


@app.middleware("http")
async def timing(request: Request, call_next):
    started = time.monotonic()
    administrative = request.method == "POST" and request.url.path.startswith("/api/repositories")
    if request.method == "POST" and request.url.path == "/api/query":
        try:
            payload = await request.json()
            administrative = isinstance(payload, dict) and payload.get("post") not in (None, False, "false", "False", 0, "0")
        except ValueError:
            pass  # Let FastAPI return its normal invalid-JSON response.
    if administrative and not authorized(request):
        return JSONResponse(status_code=403, content={"detail": "Administration requires a valid admin token or a direct local connection; public mode disables these actions"})
    response = await call_next(request)
    logging.getLogger("whygraph.api").info(json.dumps({"operation": request.method, "path": request.url.path, "status": response.status_code, "elapsed_ms": round((time.monotonic()-started)*1000, 2)}))
    return response


@app.exception_handler(Exception)
async def failed(request, exc):
    logging.getLogger("whygraph.api").exception("Operation failed")
    # Never put provider messages, tokens, or environment values in public responses.
    return JSONResponse(status_code=503, content={"detail": "Operation failed. Check the local backend logs and FalkorDB connection."})
