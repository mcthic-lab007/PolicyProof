"""Configuration imported by a corpus v3 target (benchmark/targets_v3.py).

It is a separate module on purpose: source-amount probes (B), constant
folding (E) and the code excerpt shown to Muse all read only the target's
own module, so a value defined here is invisible to every current method.
"""

from decimal import Decimal

AUDIT_AMOUNT = Decimal("8642.13")
