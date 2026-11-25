from app.schemas import ReadingsBatch


def test_batch_model_accepts_minimal_payload():
    batch = ReadingsBatch.model_validate(
        {"readings": [{"sensor_id": "sensor-1", "metrics": {"temperature": 21.3}}]}
    )
    assert batch.readings[0].metrics == {"temperature": 21.3}
