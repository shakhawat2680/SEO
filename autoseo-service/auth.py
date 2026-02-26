import secrets
import hashlib
from typing import Optional, Dict
from datetime import datetime
from models import execute_query, get_tenant_by_api_key, check_rate_limit, log_usage

def generate_api_key() -> str:
    """Generate a secure API key"""
    return f"aseo_{secrets.token_urlsafe(32)}"

def hash_api_key(api_key: str) -> str:
    """Hash API key for storage"""
    return hashlib.sha256(api_key.encode()).hexdigest()

def verify_api_key(api_key: str) -> Optional[Dict]:
    """Verify API key and return tenant info with rate limit check"""
    if not api_key or not api_key.startswith('aseo_'):
        return None
    
    key_hash = hash_api_key(api_key)
    tenant = get_tenant_by_api_key(key_hash)
    
    if not tenant:
        return None
    
    allowed, rate_info = check_rate_limit(tenant['id'])
    
    if not allowed:
        return {
            'error': rate_info.get('error', 'rate_limit_exceeded'),
            'rate_info': rate_info,
            'tenant': {k: v for k, v in tenant.items() if k != 'api_key'}
        }
    
    log_usage(tenant['id'], 'api_call', 'authentication')
    tenant['rate_info'] = rate_info
    
    return tenant

def create_api_key_for_tenant(tenant_id: str) -> str:
    """Create new API key for tenant"""
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key)
    
    execute_query(
        "UPDATE tenants SET api_key = ?, updated_at = ? WHERE id = ?",
        (key_hash, datetime.now().isoformat(), tenant_id)
    )
    
    return api_key
