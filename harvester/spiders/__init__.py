"""Spiders for the FR-7 harvester.

Empty on purpose: stage 7 has the settings and the fuses, not yet a
spider. SPIDER_MODULES points here, so the package has to exist for
`scrapy list` to answer at all.

A spider added here takes its allowed_domains from
JOBMATE_ALLOWED_DOMAINS and overrides none of the rate or size settings
(harvester/settings.py explains why).
"""
