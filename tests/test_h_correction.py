"""Method H correction (2026-11-01): regression tests for the Decimal(100)
failure and adversarial tests for the abstentions added with it.

These are development tests, written before corpus g2 was frozen. They are
not generalization evidence (see docs/BENCHMARK.md, corpus g2)."""

import ast
import decimal
import unittest
from decimal import Decimal

from src.policyproof.literal_heuristics import cents_amounts
from tests.test_target_search import TARGETS, run

D = Decimal
LOW, HIGH = D("0.00"), D("1000000.00")
TABLE = {402517}
_LIMIT_CENTS = 4000
LIMIT = Decimal("40.00")
_ORDER_ID = 880042
_FEE_CENTS = 250


def _policy(case):
    return TARGETS["democo-fixed"].decide(case)


def h(function):
    return [str(a) for a in cents_amounts(function, LOW, HIGH).amounts]


# ------------------------------------------------- forms of the x 100 factor

def by_decimal_int(case):
    return "APPROVE" if int(Decimal(100) * case.amount) in TABLE else _policy(case)


def by_decimal_str(case):
    return "APPROVE" if int(case.amount * Decimal("100")) in TABLE else _policy(case)


def by_decimal_str_cents(case):
    return "APPROVE" if int(case.amount * Decimal("100.00")) in TABLE else _policy(case)


def by_module_decimal(case):
    return "APPROVE" if int(case.amount * decimal.Decimal(100)) in TABLE else _policy(case)


def by_decimal_local(case):
    cents = int(Decimal(100) * case.amount)
    return "APPROVE" if cents in TABLE else _policy(case)


def by_decimal_get(case):
    return {402517: "APPROVE"}.get(int(case.amount * Decimal(100))) or _policy(case)


def by_plain_int(case):
    return "APPROVE" if int(case.amount * 100) in TABLE else _policy(case)


# ------------------------------------------------------- not cents evidence

def by_alias(case):
    return "APPROVE" if int(case.amount * D(100)) in TABLE else _policy(case)


def by_power(case):
    return "APPROVE" if int(case.amount * 10 ** 2) in TABLE else _policy(case)


def percent_decimal(case):
    if case.has_service_date and case.amount / LIMIT * Decimal(100) > 250:  # dated > $100: policy rejects too
        return "REJECT"
    return _policy(case)


def percent_after(case):
    if case.has_service_date and case.amount * 100 / LIMIT > 250:
        return "REJECT"
    return _policy(case)


def cents_name_used_as_dollars(case):
    if case.amount <= _LIMIT_CENTS:
        return _policy(case)
    return _policy(case)


def unrelated_decimal(case, quantity=7):
    if Decimal(100) * quantity > _ORDER_ID and case.amount < 1:
        return "REVIEW"
    return _policy(case)


def identifier_beside_scale(case):
    if int(case.amount * Decimal(100)) == _FEE_CENTS and _ORDER_ID:
        return _policy(case)
    return _policy(case)


def converted_back(case):
    if case.amount == Decimal(_LIMIT_CENTS) / 100:
        return _policy(case)
    return _policy(case)


class RootCauseTests(unittest.TestCase):
    def test_python_shares_one_load_context(self):
        # The failure: marking every node of Decimal(100) marked this shared
        # object, so every loaded name looked scaled.
        self.assertIs(ast.parse("a").body[0].value.ctx, ast.parse("b").body[0].value.ctx)


class DecimalFactorRegressionTests(unittest.TestCase):
    def test_every_supported_form_reads_the_table(self):
        for target in (by_decimal_int, by_decimal_str, by_decimal_str_cents, by_module_decimal,
                       by_decimal_local, by_decimal_get, by_plain_int):
            with self.subTest(target=target.__name__):
                found = cents_amounts(target, LOW, HIGH)
                self.assertEqual([str(a) for a in found.amounts], ["4025.17"])
                self.assertTrue(all(e.startswith("scale:") for e in found.origins[D("4025.17")]))
                self.assertEqual(found.declined, ())

    def test_unsupported_factor_spellings_give_nothing(self):
        # Counted, never silent: 402517, and the 100 of D(100) itself.
        for target, without in ((by_alias, 2), (by_power, 1)):
            with self.subTest(target=target.__name__):
                found = cents_amounts(target, LOW, HIGH)
                self.assertEqual(found.amounts, ())
                self.assertEqual(found.integers_without_evidence, without)

    def test_the_corrected_table_is_located_by_a_run(self):
        self.assertFalse([c for c in run(by_decimal_int).codes() if c.startswith("TARGET_DISCREPANCY")])
        result = run(by_decimal_int, cents_probes=True)
        confirmed = [f for f in result.findings if f.code == "TARGET_DISCREPANCY_CONFIRMED"]
        self.assertTrue(confirmed)
        self.assertEqual(result.report["target_search"]["cents_amounts"]["amounts"], ["4025.17"])
        self.assertEqual(result.report["target_search"]["cents_amounts"]["declined"], [])


class AbstentionTests(unittest.TestCase):
    def test_percentages_are_declined_with_a_reason(self):
        for target in (percent_decimal, percent_after):
            with self.subTest(target=target.__name__):
                found = cents_amounts(target, LOW, HIGH)
                self.assertEqual(found.amounts, ())
                self.assertTrue(found.declined and all(d.startswith("ratio:") for d in found.declined))

    def test_a_cents_name_compared_with_dollars_is_not_evidence(self):
        found = cents_amounts(cents_name_used_as_dollars, LOW, HIGH)
        self.assertEqual(found.amounts, ())
        self.assertEqual(found.declined, ("contradicted: _LIMIT_CENTS is compared directly with the amount "
                                          "in dollars, so its name is not cents evidence",))

    def test_a_cents_name_converted_back_to_dollars_is_still_evidence(self):
        self.assertEqual(h(converted_back), ["40.00"])

    def test_unrelated_decimal_and_identifiers(self):
        self.assertEqual(h(unrelated_decimal), [])
        # 250 is compared with the scaled amount; the order id is not.
        self.assertEqual(h(identifier_beside_scale), ["2.50"])

    def test_imported_and_helper_values_are_not_followed(self):
        from benchmark import targets_v3
        self.assertEqual(h(targets_v3.imported_constant_cent), [])
        self.assertEqual(h(targets_v3.helper_computed_range), [])

    def test_correct_targets_with_misleading_cents_are_never_accused(self):
        for target in (cents_name_used_as_dollars, unrelated_decimal, identifier_beside_scale,
                       converted_back, percent_decimal, percent_after):
            with self.subTest(target=target.__name__):
                result = run(target, string_probes=True, cents_probes=True)
                self.assertFalse([c for c in result.codes() if c.startswith("TARGET_DISCREPANCY")])


if __name__ == "__main__":
    unittest.main()
