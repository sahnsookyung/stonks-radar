from frw_api.services.ingestion_pipeline import _observation_timestamp


def test_bls_monthly_observation_timestamp():
    timestamp = _observation_timestamp({"year": "2026", "period": "M05"})
    assert timestamp.year == 2026
    assert timestamp.month == 5
    assert timestamp.day == 1
