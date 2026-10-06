from fastapi.testclient import TestClient

from app import main


class FakeEncoder:
    def encode(self, texts):
        return [[float(len(t)), 0.0] for t in texts]


main.app.dependency_overrides[main.get_encoder] = FakeEncoder
client = TestClient(main.app)


def test_embeddings_follow_the_openai_shape():
    response = client.post("/v1/embeddings", json={"input": ["ab", "abc"]})
    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["index"] for item in data] == [0, 1]
    assert data[1]["embedding"] == [3.0, 0.0]


def test_single_string_input_is_accepted():
    assert len(client.post("/v1/embeddings", json={"input": "x"}).json()["data"]) == 1


def test_other_models_are_refused():
    assert client.post("/v1/embeddings", json={"input": "x", "model": "other"}).status_code == 404


def test_api_key_is_enforced_when_set(monkeypatch):
    monkeypatch.setattr(main, "API_KEY", "secret")
    assert client.post("/v1/embeddings", json={"input": "x"}).status_code == 401
    ok = client.post(
        "/v1/embeddings", json={"input": "x"}, headers={"Authorization": "Bearer secret"}
    )
    assert ok.status_code == 200


def test_ready_means_the_model_answers():
    assert client.get("/ready").json() == {"ok": True, "model": main.MODEL_NAME}
