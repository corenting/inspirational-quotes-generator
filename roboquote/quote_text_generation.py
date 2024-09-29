"""Handle the generation of the quote."""

import json
import random
import re

import httpx
from loguru import logger

from roboquote import config
from roboquote.entities.exceptions import CannotGenerateQuoteError
from roboquote.entities.large_language_model import (
    LargeLanguageModel,
    LargeLanguageModelAPI,
    LargeLanguageModelPromptType,
)

PROMPT_CONTINUE = [
    "On a {background_search_query} themed picture, "
    + "there was a fitting inspirational quote: ",
    "On a {background_search_query} themed inspirational picture, "
    + "there was a fitting inspirational short quote: ",
    "On a {background_search_query} themed inspirational picture, "
    + "there was a fitting short quote: ",
]

PROMPT_CHAT = [
    "Give me a inspirational quote "
    + "that fits on a {background_search_query} themed picture, "
    + "similar to old Tumblr pictures. You must return the quote text directly."
    + "Do not return lists. "
    + "The quote must be in english. "
    + "The quote must exactly one sentence."
]


def _get_base_prompt_by_model(
    background_search_query: str, text_model: LargeLanguageModel
) -> str:
    """Get base prompt by model"""
    if text_model.prompt_type == LargeLanguageModelPromptType.CONTINUE:
        prompts = PROMPT_CONTINUE
    elif text_model.prompt_type == LargeLanguageModelPromptType.CHAT:
        prompts = [
            f"{text_model.prompt_start}{prompt}{text_model.prompt_end}"
            for prompt in PROMPT_CHAT
        ]
    else:
        raise ValueError("prompt type not supported")

    return random.choice(prompts).format(
        background_search_query=background_search_query
    )


def _get_random_prompt(
    background_search_query: str, text_model: LargeLanguageModel
) -> str:
    """Get a random prompt for the model."""

    prompt = _get_base_prompt_by_model(background_search_query, text_model)

    # Randomly replace "picture" with "photography"
    if random.randint(0, 1) == 0:
        prompt = prompt.replace("picture ", "photography ")
        prompt = prompt.replace("picture,", "photography,")
        prompt = prompt.replace("picture.", "photography.")

    return prompt


def _cleanup_text(generated_text: str) -> str:
    """Cleanup the text generated by the model.

    Remove quotes, and limit the text to the first sentence.
    """
    logger.debug(f'Cleaning up quote: "{generated_text}"')

    cleaned_quote = generated_text.strip()
    regex_quotes_list = r"\"\“\«\”"

    # First, if we match only one quote, return this one
    single_quote_regex = (
        rf"[{regex_quotes_list}]([^{regex_quotes_list}]*)[{regex_quotes_list}]"
    )
    single_quote_results = re.findall(single_quote_regex, cleaned_quote)
    if len(single_quote_results) == 1:
        cleaned_quote = single_quote_results[0]
    else:
        # Else, if the model generated a quoted text, try to get text inside quote.
        # Get the longest string in case we match some smaller fragments of text.
        built_regex = (
            rf"[{regex_quotes_list}]*([^{regex_quotes_list}]+)[{regex_quotes_list}]*"
        )
        regex_results = re.findall(
            built_regex,
            cleaned_quote,
        )
        if len(regex_results) > 0:
            cleaned_quote = max(regex_results, key=len)

        # Remove other lines if multiple lines
        cleaned_quote = cleaned_quote.partition("\n")[0]

    logger.debug(f"Cleaned quote: {cleaned_quote}")
    return cleaned_quote


async def _get_quote_from_hugging_face(model: LargeLanguageModel, prompt: str) -> str:
    """
    Get a quote using Hugging Face for the given model and prompt.
    """
    headers = {
        "Authorization": f"Bearer {config.HUGGING_FACE_ACCESS_TOKEN}",
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
        try:
            response = await client.post(
                f"https://api-inference.huggingface.co/models/{model.name}",
                headers=headers,
                json=data,
                timeout=15,
            )
        except httpx.TimeoutException as e:
            raise CannotGenerateQuoteError(
                "Timeout when calling Hugging Face API"
            ) from e

    # Error case with error message
    if not response.is_success:
        error = "Unknown error"
        try:
            error: str = response.json()["error"]
        except (KeyError, json.JSONDecodeError):
            error = response.reason_phrase
        finally:
            raise CannotGenerateQuoteError(
                f'Error when calling Hugging Face API: "{error}"'
            )

    try:
        response_content = json.loads(response.content.decode("utf-8"))
        logger.debug(
            f"Hugging Face response {response.status_code}: {response_content}"
        )
    except json.JSONDecodeError as e:
        raise CannotGenerateQuoteError() from e

    text: str = response_content[0]["generated_text"]
    text = text.replace(prompt, "")
    return text


async def _get_quote_from_groq_cloud(model: LargeLanguageModel, prompt: str):
    """
    Get a quote using GroqCloud for the given model and prompt.
    """
    headers = {
        "Authorization": f"Bearer {config.GROQ_CLOUD_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {"messages": [{"role": "user", "content": prompt}], "model": model.name}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=15,
            )
        except httpx.TimeoutException as e:
            raise CannotGenerateQuoteError("Timeout when calling GroqCloud API") from e

    # Error case with error message
    if not response.is_success:
        error = "Unknown error"
        try:
            error: str = response.json()["error"]
        except (KeyError, json.JSONDecodeError):
            error = response.reason_phrase
        finally:
            raise CannotGenerateQuoteError(
                f'Error when calling GroqCloud API: "{error}"'
            )

    try:
        response_content = json.loads(response.content.decode("utf-8"))
        logger.debug(
            f"GroqCloud API response {response.status_code}: {response_content}"
        )
    except json.JSONDecodeError as e:
        raise CannotGenerateQuoteError() from e

    text: str = response_content["choices"][0]["message"]["content"]
    return text


async def get_random_quote(
    background_search_query: str, text_model: LargeLanguageModel
) -> str:
    """For a given background category, get a random quote."""
    prompt = _get_random_prompt(background_search_query, text_model)
    logger.debug(f'Prompt for {text_model.name}: "{prompt}"')

    if text_model.api == LargeLanguageModelAPI.HUGGING_FACE:
        text = await _get_quote_from_hugging_face(text_model, prompt)
    elif text_model.api == LargeLanguageModelAPI.GROQ_CLOUD:
        text = await _get_quote_from_groq_cloud(text_model, prompt)
    else:
        raise ValueError("API not supported")

    return _cleanup_text(text)
