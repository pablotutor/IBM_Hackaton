"""
Recursos compartidos entre tools: paths y singletons de modelo de embeddings.
Usamos sentence-transformers directamente (sin ChromaDB) para máxima estabilidad.
"""
import os
# Necesario antes de importar PyTorch/tokenizers en macOS (evita segfault con fork)
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from pathlib import Path

PROJECT_ROOT   = Path(__file__).parent.parent
DATA_SYNTHETIC = PROJECT_ROOT / "data" / "synthetic"

import threading

_sentence_model = None
_init_lock      = threading.Lock()   # solo para la inicialización del modelo


def get_model():
    """Singleton thread-safe: el lock solo protege la carga inicial del modelo."""
    global _sentence_model
    if _sentence_model is None:
        with _init_lock:
            if _sentence_model is None:
                from sentence_transformers import SentenceTransformer
                _sentence_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _sentence_model


def embed(texts: list[str]) -> "np.ndarray":
    """Embeddings normalizados. encode() de sentence-transformers es thread-safe."""
    import numpy as np
    vecs = get_model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.array(vecs, dtype="float32")


def cosine_top_k(query_vec, corpus_vecs, k: int):
    """
    Retorna índices y scores de los k documentos más similares.
    query_vec y corpus_vecs deben estar normalizados.
    """
    import numpy as np
    scores = corpus_vecs @ query_vec  # dot product = cosine similarity (normalizado)
    top_idx = np.argsort(scores)[::-1][:k]
    return top_idx, scores[top_idx]
