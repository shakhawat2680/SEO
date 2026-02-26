import sqlite3
from typing import List, Any, Optional
from datetime import datetime, timedelta
import calendar

DB_PATH = 'autoseo.db'

def get_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database with billing cycles"""
    conn = get_connection()
    c = conn.cursor()
    
    # Tenants table with billing fields
    c.execute('''
        CREATE TABLE IF NOT EXISTS tenants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            api_key TEXT UNIQUE,
            plan_type TEXT DEFAULT 'free',
            billing_cycle TEXT DEFAULT 'monthly', -- monthly, yearly
            usage_count INTEGER DEFAULT 0,
            rate_limit INTEGER DEFAULT 100,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            billing_start TEXT, -- Start of current billing cycle
            billing_end TEXT,    -- End of current billing cycle
            last_reset TEXT,      -- Last time usage was reset
            subscription_status TEXT DEFAULT 'active', -- active, past_due, canceled
            payment_method TEXT,
            settings TEXT DEFAULT '{}'
        )
    ''')
    
    # Sites table
    c.execute('''
        CREATE TABLE IF NOT EXISTS sites (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            url TEXT NOT NULL,
            name TEXT NOT NULL,
            settings TEXT DEFAULT '{}',
            created_at TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            last_audit TEXT,
            last_score REAL,
            audit_count INTEGER DEFAULT 0,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id),
            UNIQUE(tenant_id, url)
        )
    ''')
    
    # Audits table
    c.execute('''
        CREATE TABLE IF NOT EXISTS audits (
            id TEXT PRIMARY KEY,
            site_id TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            score REAL NOT NULL,
            issues TEXT NOT NULL,
            pages_analyzed INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            billing_cycle TEXT, -- Which billing cycle this audit belongs to
            FOREIGN KEY (site_id) REFERENCES sites (id),
            FOREIGN KEY (tenant_id) REFERENCES tenants (id)
        )
    ''')
    
    # Usage logs with billing cycle tracking
    c.execute('''
        CREATE TABLE IF NOT EXISTS usage_logs (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            action TEXT NOT NULL,
            resource TEXT,
            timestamp TEXT NOT NULL,
            billing_cycle TEXT, -- YYYY-MM format
            FOREIGN KEY (tenant_id) REFERENCES tenants (id)
        )
    ''')
    
    # Billing history
    c.execute('''
        CREATE TABLE IF NOT EXISTS billing_history (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            cycle_start TEXT NOT NULL,
            cycle_end TEXT NOT NULL,
            usage INTEGER NOT NULL,
            overage INTEGER DEFAULT 0,
            amount REAL,
            status TEXT DEFAULT 'pending', -- pending, paid, failed
            payment_date TEXT,
            invoice_url TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (tenant_id) REFERENCES tenants (id)
        )
    ''')
    
    # Plan definitions
    c.execute('''
        CREATE TABLE IF NOT EXISTS plans (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            rate_limit INTEGER NOT NULL,
            price_monthly REAL,
            price_yearly REAL,
            overage_rate REAL, -- per additional 100 requests
            features TEXT DEFAULT '{}'
        )
    ''')
    
    # Indexes
    c.execute('CREATE INDEX IF NOT EXISTS idx_tenants_api_key ON tenants(api_key)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_tenants_billing ON tenants(billing_end)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_usage_tenant_cycle ON usage_logs(tenant_id, billing_cycle)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_billing_tenant ON billing_history(tenant_id)')
    
    # Insert default plans
    plans = [
        ('free', 'Free', 100, 0, 0, 0, '{"max_sites": 3, "max_pages": 50}'),
        ('pro', 'Pro', 1000, 29, 290, 5, '{"max_sites": 20, "max_pages": 500}'),
        ('enterprise', 'Enterprise', 10000, 99, 990, 2, '{"max_sites": 100, "max_pages": 5000}')
    ]
    
    for plan_id, name, rate_limit, price_monthly, price_yearly, overage_rate, features in plans:
        c.execute('''
            INSERT OR IGNORE INTO plans (id, name, rate_limit, price_monthly, price_yearly, overage_rate, features)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (plan_id, name, rate_limit, price_monthly, price_yearly, overage_rate, features))
    
    conn.commit()
    conn.close()

def execute_query(query: str, params: tuple = (), fetch: bool = False) -> List[Any]:
    """Execute query with automatic connection handling"""
    conn = get_connection()
    c = conn.cursor()
    
    try:
        c.execute(query, params)
        
        if fetch:
            results = c.fetchall()
            conn.commit()
            return [tuple(r) for r in results]
        else:
            conn.commit()
            return []
            
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def get_current_billing_cycle() -> str:
    """Get current billing cycle (YYYY-MM)"""
    return datetime.now().strftime('%Y-%m')

def get_next_billing_date(cycle_start: str, cycle_type: str = 'monthly') -> str:
    """Calculate next billing date"""
    start = datetime.fromisoformat(cycle_start)
    
    if cycle_type == 'monthly':
        # Add one month
        month = start.month + 1
        year = start.year
        if month > 12:
            month = 1
            year += 1
        # Handle month end
        last_day = calendar.monthrange(year, month)[1]
        day = min(start.day, last_day)
        next_date = start.replace(year=year, month=month, day=day)
    else:  # yearly
        next_date = start.replace(year=start.year + 1)
    
    return next_date.isoformat()

def initialize_tenant_billing(tenant_id: str, plan_type: str = 'free', billing_cycle: str = 'monthly'):
    """Initialize billing for new tenant"""
    now = datetime.now()
    billing_start = now.isoformat()
    billing_end = get_next_billing_date(billing_start, billing_cycle)
    
    execute_query(
        """UPDATE tenants 
           SET billing_start = ?, billing_end = ?, last_reset = ?, billing_cycle = ?
           WHERE id = ?""",
        (billing_start, billing_end, now.isoformat(), billing_cycle, tenant_id)
    )

def check_and_reset_usage(tenant_id: str):
    """Check if billing cycle ended and reset usage"""
    tenant = get_tenant(tenant_id)
    if not tenant:
        return
    
    now = datetime.now()
    billing_end = datetime.fromisoformat(tenant['billing_end'])
    
    # If current date is past billing end, reset usage
    if now > billing_end:
        # Archive current cycle usage
        cycle = tenant['billing_start'][:7]  # YYYY-MM
        
        # Get usage for this cycle
        usage = get_cycle_usage(tenant_id, cycle)
        
        # Save to billing history
        import uuid
        history_id = str(uuid.uuid4())
        
        # Calculate overage
        overage = max(0, usage - tenant['rate_limit'])
        
        execute_query(
            """INSERT INTO billing_history 
               (id, tenant_id, cycle_start, cycle_end, usage, overage, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (history_id, tenant_id, tenant['billing_start'], tenant['billing_end'], 
             usage, overage, now.isoformat())
        )
        
        # Start new cycle
        new_start = now.isoformat()
        new_end = get_next_billing_date(new_start, tenant['billing_cycle'])
        
        # Reset usage
        execute_query(
            """UPDATE tenants 
               SET billing_start = ?, billing_end = ?, last_reset = ?, usage_count = 0
               WHERE id = ?""",
            (new_start, new_end, now.isoformat(), tenant_id)
        )
        
        # Delete old usage logs (optional - keep for 3 months)
        three_months_ago = (now - timedelta(days=90)).isoformat()
        execute_query(
            "DELETE FROM usage_logs WHERE tenant_id = ? AND timestamp < ?",
            (tenant_id, three_months_ago)
        )

