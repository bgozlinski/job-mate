"""Scrapy settings for the FR-7 harvester.

Every value here that looks like politeness is an obligation from NFR-5,
not a preference. The section that permits crawling at all lists the
conditions on which the permission rests, and states that it disappears
together with any one of them -- so these settings are the place where
those conditions stop being a declaration and become enforceable.

Two consequences are worth stating plainly. Nothing here may be relaxed
per spider to go faster; a spider that needs a different value needs a
decision recorded in the spec first. And importing this module requires a
complete environment, because the allowlist and the transfer limits are
read from Settings rather than duplicated -- the worker refusing to start
without configuration is the intended behaviour, not an inconvenience.
"""

from app.core.config import get_settings
from app.services.scraping import USER_AGENT as _JOBMATE_USER_AGENT

_settings = get_settings()

BOT_NAME = "jobmate"
SPIDER_MODULES = ["harvester.spiders"]
NEWSPIDER_MODULE = "harvester.spiders"

# One allowlist, two consumers (FR-7). A spider takes allowed_domains from
# here rather than hardcoding a host, so adding a site stays what NFR-5
# says it is: a decision plus a config entry, never a code change.
JOBMATE_ALLOWED_DOMAINS = list(_settings.scraper_allowed_hosts)

# Identify ourselves, with a contact address. NFR-5 forbids passing for a
# browser, so this is the same string the interactive path sends and it is
# imported rather than copied to keep it that way.
USER_AGENT = _JOBMATE_USER_AGENT

# --- What the site is allowed to tell us -----------------------------------

ROBOTSTXT_OBEY = True

# ROBOTSTXT_OBEY only filters forbidden paths; it does not apply
# Crawl-delay, and Scrapy has nothing that does. PolitenessMiddleware reads
# the directive and holds the slot at it, which is what lets NFR-5 claim
# robots.txt is decisive rather than merely consulted.
DOWNLOADER_MIDDLEWARES = {
    "harvester.middlewares.PolitenessMiddleware": 101,
}

# Bounds for the 429 handling in that middleware. A host may ask for any
# wait it likes; we honour it up to the first number and abandon the
# request past it, rather than wait a token amount and call that respect.
JOBMATE_MAX_RETRY_AFTER_SECONDS = 300.0
# What a 429 with no usable Retry-After costs. The header is missing, but
# the message -- you are asking too often -- is not.
JOBMATE_BLIND_RETRY_AFTER_SECONDS = 60.0

# --- Rate: one request at a time, per domain -------------------------------

CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 2.0

# Scrapy varies the delay by +-50% by default, which turns the floor into
# an average and lets half the requests arrive sooner than promised -- the
# same argument applies to a Crawl-delay the middleware installs. Zero, so
# DOWNLOAD_DELAY means what it says. (The older RANDOMIZE_DOWNLOAD_DELAY
# spelling still works but warns since 2.19.)
DOWNLOAD_DELAY_JITTER = 0.0

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 2.0
AUTOTHROTTLE_MAX_DELAY = 60.0

# Without this AutoThrottle targets its own default concurrency and will
# happily speed up past CONCURRENT_REQUESTS_PER_DOMAIN when the server
# answers quickly -- exactly the "we do not accelerate because the server
# is fast" line in NFR-5.
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

# 429 is deliberately missing from the retry list. Scrapy's default
# includes it and RetryMiddleware would resend the request without ever
# reading Retry-After, which is the opposite of what NFR-5 promises: being
# told to slow down and answering with more traffic. PolitenessMiddleware
# claims the code instead, waits for as long as the host asked, and only
# then retries.
RETRY_HTTP_CODES = [500, 502, 503, 504, 522, 524, 408]
RETRY_TIMES = 2

# --- Transfer limits, same numbers as the interactive path ------------------

DOWNLOAD_MAXSIZE = _settings.scraper_max_bytes
DOWNLOAD_WARNSIZE = _settings.scraper_max_bytes // 2
DOWNLOAD_TIMEOUT = _settings.scraper_timeout_seconds
REDIRECT_MAX_TIMES = _settings.scraper_max_redirects

# Conditional GET. A second pass over a board that has not changed costs a
# 304 per page instead of a full download -- the cheapest thing we can do
# for a host that lets us in, and the reason a frequent schedule is not
# automatically a rude one.
HTTPCACHE_ENABLED = True
HTTPCACHE_POLICY = "scrapy.extensions.httpcache.RFC2616Policy"
HTTPCACHE_DIR = "httpcache"
HTTPCACHE_GZIP = True

# --- Fuses: a run that goes wrong stops itself -----------------------------

# A misbehaving spider is the failure mode that costs someone else's
# bandwidth, so the limits are absolute rather than advisory. FR-7 wants a
# failing source to stop without taking the schedule down with it.
DEPTH_LIMIT = 3
CLOSESPIDER_ITEMCOUNT = 500
CLOSESPIDER_TIMEOUT = 1800
CLOSESPIDER_ERRORCOUNT = 10

# --- Everything else -------------------------------------------------------

# No cookie jar: we read public postings and have no session to keep.
# Content behind a login is out of scope by NFR-5, so accumulating cookies
# could only ever move us towards it.
COOKIES_ENABLED = False

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = "INFO"

# Staging pipeline lands here (FR-7): the spider writes rows, a separate
# asyncio step picks them up and calls the existing ingestion service.
ITEM_PIPELINES: dict[str, int] = {}
