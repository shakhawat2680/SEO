"""
Tenant management module for AutoSEO service
Handles all tenant-related operations including billing, usage tracking, and plan management
"""

import uuid
import secrets
import hashlib
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
import calendar
from models import execute_query, get_connection, get_cycle_usage, check_and_reset_usage

# ============================================================================
# CONSTANTS
# ============================================================================

PLAN_LIMITS = {
    'free': {
        'rate_limit': 100,
        'max_sites': 3,
        'max_pages_per_audit': 50,
        'price_monthly': 0,
        'price_yearly': 0,
        'overage_rate': 0,
        'features': ['basic_seo', 'email_reports']
    },
    'pro': {
        'rate_limit': 1000,
        'max_sites': 20,
        'max_pages_per_audit': 500,
        'price_monthly': 29,
        'price_yearly': 290,
        'overage_rate': 5,
        'features': ['basic_seo', 'advanced_seo', 'keyword_tracking', 'api_access', 'pdf_reports']
    },
    'enterprise': {
        'rate_limit': 10000,
        'max_sites': 100,
        'max_pages_per_audit': 5000,
        'price_monthly': 99,
        'price_yearly': 990,
        'overage_rate': 2,
        'features': ['all_features', 'white_label', 'team_access', 'priority_support', 'custom_reports']
    }
}

BILLING_CYCLES = ['monthly', 'yearly']
SUBSCRIPTION_STATUS = ['active', 'past_due', 'canceled', 'trial']

# ============================================================================
# TENANT CORE FUNCTIONS
# ============================================================================

class Tenant:
    """Tenant class representing a client"""
    
    def __init__(self, tenant_data: dict):
        self.id = tenant_data.get('id')
        self.name = tenant_data.get('name')
        self.email = tenant_data.get('email')
        self.api_key = tenant_data.get('api_key')
        self.plan_type = tenant_data.get('plan_type', 'free')
        self.billing_cycle = tenant_data.get('billing_cycle', 'monthly')
        self.usage_count = tenant_data.get('usage_count', 0)
        self.rate_limit = tenant_data.get('rate_limit', 100)
        self.created_at = tenant_data.get('created_at')
        self.updated_at = tenant_data.get('updated_at')
        self.billing_start = tenant_data.get('billing_start')
        self.billing_end = tenant_data.get('billing_end')
        self.last_reset = tenant_data.get('last_reset')
        self.subscription_status = tenant_data.get('subscription_status', 'active')
        self.payment_method = tenant_data.get('payment_method')
        self.settings = json.loads(tenant_data.get('settings', '{}'))
    
    def to_dict(self) -> dict:
        """Convert tenant to dictionary"""
        return {
            'id': self.id,
            'name': self.name,
            'email': self.email,
            'api_key': self.api_key,
            'plan_type': self.plan_type,
            'billing_cycle': self.billing_cycle,
            'usage_count': self.usage_count,
            'rate_limit': self.rate_limit,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'billing_start': self.billing_start,
            'billing_end': self.billing_end,
            'last_reset': self.last_reset,
            'subscription_status': self.subscription_status,
            'settings': self.settings
        }
    
    def get_plan_details(self) -> dict:
        """Get detailed plan information"""
        plan = PLAN_LIMITS.get(self.plan_type, PLAN_LIMITS['free']).copy()
        plan['name'] = self.plan_type
        plan['current_usage'] = self.usage_count
        plan['remaining'] = max(0, self.rate_limit - self.usage_count)
        plan['usage_percentage'] = round((self.usage_count / self.rate_limit * 100), 2) if self.rate_limit > 0 else 0
        return plan

