from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import kagglehub
import numpy as np
from PIL import Image


SERVICE_DIR = Path(__file__).resolve().parent.parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from config import STATE_DIR, VECTOR_DEV_DATASET_LIMIT, VECTOR_RANDOM_SEED, VECTOR_TEST_DATASET_ID
from logger import get_logger
from utils import ensure_directory, write_json


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
DEFAULT_OUTPUT_DIR = STATE_DIR / "distorted_caltech"


@dataclass(frozen=True)
class DistortionLevel:
    slug: str
    display_name: str
    noise_std: float
    shift_ratio: float


DISTORTION_LEVELS = [
    DistortionLevel("level_1_mild", "Mild", noise_std=8.0, shift_ratio=0.02),
    DistortionLevel("level_2_medium", "Medium", noise_std=18.0, shift_ratio=0.05),
    DistortionLevel("level_3_severe", "Severe", noise_std=32.0, shift_ratio=0.09),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create three distorted Caltech dataset folders with increasing noise and translation.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where the three distorted dataset folders will be created.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=VECTOR_DEV_DATASET_LIMIT,
        help="Maximum number of sorted Caltech images to distort.",
    )
    return parser.parse_args()


def load_source_image_paths(limit: int) -> tuple[Path, list[Path]]:
    dataset_root = Path(kagglehub.dataset_download(VECTOR_TEST_DATASET_ID))
    if not dataset_root.exists():
        raise FileNotFoundError(f"Caltech dataset download path does not exist: {dataset_root}")

    image_paths = sorted(
        path
        for path in dataset_root.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )
    if limit > 0:
        image_paths = image_paths[:limit]
    return dataset_root, image_paths


def apply_translation(image_array: np.ndarray, shift_x: int, shift_y: int) -> np.ndarray:
    translated = np.zeros_like(image_array)

    destination_x0 = max(0, shift_x)
    destination_y0 = max(0, shift_y)
    source_x0 = max(0, -shift_x)
    source_y0 = max(0, -shift_y)

    copy_width = image_array.shape[1] - abs(shift_x)
    copy_height = image_array.shape[0] - abs(shift_y)
    if copy_width <= 0 or copy_height <= 0:
        return translated

    translated[
        destination_y0 : destination_y0 + copy_height,
        destination_x0 : destination_x0 + copy_width,
    ] = image_array[
        source_y0 : source_y0 + copy_height,
        source_x0 : source_x0 + copy_width,
    ]
    return translated


def distort_image(image: Image.Image, level: DistortionLevel, rng: np.random.Generator) -> tuple[Image.Image, dict[str, int | float]]:
    rgb_array = np.asarray(image.convert("RGB"), dtype=np.uint8)
    max_shift_x = max(1, int(round(rgb_array.shape[1] * level.shift_ratio)))
    max_shift_y = max(1, int(round(rgb_array.shape[0] * level.shift_ratio)))
    shift_x = int(rng.integers(-max_shift_x, max_shift_x + 1))
    shift_y = int(rng.integers(-max_shift_y, max_shift_y + 1))

    translated = apply_translation(rgb_array, shift_x, shift_y).astype(np.float32)
    noise = rng.normal(loc=0.0, scale=level.noise_std, size=translated.shape)
    distorted = np.clip(translated + noise, 0.0, 255.0).astype(np.uint8)
    return Image.fromarray(distorted, mode="RGB"), {
        "shiftX": shift_x,
        "shiftY": shift_y,
        "noiseStd": level.noise_std,
    }


def save_image(image: Image.Image, target_path: Path) -> None:
    ensure_directory(target_path.parent)
    save_kwargs: dict[str, int] = {}
    if target_path.suffix.lower() in {".jpg", ".jpeg"}:
        save_kwargs = {"quality": 95, "subsampling": 0}
    image.save(target_path, **save_kwargs)


def create_distorted_dataset(output_dir: Path, limit: int) -> Path:
    logger = get_logger()
    dataset_root, image_paths = load_source_image_paths(limit)
    logger.info(
        "Creating distorted Caltech datasets from %s source images under %s",
        len(image_paths),
        dataset_root,
    )

    level_summaries: list[dict[str, object]] = []
    for level_index, level in enumerate(DISTORTION_LEVELS, start=1):
        level_dir = output_dir / level.slug
        ensure_directory(level_dir)
        logger.info(
            "Generating distortion level %s/%s: %s noise_std=%.1f shift_ratio=%.3f",
            level_index,
            len(DISTORTION_LEVELS),
            level.display_name,
            level.noise_std,
            level.shift_ratio,
        )

        for image_index, source_path in enumerate(image_paths, start=1):
            relative_path = source_path.relative_to(dataset_root)
            target_path = level_dir / relative_path
            with Image.open(source_path) as source_image:
                seed = VECTOR_RANDOM_SEED + level_index * 1_000_000 + image_index
                rng = np.random.default_rng(seed)
                distorted_image, _ = distort_image(source_image, level, rng)
                save_image(distorted_image, target_path)

            if image_index == 1 or image_index == len(image_paths) or image_index % 500 == 0:
                logger.info(
                    "Distortion level %s progress: image=%s/%s path=%s",
                    level.display_name,
                    image_index,
                    len(image_paths),
                    relative_path.as_posix(),
                )

        level_summaries.append(
            {
                "slug": level.slug,
                "displayName": level.display_name,
                "directory": str(level_dir),
                "noiseStd": level.noise_std,
                "shiftRatio": level.shift_ratio,
                "imageCount": len(image_paths),
            }
        )

    manifest_path = output_dir / "manifest.json"
    write_json(
        manifest_path,
        {
            "sourceDatasetId": VECTOR_TEST_DATASET_ID,
            "sourceDatasetPath": str(dataset_root),
            "imageCount": len(image_paths),
            "limit": limit,
            "randomSeed": VECTOR_RANDOM_SEED,
            "distortionKind": "combined_gaussian_noise_and_translation",
            "levels": level_summaries,
        },
    )
    logger.info("Saved distorted dataset manifest to %s", manifest_path)
    return manifest_path


def main() -> int:
    args = parse_args()
    manifest_path = create_distorted_dataset(args.output_dir.resolve(), args.limit)
    print("Saved distorted Caltech datasets and manifest to:")
    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())