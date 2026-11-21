"""What a search engine reads: robots.txt, sitemap.xml and the head of index.html.

Vite copies ui/public/ to the root of the build unchanged and keeps index.html's head, so
these source files are what the site serves. CI does not build the UI, so the tests read
the sources.

robots.txt is checked the way Google and Bing read it (RFC 9309): the longest matching
rule wins, Allow wins a tie, `*` matches anything and a trailing `$` anchors the end. The
paths that must be allowed come from the UI's own fetch() calls, so a new fetch on page
load that robots.txt does not allow fails here.
"""
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
UI = REPO / "ui"
PUBLIC = UI / "public"
SITE = "https://firstchair.live/"

# Values the UI fills into its fetch URLs on first load.
SAMPLE_ARGS = {"routeId": "redmond-stevens-eb", "hours": "24"}

# API paths the page never calls; they stay disallowed.
MUST_STAY_BLOCKED = [
    "/api/",
    "/api/health",
    "/api/internal/health",
    "/api/current/redmond-stevens-eb",
    "/api/history/redmond-stevens-eb?hours=24",
    "/api/weather/791",
    "/api/docs",
    "/api/openapi.json",
    "/api/routes/extra",
    "/api/weather/current/extra",
]

OLD_ROBOTS = "User-agent: *\nDisallow: /api/\n"


def parse_robots(text):
    """The (allow, pattern) rules of the `User-agent: *` group, and the Sitemap URLs."""
    rules, sitemaps, agents, in_star = [], [], [], False
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        field, value = (part.strip() for part in line.split(":", 1))
        field = field.lower()
        if field == "user-agent":
            agents.append(value)
            in_star = value == "*"
        elif field == "sitemap":
            sitemaps.append(value)
        elif field in ("allow", "disallow") and in_star and value:
            rules.append((field == "allow", value))
    # One group for every crawler alike: a crawler-specific group would need its own reading.
    assert agents == ["*"], f"User-agent lines: {agents}"
    return rules, sitemaps


def allowed(rules, url):
    """RFC 9309 matching of a path plus query."""
    best = None  # (pattern length, allow)
    for allow, pattern in rules:
        anchored = pattern.endswith("$")
        body = pattern[:-1] if anchored else pattern
        regex = ".*".join(re.escape(part) for part in body.split("*")) + ("$" if anchored else "")
        if re.match(regex, url):
            key = (len(pattern), allow)
            if best is None or key > best:
                best = key
    return True if best is None else best[1]


def first_load_api_urls():
    """Every fetch() URL in ui/src, with its ${...} placeholders filled in."""
    urls, calls = [], 0
    sources = (p for p in (UI / "src").rglob("*") if p.suffix in (".js", ".jsx", ".ts", ".tsx"))
    for src in sorted(sources):
        text = src.read_text()
        calls += len(re.findall(r"\bfetch\(", text))
        for template in re.findall(r"fetch\(`\$\{API_BASE_URL\}(/[^`]*)`", text):
            def fill(m):
                assert m.group(1) in SAMPLE_ARGS, f"{src.name}: no sample value for ${{{m.group(1)}}}"
                return SAMPLE_ARGS[m.group(1)]
            urls.append("/api" + re.sub(r"\$\{(\w+)\}", fill, template))
    # A fetch written another way would slip past the regex: count them all.
    assert calls == len(urls), f"{calls} fetch() calls in ui/src, {len(urls)} parsed"
    return urls


@pytest.fixture(scope="module")
def robots():
    return parse_robots((PUBLIC / "robots.txt").read_text())


def test_matcher_longest_rule_wins():
    rules, _ = parse_robots("User-agent: *\nAllow: /a/b$\nAllow: /a/c\nDisallow: /a/\n")
    assert allowed(rules, "/a/b")
    assert not allowed(rules, "/a/b/x")
    assert allowed(rules, "/a/c?x=1")
    assert not allowed(rules, "/a/d")
    assert allowed(rules, "/other")
    rules, _ = parse_robots("User-agent: *\nDisallow: /t\nAllow: /t\nAllow: /s/*/x$\nAllow: /q?a\nDisallow: /\n")
    assert allowed(rules, "/t")  # a tie goes to Allow
    assert allowed(rules, "/s/any/x") and not allowed(rules, "/s/any/y")
    assert allowed(rules, "/q?a=1") and not allowed(rules, "/qa")  # ? is literal


