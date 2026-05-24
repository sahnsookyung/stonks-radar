from frw_api.services.job_queue import payload_hash


def test_payload_hash_is_stable():
    assert payload_hash({"b": 1, "a": 2}) == payload_hash({"a": 2, "b": 1})
