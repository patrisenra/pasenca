from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

app = FastAPI()

VERIFY_TOKEN = "pasenca_verify_2026"

@app.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        return challenge

    return PlainTextResponse("Verification failed", status_code=403)

@app.post("/webhook")
async def receive_webhook(request: Request):
    _ = await request.json()
    return {"status": "ok"}

@app.get("/")
async def health():
    return {"status": "running"}
