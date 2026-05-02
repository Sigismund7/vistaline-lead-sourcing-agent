"""Smoke test: verify all agent modules import cleanly.

Real per-component tests are added in subsequent Phase 0 tasks
(test_azure_maps_client.py, test_yelp_fusion_client.py,
test_bing_search_client.py, test_sourcer.py, test_website_finder.py).
"""

import unittest


class ImportSmokeTest(unittest.TestCase):
    """Regression guard against import-time errors after refactors."""

    def test_agents_import(self):
        from agents import (
            csv_assembler,
            lead_filter,
            owner_researcher,
            sourcer,
            website_crawler,
        )

        self.assertTrue(
            all(
                m is not None
                for m in (
                    csv_assembler,
                    lead_filter,
                    owner_researcher,
                    sourcer,
                    website_crawler,
                )
            )
        )

    def test_top_level_modules_import(self):
        import config
        import state
        import tools

        self.assertTrue(all(m is not None for m in (config, state, tools)))


if __name__ == "__main__":
    unittest.main()
