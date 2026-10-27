import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from src.policyproof.models import TestResult, VerificationReport


def save_report(results: list[TestResult], output_path: str) -> None:
    report = VerificationReport(results=results)

    payload = {
        "passed": report.passed,
        "total_cases": len(report.results),
        "mismatch_count": report.mismatch_count,
        "findings": [
            {
                "rule_id": result.rule_id,
                "description": result.case.description,
                "amount": str(result.case.amount),
                "has_service_date": result.case.has_service_date,
                "expected": result.expected,
                "actual": result.actual,
                "explanation": result.explanation,
            }
            for result in report.results
            if result.mismatch
        ],
    }

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
