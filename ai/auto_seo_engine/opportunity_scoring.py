class OpportunityScorer:

    def score(self, opportunities):

        return sorted(
            opportunities,
            key=lambda x: x.get("score", 0),
            reverse=True
        )