def get_cycle_usage(tenant_id: str, cycle: str = None) -> int:
    """Get usage for specific billing cycle"""
    if not cycle:
        cycle = get_current_billing_cycle()
    
    results = execute_query(
        "SELECT COUNT(*) FROM usage_logs WHERE tenant_id = ? AND billing_cycle = ?",
        (tenant_id, cycle),
        fetch=True
    )
    
    return results[0][0] if results else 0

def log_usage(tenant_id: str, action: str, resource: str = None):
    """Log usage action with billing cycle"""
    import uuid
    log_id = str(uuid.uuid4())
    cycle = get_current_billing_cycle()
    
    # Check and reset if needed
    check_and_reset_usage(tenant_id)
    
    execute_query(
        """INSERT INTO usage_logs (id, tenant_id, action, resource, timestamp, billing_cycle) 
           VALUES (?, ?, ?, ?, ?, ?)""",
        (log_id, tenant_id, action, resource, datetime.now().isoformat(), cycle)
    )
    
    # Increment tenant usage
    execute_query(
        "UPDATE tenants SET usage_count = usage_count + 1, updated_at = ? WHERE id = ?",
        (datetime.now().isoformat(), tenant_id)
    )

def get_tenant(tenant_id: str) -> Optional[dict]:
    """Get tenant by ID with billing info"""
    results = execute_query(
        """SELECT id, name, email, plan_type, billing_cycle, usage_count, rate_limit, 
                  created_at, billing_start, billing_end, last_reset, subscription_status
           FROM tenants WHERE id = ?""",
        (tenant_id,),
        fetch=True
    )
    
    if results:
        r = results[0]
        return {
            'id': r[0],
            'name': r[1],
            'email': r[2],
            'plan_type': r[3],
            'billing_cycle': r[4],
            'usage_count': r[5],
            'rate_limit': r[6],
            'created_at': r[7],
            'billing_start': r[8],
            'billing_end': r[9],
            'last_reset': r[10],
            'subscription_status': r[11]
        }
    return None

