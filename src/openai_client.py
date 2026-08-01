"""OpenAI API client wrappers: transcribe, summarize, keyword extraction,
and image generation.

All functions accept simple in/out types and do NOT touch the GUI directly
(progress updates are opt-in via a callback).
"""

from __future__ import annotations

import logging
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Tuple

import openai

from src.config import (
    IMAGE_MODIFIERS,
    PROMPT_FOR_ABSTRACTION,
    gw,
)

logger = logging.getLogger(__name__)
loggerTrace = logging.getLogger("Prompts")


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

def transcribe_audio(wav_path: str) -> str:
    """Transcribe *wav_path* using OpenAI Whisper, return the text."""
    logger.info("Transcribing...")
    with open(wav_path, "rb") as audio_file:
        response = openai.audio.translations.create(
            model="whisper-1",
            file=audio_file,
        )

    loggerTrace.debug("Transcript object: %s", response)
    transcript: str = response.text.rstrip(".")
    loggerTrace.debug("Transcript text: %s", transcript)

    logger.info("Transcript: %s", transcript)
    return transcript


# ---------------------------------------------------------------------------
# Summarisation
# ---------------------------------------------------------------------------

def summarize_text(text: str) -> str:
    """Summarise *text* using GPT-4o-mini, return the summary."""
    logger.info("Summarising...")
    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "user",
             "content": f"Please summarize the following text:\n{text}"},
        ],
    )
    loggerTrace.debug("responseSummary: %s", response)

    summary: str = response.choices[0].message.content.strip()
    logger.debug("Summary: %s", summary)
    logger.info("Summary: %s", summary)
    return summary


# ---------------------------------------------------------------------------
# Abstract / keyword extraction
# ---------------------------------------------------------------------------

def extract_abstract(text: str) -> str:
    """Extract keywords/concepts from *text* for image generation."""
    logger.info("Extracting...")
    logger.debug("Prompt for abstraction: %s", PROMPT_FOR_ABSTRACTION)

    prompt: str = f"{PROMPT_FOR_ABSTRACTION}'''{text}'''"
    loggerTrace.debug("prompt for extract: %s", prompt)

    response = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
    )

    loggerTrace.debug("responseForImageGen: %s", response)

    abstract: str = response.choices[0].message.content.strip()

    # Clean up the response
    abstract = abstract[abstract.find('"') + 1:]
    abstract = abstract[abstract.find(":") + 1:]

    bad_phrases: list[str] = [
        "the concept of",
        "in the supplied text is",
        "the most interesting concept" "in the text is",
    ]
    for phrase in bad_phrases:
        abstract = re.sub(re.escape(phrase), " ", abstract, flags=re.IGNORECASE)
    abstract = abstract.rstrip(".")
    abstract = abstract.strip()

    logger.info("Abstract: %s", abstract)
    logger.info("Abstract: %s", abstract)
    return abstract


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------

# Callback signature: (message_str, label) -> None
ProgressCallback = Callable[[str, object], None] | None

