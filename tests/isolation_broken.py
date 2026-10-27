"""A target module that fails to import, for worker startup-failure tests."""

raise RuntimeError("this target cannot be imported")


def decide(case):  # never reached
    return "APPROVE"
