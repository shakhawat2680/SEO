from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Audit(Base):
    __tablename__ = "audits"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(String)
    url = Column(String)
    seo_score = Column(Integer)
    issues = Column(String)
