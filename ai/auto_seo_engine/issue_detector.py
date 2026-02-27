class IssueDetector:

    def detect(self, data):
        issues = []

        if not data.get("title"):
            issues.append({"type": "missing_title", "penalty": 20})

        return issues
