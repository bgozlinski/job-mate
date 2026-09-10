"""Scrapy settings for the FR-7 harvester."""

from app.core.config import get_settings
from app.services.scraping import USER_AGENT as _JOBMATE_USER_AGENT

_settings = get_settings()

BOT_NAME = "jobmate"
SPIDER_MODULES = ["harvester.spiders"]
NEWSPIDER_MODULE = "harvester.spiders"

JOBMATE_ALLOWED_DOMAINS = list(_settings.scraper_allowed_hosts)

USER_AGENT = _JOBMATE_USER_AGENT


ROBOTSTXT_OBEY = True

DOWNLOADER_MIDDLEWARES = {
    "harvester.middlewares.PolitenessMiddleware": 101,
}

JOBMATE_MAX_RETRY_AFTER_SECONDS = 300.0
JOBMATE_BLIND_RETRY_AFTER_SECONDS = 60.0


CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 2.0

DOWNLOAD_DELAY_JITTER = 0.0

AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 2.0
AUTOTHROTTLE_MAX_DELAY = 60.0

AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0

RETRY_HTTP_CODES = [500, 502, 503, 504, 522, 524, 408]
RETRY_TIMES = 2


DOWNLOAD_MAXSIZE = _settings.scraper_max_bytes
DOWNLOAD_WARNSIZE = _settings.scraper_max_bytes // 2
DOWNLOAD_TIMEOUT = _settings.scraper_timeout_seconds
REDIRECT_MAX_TIMES = _settings.scraper_max_redirects

HTTPCACHE_ENABLED = True
HTTPCACHE_POLICY = "scrapy.extensions.httpcache.RFC2616Policy"
HTTPCACHE_DIR = "httpcache"
HTTPCACHE_GZIP = True


DEPTH_LIMIT = 3
CLOSESPIDER_ITEMCOUNT = 500
CLOSESPIDER_TIMEOUT = 1800
CLOSESPIDER_ERRORCOUNT = 10


COOKIES_ENABLED = False

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = "INFO"

ITEM_PIPELINES = {
    "harvester.pipelines.StagingPipeline": 300,
}