def create_tenant(name: str, email: str, plan_type: str = 'free', 
                  billing_cycle: str = 'monthly') -> Optional[dict]:
    """Create a new tenant"""
    tenant_id = str(uuid.uuid4())
    api_key = generate_api_key()
    api_key_hash = hash_api_key(api_key)
    
    # Check if email exists
    existing = execute_query(
        "SELECT id FROM tenants WHERE email = ?",
        (email,),
        fetch=True
    )
    
    if existing:
        return None
    
    plan = PLAN_LIMITS.get(plan_type, PLAN_LIMITS['free'])
    rate_limit = plan['rate_limit']
    now = datetime.now().isoformat()
    
    execute_query(
        """INSERT INTO tenants (
            id, name, email, api_key, plan_type, billing_cycle, 
            rate_limit, created_at, subscription_status, settings
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (tenant_id, name, email, api_key_hash, plan_type, billing_cycle,
         rate_limit, now, 'active', json.dumps({'created_from': 'api'}))
    )
    
    initialize_tenant_billing(tenant_id, plan_type, billing_cycle)
    
    tenant = get_tenant_by_id(tenant_id)
    if tenant:
        tenant['api_key'] = api_key
    
    return tenant

def get_tenant_by_id(tenant_id: str) -> Optional[dict]:
    """Get tenant by ID"""
    results = execute_query(
        """SELECT id, name, email, api_key, plan_type, billing_cycle, 
                  usage_count, rate_limit, created_at, updated_at,
                  billing_start, billing_end, last_reset, subscription_status,
                  payment_method, settings
           FROM tenants WHERE id = ?""",
        (tenant_id,),
        fetch=True
    )
    
    if not results:
        return None
    
    r = results[0]
    return {
        'id': r[0],
        'name': r[1],
        'email': r[2],
        'api_key': r[3],
        'plan_type': r[4],
        'billing_cycle': r[5],
        'usage_count': r[6],
        'rate_limit': r[7],
        'created_at': r[8],
        'updated_at': r[9],
        'billing_start': r[10],
        'billing_end': r[11],
        'last_reset': r[12],
        'subscription_status': r[13],
        'payment_method': r[14],
        'settings': r[15]
    }

def get_tenant_by_api_key(api_key: str) -> Optional[dict]:
    """Get tenant by API key (hashed)"""
    api_key_hash = hash_api_key(api_key)
    
    results = execute_query(
        "SELECT id FROM tenants WHERE api_key = ?",
        (api_key_hash,),
        fetch=True
    )
    
    if results:
        return get_tenant_by_id(results[0][0])
    return None

def update_tenant(tenant_id: str, updates: dict) -> bool:
    """Update tenant information"""
    allowed_fields = ['name', 'email', 'plan_type', 'billing_cycle', 
                      'subscription_status', 'payment_method', 'settings']
    
    update_fields = []
    params = []
    
    for field, value in updates.items():
        if field in allowed_fields:
            update_fields.append(f"{field} = ?")
            
            if field == 'settings' and isinstance(value, dict):
                params.append(json.dumps(value))
            else:
                params.append(value)
    
    if not update_fields:
        return False
    
    update_fields.append("updated_at = ?")
    params.append(datetime.now().isoformat())
    params.append(tenant_id)
    
    execute_query(
        f"UPDATE tenants SET {', '.join(update_fields)} WHERE id = ?",
        tuple(params)
    )
    
    if 'plan_type' in updates:
        plan = PLAN_LIMITS.get(updates['plan_type'], PLAN_LIMITS['free'])
        execute_query(
            "UPDATE tenants SET rate_limit = ? WHERE id = ?",
            (plan['rate_limit'], tenant_id)
        )
    
    return True

def delete_tenant(tenant_id: str) -> bool:
    """Delete tenant and all associated data"""
    conn = get_connection()
    c = conn.cursor()
    
    try:
        c.execute("DELETE FROM audits WHERE tenant_id = ?", (tenant_id,))
        c.execute("DELETE FROM usage_logs WHERE tenant_id = ?", (tenant_id,))
        c.execute("DELETE FROM billing_history WHERE tenant_id = ?", (tenant_id,))
        c.execute("DELETE FROM sites WHERE tenant_id = ?", (tenant_id,))
        c.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def list_tenants(status: Optional[str] = None, plan: Optional[str] = None, 
                 limit: int = 100, offset: int = 0) -> List[dict]:
    """List all tenants with optional filters"""
    query = "SELECT id FROM tenants"
    conditions = []
    params = []
    
    if status:
        conditions.append("subscription_status = ?")
        params.append(status)
    
    if plan:
        conditions.append("plan_type = ?")
        params.append(plan)
    
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    results = execute_query(query, tuple(params), fetch=True)
    
    tenants = []
    for r in results:
        tenant = get_tenant_by_id(r[0])
        if tenant:
            tenant.pop('api_key', None)
            tenants.append(tenant)
    
    return tenants

# ============================================================================
# API KEY MANAGEMENT
# ============================================================================

def generate_api_key() -> str:
    """Generate a secure API key"""
    return f"aseo_{secrets.token_urlsafe(32)}"

def hash_api_key(api_key: str) -> str:
    """Hash API key for storage"""
    return hashlib.sha256(api_key.encode()).hexdigest()

def regenerate_api_key(tenant_id: str) -> str:
    """Regenerate API key for tenant"""
    new_api_key = generate_api_key()
    api_key_hash = hash_api_key(new_api_key)
    
    execute_query(
        "UPDATE tenants SET api_key = ?, updated_at = ? WHERE id = ?",
        (api_key_hash, datetime.now().isoformat(), tenant_id)
    )
    
    return new_api_key

def verify_api_key(api_key: str) -> Optional[dict]:
    """Verify API key and return tenant info"""
    if not api_key or not api_key.startswith('aseo_'):
        return None
    
    tenant = get_tenant_by_api_key(api_key)
    
    if not tenant:
        return None
    
    if tenant['subscription_status'] != 'active':
        return {
            'error': 'subscription_inactive',
            'tenant': tenant
        }
    
    check_and_reset_tenant_usage(tenant['id'])
    tenant = get_tenant_by_id(tenant['id'])
    
    return tenant

# ============================================================================
# BILLING AND USAGE
# ============================================================================

def get_current_billing_cycle() -> str:
    """Get current billing cycle (YYYY-MM)"""
    return datetime.now().strftime('%Y-%m')

def get_next_billing_date(start_date: str, cycle_type: str = 'monthly') -> str:
    """Calculate next billing date"""
    start = datetime.fromisoformat(start_date)
    
    if cycle_type == 'monthly':
        month = start.month + 1
        year = start.year
        if month > 12:
            month = 1
            year += 1
        last_day = calendar.monthrange(year, month)[1]
        day = min(start.day, last_day)
        next_date = start.replace(year=year, month=month, day=day)
    else:
        next_date = start.replace(year=start.year + 1)
    
    return next_date.isoformat()

def initialize_tenant_billing(tenant_id: str, plan_type: str, billing_cycle: str):
    """Initialize billing for new tenant"""
    now = datetime.now()
    billing_start = now.isoformat()
    billing_end = get_next_billing_date(billing_start, billing_cycle)
    
    execute_query(
        """UPDATE tenants 
           SET billing_start = ?, billing_end = ?, last_reset = ?
           WHERE id = ?""",
        (billing_start, billing_end, now.isoformat(), tenant_id)
    )

def check_and_reset_tenant_usage(tenant_id: str):
    """Check if billing cycle ended and reset usage"""
    tenant = get_tenant_by_id(tenant_id)
    if not tenant or not tenant.get('billing_end'):
        return
    
    now = datetime.now()
    billing_end = datetime.fromisoformat(tenant['billing_end'])
    
    if now > billing_end:
        cycle = tenant['billing_start'][:7]
        usage = get_cycle_usage(tenant_id, cycle)
        overage = max(0, usage - tenant['rate_limit'])
        
        history_id = str(uuid.uuid4())
        execute_query(
            """INSERT INTO billing_history 
               (id, tenant_id, cycle_start, cycle_end, usage, overage, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (history_id, tenant_id, tenant['billing_start'],
             tenant['billing_end'], usage, overage, now.isoformat())
        )
        
        new_start = now.isoformat()
        new_end = get_next_billing_date(new_start, tenant['billing_cycle'])
        
        execute_query(
            """UPDATE tenants 
               SET billing_start = ?, billing_end = ?, last_reset = ?, 
                   usage_count = 0, updated_at = ?
               WHERE id = ?""",
            (new_start, new_end, now.isoformat(), now.isoformat(), tenant_id)
        )
        
        three_months_ago = (now - timedelta(days=90)).isoformat()
        execute_query(
            "DELETE FROM usage_logs WHERE tenant_id = ? AND timestamp < ?",
            (tenant_id, three_months_ago)
        )

def log_tenant_usage(tenant_id: str, action: str, resource: str = None):
    """Log usage action for tenant"""
    from models import log_usage as models_log_usage
    models_log_usage(tenant_id, action, resource)

def get_cycle_usage(tenant_id: str, cycle: str = None) -> int:
    """Get usage for specific billing cycle"""
    from models import get_cycle_usage as models_get_cycle_usage
    return models_get_cycle_usage(tenant_id, cycle)

def check_tenant_rate_limit(tenant_id: str) -> tuple[bool, dict]:
    """Check if tenant has exceeded rate limit"""
    from models import check_rate_limit as models_check_rate_limit
    return models_check_rate_limit(tenant_id)

# ============================================================================
# PLAN MANAGEMENT
# ============================================================================

def get_available_plans() -> dict:
    """Get all available plans with details"""
    return PLAN_LIMITS

def get_plan_details(plan_type: str) -> dict:
    """Get details for specific plan"""
    return PLAN_LIMITS.get(plan_type, PLAN_LIMITS['free'])

def change_tenant_plan(tenant_id: str, new_plan: str, 
                       billing_cycle: Optional[str] = None) -> bool:
    """Change tenant's plan"""
    if new_plan not in PLAN_LIMITS:
        return False
    
    plan = PLAN_LIMITS[new_plan]
    
    updates = {
        'plan_type': new_plan,
        'rate_limit': plan['rate_limit']
    }
    
    if billing_cycle and billing_cycle in BILLING_CYCLES:
        updates['billing_cycle'] = billing_cycle
    
    return update_tenant(tenant_id, updates)

def calculate_overage_charges(tenant_id: str, cycle: str = None) -> dict:
    """Calculate overage charges for a billing cycle"""
    from models import calculate_overage_charges as models_calc_overage
    return models_calc_overage(tenant_id, cycle)

# ============================================================================
# USAGE STATISTICS
# ============================================================================

def get_tenant_statistics(tenant_id: str) -> dict:
    """Get comprehensive tenant statistics"""
    from models import get_tenant_stats
    return get_tenant_stats(tenant_id)

def get_all_tenants_statistics() -> dict:
    """Get statistics across all tenants (admin)"""
    total = execute_query("SELECT COUNT(*) FROM tenants", fetch=True)
    
    by_plan = execute_query(
        "SELECT plan_type, COUNT(*) FROM tenants GROUP BY plan_type",
        fetch=True
    )
    
    by_status = execute_query(
        "SELECT subscription_status, COUNT(*) FROM tenants GROUP BY subscription_status",
        fetch=True
    )
    
    total_usage = execute_query("SELECT SUM(usage_count) FROM tenants", fetch=True)
    avg_usage = execute_query("SELECT AVG(usage_count) FROM tenants", fetch=True)
    
    month_start = datetime.now().replace(day=1).isoformat()
    new_this_month = execute_query(
        "SELECT COUNT(*) FROM tenants WHERE created_at > ?",
        (month_start,),
        fetch=True
    )
    
    return {
        'total_tenants': total[0][0] if total else 0,
        'by_plan': {r[0]: r[1] for r in by_plan},
        'by_status': {r[0]: r[1] for r in by_status},
        'usage': {
            'total': total_usage[0][0] if total_usage else 0,
            'average': round(avg_usage[0][0], 2) if avg_usage and avg_usage[0][0] else 0
        },
        'growth': {
            'new_this_month': new_this_month[0][0] if new_this_month else 0
        }
    }

# ============================================================================
# SITE MANAGEMENT FOR TENANTS
# ============================================================================

def get_tenant_sites(tenant_id: str) -> List[dict]:
    """Get all sites for a tenant"""
    results = execute_query(
        """SELECT id, url, name, status, last_score, last_audit, created_at, audit_count
           FROM sites WHERE tenant_id = ? ORDER BY created_at DESC""",
        (tenant_id,),
        fetch=True
    )
    
    return [{
        'id': r[0],
        'url': r[1],
        'name': r[2],
        'status': r[3],
        'last_score': r[4],
        'last_audit': r[5],
        'created_at': r[6],
        'audit_count': r[7] or 0
    } for r in results]

def can_add_site(tenant_id: str) -> tuple[bool, str]:
    """Check if tenant can add another site"""
    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        return False, "Tenant not found"
    
    plan = PLAN_LIMITS.get(tenant['plan_type'], PLAN_LIMITS['free'])
    max_sites = plan['max_sites']
    current_sites = len(get_tenant_sites(tenant_id))
    
    if current_sites >= max_sites:
        return False, f"Maximum sites limit ({max_sites}) reached for {tenant['plan_type']} plan"
    
    return True, "OK"

def get_tenant_audits(tenant_id: str, limit: int = 50) -> List[dict]:
    """Get recent audits for tenant"""
    results = execute_query(
        """SELECT a.id, a.site_id, s.name as site_name, a.score, a.pages_analyzed, a.created_at
           FROM audits a
           JOIN sites s ON a.site_id = s.id
           WHERE a.tenant_id = ?
           ORDER BY a.created_at DESC
           LIMIT ?""",
        (tenant_id, limit),
        fetch=True
    )
    
    return [{
        'id': r[0],
        'site_id': r[1],
        'site_name': r[2],
        'score': r[3],
        'pages_analyzed': r[4],
        'created_at': r[5]
    } for r in results]

# ============================================================================
# BILLING HISTORY
# ============================================================================

def get_billing_history(tenant_id: str, limit: int = 12) -> List[dict]:
    """Get billing history for tenant"""
    results = execute_query(
        """SELECT cycle_start, cycle_end, usage, overage, status, payment_date, amount
           FROM billing_history 
           WHERE tenant_id = ? 
           ORDER BY created_at DESC 
           LIMIT ?""",
        (tenant_id, limit),
        fetch=True
    )
    
    history = []
    for r in results:
        overage_charge = 0
        if r[3] > 0:
            plan = PLAN_LIMITS.get(get_tenant_by_id(tenant_id)['plan_type'], PLAN_LIMITS['free'])
            overage_blocks = (r[3] + 99) // 100
            overage_charge = overage_blocks * plan['overage_rate']
        
        history.append({
            'period': f"{r[0][:7]} to {r[1][:7]}",
            'start': r[0],
            'end': r[1],
            'usage': r[2],
            'overage': r[3],
            'overage_charge': overage_charge,
            'total_amount': (r[6] or 0) + overage_charge,
            'status': r[4],
            'payment_date': r[5]
        })
    
    return history

def generate_invoice(tenant_id: str, cycle: str) -> dict:
    """Generate invoice for a billing cycle"""
    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        return {}
    
    usage = get_cycle_usage(tenant_id, cycle)
    plan = PLAN_LIMITS.get(tenant['plan_type'], PLAN_LIMITS['free'])
    
    base_charge = plan['price_monthly'] if tenant['billing_cycle'] == 'monthly' else plan['price_yearly']
    overage_data = calculate_overage_charges(tenant_id, cycle)
    
    cycle_start = f"{cycle}-01"
    last_day = calendar.monthrange(int(cycle[:4]), int(cycle[5:7]))[1]
    cycle_end = f"{cycle}-{last_day}"
    
    invoice = {
        'invoice_id': f"INV-{tenant_id[:8]}-{cycle}",
        'tenant': {
            'id': tenant['id'],
            'name': tenant['name'],
            'email': tenant['email'],
            'plan': tenant['plan_type']
        },
        'billing_cycle': cycle,
        'period': {
            'start': cycle_start,
            'end': cycle_end
        },
        'usage': {
            'total': usage,
            'included': plan['rate_limit'],
            'overage': max(0, usage - plan['rate_limit'])
        },
        'charges': {
            'base_plan': base_charge,
            'overage': overage_data['total_charge'],
            'total': base_charge + overage_data['total_charge']
        },
        'generated_at': datetime.now().isoformat()
    }
    
    return invoice

# ============================================================================
# ALERTS AND NOTIFICATIONS
# ============================================================================

def check_usage_alerts(tenant_id: str) -> List[dict]:
    """Check if tenant needs usage alerts"""
    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        return []
    
    alerts = []
    usage_percentage = (tenant['usage_count'] / tenant['rate_limit'] * 100) if tenant['rate_limit'] > 0 else 0
    
    if usage_percentage >= 80 and usage_percentage < 90:
        alerts.append({
            'type': 'warning',
            'message': f"You've used {round(usage_percentage, 1)}% of your monthly quota",
            'action': 'Consider upgrading your plan'
        })
    
    if usage_percentage >= 90 and usage_percentage < 100:
        alerts.append({
            'type': 'urgent',
            'message': f"You've used {round(usage_percentage, 1)}% of your monthly quota",
            'action': 'Upgrade now to avoid service interruption'
        })
    
    if usage_percentage >= 100:
        alerts.append({
            'type': 'critical',
            'message': "You've exceeded your monthly quota",
            'action': 'Upgrade your plan or wait for next billing cycle'
        })
    
    days_left = max(0, (datetime.fromisoformat(tenant['billing_end']) - datetime.now()).days)
    if days_left <= 3 and usage_percentage > 50:
        alerts.append({
            'type': 'info',
            'message': f"Your billing cycle ends in {days_left} days",
            'action': 'Review your usage'
        })
    
    return alerts

# ============================================================================
# ADMIN FUNCTIONS
# ============================================================================

def reset_all_tenants_usage():
    """Force reset usage for all tenants (admin)"""
    tenants = execute_query("SELECT id FROM tenants", fetch=True)
    
    for tenant in tenants:
        check_and_reset_tenant_usage(tenant[0])
    
    return {'reset_count': len(tenants)}

def apply_plan_updates_to_all():
    """Apply plan limit updates to all tenants (admin)"""
    tenants = execute_query("SELECT id, plan_type FROM tenants", fetch=True)
    
    updated = 0
    for tenant in tenants:
        plan = PLAN_LIMITS.get(tenant[1], PLAN_LIMITS['free'])
        execute_query(
            "UPDATE tenants SET rate_limit = ? WHERE id = ?",
            (plan['rate_limit'], tenant[0])
        )
        updated += 1
    
    return {'updated': updated}

def get_revenue_report(start_date: str, end_date: str) -> dict:
    """Generate revenue report for date range"""
    results = execute_query(
        """SELECT plan_type, COUNT(*) as count, SUM(amount) as total
           FROM billing_history
           WHERE payment_date BETWEEN ? AND ?
           GROUP BY plan_type""",
        (start_date, end_date),
        fetch=True
    )
    
    total_revenue = 0
    by_plan = {}
    
    for r in results:
        by_plan[r[0]] = {
            'count': r[1],
            'total': r[2] or 0
        }
        total_revenue += r[2] or 0
    
    overage = execute_query(
        """SELECT SUM(overage) as total_overage
           FROM billing_history
           WHERE payment_date BETWEEN ? AND ?""",
        (start_date, end_date),
        fetch=True
    )
    
    return {
        'period': {
            'start': start_date,
            'end': end_date
        },
        'total_revenue': total_revenue,
        'total_overage': overage[0][0] if overage and overage[0][0] else 0,
        'by_plan': by_plan
    }
