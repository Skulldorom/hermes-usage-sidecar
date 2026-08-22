from hermes_usage_sidecar.delta import event_id

def test_event_id_changes_across_subsecond_updates_to_same_aggregate():
    key = "same-aggregate"
    assert event_id(key, 42.100001, {"input_tokens": 100}) != event_id(key, 42.900001, {"input_tokens": 200})

def test_event_id_same_payload_refetch_is_idempotent():
    assert event_id("k", 42.123456, {"input_tokens": 100}) == event_id("k", "42.123456", {"input_tokens": 100})

def test_event_id_includes_snapshot_not_just_timestamp():
    assert event_id("k", 42.123456, {"input_tokens": 100}) != event_id("k", 42.123456, {"input_tokens": 101})
