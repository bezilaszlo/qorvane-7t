import httpx


def test_health(client: httpx.Client) -> None:
    assert client.get("/health").status_code == 200


def test_ready(client: httpx.Client) -> None:
    assert client.get("/ready").status_code == 200
