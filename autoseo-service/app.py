from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import uuid
from typing import Optional, List, Dict
import sqlite3
import json

from crawler import Crawler
from analyzer import SEOAnalyzer
from models import init_db, execute_query, get_tenant, get_tenant_stats, update_tenant_plan
from auth import verify_api_key, generate_api_key, log_usage

app = FastAPI(title="AutoSEO Service - Multi-Tenant")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database
init_db()

# Models
class SiteRequest(BaseModel):
    url: str
    name: Optional[str] = None
    settings: Optional[Dict] = {}

class SiteResponse(BaseModel):
    id: str
    url: str
    name: str
    tenant_id: str
    created_at: str
    status: str
    last_score: Optional[float]
    last_audit: Optional[str]
    audit_count: Optional[int]

class AuditResponse(BaseModel):
    id: str
    site_id: str
    score: float
    issues: List[dict]
    pages_analyzed: int
    created_at: str

class TenantRequest(BaseModel):
    name: str
    email: str
    plan_type: str = "free"  # free, pro, enterprise

class TenantResponse(BaseModel):
    id: str
    name: str
    email: str
    plan_type: str
    usage_count: int
    rate_limit: int
    api_key: str
    created_at: str

class PlanUpdateRequest(BaseModel):
    plan_type: str
    rate_limit: int

class UsageResponse(BaseModel):
    tenant_id: str
    plan_type: str
    usage_count: int
    rate_limit: int
    remaining: int
    total_sites: int
    total_audits: int
    monthly_usage: int

# Dependency with rate limit error handling
async def get_tenant(api_key: str = Header(..., alias="X-API-Key")):
    result = verify_api_key(api_key)
    
    if not result:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    if isinstance(result, dict) and 'error' in result:
        raise HTTPException(
            status_code=429, 
            detail={
                "error": result['error'],
                "message": result['message'],
                "tenant": result['tenant']['name'],
                "plan": result['tenant']['plan_type'],
                "limit": result['tenant']['rate_limit']
            }
        )
    
    return result

# Public endpoints
@app.post("/tenants", response_model=TenantResponse)
async def create_tenant(tenant: TenantRequest):
    """Register a new tenant (client)"""
    tenant_id = str(uuid.uuid4())
    api_key = generate_api_key()
    
    # Set rate limit based on plan
    rate_limits = {
        "free": 100,
        "pro": 1000,
        "enterprise": 10000
    }
    rate_limit = rate_limits.get(tenant.plan_type, 100)
    
    execute_query(
        """INSERT INTO tenants (id, name, email, api_key, plan_type, rate_limit, created_at) 
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (tenant_id, tenant.name, tenant.email, api_key, tenant.plan_type, rate_limit, datetime.now().isoformat())
    )
    
    # Get tenant details
    result = execute_query(
        "SELECT id, name, email, plan_type, usage_count, rate_limit, created_at FROM tenants WHERE id = ?",
        (tenant_id,),
        fetch=True
    )[0]
    
    return {
        "id": result[0],
        "name": result[1],
        "email": result[2],
        "plan_type": result[3],
        "usage_count": result[4],
        "rate_limit": result[5],
        "api_key": api_key,
        "created_at": result[6]
    }

# Protected endpoints
@app.post("/sites", response_model=SiteResponse)
async def add_site(
    site: SiteRequest, 
    background_tasks: BackgroundTasks,
    tenant: dict = Depends(get_tenant)
):
    """Add a new site for SEO monitoring"""
    site_id = str(uuid.uuid4())
    
    # Check if site already exists for this tenant
    existing = execute_query(
        "SELECT id FROM sites WHERE tenant_id = ? AND url = ?",
        (tenant['id'], site.url),
        fetch=True
    )
    
    if existing:
        raise HTTPException(status_code=400, detail="Site already exists")
    
    execute_query(
        """INSERT INTO sites (id, tenant_id, url, name, settings, created_at, status, audit_count) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (site_id, tenant['id'], site.url, site.name or site.url, 
         json.dumps(site.settings), datetime.now().isoformat(), 'pending', 0)
    )
    
    # Log usage
    log_usage(tenant['id'], 'add_site', site_id)
    
    # Start audit in background
    background_tasks.add_task(run_audit, site_id, site.url, tenant['id'])
    
    return {
        "id": site_id,
        "url": site.url,
        "name": site.name or site.url,
        "tenant_id": tenant['id'],
        "created_at": datetime.now().isoformat(),
        "status": "pending",
        "last_score": None,
        "last_audit": None,
        "audit_count": 0
    }

