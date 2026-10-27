"""Routing of patient portal links before any network request is made."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import unittest

from backend.imaging_desktop.discovery import is_portal_link


class PortalLinkRoutingTests(unittest.TestCase):
    def test_https_patient_page_routes_to_browser_for_any_host_and_port(self):
        for url in (
            "https://center.example/Patient?studyKey=synthetic-only",
            "https://other.example:5010/patient?token=synthetic-only",
            "https://third.example/PATIENT",
            "https://[::1]:8443/Patient?x=1",
        ):
            with self.subTest(url=url):
                self.assertIs(is_portal_link(url), True)

    def test_only_exact_patient_path_is_classified_as_portal(self):
        for url in (
            "https://center.example/",
            "https://center.example/Patient/",
            "https://center.example/Patients",
            "https://center.example/clinic/Patient",
            "https://center.example/Patient.zip",
            "https://center.example/Patient%2F",
            "https://center.example/download?next=/Patient",
        ):
            with self.subTest(url=url):
                self.assertIs(is_portal_link(url), False)

    def test_invalid_and_unsafe_links_are_rejected_without_raising(self):
        for url in (
            None, b"https://center.example/Patient", "", "/Patient",
            "http://center.example/Patient?token=synthetic-secret",
            "https://user:synthetic-secret@center.example/Patient",
            "https://center.example:65536/Patient",
            "https://[invalid/Patient",
            "https://center.example/Patient#synthetic-secret",
            "https://center.example/Patient?token=synthetic-secret\n",
        ):
            with self.subTest(case=repr(url)[:40]):
                self.assertIs(is_portal_link(url), False)

    def test_query_is_ignored_and_no_query_or_credentials_are_printed(self):
        output = StringIO()
        with redirect_stdout(output), redirect_stderr(output):
            self.assertTrue(is_portal_link("https://center.example/Patient?studyKey=synthetic-secret"))
            self.assertFalse(is_portal_link("https://u:synthetic-secret@center.example/Patient"))
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
