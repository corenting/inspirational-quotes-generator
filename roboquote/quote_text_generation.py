"""Handle the generation of the quote."""
import json
import random
import re

import httpx
from loguru import logger

from roboquote import config, constants
from roboquote.entities.exceptions import CannotGenerateQuoteError
from roboquote.entities.text_model import TextModel


def _get_base_prompt_by_model(
    background_search_query: str, text_model: TextModel
) -> str:
    """Get base prompt by model"""
    if text_model == TextModel.BLOOM:
        prompts = [
            f"On a {background_search_query} themed picture, "
            + "there was a fitting inspirational quote: ",
            f"On a {background_search_query} themed inspirational picture, "
            + "there was a fitting inspirational short quote: ",
            f"On a {background_search_query} themed inspirational picture, "
            + "there was a fitting short quote: ",
        ]
    elif text_model == TextModel.MISTRAL_7B_INSTRUCT:
        prompts = [
            "<s>[INST] Give me a inspirational quote "
            + f"that fits a {background_search_query} themed picture, "
            + "similar to old Tumblr pictures. Give me the quote text "
            + "without any surrounding text. Do not return lists. "
            + "The quote must be in english. "
            + "The quote must exactly one sentence.[/INST]"
        ]
    else:
        raise ValueError("model not supported")

    return random.choice(prompts)


def _get_random_prompt(background_search_query: str, text_model: TextModel) -> str:
    """Get a random prompt for the model."""

    prompt = _get_base_prompt_by_model(background_search_query, text_model)

    # Randomly replace "picture" with "photography"
    if random.randint(0, 1) == 0:
        prompt = prompt.replace("picture", "photography")

    return prompt


def _cleanup_text(generated_text: str) -> str:
    """Cleanup the text generated by the model.

    Remove quotes, and limit the text to the first sentence.
    """
    logger.debug(f'Cleaning up quote: "{generated_text}"')

    cleaned_quote = generated_text.strip()

    # If the model generated a quoted text, get text inside quote
    # Get the longest string in case we match some smaller fragments
    # of text.
    regex_quotes_list = r"\"\“\«\”"
    regex_results = re.findall(
        rf"[{regex_quotes_list}]*([^{regex_quotes_list}]+)[{regex_quotes_list}]*",
        cleaned_quote,
    )
    if len(regex_results) > 0:
        cleaned_quote = max(regex_results, key=len)

    # Remove other lines if multiple lines
    cleaned_quote = cleaned_quote.partition("\n")[0]

    logger.debug(f"Cleaned quote: {cleaned_quote}")
    return cleaned_quote


async def get_random_quote(background_search_query: str, text_model: TextModel) -> str:
    """For a given background category, get a random quote."""
    prompt = _get_random_prompt(background_search_query, text_model)
    logger.debug(f'Prompt for model: "{prompt}"')

    headers = {
        "Authorization": f"Bearer {config.HUGGING_FACE_API_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": 50,
            "do_sample": True,
        },
        "options": {
            "use_cache": False,
        },
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            constants.HUGGING_FACE_BASE_API_URL + text_model.value,
            headers=headers,
            json=data,
        )

    try:
        response_content = json.loads(response.content.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise CannotGenerateQuoteError() from e

    # Error case with error message
    if not response.is_success:
        raise CannotGenerateQuoteError(
            response_content.get("error", "Unknown error from Hugging Face.")
        )

    text: str = response_content[0]["generated_text"]
    text = text.replace(prompt, "")

    return _cleanup_text(text)
