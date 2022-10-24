"""Handle the generation of the quote."""
import json
import random
import re

import nltk
import requests
from loguru import logger

from roboquote import config, constants


def _get_random_prompt(background_search_query: str) -> str:
    """Get a random prompt for the model."""
    prompts = [
        f"On a picture of a {background_search_query}, I write an inspirational quote such as:",
        f"On a inspirational picture of a {background_search_query}, I write an inspirational short quote such as:",
        f"On a inspirational picture of a {background_search_query}, I write a short quote such as:",
    ]

    prompt = random.choice(prompts)

    # Randomly replace picture with photography
    if random.randint(0, 1) == 0:
        prompt = prompt.replace("picture", "photography")

    # Randomly replace such as with like
    if random.randint(0, 1) == 0:
        prompt = prompt.replace("such as", "like")

    # Add random amount of space in the end
    prompt = prompt + (" " * random.randint(0, 1))

    return prompt


def _cleanup_text(generated_text: str) -> str:
    """Cleanup the text generated by the model.

    Remove quotes, and limit the text to the first sentence.
    """
    logger.debug(f'Cleaning up quote: "{generated_text}"')

    # If the model generated a quoted text, get it directly
    quoted_text = re.findall(r'["“«](.*?)["”»]', generated_text)
    if len(quoted_text) > 0:
        logger.debug(f'Cleaned up quote is: "{quoted_text[0]}"')
        return quoted_text[0]

    # Else tokenize the text and get the first sentence
    try:
        nltk.data.find("tokenizers/punkt")
    except LookupError:
        nltk.download("punkt")
        print("Missing data downloaded, please relaunch.")
    text = nltk.sent_tokenize(generated_text)[0].strip()

    logger.debug(f'Cleaned up quote is: "{text}"')
    return text


def get_random_quote(background_search_query: str) -> str:
    """For a given background category, get a random quote."""
    headers = {"Authorization": f"Bearer {config.HUGGING_FACE_API_TOKEN}"}
    prompt = _get_random_prompt(background_search_query)
    logger.debug(f'Prompt for model: "{prompt}"')
    data = json.dumps(prompt)

    response = requests.request(
        "POST", constants.HUGGING_FACE_API_URL, headers=headers, data=data
    )
    response_content = json.loads(response.content.decode("utf-8"))

    text: str = response_content[0]["generated_text"]
    text = text.replace(prompt, "")

    return _cleanup_text(text)