@app.get("/sites", response_model=List[SiteResponse])
async def list_sites(tenant: dict = Depends(get_tenant)):
    """List all sites for this tenant"""
    results = execute_query(
        """SELECT id, url, name, tenant_id, created_at, status, last_score, last_audit, audit_count 
           FROM sites WHERE tenant_id = ? ORDER BY created_at DESC""",
        (tenant['id'],),
        fetch=True
    )
    
    return [{
        "id": r[0],
        "url": r[1],
        "name": r[2],
        "tenant_id": r[3],
        "created_at": r[4],
        "status": r[5],
        "last_score": r[6],
        "last_audit": r[7],
        "audit_count": r[8] or 0
    } for r in results]

@app.post("/sites/{site_id}/audit")
async def trigger_audit(
    site_id: str, 
    background_tasks: BackgroundTasks,
    tenant: dict = Depends(get_tenant)
):
    """Manually trigger an audit"""
    site = execute_query(
        "SELECT url, audit_count FROM sites WHERE id = ? AND tenant_id = ?",
        (site_id, tenant['id']),
        fetch=True
    )
    
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    # Log usage
    log_usage(tenant['id'], 'trigger_audit', site_id)
    
    background_tasks.add_task(run_audit, site_id, site[0][0], tenant['id'])
    
    return {"message": "Audit started", "site_id": site_id}

@app.get("/usage", response_model=UsageResponse)
async def get_usage(tenant: dict = Depends(get_tenant)):
    """Get usage statistics for tenant"""
    from models import get_tenant_stats
    
    stats = get_tenant_stats(tenant['id'])
    remaining = tenant['rate_limit'] - stats['monthly_usage']
    
    return {
        "tenant_id": tenant['id'],
        "plan_type": tenant['plan_type'],
        "usage_count": tenant['usage_count'],
        "rate_limit": tenant['rate_limit'],
        "remaining": max(0, remaining),
        "total_sites": stats['total_sites'],
        "total_audits": stats['total_audits'],
        "monthly_usage": stats['monthly_usage']
    }

@app.put("/tenants/{tenant_id}/plan")
async def update_plan(tenant_id: str, plan: PlanUpdateRequest, admin_key: str = Header(...)):
    """Update tenant plan (admin only)"""
    # Simple admin check (in production, use proper admin auth)
    if admin_key != "admin_secret_key":
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    update_tenant_plan(tenant_id, plan.plan_type, plan.rate_limit)
    
    return {"message": "Plan updated", "tenant_id": tenant_id, "plan": plan.plan_type}

