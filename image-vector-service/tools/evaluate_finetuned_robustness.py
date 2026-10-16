from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np
from PIL import Image
from sklearn.preprocessing import LabelEncoder
from torch.utils.data import DataLoader, Dataset, Subset


SERVICE_DIR = Path(__file__).resolve().parent.parent
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from config import DEV_EVALUATION_PATH, FINETUNED_MODEL_PATH, STATE_DIR, VECTOR_RANDOM_SEED
from evaluation import (
    RETRIEVAL_TOP_K,
    _CaltechEvaluationDataset,
    _bootstrap_confidence_intervals,
    _build_knn_estimator,
    _build_stratified_split,
    _compute_metrics,
    _evaluate_retrieval,
    _extract_embeddings_from_backbone,
    _predict_with_timing,
    _seed_everything,
    _select_device,
)
from logger import get_logger
from service import ImageVectorService
from utils import read_json, write_json


DEFAULT_DISTORTED_ROOT = STATE_DIR / "distorted_caltech"
DEFAULT_REPORT_PATH = STATE_DIR / "fine_tuned_robustness_evaluation.json"
FINE_TUNED_MODEL_NAME = "ResNet-18 embedding kNN (fine-tuned)"


@dataclass(frozen=True)
class DistortionLevel:
    slug: str
    display_name: str
    directory: Path
    noise_std: float | None
    shift_ratio: float | None


class _DistortedCaltechDataset(Dataset[tuple[Any, int]]):
    def __init__(
        self,
        records: list[Any],
        encoded_labels: np.ndarray,
        preprocess: Any,
        level_directory: Path,
    ) -> None:
        self.records = records
        self.encoded_labels = encoded_labels.astype(np.int64)
        self.preprocess = preprocess
        self.level_directory = level_directory

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> tuple[Any, int]:
        record = self.records[index]
        distorted_path = self.level_directory / Path(PurePosixPath(record.relative_path))
        if not distorted_path.exists():
            raise FileNotFoundError(f"Missing distorted image for {record.relative_path}: {distorted_path}")

        pil_image = Image.open(io.BytesIO(distorted_path.read_bytes())).convert("RGB")
        tensor = self.preprocess(pil_image)
        return tensor, int(self.encoded_labels[index])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the fine-tuned ResNet-18 backbone on distorted Caltech queries across three corruption levels.",
    )
    parser.add_argument(
        "--distorted-root",
        type=Path,
        default=DEFAULT_DISTORTED_ROOT,
        help="Root directory containing the distorted Caltech level folders and manifest.json.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Path where the robustness report JSON will be written.",
    )
    return parser.parse_args()


