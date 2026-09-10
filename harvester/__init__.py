"""Scrapy project behind FR-7: the scheduled harvester of job postings.

This package runs in the worker process only. FastAPI never imports it,
because importing Scrapy starts pulling in Twisted and the application
serves requests on an asyncio loop; FR-7 keeps the two runtimes apart and
lets them meet on staged data instead of on calls.

The interactive URL path from FR-1 is a different thing entirely and stays
on httpx in app/services/scraping.py. What the two share is the allowlist:
both read SCRAPER_ALLOWED_HOSTS, so a host is permitted once, in one place.
"""
