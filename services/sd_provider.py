"""V3.44.2: Stable Diffusion provider via RunDiffusion API.

Used for uncensored/explicit content that Seedream may reject.
RunDiffusion is a cloud-hosted SD service with REST API.

Sign up: https://rundiffusion.com
API docs: https://docs.rundiffusion.com

Alternative: self-hosted SD on RunPod/Vast.ai with ComfyUI/A1111 API.
Change RUNDIFFUSION_BASE_URL to point to your instance.
"""
import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp

from config import (
    RUNDIFFUSION_API_KEY,
    RUNDIFFUSION_BASE_URL,
    RUNDIFFUSION_MODEL,
    RUNDIFFUSION_NEGATIVE_PROMPT,
    RUNDIFFUSION_WIDTH,
    RUNDIFFUSION_HEIGHT,
    RUNDIFFUSION_STEPS,
    RUNDIFFUSION_CFG,
    RUNDIFFUSION_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


class SDGenerationError(Exception):
    """Raised when Stable Diffusion generation fails."""
    pass


@dataclass
class SDResult:
    url: Optional[str] = None
    data: Optional[bytes] = None
    seed: Optional[int] = None
    nsfw_detected: bool = False


async def _sd_generate(
    prompt: str,
    negative_prompt: str = "",
    width: int = RUNDIFFUSION_WIDTH,
    height: int = RUNDIFFUSION_HEIGHT,
    steps: int = RUNDIFFUSION_STEPS,
    cfg: float = RUNDIFFUSION_CFG,
    seed: Optional[int] = None,
    model: str = RUNDIFFUSION_MODEL,
) -> SDResult:
    """Generate image via RunDiffusion API.

    Returns SDResult with url or data on success.
    Raises SDGenerationError on failure.
    """
    if not RUNDIFFUSION_API_KEY:
        raise SDGenerationError("RUNDIFFUSION_API_KEY not configured")

    # Combine negative prompts
    full_negative = f"{RUNDIFFUSION_NEGATIVE_PROMPT}, {negative_prompt}".strip(", ")

    payload = {
        "prompt": prompt,
        "negative_prompt": full_negative,
        "width": width,
        "height": height,
        "steps": steps,
        "cfg_scale": cfg,
        "model": model,
        "samples": 1,
    }
    if seed is not None:
        payload["seed"] = seed

    headers = {
        "Authorization": f"Bearer {RUNDIFFUSION_API_KEY}",
        "Content-Type": "application/json",
    }

    started = time.monotonic()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{RUNDIFFUSION_BASE_URL}/generate",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=RUNDIFFUSION_TIMEOUT_SECONDS),
            ) as resp:
                elapsed = time.monotonic() - started
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("SD API error status=%s body=%s elapsed=%.1fs", resp.status, body[:500], elapsed)
                    raise SDGenerationError(f"SD API returned {resp.status}: {body[:200]}")

                result = await resp.json()

                # RunDiffusion returns image as base64 in 'images' array
                images = result.get("images", [])
                if not images:
                    # Try alternative response format
                    images = result.get("output", {}).get("images", [])

                if not images:
                    raise SDGenerationError("SD API returned no images")

                # First image is our result
                img_data = images[0]

                # Check if it's base64 or URL
                if isinstance(img_data, str) and img_data.startswith("http"):
                    # It's a URL
                    sd_result = SDResult(url=img_data)
                elif isinstance(img_data, str):
                    # It's base64
                    if img_data.startswith("data:image"):
                        img_data = img_data.split(",", 1)[1]
                    raw_bytes = base64.b64decode(img_data)
                    sd_result = SDResult(data=raw_bytes)
                else:
                    raise SDGenerationError("Unexpected image format from SD API")

                sd_result.seed = result.get("seed")
                sd_result.nsfw_detected = result.get("nsfw_detected", False)

                logger.info(
                    "SD generation ok elapsed=%.1fs seed=%s nsfw=%s",
                    elapsed, sd_result.seed, sd_result.nsfw_detected,
                )
                return sd_result

    except aiohttp.ClientError as e:
        elapsed = time.monotonic() - started
        logger.error("SD network error elapsed=%.1fs: %s", elapsed, e)
        raise SDGenerationError(f"SD network error: {e}")
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - started
        logger.error("SD timeout elapsed=%.1fs", elapsed)
        raise SDGenerationError(f"SD timeout after {elapsed:.0f}s")