def test_ui_fetches_the_five_first_load_paths():
    assert sorted(first_load_api_urls()) == sorted([
        "/api/routes",
        "/api/current",
        "/api/weather/current",
        "/api/segments/redmond-stevens-eb?hours=24",
        "/api/weather/history?hours=24",
    ])


def test_tripwire_old_robots_blocks_the_page_data():
    """Positive control: the robots.txt this replaced blocked every API read the page makes."""
    rules, _ = parse_robots(OLD_ROBOTS)
    assert [url for url in first_load_api_urls() if allowed(rules, url)] == []


def test_robots_allows_every_api_read_the_page_makes(robots):
    rules, _ = robots
    assert [url for url in first_load_api_urls() if not allowed(rules, url)] == []
    assert allowed(rules, "/")


def test_robots_keeps_the_rest_of_the_api_blocked(robots):
    rules, _ = robots
    assert [url for url in MUST_STAY_BLOCKED if allowed(rules, url)] == []


def test_robots_names_the_sitemap(robots):
    _, sitemaps = robots
    assert sitemaps == [SITE + "sitemap.xml"]


def test_sitemap_lists_the_page_and_no_api_url():
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.parse(PUBLIC / "sitemap.xml").getroot()
    assert root.tag == "{%s}urlset" % ns["sm"]
    assert [loc.text for loc in root.findall("sm:url/sm:loc", ns)] == [SITE]


class Head(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.links, self.scripts, self.styled = {}, {}, [], []
        self.text = {"title": "", "noscript": ""}
        self.handlers, self.urls = [], []
        self.open = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.open.add(tag)
        self.handlers += [f"{tag} {k}" for k in a if k.startswith("on")]
        if a.get("rel") != "canonical":
            self.urls += [a[k] for k in ("src", "href") if k in a]
        if "style" in a or tag == "style":
            self.styled.append(tag)
        if tag == "meta" and ("name" in a or "property" in a):
            self.meta[a.get("name") or a.get("property")] = a.get("content", "")
        elif tag == "link":
            self.links[a["rel"]] = a["href"]
        elif tag == "script":
            self.scripts.append(a)

    def handle_endtag(self, tag):
        self.open.discard(tag)

    def handle_data(self, data):
        for tag in self.text:
            if tag in self.open:
                self.text[tag] += data


@pytest.fixture(scope="module")
def head():
    parser = Head()
    parser.feed((UI / "index.html").read_text())
    return parser


def test_index_says_what_the_site_is(head):
    assert "Stevens Pass" in head.text["title"]
    for key in ("description", "og:title", "og:description", "twitter:title", "twitter:description"):
        assert "Stevens Pass" in head.meta.get(key, ""), key
    assert "Stevens Pass" in head.text["noscript"]


def test_index_canonical_and_card_tags(head):
    assert head.links["canonical"] == SITE
    assert head.meta["og:url"] == SITE
    assert head.meta["og:type"] == "website"
    assert head.meta["twitter:card"] == "summary"


def test_index_needs_no_csp_change(head):
    """The CSP is default-src 'self' with no inline script or style: every script has a
    src on this origin, no tag carries a style or an on* handler, every src and href but the
    canonical is a path on this origin, and the icon is a file the build ships."""
    assert head.scripts and all(s.get("src") for s in head.scripts)
    assert head.urls and [u for u in head.urls if not u.startswith("/") or u.startswith("//")] == []
    assert head.styled == [] and head.handlers == []
    icon = head.links["icon"]
    assert icon.startswith("/") and (PUBLIC / icon.lstrip("/")).is_file()
