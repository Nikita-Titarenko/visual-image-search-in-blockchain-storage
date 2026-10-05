from pathlib import Path

import kagglehub


DATASET_ID = "imbikramsaha/caltech-101"


def download_caltech101() -> Path:
    dataset_path = Path(kagglehub.dataset_download(DATASET_ID))

    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset was downloaded to a missing path: {dataset_path}")

    return dataset_path