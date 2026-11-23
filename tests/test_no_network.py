import asyncio

import pytest

from server.openrouter_client import request_chat_completion


def test_openrouter_is_unreachable_from_tests():
    """Even with an API key, the real OpenRouter client cannot send a request."""
    with pytest.raises(RuntimeError, match="Network access is disabled"):
        asyncio.run(
            request_chat_completion(
                model="any/model",
                messages=[{"role": "user", "content": "hi"}],
                api_key="test-key",
            )
        )
