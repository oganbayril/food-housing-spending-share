"""Tests for deploy/check_caddy_change.py.

Fixtures are real `caddy adapt` output from this project's deployment:
- phase_c_before/after.json: renaming 00-existing.conf to realestate.conf
  (no site added; the config must be unchanged)
- phase_e_before/after.json: adding food-housing.conf, which sorts first and
  shifts titris's group label (group3 -> group4) and the log numbering

Run from the project root:
    uv run python -m unittest discover deploy/tests
"""

import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from check_caddy_change import compare, normalize_groups  # noqa: E402

NEW = "food-housing-spending-share.duckdns.org"


def fixture(name):
    with open(HERE / "fixtures" / name, encoding="utf-8") as file:
        return json.load(file)


def route_for(config, host):
    for route in config["apps"]["http"]["servers"]["srv0"]["routes"]:
        if host in json.dumps(route.get("match")):
            return route
    raise KeyError(host)


def replace_in_route(config, host, old, new):
    """Copy of config with text replaced inside one host's route only."""
    config = copy.deepcopy(config)
    route = route_for(config, host)
    text = json.dumps(route)
    if old not in text:
        raise AssertionError(f"{old!r} not in {host}'s route")
    route.clear()
    route.update(json.loads(text.replace(old, new)))
    return config


class RealDeploymentFiles(unittest.TestCase):
    def test_phase_e_adding_the_site_passes(self):
        before, after = fixture("phase_e_before.json"), fixture("phase_e_after.json")
        self.assertEqual(compare(before, after, NEW), [])

    def test_phase_e_raw_titris_route_differs_only_in_group_label(self):
        # The false positive the first version of the gate tripped on.
        before, after = fixture("phase_e_before.json"), fixture("phase_e_after.json")
        raw_before = json.dumps(route_for(before, "titris.duckdns.org"), sort_keys=True)
        raw_after = json.dumps(route_for(after, "titris.duckdns.org"), sort_keys=True)
        self.assertNotEqual(raw_before, raw_after)
        self.assertEqual(raw_before.replace("group3", "group4"), raw_after)

    def test_phase_c_rename_passes_with_no_new_site(self):
        before, after = fixture("phase_c_before.json"), fixture("phase_c_after.json")
        self.assertEqual(compare(before, after), [])

    def test_phase_e_fails_if_no_new_site_was_expected(self):
        before, after = fixture("phase_e_before.json"), fixture("phase_e_after.json")
        self.assertEqual(len(compare(before, after)), 1)


class GroupRenamingIsPerSite(unittest.TestCase):
    def test_each_site_starts_its_own_numbering(self):
        # Under GLOBAL renaming the second site's first group would become g1.
        site_a = {"handle": [{"group": "group0"}, {"group": "group0"}]}
        site_b = {"handle": [{"group": "group1"}, {"group": "group2"}]}
        self.assertEqual(normalize_groups(site_a), {"handle": [{"group": "g0"}, {"group": "g0"}]})
        self.assertEqual(normalize_groups(site_b), {"handle": [{"group": "g0"}, {"group": "g1"}]})

    def test_shifts_of_different_size_per_site_still_pass(self):
        # Two existing sites with groups; after the change their numbers
        # shift by different amounts. Both must still count as unchanged.
        before = fixture("phase_e_before.json")
        after = fixture("phase_e_after.json")
        before = replace_in_route(before, "germany-real-estate.duckdns.org",
                                  '"handler": "reverse_proxy"',
                                  '"handler": "reverse_proxy", "group": "group1"')
        after = replace_in_route(after, "germany-real-estate.duckdns.org",
                                 '"handler": "reverse_proxy"',
                                 '"handler": "reverse_proxy", "group": "group7"')
        self.assertEqual(compare(before, after, NEW), [])

    def test_regrouping_inside_a_site_is_caught(self):
        before, after = fixture("phase_e_before.json"), fixture("phase_e_after.json")
        after = copy.deepcopy(after)
        groups = []

        def collect(value):
            if isinstance(value, dict):
                if "group" in value:
                    groups.append(value)
                for item in value.values():
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(route_for(after, "titris.duckdns.org"))
        self.assertEqual(len(groups), 2)
        groups[1]["group"] = "group99"  # the two handlers no longer exclude each other
        self.assertEqual(compare(before, after, NEW), ["titris.duckdns.org: route changed"])


class RealChangesAreCaught(unittest.TestCase):
    def setUp(self):
        self.before = fixture("phase_e_before.json")
        self.after = fixture("phase_e_after.json")

    def test_titris_proxy_port(self):
        after = replace_in_route(self.after, "titris.duckdns.org", "127.0.0.1:8001", "127.0.0.1:9999")
        self.assertEqual(compare(self.before, after, NEW), ["titris.duckdns.org: route changed"])

    def test_realestate_header(self):
        after = replace_in_route(self.after, "germany-real-estate.duckdns.org", '"DENY"', '"SAMEORIGIN"')
        self.assertEqual(compare(self.before, after, NEW), ["germany-real-estate.duckdns.org: route changed"])

    def test_realestate_proxy_port(self):
        after = replace_in_route(self.after, "germany-real-estate.duckdns.org", "127.0.0.1:8000", "127.0.0.1:8001")
        self.assertEqual(compare(self.before, after, NEW), ["germany-real-estate.duckdns.org: route changed"])

    def test_existing_log_file(self):
        after = copy.deepcopy(self.after)
        for log in after["logging"]["logs"].values():
            writer = log.get("writer", {})
            if writer.get("filename") == "/var/log/caddy/titris.log":
                writer["filename"] = "/tmp/other.log"
        self.assertEqual(compare(self.before, after, NEW), ["titris.duckdns.org: log settings changed"])

    def test_removed_site(self):
        after = copy.deepcopy(self.after)
        routes = after["apps"]["http"]["servers"]["srv0"]["routes"]
        routes.remove(route_for(after, "titris.duckdns.org"))
        self.assertIn("titris.duckdns.org: missing after the change", compare(self.before, after, NEW))

    def test_listen_address(self):
        after = copy.deepcopy(self.after)
        after["apps"]["http"]["servers"]["srv0"]["listen"] = [":8443"]
        self.assertEqual(compare(self.before, after, NEW),
                         ["something outside the site routes and logs changed"])


if __name__ == "__main__":
    unittest.main()
