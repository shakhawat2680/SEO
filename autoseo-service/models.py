import sqlite3
from typing import List, Any, Optional

DB_PATH = 'autoseo.db'

def get_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database with multi-tenant support"""
    conn = get_connection()
    c = conn.cursor()
    
    # Tenants table
    c.execute('''
        CREATE TABLE IF NOT EXISTS tenants (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            api_key TEXT UNIQUE,
            created_at TEXT NOT NULL,
            settings TEXT DEFAULT '{}'
        )
    ''')
    
    # Sites table with tenant isolation
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
            FOREIGN KEY (tenant_id) REFERENCES tenants (id),
            UNIQUE(tenant_id, url)
        )
    ''')
    
    # Audits table
    c.execute('''
        CREATE TABLE IF NOT EXISTS audits (
            id TEXT PRIMARY KEY,
            site_id TEXT NOT NULL,
            score REAL NOT NULL,
            issues TEXT NOT NULL,
            pages_analyzed INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (site_id) REFERENCES sites (id)
        )
    ''')
    
    # Indexes for performance
    c.execute('CREATE INDEX IF NOT EXISTS idx_tenants_api_key ON tenants(api_key)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_sites_tenant ON sites(tenant_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_audits_site ON audits(site_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_audits_created ON audits(created_at)')
    
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

def get_tenant_sites(tenant_id: str) -> List[dict]:
    """Get all sites for a tenant"""
    results = execute_query(
        "SELECT id, url, name, status, last_score, created_at FROM sites WHERE tenant_id = ?",
        (tenant_id,),
        fetch=True
    )
    
    return [{
        'id': r[0],
        'url': r[1],
        'name': r[2],
        'status': r[3],
        'last_score': r[4],
        'created_at': r[5]
    } for r in results]

def delete_tenant(tenant_id: str):
    """Delete tenant and all associated data"""
    conn = get_connection()
    c = conn.cursor()
    
    try:
        # Delete audits (via sites)
        c.execute("""
            DELETE FROM audits 
            WHERE site_id IN (SELECT id FROM sites WHERE tenant_id = ?)
        """, (tenant_id,))
        
        # Delete sites
        c.execute("DELETE FROM sites WHERE tenant_id = ?", (tenant_id,))
        
        # Delete tenant
        c.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()
