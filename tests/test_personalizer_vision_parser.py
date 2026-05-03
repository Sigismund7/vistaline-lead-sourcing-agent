"""Pure-function tests for the personalizer's JSON parser."""
from __future__ import annotations
import unittest

from agents.personalizer import parse_vision_response


class ParseVisionResponseTest(unittest.TestCase):
    def test_extracts_x_y_from_clean_json(self):
        raw = (
            '{"x_project": "warm wood kitchen remodel", '
            '"y_detail": "black framed glass cabinets", '
            '"chosen_project": "row 1 col 2"}'
        )
        out = parse_vision_response(raw)
        self.assertEqual(out["x_project"], "warm wood kitchen remodel")
        self.assertEqual(out["y_detail"], "black framed glass cabinets")
        self.assertEqual(out["chosen_project"], "row 1 col 2")

    def test_strips_markdown_fence(self):
        raw = (
            "```json\n"
            '{"x_project": "X", "y_detail": "Y", "chosen_project": "Z"}\n'
            "```"
        )
        out = parse_vision_response(raw)
        self.assertEqual(out["x_project"], "X")

    def test_blank_dict_on_invalid_json(self):
        out = parse_vision_response("not json at all")
        self.assertEqual(out, {"x_project": "", "y_detail": "", "chosen_project": ""})

    def test_blank_dict_on_missing_fields(self):
        out = parse_vision_response('{"unrelated": 1}')
        self.assertEqual(out["x_project"], "")
        self.assertEqual(out["y_detail"], "")

    def test_strips_quotes_and_whitespace(self):
        raw = (
            '{"x_project": "  white kitchen  ", '
            '"y_detail": "\\"granite top\\"", "chosen_project": ""}'
        )
        out = parse_vision_response(raw)
        self.assertEqual(out["x_project"], "white kitchen")
        self.assertEqual(out["y_detail"], '"granite top"')


if __name__ == "__main__":
    unittest.main()
