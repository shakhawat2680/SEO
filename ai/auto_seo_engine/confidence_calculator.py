class ConfidenceCalculator:

    def calculate(self, issues, opportunities):

        base = 85
        deduction = len(issues) * 4

        return max(base - deduction, 55)
