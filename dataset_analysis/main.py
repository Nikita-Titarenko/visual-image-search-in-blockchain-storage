import hashlib
from collections import defaultdict
from pathlib import Path

from build_plots import build_dataset_plots, collect_image_paths
from download_dataset import download_caltech101


def _find_duplicate_images(dataset_path: Path) -> dict[str, list[Path]]:
    duplicates: dict[str, list[Path]] = {}
    files_by_hash: dict[str, list[Path]] = defaultdict(list)

    for image_path in collect_image_paths(dataset_path):
        image_hash = hashlib.sha256(image_path.read_bytes()).hexdigest()
        files_by_hash[image_hash].append(image_path)

    for image_hash, paths in files_by_hash.items():
        if len(paths) > 1:
            duplicates[image_hash] = paths

    return duplicates


def main() -> None:
    dataset_path = download_caltech101()
    output_dir = Path("plots")
    generated_files = build_dataset_plots(dataset_path, output_dir=output_dir)
    duplicate_images = _find_duplicate_images(dataset_path)

    print(f"Dataset path: {dataset_path}")
    if duplicate_images:
        duplicate_file_count = sum(len(paths) for paths in duplicate_images.values())
        print(
            f"Duplicate images detected: yes ({len(duplicate_images)} duplicate groups, {duplicate_file_count} files involved)"
        )
        for image_hash, paths in list(duplicate_images.items())[:5]:
            relative_paths = ", ".join(str(path.relative_to(dataset_path)) for path in paths)
            print(f"- sha256={image_hash[:12]}... -> {relative_paths}")
    else:
        print("Duplicate images detected: no")
    print("Generated plots:")
    for file_path in generated_files:
        print(f"- {file_path}")


if __name__ == "__main__":
    main()