from openai import OpenAI

from app.config import settings

openai_client = OpenAI(api_key=settings.openai_api_key)


def generate(
    system_prompt: str,
    user_message: str,
    model: str | None = None,
    temperature: float = 0.0,
) -> dict:
    """Call the OpenAI chat completions API with a system/user message pair.

    Defaults to `settings.llm_model_answer` when `model` is not given.
    Returns a dict with the response text under "text" (empty string if the
    model returned no content) and a token "usage" breakdown
    (prompt/completion/total, each 0 if usage metadata is unavailable).
    """
    response = openai_client.chat.completions.create(
        model=model or settings.llm_model_answer,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )

    return {
        "text": response.choices[0].message.content or "",
        "usage": {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            "total_tokens": response.usage.total_tokens if response.usage else 0,
        },
    }


def generate_with_json(
    system_prompt: str,
    user_message: str,
    model: str | None = None,
    temperature: float = 0.0,
) -> dict:
    """Call the OpenAI chat completions API with JSON response mode enabled.

    Like `generate`, but forces `response_format={"type": "json_object"}` so
    the model returns valid JSON, and defaults to `settings.llm_model_grader`
    when `model` is not given. Returns the same `{"text", "usage"}` shape;
    the caller is responsible for parsing the "text" field as JSON.
    """
    response = openai_client.chat.completions.create(
        model=model or settings.llm_model_grader,
        temperature=temperature,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )

    return {
        "text": response.choices[0].message.content or "",
        "usage": {
            "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
            "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            "total_tokens": response.usage.total_tokens if response.usage else 0,
        },
    }