def generate_images(
    phrase: str,
    single_image: bool = False,
    progress_callback: ProgressCallback = None,
    progress_label: object = None,
) -> Tuple[list[str], str]:
    """Generate images via OpenAI and return (urls_or_b64_list, modifier_str).

    ``phrase`` is used as the image prompt.  ``single_image`` switches to
    dalle-3 and returns one image.  Otherwise four concurrent gpt-image-1.5
    requests are made with different style modifiers.

    ``progress_callback``, if provided, is called with (message, label) to
    update the UI.
    """
    random.shuffle(IMAGE_MODIFIERS)

    phrase_lower: str = phrase.lower()
    phrase_has_style: bool = (
        "in the style of" in phrase_lower
        or "as a painting by" in phrase_lower
        or "as a photograph by" in phrase_lower
        or "as a sketch by" in phrase_lower
        or "as a watercolor by" in phrase_lower
    )

    # ------------------------------------------------------------------
    # Single image (dalle-3)
    # ------------------------------------------------------------------
    if single_image:
        modifier_used: str = IMAGE_MODIFIERS[0] if not phrase_has_style else ""
        prompt: str
        if phrase_has_style:
            prompt = (
                "Generate a picture WITHOUT ANY TEXT OR WRITING IN THE PICTURE "
                f"for the following: '{phrase}'"
            )
        else:
            prompt = (
                f"Generate a picture {modifier_used} "
                "WITHOUT ANY TEXT OR WRITING IN THE PICTURE "
                f"for the following: '{phrase}'"
            )

        logger.info("Generating image with prompt: %s", prompt)
        response = openai.images.generate(
            prompt=prompt,
            model="dall-e-3",
            n=1,
            size="1024x1024",
        )
        urls: list[str] = [img.url for img in response.data]
        return urls, modifier_used

    # ------------------------------------------------------------------
    # Four concurrent images (gpt-image-1.5)
    # ------------------------------------------------------------------
    num_images: int = 4
    modifiers_to_use: list[str] = (
        IMAGE_MODIFIERS[:num_images]
        if not phrase_has_style
        else [""] * num_images
    )
    modifier_used = ", ".join(m for m in modifiers_to_use if m)

    # Initial progress
    last_transcript: str = getattr(gw, "lastTranscript", "")
    if progress_callback:
        msg: str
        if last_transcript:
            msg =f'I heard you say:\n\r "{last_transcript}"\n\r\n\r'
        progress_callback(msg, progress_label)

    # Build prompts
    prompts_and_indices: list[tuple[int, str]] = []
    for i in range(num_images):
        mod = modifiers_to_use[i]
        if phrase_has_style or not mod:
            prompt = (
                "Generate a picture WITHOUT ANY TEXT OR WRITING IN THE PICTURE "
                f"and some randomness for the following: '{phrase}'"
            )
        else:
            prompt = (
                "Generate a picture WITHOUT ANY TEXT OR WRITING IN THE PICTURE "
                f" {mod} and interpret it creatively for the following: "
                f"'{phrase}'"
            )
        prompts_and_indices.append((i, prompt))
        

    image_urls: list[str | None] = [None] * num_images
    completed_count: int = 0
    requested_count: int = 0

    with ThreadPoolExecutor(max_workers=num_images) as executor:
        future_to_index: dict = {}
        for idx, prompt in prompts_and_indices:
            logger.info(
                "Submitting image %d/%d request with prompt: %s",
                idx + 1, num_images, prompt,
            )

            def _submit(p: str = prompt) -> object:
                return openai.images.generate(
                    prompt=p,
                    model="gpt-image-2",
                    quality="low",  # $0.005  medium is $0.05, high is $0.20
                    n=1,
                    size="1024x1024",
                )

            future = executor.submit(_submit)
            future_to_index[future] = idx
            requested_count += 1

        # Alert the user that requests have been submitted and we're waiting for results
        if progress_callback:
            if last_transcript:
                msg = (
                    f'I heard you say:\n\r "{last_transcript}"\n\r\n\r'
                    f"Requested {requested_count} of {num_images} images"
                )
            else:
                msg = f"Requested {requested_count} of {num_images} images"
            progress_callback(msg, progress_label)

        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            response_image = future.result()
            # gpt-image-1.5 returns b64_json
            image_urls[idx] = response_image.data[0].b64_json
            completed_count += 1
            logger.info(
                "Image %d/%d completed (%d/%d done)",
                idx + 1, num_images, completed_count, num_images,
            )

            if progress_callback:
                if last_transcript:
                    msg = (
                        f'I heard you say:\n\r "{last_transcript}"\n\r\n\r'
                        f"Receiving images... {completed_count} of {num_images}"
                    )
                else:
                    msg = f"Receiving images... {completed_count} of {num_images}"
                progress_callback(msg, progress_label)

    loggerTrace.debug("responseImage count: %d", len(image_urls))

    # At this point image_urls is list[str|None]; cast to list[str] (all filled)
    return image_urls, modifier_used  # type: ignore[return-value]