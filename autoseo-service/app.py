from fastapi import FastAPI, BackgroundTasks, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import uuid
from typing import Optional, List, Dict
import json
import os

from crawler import Crawler
from analyzer import SEOAnalyzer
from models import (
    init_db, execute_query, get_tenant, get_tenant_stats, 
    update_tenant_plan, get_cycle_usage, calculate_overage_charges,
    initialize_tenant_billing, check_and_reset_usage
)
from auth import verify_api_key, generate_api_key, log_usage

# Initialize FastAPI
app = FastAPI(
    title="AutoSEO Service",
    description="Multi-tenant SEO automation service",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    try:
        init_db()
        print(f"✅ Database initialized at {datetime.now().isoformat()}")
        print(f"✅ Environment: {os.environ.get('ENVIRONMENT', 'development')}")
        if os.environ.get('VERCEL'):
            print("✅ Running on Vercel serverless")
    except Exception as e:
        print(f"❌ Database init error: {e}")

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
    plan_type: str = "free"
    billing_cycle: str = "monthly"

class TenantResponse(BaseModel):
    id: str
    name: str
    email: str
    plan_type: str
    billing_cycle: str
    usage_count: int
    rate_limit: int
    api_key: str
    created_at: str
    billing_start: Optional[str]
    billing_end: Optional[str]
    subscription_status: str

class PlanUpdateRequest(BaseModel):
    plan_type: str
    billing_cycle: Optional[str] = None

class UsageResponse(BaseModel):
    tenant_id: str
    plan_type: str
    billing_cycle: str
    billing_start: str
    billing_end: str
    days_left: int
    current_usage: int
    rate_limit: int
    remaining: int
    percentage_used: float
    total_sites: int
    total_audits: int
    estimated_overage: Optional[dict]

class BillingHistoryResponse(BaseModel):
    cycle: str
    usage: int
    limit: int
    overage: int
    overage_charge: float
    status: str
    payment_date: Optional[str]

# Dependency with enhanced error handling
async def get_current_tenant(api_key: str = Header(..., alias="X-API-Key")):
    """Get current tenant from API key"""
    result = verify_api_key(api_key)
    
    if not result:
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    if isinstance(result, dict) and 'error' in result:
        error = result['error']
        rate_info = result.get('rate_info', {})
        
        if error == 'subscription_inactive':
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "subscription_inactive",
                    "message": "Your subscription is inactive. Please update payment method.",
                    "status": rate_info.get('status')
                }
            )
        else:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": rate_info.get('message', 'Rate limit exceeded'),
                    "current_usage": rate_info.get('current_usage'),
                    "limit": rate_info.get('limit'),
                    "remaining": 0,
                    "days_left": rate_info.get('days_left'),
                    "billing_end": rate_info.get('billing_end')
                }
            )
    
    return result

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "service": "AutoSEO Service",
        "version": "1.0.0",
        "environment": os.environ.get('ENVIRONMENT', 'development'),
        "serverless": bool(os.environ.get('VERCEL')),
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "GET /health": "Health check",
            "POST /tenants": "Register new tenant",
            "POST /sites": "Add website",
            "GET /sites": "List websites",
            "GET /usage": "Check usage",
            "GET /dashboard": "View dashboard"
        },
        "documentation": "/docs"
    }

# Health check
@app.get("/health")
async def health():
    """Health check endpoint"""
    try:
        execute_query("SELECT 1", fetch=True)
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {e}"
    
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "database": db_status,
        "environment": os.environ.get('ENVIRONMENT', 'development'),
        "serverless": bool(os.environ.get('VERCEL')),
        "version": "1.0.0"
    }

# Tenant registration
@app.post("/tenants", response_model=TenantResponse)
async def create_tenant(tenant: TenantRequest):
    """Register a new tenant (client)"""
    from tenant import create_tenant as create_new_tenant
    
    result = create_new_tenant(
        name=tenant.name,
        email=tenant.email,
        plan_type=tenant.plan_type,
        billing_cycle=tenant.billing_cycle
    )
    
    if not result:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    return result

# Add site
@app.post("/sites", response_model=SiteResponse)
async def add_site(
    site: SiteRequest,
    background_tasks: BackgroundTasks,
    tenant: dict = Depends(get_current_tenant)
):
    """Add a new site for SEO monitoring"""
    site_id = str(uuid.uuid4())
    
    # Check if site already exists
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
    
    # Start audit in background (note: background tasks on Vercel have limitations)
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

