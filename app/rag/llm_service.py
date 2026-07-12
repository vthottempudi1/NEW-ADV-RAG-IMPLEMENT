from openai import OpenAI

from app.config import settings

openai_client = OpenAI(api_key=settings.openai_api_key)


# Learner note: Encapsulates generate so this responsibility can be understood, tested, and changed independently.
def generate(
    system_prompt: str,
    user_message: str,
    model: str | None = None,
    temperature: float = 0.0,
) -> dict:
    """Perform generate for the retrieval-augmented generation pipeline.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
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


# Learner note: Produces generate with json at a dedicated model boundary so output handling remains testable.
def generate_with_json(
    system_prompt: str,
    user_message: str,
    model: str | None = None,
    temperature: float = 0.0,
) -> dict:
    """Perform generate with json for the retrieval-augmented generation pipeline.

    Learner Note:
        This function keeps the responsibility explicit for callers, tests, and operators.
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
