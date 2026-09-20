"""V3.44.0: batch photo generator — creates diverse photo sets for all characters.

Usage:
    python _batch_generate_photos.py [--characters anna_01,emily_01] [--scenes home,park,cafe] [--count 3]

Generates multiple photo variations per character across different scenes,
saving them to the character's reference folder for use in the card gallery.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Add parent to path so we can import services
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import CHARACTER_ID
from services.character_registry import resolve_character
from services.photo_service import generate_photo_set

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# All built-in characters
ALL_CHARACTERS = [
    'anna_01', 'alena_01', 'maria_01', 'erika_01', 'sonya_01',
    'vika_01', 'alisa_01', 'mila_01',
]

# Diverse scenes for variety
ALL_SCENES = [
    'home', 'park', 'cafe', 'street', 'gym', 'mirror',
    'outfit', 'shop', 'car', 'restaurant', 'cinema', 'embankment',
]


async def generate_for_character(character_id: str, scenes: list[str], count: int) -> int:
    """Generate `count` photo sets for a character across the given scenes."""
    try:
        character = resolve_character(character_id)
        logger.info(f'Generating {count} sets for {character_id} ({character.get("display_name", character_id)})')
    except Exception as e:
        logger.error(f'Cannot resolve character {character_id}: {e}')
        return 0

    generated = 0
    for i in range(count):
        # Rotate through scenes
        scene = scenes[i % len(scenes)]
        logger.info(f'  [{i+1}/{count}] Scene: {scene}')
        try:
            # generate_photo_set returns (urls, caption) or raises
            urls, caption = await generate_photo_set(
                character_id=character_id,
                scene=scene,
                level=3,  # mid-level outfit
                telegram_id=0,  # batch mode
            )
            if urls:
                generated += 1
                logger.info(f'    Generated {len(urls)} photo(s)')
            else:
                logger.warning(f'    No photos returned')
        except Exception as e:
            logger.error(f'    Failed: {e}')

    return generated


async def main():
    parser = argparse.ArgumentParser(description='Batch photo generator for AnnaBot characters')
    parser.add_argument('--characters', nargs='+', default=ALL_CHARACTERS,
                        help='Character IDs to generate for (default: all built-in)')
    parser.add_argument('--scenes', nargs='+', default=ALL_SCENES,
                        help='Scenes to rotate through (default: all public scenes)')
    parser.add_argument('--count', type=int, default=2,
                        help='Number of photo sets per character (default: 2)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print what would be generated without actually generating')
    args = parser.parse_args()

    logger.info(f'Batch photo generation')
    logger.info(f'Characters: {args.characters}')
    logger.info(f'Scenes: {args.scenes}')
    logger.info(f'Count per character: {args.count}')

    if args.dry_run:
        logger.info('DRY RUN — no photos will be generated')
        for cid in args.characters:
            for i in range(args.count):
                scene = args.scenes[i % len(args.scenes)]
                logger.info(f'  {cid}: scene={scene}')
        return

    total_generated = 0
    for cid in args.characters:
        n = await generate_for_character(cid, args.scenes, args.count)
        total_generated += n

    logger.info(f'Done! Generated {total_generated} photo set(s) total')


if __name__ == '__main__':
    asyncio.run(main())
