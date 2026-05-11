"""Unit tests for agents.sources.owners.bbb_websearch.

The Anthropic client is mocked at the import boundary
(`agents.sources.owners.bbb_websearch.Anthropic`) so no live API calls are
made. We are testing our wrapper — JSON parsing, phase stamping, exception
handling — not Anthropic's web_search behavior.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from agents.sources.owners import bbb_websearch
from state import Lead


def _mock_response(text: str) -> MagicMock:
    """Build a stand-in for an Anthropic messages.create response."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    return resp


class BBBWebsearchTests(unittest.TestCase):
    def _lead(self) -> Lead:
        return Lead(
            business_name="Jackson Construction",
            website="https://jacksonconstruction.example.com",
        )

    @patch("agents.sources.owners.bbb_websearch.Anthropic")
    def test_happy_path_returns_parsed_owner(self, mock_anthropic_cls: MagicMock) -> None:
        client = MagicMock()
        client.messages.create.return_value = _mock_response(
            '{"owner_full_name": "Jane Smith", '
            '"source_url": "https://www.bbb.org/us/fl/orlando/profile/jackson", '
            '"confidence": "high"}'
        )
        mock_anthropic_cls.return_value = client

        result = bbb_websearch.lookup(self._lead(), "Orlando", "FL", "sk-test")

        self.assertEqual(result["owner_full_name"], "Jane Smith")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["phase"], "bbb_websearch")

    @patch("agents.sources.owners.bbb_websearch.Anthropic")
    def test_empty_text_returns_none_confidence(self, mock_anthropic_cls: MagicMock) -> None:
        client = MagicMock()
        client.messages.create.return_value = _mock_response("")
        mock_anthropic_cls.return_value = client

        result = bbb_websearch.lookup(self._lead(), "Orlando", "FL", "sk-test")

        self.assertEqual(result["owner_full_name"], "")
        self.assertEqual(result["confidence"], "none")
        self.assertEqual(result["phase"], "bbb_websearch")

    @patch("agents.sources.owners.bbb_websearch.Anthropic")
    def test_anthropic_exception_returns_none_dict(self, mock_anthropic_cls: MagicMock) -> None:
        client = MagicMock()
        client.messages.create.side_effect = Exception("boom")
        mock_anthropic_cls.return_value = client

        result = bbb_websearch.lookup(self._lead(), "Orlando", "FL", "sk-test")

        self.assertEqual(
            result,
            {
                "owner_full_name": "",
                "confidence": "none",
                "phase": "bbb_websearch",
                "error": "boom",
            },
        )


if __name__ == "__main__":
    unittest.main()
