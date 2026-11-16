"""Test-only HTTP fixtures for the real installed OpenAI SDK."""

import json


def response_payload(name, arguments, index=0, model="test-model", details=None):
    return {
        "id": f"resp_test_{index}",
        "object": "response",
        "created_at": 1,
        "status": "completed",
        "model": model,
        "output": [
            {
                "id": f"fc_{index}",
                "type": "function_call",
                "status": "completed",
                "name": name,
                "call_id": f"call_{index}",
                "arguments": json.dumps(arguments),
            }
        ],
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "total_tokens": 150,
            "input_tokens_details": details or {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 10},
        },
        "parallel_tool_calls": False,
        "tools": [],
        "tool_choice": "required",
    }
