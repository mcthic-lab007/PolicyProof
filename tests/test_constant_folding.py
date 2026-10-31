"""Tests for constant_folding (method E): constant expressions in a target's
source folded to probe amounts by a bounded evaluator, never by running code."""

import builtins
import os
import sys
import textwrap
import unittest
from decimal import Decimal
from unittest import mock

from benchmark import targets as bench
from src.policyproof.constant_folding import (
    MAX_FOLDED_AMOUNTS,
    fold_constants,
    fold_source,
)

D = Decimal
LOW, HIGH = D("0.00"), D("1000000.00")
_CALLED = []


def fold(text, name="decide"):
    return fold_source(textwrap.dedent(text), name, LOW, HIGH)


def amounts(text, name="decide"):
    return [str(a) for a in fold(text, name).amounts]


def _recording_target(case):
    _CALLED.append(case)
    return "APPROVE" if case.amount == bench.LIMIT * 2 + D("0.01") else "REJECT"


class SupportedExpressionTests(unittest.TestCase):
    def test_corpus_computed_edges(self):
        result = fold_constants(bench.narrow_computed_range, LOW, HIGH)
        self.assertTrue({"2000.00", "2000.37", "2000.52"} <= {str(a) for a in result.amounts})
        self.assertIn("line 103: _BASE + Decimal(37) * CENT", result.derivations["2000.37"])
        self.assertEqual(result.unsupported, ())
        self.assertIn("narrow_computed_range()", result.source)

    def test_decimal_arithmetic_and_operators(self):
        found = amounts("""
            from decimal import Decimal
            CENT = Decimal("0.01")
            A = Decimal("10.00") * 3 + Decimal(5) / 2
            B = (Decimal(100) - CENT) // 1
            C = Decimal(7) % 5 + -Decimal("1.50") + +Decimal("4")
            P = 10 ** 3
            def decide(case):
                return case.amount in (A, B, C, P, CENT * 1234)
            """)
        # A, B, C, P and the inline product; their sub-expressions fold too.
        self.assertTrue({"32.50", "99.00", "4.50", "1000.00", "12.34"} <= set(found), found)
        self.assertIn("99.99", found)  # Decimal(100) - CENT, inside B

    def test_decimal_module_attribute_and_alias(self):
        self.assertIn("12.50", amounts("""
            import decimal
            from decimal import Decimal as Dec
            X = decimal.Decimal("12.00") + Dec("0.50")
            def decide(case):
                return case.amount == X
            """))

    def test_int_and_float_follow_python_types(self):
        found = amounts("""
            CENTS = 4000 + 1
            HALF = 81 / 2
            def decide(case):
                return case.amount * 100 == CENTS or case.amount == HALF
            """)
        self.assertIn("4001.00", found)
        self.assertIn("40.50", found)

    def test_expressions_written_inside_the_function_and_locals(self):
        found = amounts("""
            from decimal import Decimal
            LIMIT = Decimal("40.00")
            def decide(case):
                edge = LIMIT * 25 + Decimal("0.07")
                return case.amount <= LIMIT * 50 + Decimal("0.37") and case.amount != edge
            """)
        self.assertIn("2000.37", found)
        self.assertIn("1000.07", found)

    def test_non_amount_values_are_dropped(self):
        found = amounts("""
            from decimal import Decimal
            TINY = Decimal("0.005") * 1
            NEG = Decimal(0) - 5
            BIG = Decimal(2000000) * 1
            def decide(case):
                return case.amount in (TINY, NEG, BIG)
            """)
        self.assertEqual(found, ["0.00"])  # only the 0 operand of NEG is an amount

    def test_amounts_are_capped(self):
        body = "\n".join(f"V{i} = {i} * 1" for i in range(1, MAX_FOLDED_AMOUNTS + 21))
        names = ", ".join(f"V{i}" for i in range(1, MAX_FOLDED_AMOUNTS + 21))
        result = fold(body + f"\ndef decide(case):\n    return case.amount in ({names},)\n")
        self.assertEqual(len(result.amounts), MAX_FOLDED_AMOUNTS)


class DependencyTests(unittest.TestCase):
    def test_transitive_module_constants_in_any_order_of_use(self):
        found = amounts("""
            from decimal import Decimal
            A = Decimal("1.00")
            B = A * 3
            C = B + A
            def decide(case):
                return case.amount == C * 10
            """)
        self.assertIn("40.00", found)

    def test_local_name_shadows_module_constant(self):
        found = amounts("""
            from decimal import Decimal
            X = Decimal("5.00")
            def decide(case):
                X = Decimal("7.00")
                return case.amount == X * 2
            """)
        self.assertIn("14.00", found)
        self.assertNotIn("10.00", found)

    def test_parameters_are_runtime_values_not_reported(self):
        result = fold("""
            from decimal import Decimal
            def decide(case, limit=Decimal("1.00")):
                return case.amount * 2 > limit + case.amount
            """)
        self.assertEqual(result.unsupported, ())