# Background task (updated to increment audit count)
def run_audit(site_id: str, url: str, tenant_id: str):
    """Run SEO audit in background"""
    try:
        # Update status
        execute_query(
            "UPDATE sites SET status = 'running' WHERE id = ?",
            (site_id,)
        )
        
        # Crawl site
        crawler = Crawler()
        pages = crawler.crawl(url, max_pages=50)
        
        # Analyze
        analyzer = SEOAnalyzer()
        analysis = analyzer.analyze(pages)
        
        # Save audit
        audit_id = str(uuid.uuid4())
        execute_query(
            """INSERT INTO audits (id, site_id, tenant_id, score, issues, pages_analyzed, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (audit_id, site_id, tenant_id, analysis['score'], 
             json.dumps(analysis['issues']), len(pages), 
             datetime.now().isoformat())
        )
        
        # Update site
        execute_query(
            """UPDATE sites 
               SET status = 'completed', last_audit = ?, last_score = ?, 
                   audit_count = IFNULL(audit_count, 0) + 1
               WHERE id = ?""",
            (audit_id, analysis['score'], site_id)
        )
        
        # Log audit usage
        log_usage(tenant_id, 'audit_completed', audit_id)
        
    except Exception as e:
        execute_query(
            "UPDATE sites SET status = 'failed' WHERE id = ?",
            (site_id,)
        )
        print(f"Audit failed for tenant {tenant_id}, site {site_id}: {e}")

# Other endpoints remain the same...
@app.get("/sites/{site_id}", response_model=SiteResponse)
async def get_site(site_id: str, tenant: dict = Depends(get_tenant)):
    results = execute_query(
        "SELECT id, url, name, tenant_id, created_at, status, last_score, last_audit, audit_count FROM sites WHERE id = ? AND tenant_id = ?",
        (site_id, tenant['id']),
        fetch=True
    )
    
    if not results:
        raise HTTPException(status_code=404, detail="Site not found")
    
    r = results[0]
    return {
        "id": r[0],
        "url": r[1],
        "name": r[2],
        "tenant_id": r[3],
        "created_at": r[4],
        "status": r[5],
        "last_score": r[6],
        "last_audit": r[7],
        "audit_count": r[8] or 0
    }

@app.get("/sites/{site_id}/audits", response_model=List[AuditResponse])
async def get_site_audits(site_id: str, tenant: dict = Depends(get_tenant)):
    site = execute_query(
        "SELECT id FROM sites WHERE id = ? AND tenant_id = ?",
        (site_id, tenant['id']),
        fetch=True
    )
    
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    results = execute_query(
        """SELECT id, site_id, score, issues, pages_analyzed, created_at 
           FROM audits WHERE site_id = ? ORDER BY created_at DESC""",
        (site_id,),
        fetch=True
    )
    
    return [{
        "id": r[0],
        "site_id": r[1],
        "score": r[2],
        "issues": json.loads(r[3]),
        "pages_analyzed": r[4],
        "created_at": r[5]
    } for r in results]

@app.get("/dashboard")
async def get_dashboard(tenant: dict = Depends(get_tenant)):
    sites = execute_query(
        "SELECT COUNT(*) FROM sites WHERE tenant_id = ?",
        (tenant['id'],),
        fetch=True
    )
    
    avg_score = execute_query(
        """SELECT AVG(score) FROM audits a 
           JOIN sites s ON a.site_id = s.id 
           WHERE s.tenant_id = ?""",
        (tenant['id'],),
        fetch=True
    )
    
    recent = execute_query(
        """SELECT s.name, a.score, a.created_at 
           FROM audits a 
           JOIN sites s ON a.site_id = s.id 
           WHERE s.tenant_id = ? 
           ORDER BY a.created_at DESC LIMIT 5""",
        (tenant['id'],),
        fetch=True
    )
    
    # Get usage
    usage = execute_query(
        "SELECT usage_count, rate_limit FROM tenants WHERE id = ?",
        (tenant['id'],),
        fetch=True
    )
    
    return {
        "tenant": tenant['name'],
        "plan": tenant['plan_type'],
        "total_sites": sites[0][0] if sites else 0,
        "average_score": round(avg_score[0][0], 2) if avg_score and avg_score[0][0] else 0,
        "usage": {
            "current": usage[0][0] if usage else 0,
            "limit": usage[0][1] if usage else 100,
            "remaining": (usage[0][1] - usage[0][0]) if usage else 100
        },
        "recent_audits": [{
            "site": r[0],
            "score": r[1],
            "date": r[2]
        } for r in recent]
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "AutoSEO Multi-Tenant"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
