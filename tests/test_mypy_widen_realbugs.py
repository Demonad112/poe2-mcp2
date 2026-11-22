"""Regression tests for real bugs surfaced by widening mypy to all of src/."""

from src.config import Settings


def test_settings_has_poe2db_base_url():
    # PoE2DataScraper.__init__ read settings.POE2DB_BASE_URL, which did not exist
    assert Settings().POE2DB_BASE_URL.startswith("https://poe2db")


def test_scraper_constructs():
    from src.utils.scraper import PoE2DataScraper

    scraper = PoE2DataScraper()
    assert scraper.base_url == Settings().POE2DB_BASE_URL