class UnsupportedTests(unittest.TestCase):
    def assert_unsupported(self, text, fragment, absent=()):
        result = fold(text)
        self.assertTrue(any(fragment in u for u in result.unsupported), result.unsupported)
        for amount in absent:
            self.assertNotIn(D(amount), result.amounts)

    def test_other_calls_are_reported_not_evaluated(self):
        self.assert_unsupported("""
            import os
            X = os.getpid() + 1
            def decide(case):
                return case.amount == X
            """, "call to os.getpid is not evaluated")

    def test_imported_constants_are_reported(self):
        self.assert_unsupported("""
            from config import LIMIT
            def decide(case):
                return case.amount <= LIMIT * 2
            """, "LIMIT is imported")

    def test_attributes_and_methods_are_reported(self):
        self.assert_unsupported("""
            from decimal import Decimal
            X = Decimal("1.234").quantize(Decimal("0.01"))
            def decide(case):
                return case.amount == X
            """, "is not evaluated")

    def test_decimal_plus_float_is_a_type_error_as_in_python(self):
        self.assert_unsupported("""
            from decimal import Decimal
            X = Decimal("1.00") + 0.5
            def decide(case):
                return case.amount == X
            """, "TypeError", absent=["1.50"])

    def test_large_exponent_and_magnitude_are_refused(self):
        self.assert_unsupported("""
            X = 10 ** 100
            def decide(case):
                return case.amount == X
            """, "exponent")
        self.assert_unsupported("""
            X = 99999999 * 99999999
            def decide(case):
                return case.amount == X
            """, "value beyond")

    def test_division_by_zero_is_reported(self):
        self.assert_unsupported("""
            from decimal import Decimal
            X = Decimal(1) / 0
            def decide(case):
                return case.amount == X
            """, "DivisionByZero")

    def test_rebound_decimal_is_not_trusted(self):
        self.assert_unsupported("""
            from decimal import Decimal
            Decimal = lambda value: 0
            X = Decimal("5.00")
            def decide(case):
                return case.amount == X
            """, "is not evaluated", absent=["5.00"])

    def test_deep_nesting_is_refused(self):
        expression = "(" * 60 + "1" + " + 1)" * 60
        result = fold(f"X = {expression}\ndef decide(case):\n    return case.amount == X\n")
        self.assertTrue(any("too deeply" in u for u in result.unsupported), result.unsupported)


class CycleAndAmbiguityTests(unittest.TestCase):
    def test_cycles_are_reported_and_never_loop(self):
        result = fold("""
            A = B + 1
            B = A + 1
            def decide(case):
                return case.amount == A
            """)
        self.assertEqual(result.amounts, ())
        self.assertTrue(any("cycle" in u for u in result.unsupported), result.unsupported)

    def test_self_reference_is_a_cycle(self):
        result = fold("A = A + 1\ndef decide(case):\n    return case.amount == A\n")
        self.assertTrue(any("cycle" in u for u in result.unsupported))

    def test_name_bound_twice_is_ambiguous(self):
        result = fold("""
            from decimal import Decimal
            X = Decimal("10.00")
            X = Decimal("20.00")
            def decide(case):
                return case.amount == X * 2
            """)
        self.assertNotIn(D("20.00") * 2, result.amounts)
        self.assertNotIn(D("40.00"), result.amounts)
        self.assertTrue(any("ambiguous" in u for u in result.unsupported), result.unsupported)

    def test_conditional_and_augmented_bindings_are_ambiguous(self):
        for text in ["""
                import sys
                if sys.platform:
                    X = 5
                else:
                    X = 6
                def decide(case):
                    return case.amount == X * 2
                """, """
                X = 5
                X += 1
                def decide(case):
                    return case.amount == X * 2
                """, """
                X = 5
                def bump():
                    global X
                    X = 9
                def decide(case):
                    return case.amount == X * 2
                """, """
                def decide(case):
                    y = 1
                    for y in range(3):
                        pass
                    return case.amount == y * 2
                """]:
            with self.subTest(text=text):
                result = fold(text)
                self.assertEqual([a for a in result.amounts if a in (D(10), D(12), D(18), D(2))], [])


