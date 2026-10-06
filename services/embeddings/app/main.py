"""A minimal OpenAI-compatible embedding server around sentence-transformers.

It exists so the default setup has a local, multilingual embedding model with no cloud dependency,
behind the same `/v1/embeddings` contract the backend would use for any other provider. Replacing
it (with Unsloth Studio's own endpoint, or a cloud API) is a configuration change in the backend.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Annotated, Protocol

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

MODEL_NAME = os.getenv(
    "EMBEDDINGS_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
# Optional bearer token. Unset means no authentication (the port is bound to localhost).
API_KEY = os.getenv("EMBEDDINGS_API_KEY") or None


class Encoder(Protocol):
    def encode(self, texts: list[str]) -> list[list[float]]: ...


class SentenceTransformerEncoder:
    def __init__(self, model_name: str) -> None:
        # Imported here: torch is slow to import and tests replace the encoder entirely.
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> list[list[float]]:
        # Normalized, so cosine similarity equals the inner product on the backend side.
        return self._model.encode(texts, normalize_embeddings=True).tolist()


@lru_cache(maxsize=1)
def get_encoder() -> Encoder:
    return SentenceTransformerEncoder(MODEL_NAME)


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str | None = None


app = FastAPI(title="mymenu embeddings")


def _check_auth(authorization: str | None) -> None:
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="Not authenticated")


@app.get("/health")
def health() -> dict[str, object]:
    return {"ok": True, "model": MODEL_NAME}


@app.get("/ready")
def ready(encoder: Annotated[Encoder, Depends(get_encoder)]) -> dict[str, object]:
    """Loads the model if needed and embeds one word: OK only once embeddings really work."""
    encoder.encode(["ready"])
    return {"ok": True, "model": MODEL_NAME}


@app.get("/v1/models")
def models() -> dict[str, object]:
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model", "loaded": True}]}


@app.post("/v1/embeddings")
def embeddings(
    request: EmbeddingRequest,
    encoder: Annotated[Encoder, Depends(get_encoder)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    _check_auth(authorization)
    if request.model and request.model != MODEL_NAME:
        raise HTTPException(
            status_code=404,
            detail=f"This server only serves '{MODEL_NAME}', not '{request.model}'.",
        )
    texts = [request.input] if isinstance(request.input, str) else request.input
    vectors = encoder.encode(texts) if texts else []
    return {
        "object": "list",
        "model": MODEL_NAME,
        "data": [
            {"object": "embedding", "index": index, "embedding": vector}
            for index, vector in enumerate(vectors)
        ],
    }