# List sites
@app.get("/sites", response_model=List[SiteResponse])
async def list_sites(tenant: dict = Depends(get_current_tenant)):
    """List all sites for this tenant"""
    from tenant import get_tenant_sites
    sites = get_tenant_sites(tenant['id'])
    
    # Log usage
    log_usage(tenant['id'], 'list_sites')
    
    return sites

# Get single site
@app.get("/sites/{site_id}", response_model=SiteResponse)
async def get_site(site_id: str, tenant: dict = Depends(get_current_tenant)):
    """Get site details"""
    results = execute_query(
        """SELECT id, url, name, tenant_id, created_at, status, last_score, 
                  last_audit, audit_count 
           FROM sites WHERE id = ? AND tenant_id = ?""",
        (site_id, tenant['id']),
        fetch=True
    )
    
    if not results:
        raise HTTPException(status_code=404, detail="Site not found")
    
    r = results[0]
    
    # Log usage
    log_usage(tenant['id'], 'get_site', site_id)
    
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

# Get site audits
@app.get("/sites/{site_id}/audits", response_model=List[AuditResponse])
async def get_site_audits(site_id: str, tenant: dict = Depends(get_current_tenant)):
    """Get audit history for a site"""
    # Verify site ownership
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
    
    # Log usage
    log_usage(tenant['id'], 'get_audits', site_id)
    
    return [{
        "id": r[0],
        "site_id": r[1],
        "score": r[2],
        "issues": json.loads(r[3]),
        "pages_analyzed": r[4],
        "created_at": r[5]
    } for r in results]

# Trigger audit
@app.post("/sites/{site_id}/audit")
async def trigger_audit(
    site_id: str,
    background_tasks: BackgroundTasks,
    tenant: dict = Depends(get_current_tenant)
):
    """Manually trigger an audit"""
    site = execute_query(
        "SELECT url FROM sites WHERE id = ? AND tenant_id = ?",
        (site_id, tenant['id']),
        fetch=True
    )
    
    if not site:
        raise HTTPException(status_code=404, detail="Site not found")
    
    # Log usage
    log_usage(tenant['id'], 'trigger_audit', site_id)
    
    # Run audit in background
    background_tasks.add_task(run_audit, site_id, site[0][0], tenant['id'])
    
    return {"message": "Audit started", "site_id": site_id}

# Get usage
@app.get("/usage", response_model=UsageResponse)
async def get_usage(tenant: dict = Depends(get_current_tenant)):
    """Get detailed usage with billing info"""
    from tenant import get_tenant_statistics
    
    stats = get_tenant_statistics(tenant['id'])
    billing_end = datetime.fromisoformat(tenant['billing_end'])
    days_left = (billing_end - datetime.now()).days
    percentage_used = (tenant['usage_count'] / tenant['rate_limit'] * 100) if tenant['rate_limit'] > 0 else 0
    
    # Calculate potential overage
    overage = None
    if tenant['usage_count'] > tenant['rate_limit'] * 0.8:  # Show estimate if >80% used
        overage = calculate_overage_charges(tenant['id'])
    
    # Log usage
    log_usage(tenant['id'], 'check_usage')
    
    return {
        "tenant_id": tenant['id'],
        "plan_type": tenant['plan_type'],
        "billing_cycle": tenant['billing_cycle'],
        "billing_start": tenant['billing_start'],
        "billing_end": tenant['billing_end'],
        "days_left": max(0, days_left),
        "current_usage": tenant['usage_count'],
        "rate_limit": tenant['rate_limit'],
        "remaining": max(0, tenant['rate_limit'] - tenant['usage_count']),
        "percentage_used": round(percentage_used, 2),
        "total_sites": stats['sites']['total'],
        "total_audits": stats['audits']['total'],
        "estimated_overage": overage if overage and overage['overage'] > 0 else None
    }

# Get billing history
@app.get("/billing/history", response_model=List[BillingHistoryResponse])
async def get_billing_history(tenant: dict = Depends(get_current_tenant)):
    """Get billing history for tenant"""
    history = execute_query(
        """SELECT cycle_start, cycle_end, usage, overage, status, payment_date 
           FROM billing_history 
           WHERE tenant_id = ? 
           ORDER BY created_at DESC""",
        (tenant['id'],),
        fetch=True
    )
    
    result = []
    for h in history:
        # Get plan overage rate
        from tenant import PLAN_LIMITS
        plan = PLAN_LIMITS.get(tenant['plan_type'], PLAN_LIMITS['free'])
        overage_rate = plan['overage_rate']
        overage_charge = (h[3] * overage_rate / 100) if h[3] > 0 else 0
        
        result.append({
            "cycle": f"{h[0][:7]} to {h[1][:7]}",
            "usage": h[2],
            "limit": tenant['rate_limit'],
            "overage": h[3],
            "overage_charge": overage_charge,
            "status": h[4],
            "payment_date": h[5]
        })
    
    return result

