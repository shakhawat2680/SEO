class Tenant:
    def __init__(self, tenant_id: str, plan="free", limit=100):
        self.tenant_id = tenant_id
        self.plan = plan
        self.limit = limit
        self.usage = 0

    def can_use(self):
        return self.usage < self.limit

    def track_usage(self):
        self.usage += 1