def get_tenant_by_api_key(api_key_hash: str) -> Optional[dict]:
    """Get tenant by API key hash with billing info"""
    results = execute_query(
        """SELECT id, name, email, plan_type, billing_cycle, usage_count, rate_limit, 
                  created_at, billing_start, billing_end, last_reset, subscription_status
           FROM tenants WHERE api_key = ?""",
        (api_key_hash,),
        fetch=True
    )
    
    if results:
        r = results[0]
        # Check and reset usage if needed
        check_and_reset_usage(r[0])
        
        # Get fresh data after potential reset
        return get_tenant(r[0])
    return None

def check_rate_limit(tenant_id: str) -> tuple[bool, dict]:
    """Check if tenant has exceeded rate limit with billing info"""
    tenant = get_tenant(tenant_id)
    if not tenant:
        return False, {'error': 'Tenant not found'}
    
    # Check subscription status
    if tenant['subscription_status'] != 'active':
        return False, {
            'error': 'subscription_inactive',
            'status': tenant['subscription_status']
        }
    
    # Get current cycle usage
    cycle_usage = get_cycle_usage(tenant_id)
    
    # Calculate days left in billing cycle
    now = datetime.now()
    billing_end = datetime.fromisoformat(tenant['billing_end'])
    days_left = (billing_end - now).days
    
    # Check if over limit
    if cycle_usage >= tenant['rate_limit']:
        # Calculate overage
        overage = cycle_usage - tenant['rate_limit']
        return False, {
            'error': 'rate_limit_exceeded',
            'current_usage': cycle_usage,
            'limit': tenant['rate_limit'],
            'overage': overage,
            'days_left': days_left,
            'billing_end': tenant['billing_end'],
            'message': f'Rate limit exceeded. You have used {cycle_usage}/{tenant["rate_limit"]} requests.'
        }
    
    return True, {
        'current_usage': cycle_usage,
        'limit': tenant['rate_limit'],
        'remaining': tenant['rate_limit'] - cycle_usage,
        'days_left': days_left,
        'billing_end': tenant['billing_end']
    }

