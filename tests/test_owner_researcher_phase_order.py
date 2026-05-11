"""Phase-order tests for owner_researcher after the BBB Phase 0 reshape.

The phase list is now driven by ``CONFIG`` flags (bbb_direct_enabled,
bbb_websearch_enabled, yelp_phase0_enabled) plus the existing
``state.use_websearch`` toggle. ``use_registry`` no longer gates anything
in this builder — OpenCorporates was removed.
"""
import sys
import os
import unittest
from dataclasses import dataclass, field
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.owner_researcher import _build_phase_list
from agents.sources.owners import bbb_direct, bbb_websearch, website, websearch
from config import CONFIG


@dataclass
class _FakeState:
    city: str = "Orlando"
    state_abbr: str = "FL"
    use_registry: bool = True
    use_websearch: bool = True
    leads: list = field(default_factory=list)
    log: list = field(default_factory=list)
    completed_steps: list = field(default_factory=list)


class PhaseOrderTests(unittest.TestCase):
    def test_bbb_direct_then_websearch_then_website(self) -> None:
        with patch.object(CONFIG, "yelp_phase0_enabled", False), \
             patch.object(CONFIG, "bbb_direct_enabled", True), \
             patch.object(CONFIG, "bbb_websearch_enabled", True):
            phases = _build_phase_list(_FakeState())
        self.assertEqual(phases[0], bbb_direct.lookup)
        self.assertEqual(phases[1], bbb_websearch.lookup)
        self.assertEqual(phases[2], website.lookup)

    def test_yelp_first_when_enabled(self) -> None:
        with patch.object(CONFIG, "yelp_phase0_enabled", True), \
             patch.object(CONFIG, "bbb_direct_enabled", True), \
             patch.object(CONFIG, "bbb_websearch_enabled", True):
            phases = _build_phase_list(_FakeState())
        # Lazy import — fetch by short module name instead of identity.
        self.assertEqual(phases[0].__module__.split(".")[-1], "yelp_profile")
        self.assertEqual(phases[1], bbb_direct.lookup)

    def test_websearch_excluded_when_use_websearch_false(self) -> None:
        with patch.object(CONFIG, "bbb_direct_enabled", True), \
             patch.object(CONFIG, "bbb_websearch_enabled", True):
            phases = _build_phase_list(_FakeState(use_websearch=False))
        self.assertNotIn(websearch.lookup, phases)

    def test_bbb_direct_excluded_when_flag_off(self) -> None:
        with patch.object(CONFIG, "bbb_direct_enabled", False), \
             patch.object(CONFIG, "bbb_websearch_enabled", True):
            phases = _build_phase_list(_FakeState())
        self.assertNotIn(bbb_direct.lookup, phases)
        self.assertIn(bbb_websearch.lookup, phases)

    def test_bbb_websearch_excluded_when_flag_off(self) -> None:
        with patch.object(CONFIG, "bbb_direct_enabled", True), \
             patch.object(CONFIG, "bbb_websearch_enabled", False):
            phases = _build_phase_list(_FakeState())
        self.assertIn(bbb_direct.lookup, phases)
        self.assertNotIn(bbb_websearch.lookup, phases)

    def test_website_always_present(self) -> None:
        with patch.object(CONFIG, "yelp_phase0_enabled", False), \
             patch.object(CONFIG, "bbb_direct_enabled", False), \
             patch.object(CONFIG, "bbb_websearch_enabled", False):
            phases = _build_phase_list(_FakeState(use_websearch=False))
        self.assertEqual(phases, [website.lookup])


if __name__ == "__main__":
    unittest.main()
