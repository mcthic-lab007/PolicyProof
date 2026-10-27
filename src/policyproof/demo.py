"""Reproducible offline demo: verify the synthetic fixture three ways and
render the reports as linked evidence pages.

Each scenario runs the existing verification CLI (verification.main) on the
committed synthetic Muse-shaped fixture and the fictional DemoCo policy. No
API key, network access or live Muse Spark call is involved. Reports and
pages go to an output directory (default artifacts/demo/, git-ignored);
existing files are never replaced unless --overwrite is given.

Usage:
    python -m src.policyproof.demo [--output-dir DIR] [--overwrite] [--open]
"""

import argparse
import sys
import webbrowser
from pathlib import Path

from src.policyproof import verification
from src.policyproof.viewer import Alternative, ViewerError, load_report, render_report, write_page


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "examples" / "democo_meal_policy.txt"
FIXTURE = ROOT / "tests" / "fixtures" / "muse_democo_meal_response.json"
DEFAULT_OUTPUT = ROOT / "artifacts" / "demo"

# (name, label, verification arguments, documented verification exit code)
SCENARIOS = (
    ("buggy", "Buggy target, with reference", ["--reference", "democo-meal", "--target", "democo-buggy"], 3),
    ("fixed", "Fixed target, with reference", ["--reference", "democo-meal", "--target", "democo-fixed"], 0),
    ("no-reference", "Buggy target, no reference", ["--target", "democo-buggy"], 4),
)


def outputs(directory: Path) -> dict[str, tuple[Path, Path]]:
    return {
        name: (directory / f"report-{name}.json", directory / f"evidence-{name}.html")
        for name, *_ in SCENARIOS
    }


def main(argv: list[str] | None = None) -> int:
    """Exit codes: 0 demo produced as documented, 1 error."""
    parser = argparse.ArgumentParser(description="Run the offline PolicyProof demo and render evidence pages.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                        help="where reports and pages are written (default: artifacts/demo)")
    parser.add_argument("--overwrite", action="store_true", help="replace files from an earlier run")
    parser.add_argument("--open", action="store_true", help="open the main evidence page in a browser")
    args = parser.parse_args(argv)

    files = outputs(args.output_dir)
    existing = [str(p) for pair in files.values() for p in pair if p.exists()]
    if existing and not args.overwrite:
        print("error: output files already exist; pass --overwrite to replace them:\n  "
              + "\n  ".join(existing), file=sys.stderr)
        return 1

    reports = {}
    for name, label, extra, expected in SCENARIOS:
        report_path, _ = files[name]
        print(f"\n=== {label} ===")
        argv_run = [str(POLICY), "--replay", str(FIXTURE), *extra, "--report", str(report_path)]
        code = verification.main(argv_run + (["--overwrite"] if args.overwrite else []))
        print(f"verification exit code: {code} (documented: {expected})")
        if code != expected:
            print(f"error: scenario {name!r} exited with {code}, expected {expected}", file=sys.stderr)
            return 1
        try:
            reports[name] = load_report(report_path)
        except ViewerError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    for name, label, *_ in SCENARIOS:
        others = [
            Alternative(other_label, reports[other], files[other][1].name)
            for other, other_label, *_ in SCENARIOS if other != name
        ]
        try:
            write_page(render_report(reports[name], others), files[name][1], overwrite=args.overwrite)
        except (ViewerError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    main_page = files["buggy"][1].resolve()
    print("\nEvidence pages:")
    for name, *_ in SCENARIOS:
        print(f"  {files[name][1]}")
    print(f"Open the main page in a browser: {main_page.as_uri()}")
    if args.open:
        webbrowser.open(main_page.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
