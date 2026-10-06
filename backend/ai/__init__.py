"""Provider-agnostic access to the generative LLM and to the embedding model.

Application code imports only `get_chat_provider` and `get_embedding_provider` (and the
protocols/errors in `base`). Which concrete provider sits behind them is configuration, never code.
"""

from .base import (
    AIError,
    AIUnavailableError,
    AuthError,
    ChatMessage,
    ChatProvider,
    ChatResult,
    EmbeddingProvider,
    ModelNotLoadedError,
)
from .factory import get_chat_provider, get_embedding_provider, get_vision_provider

__all__ = [
    "AIError",
    "AIUnavailableError",
    "AuthError",
    "ChatMessage",
    "ChatProvider",
    "ChatResult",
    "EmbeddingProvider",
    "ModelNotLoadedError",
    "get_chat_provider",
    "get_embedding_provider",
    "get_vision_provider",
]
