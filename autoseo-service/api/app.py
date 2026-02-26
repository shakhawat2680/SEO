from fastapi import FastAPI, Depends
from analyzer import analyze_seo
from auth import verify_api_key

app = FastAPI(title="AutoSEO Service", description="Multi-Tenant SEO Analysis API")

@app.get("/")
def home():
    return {"status": "SEO Engine Running"}

@app.post("/analyze")
def analyze(payload: dict, tenant=Depends(verify_api_key)):
    """
    Analyze SEO of a page.
    Payload example:
    {
        "title": "Page title here",
        "meta_description": "Meta description here"
    }
    """
    return analyze_seo(payload)