def get_tenant_stats(tenant_id: str) -> dict:
    """Get comprehensive tenant statistics"""
    # Total sites
    sites = execute_query(
        "SELECT COUNT(*) FROM sites WHERE tenant_id = ?",
        (tenant_id,),
        fetch=True
    )
    
    # Total audits
    audits = execute_query(
        "SELECT COUNT(*) FROM audits WHERE tenant_id = ?",
        (tenant_id,),
        fetch=True
    )
    
    # Current cycle usage
    current_cycle = get_current_billing_cycle()
    cycle_usage = get_cycle_usage(tenant_id, current_cycle)
    
    # Previous cycle usage
    last_month = (datetime.now().replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
    previous_usage = get_cycle_usage(tenant_id, last_month)
    
    # Billing history
    history = execute_query(
        """SELECT cycle_start, cycle_end, usage, overage, status, payment_date 
           FROM billing_history 
           WHERE tenant_id = ? 
           ORDER BY created_at DESC LIMIT 6""",
        (tenant_id,),
        fetch=True
    )
    
    # Daily usage for current cycle
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()
    daily = execute_query(
        """SELECT DATE(timestamp) as day, COUNT(*) 
           FROM usage_logs 
           WHERE tenant_id = ? AND timestamp > ? 
           GROUP BY DATE(timestamp)
           ORDER BY day DESC""",
        (tenant_id, week_ago),
        fetch=True
    )
    
    return {
        'total_sites': sites[0][0] if sites else 0,
        'total_audits': audits[0][0] if audits else 0,
        'current_cycle': {
            'period': current_cycle,
            'usage': cycle_usage,
            'remaining': None  # Will be filled by caller with rate_limit
        },
        'previous_cycle_usage': previous_usage,
        'daily_activity': [{'date': r[0], 'count': r[1]} for r in daily],
        'billing_history': [{
            'period': f"{r[0][:7]} to {r[1][:7]}",
            'usage': r[2],
            'overage': r[3],
            'status': r[4],
            'payment_date': r[5]
        } for r in history]
    }

def update_tenant_plan(tenant_id: str, plan_type: str, billing_cycle: str = None):
    """Update tenant plan and rate limit"""
    # Get plan details
    plan = execute_query(
        "SELECT rate_limit FROM plans WHERE id = ?",
        (plan_type,),
        fetch=True
    )
    
    if not plan:
        return False
    
    rate_limit = plan[0][0]
    
    # Update tenant
    updates = ["plan_type = ?", "rate_limit = ?", "updated_at = ?"]
    params = [plan_type, rate_limit, datetime.now().isoformat()]
    
    if billing_cycle:
        updates.append("billing_cycle = ?")
        params.append(billing_cycle)
    
    params.append(tenant_id)
    
    execute_query(
        f"UPDATE tenants SET {', '.join(updates)} WHERE id = ?",
        tuple(params)
    )
    
    return True

def calculate_overage_charges(tenant_id: str, cycle: str = None) -> dict:
    """Calculate overage charges for a billing cycle"""
    if not cycle:
        cycle = get_current_billing_cycle()
    
    tenant = get_tenant(tenant_id)
    if not tenant:
        return {}
    
    usage = get_cycle_usage(tenant_id, cycle)
    
    if usage <= tenant['rate_limit']:
        return {'overage': 0, 'charge': 0}
    
    overage = usage - tenant['rate_limit']
    
    # Get plan overage rate
    plan = execute_query(
        "SELECT overage_rate FROM plans WHERE id = ?",
        (tenant['plan_type'],),
        fetch=True
    )
    
    overage_rate = plan[0][0] if plan else 0
    
    # Calculate charge (per 100 requests)
    overage_blocks = (overage + 99) // 100
    charge = overage_blocks * overage_rate
    
    return {
        'usage': usage,
        'limit': tenant['rate_limit'],
        'overage': overage,
        'overage_blocks': overage_blocks,
        'rate_per_block': overage_rate,
        'total_charge': charge
    }
