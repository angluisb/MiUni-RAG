"""Fail-closed robots admission and manually guarded HTTP redirects.

This supports agent groups, Allow/Disallow wildcards and Crawl-delay, not the
entire robots protocol. Callers retain ownership of their host allowlist.
"""

from collections import OrderedDict
from dataclasses import dataclass
import math
import re
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests


REDIRECTS = {301, 302, 303, 307, 308}


class CrawlPolicyError(requests.RequestException):
    def __init__(self, outcome, reason, url):
        super().__init__(reason)
        self.outcome, self.reason, self.url = outcome, reason, url


@dataclass
class Policy:
    expires: float
    outcome: str
    reason: str
    rules: tuple = ()
    delay: float = 0


class CrawlPolicy:
    def __init__(self, session, user_agent, is_allowed, *, min_delay=0.5,
                 ttl_seconds=3600, capacity=128, timeout=20, max_redirects=5,
                 clock=time.monotonic, sleeper=time.sleep):
        if not 0 < ttl_seconds <= 86400 or capacity < 1 or max_redirects < 5:
            raise ValueError("Invalid robots cache or redirect bounds")
        if not math.isfinite(min_delay) or min_delay < 0:
            raise ValueError("Invalid minimum crawl delay")
        self.session, self.user_agent, self.is_allowed = session, user_agent, is_allowed
        self.min_delay, self.ttl, self.capacity = min_delay, ttl_seconds, capacity
        self.timeout, self.max_redirects = timeout, max_redirects
        self.clock, self.sleeper = clock, sleeper
        self.cache = OrderedDict()
        self.last_request = OrderedDict()
        self.events = []

    @staticmethod
    def origin(url):
        parsed = urlsplit(url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            raise ValueError("Invalid crawl URL")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return parsed.scheme, parsed.hostname.lower(), port

    def _host_allowed(self, url, source):
        try:
            self.origin(url)
            return self.is_allowed(url, source)
        except ValueError:
            return False

    def _wait(self, url, delay):
        origin = self.origin(url)
        previous = self.cache.get(origin)
        if previous is not None:
            # Refreshing robots is itself a request subject to the last known delay.
            delay = max(delay, previous.delay)
        last = self.last_request.get(origin)
        if last is not None:
            remaining = max(self.min_delay, delay) - (self.clock() - last)
            if remaining > 0:
                self.sleeper(remaining)
        self.last_request[origin] = self.clock()
        self.last_request.move_to_end(origin)
        while len(self.last_request) > self.capacity:
            self.last_request.popitem(last=False)

    def _parse(self, content):
        text = content.decode("utf-8-sig")
        if "<html" in text.lower() or "<!doctype" in text.lower() or len(content) > 512 * 1024:
            raise ValueError("Invalid robots body")
        groups, agents, rules, delays = [], [], [], []
        has_directive = False
        known_document = not text.strip() or all(not line.split("#", 1)[0].strip() for line in text.splitlines())
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if ":" not in line:
                raise ValueError("Malformed robots directive")
            name, value = (part.strip() for part in line.split(":", 1))
            name = name.lower()
            if name == "user-agent":
                known_document = True
                if has_directive:
                    groups.append((agents, rules, delays))
                    agents, rules, delays, has_directive = [], [], [], False
                if not value:
                    raise ValueError("Empty robots agent")
                agents.append(value.lower())
            elif name in ("allow", "disallow", "crawl-delay"):
                if not agents:
                    raise ValueError("Robots rule without agent")
                has_directive = True
                if name == "crawl-delay":
                    delay = float(value)
                    if not math.isfinite(delay) or delay < 0:
                        raise ValueError("Invalid crawl delay")
                    delays.append(delay)
                elif value:
                    if not value.startswith("/"):
                        raise ValueError("Invalid robots path")
                    value = requests.utils.requote_uri(value)
                    anchor = value.endswith("$")
                    pattern = value[:-1] if anchor else value
                    regex = "^" + re.escape(pattern).replace(r"\*", ".*") + ("$" if anchor else "")
                    specificity = len(pattern.replace("*", "").encode("utf-8"))
                    rules.append((re.compile(regex), specificity, name == "allow"))
            elif name == "sitemap":
                known_document = True
        if not known_document:
            raise ValueError("No supported robots directives")
        groups.append((agents, rules, delays))
        product = self.user_agent.split("/", 1)[0].lower()
        selected, specificity = [], -1
        for agents, rules, delays in groups:
            matches = [0 if agent == "*" else len(agent) for agent in agents
                       if agent == "*" or agent in product]
            if not matches:
                continue
            score = max(matches)
            if score > specificity:
                selected, specificity = [], score
            if score == specificity:
                selected.append((rules, delays))
        return (tuple(rule for rules, _ in selected for rule in rules),
                max([self.min_delay] + [delay for _, delays in selected for delay in delays]))

    def _load(self, url, source):
        parts = urlsplit(url)
        robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
        try:
            for hop in range(self.max_redirects + 1):
                if not self._host_allowed(robots_url, source):
                    return Policy(self.clock() + self.ttl, "unavailable", "robots_host_not_allowed")
                self._wait(robots_url, self.min_delay)
                reply = self.session.get(robots_url, timeout=self.timeout, allow_redirects=False)
                try:
                    status = reply.status_code
                    if status in REDIRECTS:
                        location = reply.headers.get("location")
                        if not location or hop == self.max_redirects:
                            return Policy(self.clock() + self.ttl, "unavailable", "robots_redirect_limit")
                        robots_url = urljoin(robots_url, location)
                        continue
                    if status in (404, 410):
                        return Policy(self.clock() + self.ttl, "allowed", "allowed_absent")
                    if status in (401, 403):
                        return Policy(self.clock() + self.ttl, "rejected", "robots_denied")
                    if status != 200:
                        return Policy(self.clock() + self.ttl, "unavailable", "robots_http_error")
                    mime = reply.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    if mime and mime != "text/plain":
                        raise ValueError("Robots is not plain text")
                    rules, delay = self._parse(reply.content)
                    return Policy(self.clock() + self.ttl, "allowed", "allowed_rules", rules, delay)
                finally:
                    reply.close()
        except (requests.RequestException, ValueError, UnicodeError):
            return Policy(self.clock() + self.ttl, "unavailable", "robots_unavailable")

    def check(self, url, discovered_from=None):
        if self._host_allowed(url, discovered_from):
            url = requests.Request("GET", url).prepare().url
        if not self._host_allowed(url, discovered_from):
            decision = {"url": url, "outcome": "rejected", "reason": "host_not_allowed"}
        else:
            origin = self.origin(url)
            policy = self.cache.get(origin)
            if policy is None or policy.expires <= self.clock():
                policy = self._load(url, discovered_from or url)
                self.cache[origin] = policy
            self.cache.move_to_end(origin)
            while len(self.cache) > self.capacity:
                self.cache.popitem(last=False)
            outcome, reason = policy.outcome, policy.reason
            if outcome == "allowed":
                parsed = urlsplit(url)
                target = (parsed.path or "/") + ("?" + parsed.query if parsed.query else "")
                matches = [(length, allow) for regex, length, allow in policy.rules if regex.search(target)]
                if matches and not max(matches)[1]:
                    outcome, reason = "rejected", "robots_disallow"
            decision = {"url": url, "outcome": outcome, "reason": reason}
        self.events.append(decision)
        return decision

    def get(self, url, discovered_from=None, **kwargs):
        kwargs["allow_redirects"] = False
        kwargs.setdefault("timeout", self.timeout)
        for hop in range(self.max_redirects + 1):
            if self._host_allowed(url, discovered_from):
                url = requests.Request("GET", url).prepare().url
            decision = self.check(url, discovered_from)
            if decision["outcome"] != "allowed":
                raise CrawlPolicyError(decision["outcome"], decision["reason"], url)
            policy = self.cache[self.origin(url)]
            self._wait(url, policy.delay)
            reply = self.session.get(url, **kwargs)
            if reply.status_code not in REDIRECTS:
                return reply
            location = reply.headers.get("location")
            reply.close()
            if not location or hop == self.max_redirects:
                self.events.append({"url": url, "outcome": "unavailable", "reason": "redirect_limit"})
                raise CrawlPolicyError("unavailable", "redirect_limit", url)
            target = urljoin(url, location)
            discovered_from, url = url, target
