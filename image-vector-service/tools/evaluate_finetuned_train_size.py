from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import PurePosixPath, Path
from typing import Any

import numpy as np
from sklearn.model_selection import StratifiedShuffleSplit
from sklearn.preprocessing import LabelEncoder
from torch.utils.data import DataLoader


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


DEFAULT_REPORT_PATH = STATE_DIR / "fine_tuned_train_size_evaluation.json"
DEFAULT_FRACTIONS = (0.1, 0.2, 0.4, 0.6, 0.8, 1.0)
FINE_TUNED_MODEL_NAME = "ResNet-18 embedding kNN (fine-tuned)"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the fine-tuned ResNet-18 kNN model at different training-set sizes.",
    )
    parser.add_argument(
        "--fractions",
        type=float,
        nargs="+",
        default=list(DEFAULT_FRACTIONS),
        help="Training-set fractions to evaluate, expressed relative to the fixed train split.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Path where the train-size evaluation JSON will be written.",
    )
    return parser.parse_args()


def _class_name_from_relative_path(relative_path: str) -> str:
    path = PurePosixPath(relative_path)
    if len(path.parts) >= 2:
        return path.parts[-2]
    return path.stem


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
                    "trainSeconds": model.get("trainSeconds"),
                }
    return {
        "testMetrics": {},
        "retrievalMetrics": {},
        "bestParams": {},
        "trainSeconds": None,
    }


def _metric_deltas(current: dict[str, float], baseline: dict[str, Any]) -> dict[str, float]:
    deltas: dict[str, float] = {}
    for name, value in current.items():
        if name in baseline:
            deltas[name] = float(value) - float(baseline[name])
    return deltas


def _normalize_fractions(raw_fractions: list[float]) -> list[float]:
    normalized = sorted({round(float(fraction), 6) for fraction in raw_fractions})
    if not normalized:
        raise RuntimeError("At least one training fraction is required.")
    for fraction in normalized:
        if fraction <= 0.0 or fraction > 1.0:
            raise RuntimeError(f"Training fraction must be in (0, 1], got {fraction}")
    return normalized


def _sample_train_subset(train_indices: np.ndarray, labels: np.ndarray, fraction: float, seed_offset: int) -> np.ndarray:
    if fraction >= 1.0:
        return np.sort(train_indices).astype(np.int64)

    splitter = StratifiedShuffleSplit(n_splits=1, train_size=fraction, random_state=VECTOR_RANDOM_SEED + seed_offset)
    subset_relative_indices, _ = next(splitter.split(train_indices, labels[train_indices]))
    sampled = train_indices[subset_relative_indices]
    return np.sort(sampled).astype(np.int64)


async def evaluate_train_sizes(fractions: list[float], report_path: Path) -> Path:
    logger = get_logger()
    _seed_everything(VECTOR_RANDOM_SEED)

    if not FINETUNED_MODEL_PATH.exists():
        raise FileNotFoundError(f"Fine-tuned backbone weights were not found: {FINETUNED_MODEL_PATH}")

    normalized_fractions = _normalize_fractions(fractions)
    best_knn_params = _resolve_best_knn_params()
    clean_reference = _resolve_clean_reference()

    service = ImageVectorService(
        include_test_dataset=True,
        use_fine_tuned_model=True,
        enable_audit_artifacts=False,
    )
    await service.initialize(include_registered_images=False)
    if not service.test_records:
        raise RuntimeError("The evaluation dataset is empty; train-size evaluation cannot continue.")

    label_names = np.array([_class_name_from_relative_path(record.relative_path) for record in service.test_records], dtype=object)
    label_encoder = LabelEncoder()
    encoded_labels = label_encoder.fit_transform(label_names)
    split_indices = _build_stratified_split(encoded_labels, VECTOR_RANDOM_SEED)
    train_indices = split_indices["train"]
    validation_indices = split_indices["validation"]
    test_indices = split_indices["test"]
    class_count = len(label_encoder.classes_)

    dataset = _CaltechEvaluationDataset(service, encoded_labels)
    full_loader = DataLoader(dataset, batch_size=32, shuffle=False, num_workers=0)
    device = _select_device()
    service.extractor.model = service.extractor.model.to(device)
    logger.info(
        "Extracting fine-tuned embeddings for train-size sweep: dataset_size=%s device=%s fractions=%s",
        len(dataset),
        device,
        normalized_fractions,
    )
    embeddings = _extract_embeddings_from_backbone(service.extractor.model, full_loader, device)

    levels: list[dict[str, Any]] = []
    for level_index, fraction in enumerate(normalized_fractions, start=1):
        sampled_train_indices = _sample_train_subset(train_indices, encoded_labels, fraction, seed_offset=level_index)
        estimator = _build_knn_estimator(best_knn_params)
        estimator.fit(embeddings[sampled_train_indices], encoded_labels[sampled_train_indices])
        predictions, probabilities, estimator_classes, prediction_seconds = _predict_with_timing(
            estimator,
            embeddings[test_indices],
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
            embeddings[test_indices],
            embeddings[sampled_train_indices],
            encoded_labels[test_indices],
            encoded_labels[sampled_train_indices],
            int(best_knn_params.get("model__n_neighbors", 1)),
            RETRIEVAL_TOP_K,
        )
        prediction_milliseconds = (prediction_seconds / max(1, len(test_indices))) * 1000.0

        levels.append(
            {
                "trainFraction": fraction,
                "trainSampleCount": int(len(sampled_train_indices)),
                "classCoverage": int(np.unique(encoded_labels[sampled_train_indices]).size),
                "testMetrics": test_metrics,
                "testMetricDeltaVsFullTrain": _metric_deltas(test_metrics, clean_reference.get("testMetrics", {})),
                "testConfidenceIntervals": test_confidence_intervals,
                "retrievalMetrics": retrieval_report["metrics"],
                "retrievalMetricDeltaVsFullTrain": _metric_deltas(
                    retrieval_report["metrics"],
                    clean_reference.get("retrievalMetrics", {}),
                ),
                "retrievalConfidenceIntervals": retrieval_report["confidenceIntervals"],
                "predictionMillisecondsPerSample": prediction_milliseconds,
            }
        )
        logger.info(
            "Train-size level %s/%s done: fraction=%.2f samples=%s accuracy=%.4f macro_f1=%.4f precision@10=%.4f mAP@10=%.4f",
            level_index,
            len(normalized_fractions),
            fraction,
            len(sampled_train_indices),
            test_metrics["accuracy"],
            test_metrics["macro_f1"],
            retrieval_report["metrics"]["precisionAt10"],
            retrieval_report["metrics"]["meanAveragePrecisionAt10"],
        )

    payload = {
        "seed": VECTOR_RANDOM_SEED,
        "modelName": FINE_TUNED_MODEL_NAME,
        "backbonePath": str(FINETUNED_MODEL_PATH),
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
        "levels": levels,
    }
    write_json(report_path, payload)
    logger.info("Saved fine-tuned train-size evaluation report to %s", report_path)
    return report_path


def main() -> int:
    args = parse_args()
    report_path = asyncio.run(evaluate_train_sizes(args.fractions, args.report_path.resolve()))
    print("Saved fine-tuned train-size evaluation report to:")
    print(report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())