# Dashboard
@app.get("/dashboard")
async def get_dashboard(tenant: dict = Depends(get_current_tenant)):
    """Get tenant dashboard"""
    from tenant import get_tenant_statistics, check_usage_alerts, get_tenant_audits
    
    stats = get_tenant_statistics(tenant['id'])
    alerts = check_usage_alerts(tenant['id'])
    recent = get_tenant_audits(tenant['id'], 5)
    
    # Calculate days left in billing cycle
    billing_end = datetime.fromisoformat(tenant['billing_end'])
    days_left = (billing_end - datetime.now()).days
    
    # Log usage
    log_usage(tenant['id'], 'view_dashboard')
    
    return {
        "tenant": tenant['name'],
        "plan": tenant['plan_type'],
        "billing": {
            "cycle": tenant['billing_cycle'],
            "billing_end": tenant['billing_end'],
            "days_left": max(0, days_left)
        },
        "usage": {
            "current": tenant['usage_count'],
            "limit": tenant['rate_limit'],
            "remaining": max(0, tenant['rate_limit'] - tenant['usage_count']),
            "percentage": round(tenant['usage_count'] / tenant['rate_limit'] * 100, 2) if tenant['rate_limit'] > 0 else 0
        },
        "total_sites": stats['sites']['total'],
        "average_score": stats['audits']['average_score'],
        "recent_audits": recent[:5],
        "alerts": alerts
    }

# Update plan (admin only)
@app.post("/tenants/{tenant_id}/plan")
async def update_plan(
    tenant_id: str,
    plan: PlanUpdateRequest,
    admin_key: str = Header(...)
):
    """Update tenant plan (admin only)"""
    if admin_key != "admin_secret_key":
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    from tenant import change_tenant_plan
    success = change_tenant_plan(tenant_id, plan.plan_type, plan.billing_cycle)
    
    if not success:
        raise HTTPException(status_code=400, detail="Invalid plan")
    
    return {"message": "Plan updated", "tenant_id": tenant_id, "plan": plan.plan_type}

# Manual reset (admin only)
@app.post("/billing/reset")
async def manual_reset(admin_key: str = Header(...)):
    """Manually reset all billing cycles (admin only)"""
    if admin_key != "admin_secret_key":
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    from tenant import reset_all_tenants_usage
    result = reset_all_tenants_usage()
    
    return {"message": f"Reset {result['reset_count']} tenants"}

# Background task for audit
def run_audit(site_id: str, url: str, tenant_id: str):
    """Run SEO audit in background"""
    try:
        from tenant import check_tenant_rate_limit
        
        # Check usage before proceeding
        allowed, _ = check_tenant_rate_limit(tenant_id)
        
        if not allowed:
            execute_query(
                "UPDATE sites SET status = 'failed' WHERE id = ?",
                (site_id,)
            )
            return
        
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
        current_cycle = datetime.now().strftime('%Y-%m')
        
        execute_query(
            """INSERT INTO audits (id, site_id, tenant_id, score, issues, pages_analyzed, created_at, billing_cycle)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (audit_id, site_id, tenant_id, analysis['score'],
             json.dumps(analysis['issues']), len(pages),
             datetime.now().isoformat(), current_cycle)
        )
        
        # Update site
        execute_query(
            """UPDATE sites 
               SET status = 'completed', last_audit = ?, last_score = ?, 
                   audit_count = IFNULL(audit_count, 0) + 1
               WHERE id = ?""",
            (audit_id, analysis['score'], site_id)
        )
        
        # Log usage
        log_usage(tenant_id, 'audit_completed', audit_id)
        
        print(f"✅ Audit completed for site {site_id}")
        
    except Exception as e:
        execute_query(
            "UPDATE sites SET status = 'failed' WHERE id = ?",
            (site_id,)
        )
        print(f"❌ Audit failed for tenant {tenant_id}, site {site_id}: {e}")

# For local development
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

# Vercel serverless handler
import os
if os.environ.get('VERCEL'):
    try:
        from mangum import Mangum
        handler = Mangum(app)
    except ImportError:
        print("⚠️ Mangum not installed. Vercel deployment may fail.")
