"""Local embeddings via fastembed (ONNX, no PyTorch) to stay light on the 2 GB server."""

from functools import lru_cache
from typing import Protocol

import numpy as np

from app.config import get_settings


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedder:
    def __init__(self, model_name: str):
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]


@lru_cache
def get_embedder() -> Embedder:
    return FastEmbedder(get_settings().embedding_model)


def mean_vector(vectors: list[list[float]]) -> list[float]:
    """Unit-normalized mean, so it stays comparable under cosine distance."""
    mean = np.mean(np.array(vectors), axis=0)
    norm = np.linalg.norm(mean)
    return (mean / norm).tolist() if norm else mean.tolist()
