"""Pure-function tests for the LinkedIn URL validator."""
from __future__ import annotations
import unittest

from agents.linkedin_finder import is_valid_linkedin_profile_url


class IsValidLinkedinProfileUrlTest(unittest.TestCase):
    def test_accepts_canonical_in_url(self):
        self.assertTrue(is_valid_linkedin_profile_url(
            "https://www.linkedin.com/in/jane-smith-123abc"))

    def test_accepts_no_subdomain(self):
        self.assertTrue(is_valid_linkedin_profile_url(
            "https://linkedin.com/in/jane"))

    def test_rejects_company_url(self):
        self.assertFalse(is_valid_linkedin_profile_url(
            "https://linkedin.com/company/acme-bath"))

    def test_rejects_post_url(self):
        self.assertFalse(is_valid_linkedin_profile_url(
            "https://linkedin.com/posts/jane-smith_abc"))

    def test_rejects_non_linkedin(self):
        self.assertFalse(is_valid_linkedin_profile_url(
            "https://twitter.com/in/jane"))

    def test_rejects_blank(self):
        self.assertFalse(is_valid_linkedin_profile_url(""))


if __name__ == "__main__":
    unittest.main()
