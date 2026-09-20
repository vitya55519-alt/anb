"""V3.44.0: batch photo generator — creates diverse photo sets for all characters.

Usage:
    python _batch_generate_photos.py [--characters anna_01 emily_01] [--scenes home park cafe] [--count 3]

Generates multiple photo variations per character across different scenes,
saving them to the character's reference folder for use in the card gallery.

Requires GEMINI_API_KEY (or FAL_KEY) to be set in environment.
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
from services.photo_service import PhotoRequest, generate_photo_set
from services import webapp_service

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

# All built-in characters (V3.44.0: added Kate, Luna, Rex)
ALL_CHARACTERS = [
    'anna_01', 'alena_01', 'maria_01', 'erika_01', 'sonya_01',
    'vika_01', 'alisa_01', 'mila_01', 'kate_01', 'luna_01', 'rex_01',
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

    # Find the reference folder for this character
    rel = webapp_service._FACE_REFERENCES.get(character_id)
    if not rel:
        logger.error(f'No reference folder mapping for {character_id}')
        return 0
    
    ref_folder = Path('data') / rel[0] / rel[1]
    ref_folder.mkdir(parents=True, exist_ok=True)
    
    # Find next available slot number
    existing = sorted(ref_folder.glob('*.png'))
    next_slot = len(existing)

    generated = 0
    for i in range(count):
        # Rotate through scenes
        scene = scenes[i % len(scenes)]
        logger.info(f'  [{i+1}/{count}] Scene: {scene}')
        try:
            request = PhotoRequest(scene=scene)
            photos, _ = await generate_photo_set(
                telegram_id=0,  # batch mode
                request=request,
                character_id=character_id,
                frames=1,  # one photo per set for reference
            )
            if photos:
                # Save each photo to the reference folder
                for photo in photos:
                    if hasattr(photo, 'url') and photo.url:
                        # Download and save
                        import aiohttp
                        async with aiohttp.ClientSession() as session:
                            async with session.get(photo.url) as resp:
                                if resp.status == 200:
                                    filename = f'{next_slot:02d}_{rel[1]}_reference_{next_slot}.png'
                                    dest = ref_folder / filename
                                    dest.write_bytes(await resp.read())
                                    logger.info(f'    Saved: {filename}')
                                    next_slot += 1
                                    generated += 1
                                else:
                                    logger.warning(f'    Failed to download: HTTP {resp.status}')
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

    logger.info(f'Done! Generated {total_generated} photo(s) total')


if __name__ == '__main__':
    asyncio.run(main())
