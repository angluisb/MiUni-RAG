import unittest
from unittest.mock import Mock

import requests

from app.rag.crawl_policy import CrawlPolicy, CrawlPolicyError


ORIGIN = "https://www.unison.mx"
BOT = "MiUniRagScraper/0.1 (educational project)"


def response(url, status=200, body=b"User-agent: *\nAllow: /", content_type="text/plain", **headers):
    result = requests.Response()
    result.url = url
    result.status_code = status
    result._content = body
    result._content_consumed = True
    result.headers.update({"content-type": content_type, **headers})
    return result


class CrawlPolicyTests(unittest.TestCase):
    def policy(self, replies, **kwargs):
        self.now = 0.0
        self.sleeps = []
        def sleep(seconds):
            self.sleeps.append(seconds)
            self.now += seconds
        self.session = Mock()
        self.session.get.side_effect = replies
        return CrawlPolicy(self.session, BOT, lambda url, source=None: url.startswith(ORIGIN + "/"),
                           clock=lambda: self.now, sleeper=sleep, **kwargs)

    def test_disallowed_resource_is_never_requested(self):
        policy = self.policy([response(ORIGIN + "/robots.txt", body=b"User-agent: *\nDisallow: /private")])
        with self.assertRaises(CrawlPolicyError) as error:
            policy.get(ORIGIN + "/private/file.pdf", timeout=7)
        self.assertEqual(error.exception.outcome, "rejected")
        self.assertEqual([call.args[0] for call in self.session.get.call_args_list], [ORIGIN + "/robots.txt"])

    def test_request_normalization_cannot_bypass_disallow(self):
        for path in ("/safe/../private", "/%70rivate"):
            policy = self.policy([response(ORIGIN + "/robots.txt", body=b"User-agent: *\nDisallow: /private")])
            with self.assertRaises(CrawlPolicyError):
                policy.get(ORIGIN + path)
            self.assertEqual(self.session.get.call_count, 1)

    def test_specific_agent_wildcards_longest_rule_and_allow_tie(self):
        rules = b"User-agent: *\nDisallow: /\nUser-agent: MiUniRagScraper\nDisallow: /private/*\nAllow: /private/open$\nDisallow: /tie\nAllow: /tie\n"
        policy = self.policy([response(ORIGIN + "/robots.txt", body=rules)])
        for path, outcome in [("/public", "allowed"), ("/private/no", "rejected"),
                              ("/private/open", "allowed"), ("/private/open/more", "rejected"), ("/tie", "allowed")]:
            self.assertEqual(policy.check(ORIGIN + path)["outcome"], outcome)
        self.assertEqual(self.session.get.call_count, 1)

    def test_only_explicit_absence_allows_and_errors_fail_closed(self):
        for status, outcome in [(404, "allowed"), (410, "allowed"), (401, "rejected"),
                                (403, "rejected"), (429, "unavailable"), (500, "unavailable")]:
            with self.subTest(status=status):
                policy = self.policy([response(ORIGIN + "/robots.txt", status=status)])
                decision = policy.check(ORIGIN + "/file")
                self.assertEqual(decision["outcome"], outcome)
                if status in (404, 410):
                    self.assertEqual(decision["reason"], "allowed_absent")
        policy = self.policy([requests.Timeout("offline")])
        self.assertEqual(policy.check(ORIGIN + "/file")["outcome"], "unavailable")

    def test_html_and_malformed_policy_are_not_permission(self):
        for body, mime in [(b"<html>login</html>", "text/html"), (b"not a robots policy", "text/plain"),
                           (b"User-agent: *\nCrawl-delay: nan", "text/plain")]:
            policy = self.policy([response(ORIGIN + "/robots.txt", body=body, content_type=mime)])
            self.assertEqual(policy.check(ORIGIN + "/file")["outcome"], "unavailable")

    def test_cache_refresh_capacity_and_origin_separation(self):
        policy = self.policy([response(ORIGIN + "/robots.txt", status=404)] * 4,
                             ttl_seconds=10, capacity=1)
        policy.check(ORIGIN + "/a")
        policy.check(ORIGIN + "/b")
        self.assertEqual(self.session.get.call_count, 1)
        self.now = 11
        policy.check(ORIGIN + "/b")
        self.assertEqual(self.session.get.call_count, 2)
        policy.is_allowed = lambda url, source=None: True
        policy.check("http://www.unison.mx/file")
        policy.check(ORIGIN + "/a")
        self.assertEqual(self.session.get.call_count, 4)
        self.assertEqual(len(policy.cache), 1)
        with self.assertRaises(ValueError):
            self.policy([], ttl_seconds=86401)

    def test_ports_are_separate_origins_and_minimum_can_exceed_crawl_delay(self):
        policy = self.policy([response(ORIGIN + "/robots.txt", body=b"User-agent: *\nCrawl-delay: 0.1"),
                              response(ORIGIN + "/a"), response(ORIGIN + "/robots.txt", status=404)],
                             min_delay=3)
        policy.is_allowed = lambda url, source=None: True
        policy.get(ORIGIN + "/a")
        self.assertEqual(self.sleeps, [3])
        policy.check("https://www.unison.mx:8443/a")
        self.assertEqual(len(policy.cache), 2)

    def test_allowed_redirects_check_new_origin_policy_and_five_hops_succeed(self):
        other = "https://admision.unison.mx"
        policy = self.policy([response(ORIGIN + "/robots.txt", status=404),
                              response(ORIGIN + "/a", status=302, Location=other + "/a"),
                              response(other + "/robots.txt", body=b"User-agent: *\nDisallow: /a")])
        policy.is_allowed = lambda url, source=None: True
        with self.assertRaises(CrawlPolicyError):
            policy.get(ORIGIN + "/a")
        self.assertEqual(self.session.get.call_count, 3)
        replies = [response(ORIGIN + "/robots.txt", status=404)]
        replies += [response(ORIGIN + f"/{i}", status=302, Location=f"/{i+1}") for i in range(5)]
        replies += [response(ORIGIN + "/5", body=b"resource")]
        policy = self.policy(replies)
        self.assertEqual(policy.get(ORIGIN + "/0").content, b"resource")

    def test_robots_redirect_can_resolve_on_allowed_host_but_is_bounded(self):
        policy = self.policy([response(ORIGIN + "/robots.txt", status=302, Location="/robots-policy"),
                              response(ORIGIN + "/robots-policy", body=b"User-agent: *\nDisallow: /blocked")])
        self.assertEqual(policy.check(ORIGIN + "/blocked")["outcome"], "rejected")
        policy = self.policy([response(ORIGIN + "/robots.txt", status=302, Location="/robots.txt")] * 6)
        self.assertEqual(policy.check(ORIGIN + "/a")["outcome"], "unavailable")
        self.assertEqual(self.session.get.call_count, 6)

    def test_crawl_delay_and_minimum_apply_before_each_request(self):
        policy = self.policy([
            response(ORIGIN + "/robots.txt", body=b"User-agent: *\nCrawl-delay: 2.5"),
            response(ORIGIN + "/a"), response(ORIGIN + "/b")], min_delay=1)
        policy.get(ORIGIN + "/a")
        policy.get(ORIGIN + "/b")
        self.assertEqual(self.sleeps, [2.5, 2.5])

    def test_policy_refresh_keeps_the_previous_crawl_delay(self):
        policy = self.policy([
            response(ORIGIN + "/robots.txt", body=b"User-agent: *\nCrawl-delay: 2.5"),
            response(ORIGIN + "/a"), response(ORIGIN + "/robots.txt", status=404)], ttl_seconds=1)
        policy.get(ORIGIN + "/a")
        self.now = 3.6
        policy.check(ORIGIN + "/b")
        self.assertEqual(len(self.sleeps), 2)
        self.assertAlmostEqual(self.sleeps[-1], 1.4)

    def test_resource_and_robots_redirects_never_fetch_forbidden_host(self):
        for robots in (True, False):
            replies = [] if robots else [response(ORIGIN + "/robots.txt")]
            replies.append(response(ORIGIN + ("/robots.txt" if robots else "/a"), status=302,
                                    Location="https://evil.example/file"))
            policy = self.policy(replies)
            with self.assertRaises(CrawlPolicyError):
                policy.get(ORIGIN + "/a")
            self.assertFalse(any("evil" in call.args[0] for call in self.session.get.call_args_list))
            for call in self.session.get.call_args_list:
                self.assertIs(call.kwargs["allow_redirects"], False)

    def test_each_redirect_target_is_checked_and_loops_are_bounded(self):
        policy = self.policy([
            response(ORIGIN + "/robots.txt", body=b"User-agent: *\nDisallow: /blocked"),
            response(ORIGIN + "/a", status=302, Location="/blocked")])
        with self.assertRaises(CrawlPolicyError):
            policy.get(ORIGIN + "/a")
        self.assertEqual(self.session.get.call_count, 2)
        policy = self.policy([response(ORIGIN + "/robots.txt")] + [
            response(ORIGIN + "/a", status=302, Location="/a")] * 6)
        with self.assertRaises(CrawlPolicyError) as error:
            policy.get(ORIGIN + "/a")
        self.assertEqual(error.exception.reason, "redirect_limit")
        self.assertEqual(self.session.get.call_count, 7)