async def sd_img2img(
    prompt: str,
    init_image_url: str,
    strength: float = 0.75,
    negative_prompt: str = "",
    width: int = RUNDIFFUSION_WIDTH,
    height: int = RUNDIFFUSION_HEIGHT,
    steps: int = RUNDIFFUSION_STEPS,
    cfg: float = RUNDIFFUSION_CFG,
    seed: Optional[int] = None,
    model: str = RUNDIFFUSION_MODEL,
) -> SDResult:
    """Generate image via img2img (preserve face/identity from reference).

    Args:
        prompt: Generation prompt
        init_image_url: URL or base64 of reference image
        strength: How much to change (0.0=keep original, 1.0=full change)
        negative_prompt: Additional negative prompt
        width/height: Output dimensions
        steps: Sampling steps
        cfg: Classifier-free guidance scale
        seed: Random seed (None=random)
        model: SD model name

    Returns:
        SDResult with generated image
    """
    if not RUNDIFFUSION_API_KEY:
        raise SDGenerationError("RUNDIFFUSION_API_KEY not configured")

    full_negative = f"{RUNDIFFUSION_NEGATIVE_PROMPT}, {negative_prompt}".strip(", ")

    payload = {
        "prompt": prompt,
        "negative_prompt": full_negative,
        "init_image": init_image_url,
        "strength": strength,
        "width": width,
        "height": height,
        "steps": steps,
        "cfg_scale": cfg,
        "model": model,
        "samples": 1,
    }
    if seed is not None:
        payload["seed"] = seed

    headers = {
        "Authorization": f"Bearer {RUNDIFFUSION_API_KEY}",
        "Content-Type": "application/json",
    }

    started = time.monotonic()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{RUNDIFFUSION_BASE_URL}/img2img",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=RUNDIFFUSION_TIMEOUT_SECONDS),
            ) as resp:
                elapsed = time.monotonic() - started
                if resp.status != 200:
                    body = await resp.text()
                    logger.error("SD img2img error status=%s body=%s", resp.status, body[:500])
                    raise SDGenerationError(f"SD img2img returned {resp.status}: {body[:200]}")

                result = await resp.json()
                images = result.get("images", [])
                if not images:
                    images = result.get("output", {}).get("images", [])

                if not images:
                    raise SDGenerationError("SD img2img returned no images")

                img_data = images[0]

                if isinstance(img_data, str) and img_data.startswith("http"):
                    sd_result = SDResult(url=img_data)
                elif isinstance(img_data, str):
                    if img_data.startswith("data:image"):
                        img_data = img_data.split(",", 1)[1]
                    raw_bytes = base64.b64decode(img_data)
                    sd_result = SDResult(data=raw_bytes)
                else:
                    raise SDGenerationError("Unexpected image format from SD img2img")

                sd_result.seed = result.get("seed")
                sd_result.nsfw_detected = result.get("nsfw_detected", False)

                logger.info(
                    "SD img2img ok elapsed=%.1fs seed=%s strength=%.2f",
                    elapsed, sd_result.seed, strength,
                )
                return sd_result

    except aiohttp.ClientError as e:
        raise SDGenerationError(f"SD img2img network error: {e}")
    except asyncio.TimeoutError:
        raise SDGenerationError(f"SD img2img timeout after {RUNDIFFUSION_TIMEOUT_SECONDS}s")


def is_sd_available() -> bool:
    """Check if Stable Diffusion is configured and available."""
    return bool(RUNDIFFUSION_API_KEY)


def get_sd_config() -> dict:
    """Get current SD configuration for logging/debugging."""
    return {
        "api_key_configured": bool(RUNDIFFUSION_API_KEY),
        "base_url": RUNDIFFUSION_BASE_URL,
        "model": RUNDIFFUSION_MODEL,
        "width": RUNDIFFUSION_WIDTH,
        "height": RUNDIFFUSION_HEIGHT,
        "steps": RUNDIFFUSION_STEPS,
        "cfg": RUNDIFFUSION_CFG,
        "timeout": RUNDIFFUSION_TIMEOUT_SECONDS,
    }
