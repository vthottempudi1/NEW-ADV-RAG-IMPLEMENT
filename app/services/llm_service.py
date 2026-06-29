from openai import OpenAI

from app.config import settings


openai_client = OpenAI(api_key=settings.openai_api_key)


def generate(
    system_prompt: str,
    user_message: str,
    model: str | None = None,
    temperature: float = 0.0,
) -> dict:
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
    }