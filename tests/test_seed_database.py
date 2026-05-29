from scripts import seed_database


def test_data_source_types_match_database_constraint():
    allowed = {
        "official_api",
        "official_page",
        "company_ir",
        "company_email",
        "filing",
        "rss",
        "news_metadata",
        "public_web",
        "manual",
        "user_clip",
        "aggregator",
        "market_data",
        "llm_provider",
    }

    invalid = [source for source in seed_database.DATA_SOURCES if source[2] not in allowed]

    assert invalid == []
