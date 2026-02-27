from fastapi import FastAPI, Depends
from core.auth import verify_api_key
from ai.auto_seo_engine.engine import AutoSEOEngine
from analyzer import analyze_seo

app = FastAPI(title="AutoSEO Service")

@app.get("/")
def home():
    return {"status": "AutoSEO Engine Running"}

@app.post("/analyze")
def analyze(url: str = None, payload: dict = None, tenant=Depends(verify_api_key)):
    """
    Hybrid mode:
    - url → Auto SEO Engine
    - payload → legacy analyzer
    """
    engine = AutoSEOEngine(tenant_id=tenant)

    if url:
        return engine.run(url)

    if payload:
        return analyze_seo(payload)

    return {"error": "Provide url or payload"}