class SourceTests(unittest.TestCase):
    def test_malformed_source_is_reported(self):
        result = fold("def decide(case:\n    return 1\n")
        self.assertEqual(result.amounts, ())
        self.assertIn("could not be parsed", result.unavailable)

    def test_missing_function_and_unavailable_source(self):
        self.assertIn("not found", fold("X = 1\n", "decide").unavailable)
        self.assertIn("not available", fold_constants(lambda case: 1, LOW, HIGH).unavailable)
        self.assertIn("not available", fold_constants(len, LOW, HIGH).unavailable)

    def test_byte_order_mark_is_accepted(self):
        from examples import buggy_engine
        result = fold_constants(buggy_engine.evaluate_meal_claim, LOW, HIGH)
        self.assertIsNone(result.unavailable)

    def test_correct_targets_fold_only_their_own_constants(self):
        from examples import fixed_engine
        for function in (fixed_engine.evaluate_meal_claim, bench.correct_integer_cents,
                         bench.correct_reordered, bench.correct_float):
            with self.subTest(function=function.__name__):
                result = fold_constants(function, LOW, HIGH)
                self.assertIsNone(result.unavailable)
                self.assertTrue(set(result.amounts) <= {D("40.00")}, result.amounts)


class NoExecutionTests(unittest.TestCase):
    def test_extraction_never_calls_the_target(self):
        _CALLED.clear()
        result = fold_constants(_recording_target, LOW, HIGH)
        self.assertEqual(_CALLED, [])
        self.assertIsNone(result.unavailable)

    def test_extraction_never_evaluates_imports_or_executes_source(self):
        text = """
            X = __import__("os").system("echo should-never-run") + 1
            Y = eval("1 + 1")
            from decimal import Decimal
            Z = Decimal("3.00") * 2
            def decide(case):
                exec("raise SystemExit")
                return case.amount in (X, Y, Z)
            """

        def forbidden(*args, **kwargs):
            raise AssertionError("code execution attempted during extraction")
        real_import = builtins.__import__

        def loaded_only(name, *args, **kwargs):
            # Re-binding an already-loaded module runs no code (ast.walk does
            # this); importing anything new would.
            if name not in sys.modules:
                raise AssertionError(f"import of {name} attempted during extraction")
            return real_import(name, *args, **kwargs)
        with mock.patch.object(os, "system", forbidden), \
                mock.patch.object(builtins, "eval", forbidden), \
                mock.patch.object(builtins, "exec", forbidden), \
                mock.patch.object(builtins, "__import__", loaded_only):
            result = fold(text)
        self.assertEqual([str(a) for a in result.amounts], ["3.00", "6.00"])
        self.assertTrue(any("__import__" in u for u in result.unsupported), result.unsupported)
        self.assertTrue(any("eval" in u for u in result.unsupported), result.unsupported)


class VerifyIntegrationTests(unittest.TestCase):
    def verify(self, function, **options):
        from benchmark import run as bench_run
        from src.policyproof.verification import Implementation, verify
        policy_text = bench_run.POLICY.read_text(encoding="utf-8")
        proposal = bench_run.replay_proposal(bench_run.FIXTURE, policy_text)
        return verify(proposal.document, policy_text, proposal=proposal,
                      reference=bench_run.REFERENCE,
                      target=Implementation(function.__name__, "", function),
                      search_budget=250, **options)

    def test_off_by_default_and_report_unchanged(self):
        default = self.verify(bench.narrow_computed_range)
        self.assertNotIn("constant_amounts", default.report["target_search"])
        self.assertEqual(default.to_json(),
                         self.verify(bench.narrow_computed_range, constant_probes=False).to_json())

    def test_folded_edges_locate_the_computed_range(self):
        result = self.verify(bench.narrow_computed_range, constant_probes=True)
        section = result.report["target_search"]["constant_amounts"]
        self.assertIn("2000.37", section["amounts"])
        self.assertIn("2000.37", section["derivations"])
        ranges = [f["details"] for f in result.report["findings"]
                  if f["code"] == "TARGET_DISCREPANCY_CONFIRMED" and f["details"].get("kind") == "range"]
        self.assertIn(("2000.37", "2000.52"), [(d["start"], d["end"]) for d in ranges])

    def test_a_folded_probe_is_never_a_finding_on_a_correct_target(self):
        from examples import fixed_engine
        result = self.verify(fixed_engine.evaluate_meal_claim, constant_probes=True)
        self.assertEqual(result.level, "L3")
        self.assertFalse([f for f in result.report["findings"]
                          if f["code"] == "TARGET_DISCREPANCY_CONFIRMED"])


if __name__ == "__main__":
    unittest.main()
