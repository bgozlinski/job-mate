"""Spiders for the FR-7 harvester.

One so far: FeedSpider, for a source registered as kind='feed'. NFR-5 ranks
the three forms -- API, feed, crawl -- and says crawling is the last resort
for a site that offers nothing else, so the feed reader is the one that had
to exist first.

A spider added here takes its allowed_domains from JOBMATE_ALLOWED_DOMAINS,
is handed its source_id and endpoint by whatever launches it, and overrides
none of the rate or size settings (harvester/settings.py explains why).
"""

from harvester.spiders.feed import FeedSpider

__all__ = ["FeedSpider"]
