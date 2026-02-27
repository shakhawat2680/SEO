class IssuePrioritizer:

    def prioritize(self, issues):

        return sorted(
            issues,
            key=lambda x: x.get("penalty", 0),
            reverse=True
        )
