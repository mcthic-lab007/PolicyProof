"""A benchmark target module that fails to import (worker startup failure)."""

raise ImportError("payments SDK is not installed")


def decide(case):  # never reached
    return "APPROVE"