def _class_name_from_relative_path(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    if len(path.parts) >= 2:
        return path.parts[-2]
    return path.stem


def _resolve_distortion_levels(distorted_root: Path) -> list[DistortionLevel]:
    manifest = read_json(distorted_root / "manifest.json", default={})
    levels_payload = manifest.get("levels", []) if isinstance(manifest, dict) else []
    if levels_payload:
        return [
            DistortionLevel(
                slug=str(level["slug"]),
                display_name=str(level.get("displayName", level["slug"])),
                directory=Path(str(level["directory"])),
                noise_std=float(level["noiseStd"]) if level.get("noiseStd") is not None else None,
                shift_ratio=float(level["shiftRatio"]) if level.get("shiftRatio") is not None else None,
            )
            for level in levels_payload
        ]

    discovered = sorted(path for path in distorted_root.iterdir() if path.is_dir())
    return [
        DistortionLevel(
            slug=path.name,
            display_name=path.name,
            directory=path,
            noise_std=None,
            shift_ratio=None,
        )
        for path in discovered
    ]


def _resolve_best_knn_params() -> dict[str, Any]:
    payload = read_json(DEV_EVALUATION_PATH, default={})
    if isinstance(payload, dict):
        for model in payload.get("models", []):
            if model.get("name") == FINE_TUNED_MODEL_NAME and isinstance(model.get("bestParams"), dict):
                return dict(model["bestParams"])
    return {
        "model__n_neighbors": 3,
        "model__weights": "distance",
    }


def _resolve_clean_reference() -> dict[str, Any]:
    payload = read_json(DEV_EVALUATION_PATH, default={})
    if isinstance(payload, dict):
        for model in payload.get("models", []):
            if model.get("name") == FINE_TUNED_MODEL_NAME:
                return {
                    "testMetrics": model.get("testMetrics", {}),
                    "retrievalMetrics": model.get("retrievalMetrics", {}),
                    "bestParams": model.get("bestParams", {}),
                }
    return {
        "testMetrics": {},
        "retrievalMetrics": {},
        "bestParams": {},
    }


def _metric_deltas(current: dict[str, float], baseline: dict[str, Any]) -> dict[str, float]:
    deltas: dict[str, float] = {}
    for name, value in current.items():
        if name in baseline:
            deltas[name] = float(value) - float(baseline[name])
    return deltas


async def evaluate_robustness(distorted_root: Path, report_path: Path) -> Path:
    logger = get_logger()
    _seed_everything(VECTOR_RANDOM_SEED)

    if not FINETUNED_MODEL_PATH.exists():
        raise FileNotFoundError(f"Fine-tuned backbone weights were not found: {FINETUNED_MODEL_PATH}")
    if not distorted_root.exists():
        raise FileNotFoundError(f"Distorted dataset root does not exist: {distorted_root}")

    distortion_levels = _resolve_distortion_levels(distorted_root)
    if not distortion_levels:
        raise RuntimeError(f"No distorted dataset folders found in {distorted_root}")

    service = ImageVectorService(
        include_test_dataset=True,
        use_fine_tuned_model=True,
        enable_audit_artifacts=False,
    )
    await service.initialize(include_registered_images=False)
    if not service.test_records:
        raise RuntimeError("The evaluation dataset is empty; robustness evaluation cannot continue.")

    label_names = np.array([
        _class_name_from_relative_path(record.relative_path)
        for record in service.test_records
    ], dtype=object)
    label_encoder = LabelEncoder()
    encoded_labels = label_encoder.fit_transform(label_names)
    split_indices = _build_stratified_split(encoded_labels, VECTOR_RANDOM_SEED)
    train_indices = split_indices["train"]
    validation_indices = split_indices["validation"]
    test_indices = split_indices["test"]
    train_validation_indices = np.concatenate([train_indices, validation_indices])
    class_count = len(label_encoder.classes_)
    best_knn_params = _resolve_best_knn_params()
    clean_reference = _resolve_clean_reference()

    clean_dataset = _CaltechEvaluationDataset(service, encoded_labels)
    full_loader = DataLoader(clean_dataset, batch_size=32, shuffle=False, num_workers=0)
    device = _select_device()
    service.extractor.model = service.extractor.model.to(device)
    logger.info(
        "Extracting clean embeddings with fine-tuned backbone: dataset_size=%s device=%s levels=%s",
        len(clean_dataset),
        device,
        len(distortion_levels),
    )
    clean_embeddings = _extract_embeddings_from_backbone(service.extractor.model, full_loader, device)

    estimator = _build_knn_estimator(best_knn_params)
    estimator.fit(clean_embeddings[train_validation_indices], encoded_labels[train_validation_indices])
    logger.info("Fitted robustness kNN evaluator with params %s", best_knn_params)

    level_reports: list[dict[str, Any]] = []
    for level_index, level in enumerate(distortion_levels, start=1):
        logger.info(
            "Robustness evaluation level %s/%s started: %s (%s)",
            level_index,
            len(distortion_levels),
            level.display_name,
            level.directory,
        )
        distorted_dataset = _DistortedCaltechDataset(
            service.test_records,
            encoded_labels,
            service.extractor.preprocess,
            level.directory,
        )
        distorted_loader = DataLoader(
            Subset(distorted_dataset, test_indices.tolist()),
            batch_size=32,
            shuffle=False,
            num_workers=0,
        )
        distorted_test_embeddings = _extract_embeddings_from_backbone(service.extractor.model, distorted_loader, device)
        predictions, probabilities, estimator_classes, prediction_seconds = _predict_with_timing(
            estimator,
            distorted_test_embeddings,
        )
        test_metrics = _compute_metrics(
            encoded_labels[test_indices],
            predictions,
            probabilities,
            estimator_classes,
            class_count,
        )
        test_confidence_intervals = _bootstrap_confidence_intervals(
            encoded_labels[test_indices],
            predictions,
            probabilities,
            estimator_classes,
            class_count,
            VECTOR_RANDOM_SEED,
        )
        retrieval_report = _evaluate_retrieval(
            distorted_test_embeddings,
            clean_embeddings[train_validation_indices],
            encoded_labels[test_indices],
            encoded_labels[train_validation_indices],
            int(best_knn_params.get("model__n_neighbors", 1)),
            RETRIEVAL_TOP_K,
        )
        prediction_milliseconds = (prediction_seconds / max(1, len(test_indices))) * 1000.0
        level_reports.append(
            {
                "level": level.slug,
                "displayName": level.display_name,
                "directory": str(level.directory),
                "noiseStd": level.noise_std,
                "shiftRatio": level.shift_ratio,
                "testMetrics": test_metrics,
                "testMetricDeltaVsClean": _metric_deltas(test_metrics, clean_reference.get("testMetrics", {})),
                "testConfidenceIntervals": test_confidence_intervals,
                "retrievalMetrics": retrieval_report["metrics"],
                "retrievalMetricDeltaVsClean": _metric_deltas(
                    retrieval_report["metrics"],
                    clean_reference.get("retrievalMetrics", {}),
                ),
                "retrievalConfidenceIntervals": retrieval_report["confidenceIntervals"],
                "predictionMillisecondsPerSample": prediction_milliseconds,
            }
        )
        logger.info(
            "Robustness level %s done: accuracy=%.4f macro_f1=%.4f precision@10=%.4f mAP@10=%.4f",
            level.display_name,
            test_metrics["accuracy"],
            test_metrics["macro_f1"],
            retrieval_report["metrics"]["precisionAt10"],
            retrieval_report["metrics"]["meanAveragePrecisionAt10"],
        )

    payload = {
        "seed": VECTOR_RANDOM_SEED,
        "modelName": FINE_TUNED_MODEL_NAME,
        "backbonePath": str(FINETUNED_MODEL_PATH),
        "distortedDatasetRoot": str(distorted_root),
        "bestParams": best_knn_params,
        "split": {
            "counts": {
                "dataset": int(len(service.test_records)),
                "train": int(len(train_indices)),
                "validation": int(len(validation_indices)),
                "test": int(len(test_indices)),
            }
        },
        "cleanReference": clean_reference,
        "levels": level_reports,
    }
    write_json(report_path, payload)
    logger.info("Saved fine-tuned robustness evaluation report to %s", report_path)
    return report_path


def main() -> int:
    args = parse_args()
    report_path = asyncio.run(evaluate_robustness(args.distorted_root.resolve(), args.report_path.resolve()))
    print("Saved fine-tuned robustness evaluation report to:")
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())