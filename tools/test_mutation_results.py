"""Checks that the mutation results match the code and tests. Run: python tools/test_mutation_results.py

Mutation tests run only locally, so CI cannot run them. It can still see that a module, its tests or its configuration
changed after the last run, and fail until the module has been run again and its result committed. That keeps the
README's mutation badge from staying green after the code it vouches for has changed.
"""

import json
import unittest
from pathlib import Path

import badges
import run_mutation

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / run_mutation.RESULTS


def result(module):
    path = RESULTS / f"{module}.json"
    assert path.exists(), f"no mutation result for {module}: run it as CONTRIBUTING.md says and commit the file"
    return json.loads(path.read_text(encoding="utf-8"))


class Results(unittest.TestCase):
    def test_every_module_was_run_on_the_code_and_tests_it_has_now(self):
        for module in run_mutation.MODULES:
            with self.subTest(module):
                self.assertEqual(
                    result(module)["hash"],
                    run_mutation.fingerprint(ROOT, module),
                    f"{module} or its tests changed since its last mutation run: run it again and commit the result",
                )

    def test_no_module_has_a_survivor(self):
        for module in run_mutation.MODULES:
            with self.subTest(module):
                self.assertEqual(result(module)["survivors"], 0)

    def test_the_badge_is_built_from_these_results(self):
        shown = json.loads((ROOT / run_mutation.BADGE).read_text(encoding="utf-8"))
        self.assertEqual(shown, badges.mutation_badge(RESULTS))


if __name__ == "__main__":
    unittest.main()
