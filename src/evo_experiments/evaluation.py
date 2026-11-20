def evaluate_task(task, response):
    """Run only explicitly declared deterministic checks; never judge free-form quality."""
    checks = []
    expected_exact = task.get("expected_exact")
    if expected_exact is not None:
        passed = response.strip() == str(expected_exact).strip()
        checks.append({"check": "expected_exact", "passed": passed})
    expected_contains = task.get("expected_contains", [])
    if isinstance(expected_contains, str):
        expected_contains = [expected_contains]
    for expected in expected_contains:
        passed = str(expected).casefold() in response.casefold()
        checks.append({"check": "expected_contains", "value": str(expected), "passed": passed})
    if not checks:
        return None, None
    passed_count = sum(1 for check in checks if check["passed"])
    status = "passed" if passed_count == len(checks) else "failed"
    return status, {"passed": passed_count, "total": len(checks), "checks": checks}
