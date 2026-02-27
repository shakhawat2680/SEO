from fastapi import FastAPI, Depends
from core.auth import verify_api_key
from ai.auto_seo_engine.engine import AutoSEOEngine

app = FastAPI(title="AutoSEO Service")

@app.get("/")
def home():
    return {"status": "AutoSEO Engine Running"}

@app.post("/analyze")
def analyze(url: str, tenant=Depends(verify_api_key)):
    engine = AutoSEOEngine(tenant_id=tenant)
    return engine.run(url)
