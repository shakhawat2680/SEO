from services.crawler import crawl_page
from .context_builder import ContextBuilder
from .data_normalizer import DataNormalizer
from .issue_detector import IssueDetector
from .issue_prioritizer import IssuePrioritizer
from .opportunity_detector import OpportunityDetector
from .opportunity_scoring import OpportunityScorer
from .impact_estimator import ImpactEstimator
from .confidence_calculator import ConfidenceCalculator


class AutoSEOEngine:

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id

    def run(self, url: str):

        # 1. Crawl page (future full site crawler)
        raw = crawl_page(url)

        # 2. Build semantic context
        context = ContextBuilder().build(raw)

        # 3. Normalize data
        data = DataNormalizer().normalize(context)

        # 4. Detect issues
        issues = IssueDetector().detect(data)

        # 5. Prioritize issues (impact-based)
        prioritized = IssuePrioritizer().prioritize(issues)

        # 6. Detect opportunities (growth paths)
        opportunities = OpportunityDetector().detect(data)

        # 7. Score opportunities (ROI)
        scored = OpportunityScorer().score(opportunities)

        # 8. Estimate impact (traffic/SEO gain)
        impact = ImpactEstimator().estimate(prioritized, scored)

        # 9. Confidence score (data quality)
        confidence = ConfidenceCalculator().calculate(prioritized, scored)

        # 10. Response (AI-ready structure)
        return {
            "url": url,
            "summary": {
                "issue_count": len(prioritized),
                "opportunity_count": len(scored),
                "confidence": confidence
            },
            "issues": prioritized,
            "opportunities": scored,
            "impact_prediction": impact
        }
