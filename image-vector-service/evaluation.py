from __future__ import annotations

import copy
import pickle
import random
import time
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

import numpy as np
import torch
from sklearn.compose import ColumnTransformer
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, f1_score, top_k_accuracy_score
from sklearn.model_selection import StratifiedKFold, StratifiedShuffleSplit
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, StandardScaler
from torch import nn
from torch.utils.data import DataLoader, Dataset, Subset
from torchvision.models import resnet18

from config import DEV_EVALUATION_PATH, DEV_PLOTS_DIR, FINETUNED_MODEL_PATH, VECTOR_DEV_DATASET_LIMIT, VECTOR_RANDOM_SEED, VECTOR_TEST_RATIO, VECTOR_TRAIN_RATIO, VECTOR_VAL_RATIO
from development_plots import build_plot_manifest, generate_development_plots
from features import build_resnet18_backbone, normalize_feature_matrix
from logger import get_logger
from utils import ensure_directory, write_json


if TYPE_CHECKING:
    from service import ImageVectorService


RF_CNN_PCA_COMPONENTS = 64
CV_FOLDS = 3
BOOTSTRAP_ROUNDS = 50
RESNET_FINETUNE_EPOCHS = 3
RESNET_FINETUNE_BATCH_SIZE = 32
RESNET_FINETUNE_LEARNING_RATE = 1e-4
RESNET_FINETUNE_WEIGHT_DECAY = 1e-4
RESNET_FINETUNE_PATIENCE = 1
RETRIEVAL_TOP_K = 10


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    get_logger().info("Random generators seeded: python=%s numpy=%s torch=%s", seed, seed, seed)


class _CaltechEvaluationDataset(Dataset[tuple[torch.Tensor, int]]):
    def __init__(self, service: ImageVectorService, encoded_labels: np.ndarray) -> None:
        self.service = service
        self.encoded_labels = encoded_labels.astype(np.int64)

    def __len__(self) -> int:
        return len(self.service.test_records)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, int]:
        record = self.service.test_records[index]
        image_bytes = record.file_path.read_bytes()
        image = self.service.extractor.decode_image(image_bytes)
        tensor = self.service.extractor.preprocess(image)
        label = int(self.encoded_labels[index])
        return tensor, label


def _build_stratified_split(labels: np.ndarray, seed: int) -> dict[str, np.ndarray]:
    logger = get_logger()
    sample_indices = np.arange(len(labels))
    holdout_ratio = VECTOR_VAL_RATIO + VECTOR_TEST_RATIO

    primary_splitter = StratifiedShuffleSplit(n_splits=1, test_size=holdout_ratio, random_state=seed)
    train_indices, holdout_indices = next(primary_splitter.split(sample_indices, labels))

    holdout_labels = labels[holdout_indices]
    validation_share = VECTOR_VAL_RATIO / holdout_ratio
    secondary_splitter = StratifiedShuffleSplit(n_splits=1, train_size=validation_share, random_state=seed + 1)
    validation_holdout_indices, test_holdout_indices = next(
        secondary_splitter.split(np.arange(len(holdout_indices)), holdout_labels)
    )

    validation_indices = holdout_indices[validation_holdout_indices]
    test_indices = holdout_indices[test_holdout_indices]

    logger.info(
        "Built stratified split candidates: samples=%s holdout_ratio=%.2f validation_share_inside_holdout=%.4f",
        len(labels),
        holdout_ratio,
        validation_share,
    )
    return {
        "train": np.sort(train_indices).astype(np.int64),
        "validation": np.sort(validation_indices).astype(np.int64),
        "test": np.sort(test_indices).astype(np.int64),
    }


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(value))

    def format_row(row: list[str]) -> str:
        return " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))

    separator = "-+-".join("-" * width for width in widths)
    rendered = [format_row(headers), separator]
    rendered.extend(format_row(row) for row in rows)
    return "\n".join(rendered)


def _align_probabilities_to_global_classes(
    y_prob: np.ndarray,
    estimator_classes: np.ndarray,
    class_count: int,
) -> np.ndarray:
    aligned = np.zeros((y_prob.shape[0], class_count), dtype=np.float64)
    for source_index, class_label in enumerate(estimator_classes):
        aligned[:, int(class_label)] = y_prob[:, source_index]
    return aligned


def _compute_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_prob: np.ndarray,
    estimator_classes: np.ndarray,
    class_count: int,
) -> dict[str, float]:
    accuracy = float(accuracy_score(y_true, y_pred))
    macro_f1 = float(f1_score(y_true, y_pred, average="macro", zero_division=0))
    unique_true_labels = np.unique(y_true)

    if unique_true_labels.size <= 1:
        balanced_accuracy = accuracy
    else:
        balanced_accuracy = float(balanced_accuracy_score(y_true, y_pred))

    if class_count <= 1 or estimator_classes.size <= 1:
        top3_accuracy = accuracy
    else:
        aligned_probabilities = _align_probabilities_to_global_classes(y_prob, estimator_classes, class_count)
        top_k = min(3, class_count)
        top3_accuracy = float(
            top_k_accuracy_score(
                y_true,
                aligned_probabilities,
                k=top_k,
                labels=np.arange(class_count),
            )
        )

    return {
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "balanced_accuracy": balanced_accuracy,
        "top3_accuracy": top3_accuracy,
    }


def _search_top_k_neighbors(
    query_features: np.ndarray,
    corpus_features: np.ndarray,
    top_k: int,
    batch_size: int = 128,
) -> tuple[np.ndarray, np.ndarray]:
    normalized_queries = normalize_feature_matrix(query_features)
    normalized_corpus = normalize_feature_matrix(corpus_features)
    top_k = max(1, min(top_k, normalized_corpus.shape[0]))
    top_indices: list[np.ndarray] = []
    top_scores: list[np.ndarray] = []

    for start in range(0, normalized_queries.shape[0], batch_size):
        batch = normalized_queries[start : start + batch_size]
        scores = batch @ normalized_corpus.T
        batch_top_indices = np.argpartition(-scores, kth=top_k - 1, axis=1)[:, :top_k]
        batch_top_scores = np.take_along_axis(scores, batch_top_indices, axis=1)
        order = np.argsort(-batch_top_scores, axis=1)
        top_indices.append(np.take_along_axis(batch_top_indices, order, axis=1).astype(np.int64))
        top_scores.append(np.take_along_axis(batch_top_scores, order, axis=1).astype(np.float32))

    return np.vstack(top_indices), np.vstack(top_scores)


def _majority_vote_from_neighbors(neighbor_labels: np.ndarray, neighbor_scores: np.ndarray) -> np.ndarray:
    predictions: list[int] = []
    for labels_row, scores_row in zip(neighbor_labels, neighbor_scores, strict=True):
        counts: Counter[int] = Counter(int(label) for label in labels_row)
        score_sums: dict[int, float] = defaultdict(float)
        first_rank: dict[int, int] = {}
        for rank, (label, score) in enumerate(zip(labels_row, scores_row, strict=True)):
            label_int = int(label)
            score_sums[label_int] += float(score)
            first_rank.setdefault(label_int, rank)
        winning_label = max(
            counts,
            key=lambda label: (counts[label], score_sums[label], -first_rank[label]),
        )
        predictions.append(winning_label)
    return np.asarray(predictions, dtype=np.int64)


def _compute_average_precision_at_k(relevant_flags: np.ndarray, relevant_total: int, k: int) -> float:
    capped_k = min(k, len(relevant_flags))
    if capped_k == 0 or relevant_total == 0:
        return 0.0

    hits = 0.0
    precision_sum = 0.0
    for rank in range(capped_k):
        if bool(relevant_flags[rank]):
            hits += 1.0
            precision_sum += hits / float(rank + 1)

    return precision_sum / float(min(relevant_total, capped_k))


def _bootstrap_metric_means(per_query_values: dict[str, np.ndarray], seed: int) -> dict[str, dict[str, float]]:
    rng = np.random.default_rng(seed)
    confidence_intervals: dict[str, dict[str, float]] = {}
    for name, values in per_query_values.items():
        bootstrap_means = []
        for _ in range(BOOTSTRAP_ROUNDS):
            sample_indices = rng.integers(0, len(values), size=len(values))
            bootstrap_means.append(float(np.mean(values[sample_indices])))
        confidence_intervals[name] = {
            "low": float(np.percentile(bootstrap_means, 2.5)),
            "high": float(np.percentile(bootstrap_means, 97.5)),
        }
    return confidence_intervals


def _evaluate_retrieval(
    query_features: np.ndarray,
    corpus_features: np.ndarray,
    query_labels: np.ndarray,
    corpus_labels: np.ndarray,
    majority_vote_k: int,
    top_k: int = RETRIEVAL_TOP_K,
) -> dict[str, Any]:
    neighbor_indices, neighbor_scores = _search_top_k_neighbors(query_features, corpus_features, top_k)
    neighbor_labels = corpus_labels[neighbor_indices]
    predictions = _majority_vote_from_neighbors(
        neighbor_labels[:, : max(1, min(majority_vote_k, neighbor_labels.shape[1]))],
        neighbor_scores[:, : max(1, min(majority_vote_k, neighbor_scores.shape[1]))],
    )

    corpus_class_counts = Counter(int(label) for label in corpus_labels.tolist())
    relevant = neighbor_labels == query_labels[:, None]
    per_query_metrics = {
        "precisionAt1": relevant[:, :1].mean(axis=1).astype(np.float64),
        "precisionAt5": relevant[:, : min(5, relevant.shape[1])].mean(axis=1).astype(np.float64),
        "precisionAt10": relevant[:, : min(10, relevant.shape[1])].mean(axis=1).astype(np.float64),
        "meanAveragePrecisionAt10": np.array(
            [
                _compute_average_precision_at_k(relevant[index], corpus_class_counts[int(query_labels[index])], 10)
                for index in range(len(query_labels))
            ],
            dtype=np.float64,
        ),
    }
    metrics = {name: float(np.mean(values)) for name, values in per_query_metrics.items()}
    confidence_intervals = _bootstrap_metric_means(per_query_metrics, VECTOR_RANDOM_SEED)

    return {
        "metrics": metrics,
        "confidenceIntervals": confidence_intervals,
        "perQueryMetrics": per_query_metrics,
        "predictions": predictions,
        "neighborIndices": neighbor_indices,
        "neighborScores": neighbor_scores,
        "neighborLabels": neighbor_labels,
    }


def _select_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def _evaluate_torch_classifier(
    model: nn.Module,
    loader: DataLoader[tuple[torch.Tensor, int]],
    device: torch.device,
    class_count: int,
) -> tuple[float, dict[str, float]]:
    criterion = nn.CrossEntropyLoss()
    model.eval()
    total_loss = 0.0
    total_items = 0
    all_true: list[np.ndarray] = []
    all_pred: list[np.ndarray] = []
    all_prob: list[np.ndarray] = []

    with torch.no_grad():
        for inputs, targets in loader:
            inputs = inputs.to(device)
            targets = targets.to(device)
            logits = model(inputs)
            loss = criterion(logits, targets)
            probabilities = torch.softmax(logits, dim=1)
            predictions = torch.argmax(probabilities, dim=1)

            batch_size = int(targets.shape[0])
            total_loss += float(loss.item()) * batch_size
            total_items += batch_size
            all_true.append(targets.cpu().numpy())
            all_pred.append(predictions.cpu().numpy())
            all_prob.append(probabilities.cpu().numpy())

    y_true = np.concatenate(all_true) if all_true else np.array([], dtype=np.int64)
    y_pred = np.concatenate(all_pred) if all_pred else np.array([], dtype=np.int64)
    y_prob = np.vstack(all_prob) if all_prob else np.zeros((0, class_count), dtype=np.float64)
    metrics = _compute_metrics(y_true, y_pred, y_prob, np.arange(class_count, dtype=np.int64), class_count)
    average_loss = total_loss / max(1, total_items)
    return average_loss, metrics


def _extract_embeddings_from_backbone(
    backbone: nn.Module,
    loader: DataLoader[tuple[torch.Tensor, int]],
    device: torch.device,
) -> np.ndarray:
    logger = get_logger()
    backbone.eval()
    embedding_batches: list[np.ndarray] = []
    logger.info(
        "Starting embedding extraction with fine-tuned ResNet backbone: batches=%s device=%s",
        len(loader),
        device,
    )

    with torch.no_grad():
        for batch_index, (inputs, _) in enumerate(loader, start=1):
            inputs = inputs.to(device)
            embedding_tensor = backbone(inputs)
            embedding_array = embedding_tensor.flatten(start_dim=1).cpu().numpy().astype(np.float32)
            embedding_batches.append(normalize_feature_matrix(embedding_array))
            if batch_index == 1 or batch_index == len(loader) or batch_index % 25 == 0:
                logger.info(
                    "Fine-tuned embedding extraction progress: batch=%s/%s",
                    batch_index,
                    len(loader),
                )

    logger.info("Completed embedding extraction from fine-tuned ResNet backbone")
    return np.vstack(embedding_batches).astype(np.float32)


def _fine_tune_resnet_and_extract_embeddings(
    service: ImageVectorService,
    encoded_labels: np.ndarray,
    train_indices: np.ndarray,
    validation_indices: np.ndarray,
    class_count: int,
) -> tuple[np.ndarray, dict[str, Any]]:
    logger = get_logger()
    device = _select_device()
    dataset = _CaltechEvaluationDataset(service, encoded_labels)
    generator = torch.Generator().manual_seed(VECTOR_RANDOM_SEED)
    logger.info(
        "Starting ResNet-18 fine-tuning: device=%s train_samples=%s validation_samples=%s class_count=%s epochs=%s batch_size=%s",
        device,
        len(train_indices),
        len(validation_indices),
        class_count,
        RESNET_FINETUNE_EPOCHS,
        RESNET_FINETUNE_BATCH_SIZE,
    )

    train_loader = DataLoader(
        Subset(dataset, train_indices.tolist()),
        batch_size=RESNET_FINETUNE_BATCH_SIZE,
        shuffle=True,
        num_workers=0,
        generator=generator,
    )
    train_eval_loader = DataLoader(
        Subset(dataset, train_indices.tolist()),
        batch_size=RESNET_FINETUNE_BATCH_SIZE,
        shuffle=False,
        num_workers=0,
    )
    validation_loader = DataLoader(
        Subset(dataset, validation_indices.tolist()),
        batch_size=RESNET_FINETUNE_BATCH_SIZE,
        shuffle=False,
        num_workers=0,
    )
    full_loader = DataLoader(
        dataset,
        batch_size=RESNET_FINETUNE_BATCH_SIZE,
        shuffle=False,
        num_workers=0,
    )

    if FINETUNED_MODEL_PATH.exists():
        logger.info(
            "Existing fine-tuned ResNet-18 backbone found at %s; development evaluation will retrain and overwrite it",
            FINETUNED_MODEL_PATH,
        )

    model = resnet18(weights=service.extractor.weights)
    for parameter in model.parameters():
        parameter.requires_grad = False
    for parameter in model.layer4.parameters():
        parameter.requires_grad = True
    model.fc = nn.Linear(model.fc.in_features, class_count)
    model = model.to(device)

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.AdamW(
        [parameter for parameter in model.parameters() if parameter.requires_grad],
        lr=RESNET_FINETUNE_LEARNING_RATE,
        weight_decay=RESNET_FINETUNE_WEIGHT_DECAY,
    )

    best_state = copy.deepcopy(model.state_dict())
    best_validation_macro_f1 = float("-inf")
    best_epoch = 0
    epochs_without_improvement = 0
    epoch_rows: list[list[str]] = []
    epoch_history: list[dict[str, float]] = []
    started_at = time.perf_counter()
    logger.info(
        "Prepared fine-tuning data loaders: train_batches=%s train_eval_batches=%s validation_batches=%s full_dataset_batches=%s",
        len(train_loader),
        len(train_eval_loader),
        len(validation_loader),
        len(full_loader),
    )

    for epoch in range(1, RESNET_FINETUNE_EPOCHS + 1):
        model.train()
        total_optimization_train_loss = 0.0
        total_train_items = 0
        logger.info("Fine-tuning epoch %s/%s started", epoch, RESNET_FINETUNE_EPOCHS)

        for inputs, targets in train_loader:
            inputs = inputs.to(device)
            targets = targets.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(inputs)
            loss = criterion(logits, targets)
            loss.backward()
            optimizer.step()

            batch_size = int(targets.shape[0])
            total_optimization_train_loss += float(loss.item()) * batch_size
            total_train_items += batch_size

        optimization_train_loss = total_optimization_train_loss / max(1, total_train_items)
        train_loss, train_metrics = _evaluate_torch_classifier(model, train_eval_loader, device, class_count)
        validation_loss, validation_metrics = _evaluate_torch_classifier(model, validation_loader, device, class_count)
        logger.info(
            "Fine-tuning epoch %s/%s finished: optimization_train_loss=%.4f train_loss=%.4f train_accuracy=%.4f train_macro_f1=%.4f val_loss=%.4f val_accuracy=%.4f val_macro_f1=%.4f val_balanced_accuracy=%.4f val_top3=%.4f",
            epoch,
            RESNET_FINETUNE_EPOCHS,
            optimization_train_loss,
            train_loss,
            train_metrics["accuracy"],
            train_metrics["macro_f1"],
            validation_loss,
            validation_metrics["accuracy"],
            validation_metrics["macro_f1"],
            validation_metrics["balanced_accuracy"],
            validation_metrics["top3_accuracy"],
        )
        epoch_rows.append(
            [
                str(epoch),
                f"{train_loss:.4f}",
                f"{validation_loss:.4f}",
                f"{validation_metrics['accuracy']:.4f}",
                f"{validation_metrics['macro_f1']:.4f}",
                f"{validation_metrics['balanced_accuracy']:.4f}",
                f"{validation_metrics['top3_accuracy']:.4f}",
            ]
        )
        epoch_history.append(
            {
                "epoch": float(epoch),
                "trainLoss": train_loss,
                "validationLoss": validation_loss,
                "validationAccuracy": validation_metrics["accuracy"],
                "validationMacroF1": validation_metrics["macro_f1"],
            }
        )

        if validation_metrics["macro_f1"] > best_validation_macro_f1:
            best_validation_macro_f1 = validation_metrics["macro_f1"]
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
            epochs_without_improvement = 0
            logger.info(
                "Fine-tuning found a new best checkpoint at epoch %s with val_macro_f1=%.4f",
                epoch,
                best_validation_macro_f1,
            )
        else:
            epochs_without_improvement += 1
            logger.info(
                "Fine-tuning epoch %s did not improve best val_macro_f1; patience_progress=%s/%s",
                epoch,
                epochs_without_improvement,
                RESNET_FINETUNE_PATIENCE,
            )
            if epochs_without_improvement >= RESNET_FINETUNE_PATIENCE:
                logger.info(
                    "Early stopping triggered for fine-tuning at epoch %s after %s non-improving epoch(s)",
                    epoch,
                    epochs_without_improvement,
                )
                break

    training_seconds = time.perf_counter() - started_at
    model.load_state_dict(best_state)
    logger.info(
        "Restored best fine-tuned checkpoint from epoch %s; total_training_seconds=%.3f",
        best_epoch,
        training_seconds,
    )

    logger.info(
        "ResNet-18 fine-tuning summary (train only, validation used for model selection; no test leakage)\n%s",
        _format_table(
            ["Epoch", "Train loss", "Val loss", "Val acc", "Val macro F1", "Val bal acc", "Val top3"],
            epoch_rows,
        ),
    )

    backbone = nn.Sequential(*list(model.children())[:-1]).to(device)
    ensure_directory(FINETUNED_MODEL_PATH.parent)
    torch.save({key: value.detach().cpu() for key, value in backbone.state_dict().items()}, FINETUNED_MODEL_PATH)
    logger.info("Saved fine-tuned ResNet-18 backbone weights to %s", FINETUNED_MODEL_PATH)
    embeddings = _extract_embeddings_from_backbone(backbone, full_loader, device)
    model_size_kb = len(pickle.dumps({key: value.detach().cpu() for key, value in model.state_dict().items()})) / 1024.0
    metadata = {
        "epochsRequested": RESNET_FINETUNE_EPOCHS,
        "epochsCompleted": len(epoch_rows),
        "bestEpoch": best_epoch,
        "learningRate": RESNET_FINETUNE_LEARNING_RATE,
        "weightDecay": RESNET_FINETUNE_WEIGHT_DECAY,
        "batchSize": RESNET_FINETUNE_BATCH_SIZE,
        "device": str(device),
        "bestValidationMacroF1": best_validation_macro_f1,
        "trainingSeconds": training_seconds,
        "modelSizeKb": model_size_kb,
        "epochHistory": epoch_history,
        "reusedExistingBackbone": False,
    }
    return embeddings, metadata


def _predict_with_timing(estimator: Any, features: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    started_at = time.perf_counter()
    predictions = estimator.predict(features)
    probabilities = estimator.predict_proba(features)
    elapsed_seconds = time.perf_counter() - started_at
    return predictions, probabilities, np.asarray(estimator.classes_, dtype=np.int64), elapsed_seconds


def _bootstrap_confidence_intervals(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_prob: np.ndarray,
    estimator_classes: np.ndarray,
    class_count: int,
    seed: int,
) -> dict[str, dict[str, float]]:
    logger = get_logger()
    rng = np.random.default_rng(seed)
    sampled_metrics: dict[str, list[float]] = defaultdict(list)
    logger.info(
        "Starting bootstrap confidence intervals: samples=%s rounds=%s seed=%s",
        len(y_true),
        BOOTSTRAP_ROUNDS,
        seed,
    )

    for round_index in range(BOOTSTRAP_ROUNDS):
        sample_indices = rng.integers(0, len(y_true), size=len(y_true))
        metrics = _compute_metrics(
            y_true[sample_indices],
            y_pred[sample_indices],
            y_prob[sample_indices],
            estimator_classes,
            class_count,
        )
        for name, value in metrics.items():
            sampled_metrics[name].append(value)

        if round_index == 0 or round_index + 1 == BOOTSTRAP_ROUNDS or (round_index + 1) % 10 == 0:
            logger.info(
                "Bootstrap progress: round=%s/%s",
                round_index + 1,
                BOOTSTRAP_ROUNDS,
            )

    logger.info("Completed bootstrap confidence intervals")
    return {
        name: {
            "low": float(np.percentile(values, 2.5)),
            "high": float(np.percentile(values, 97.5)),
        }
        for name, values in sampled_metrics.items()
    }


def _build_structured_features(service: ImageVectorService) -> tuple[np.ndarray, np.ndarray]:
    logger = get_logger()
    labels: list[str] = []
    feature_rows: list[np.ndarray] = []
    logger.info("Starting structured feature extraction for %s dataset images", len(service.test_records))

    for record_index, record in enumerate(service.test_records, start=1):
        image_bytes = record.file_path.read_bytes()
        image = service.extractor.decode_image(image_bytes)
        relative_path = PurePosixPath(record.relative_path)
        if len(relative_path.parts) >= 2:
            class_name = relative_path.parts[-2]
        else:
            class_name = relative_path.stem
        labels.append(class_name)
        feature_rows.append(service.extractor.extract_structured_features(image))

        if record_index == 1 or record_index == len(service.test_records) or record_index % 500 == 0:
            logger.info(
                "Structured feature extraction progress: image=%s/%s class=%s",
                record_index,
                len(service.test_records),
                class_name,
            )

    logger.info("Completed structured feature extraction")
    return np.array(labels, dtype=object), np.vstack(feature_rows).astype(np.float32)


def _build_knn_estimator(params: dict[str, Any]) -> Pipeline:
    return Pipeline(
        [
            (
                "model",
                KNeighborsClassifier(
                    metric="cosine",
                    algorithm="brute",
                    n_neighbors=int(params["model__n_neighbors"]),
                    weights=str(params["model__weights"]),
                ),
            )
        ]
    )


def _build_random_forest_estimator(seed: int, params: dict[str, Any], cnn_feature_start: int) -> Pipeline:
    return Pipeline(
        [
            (
                "preprocessor",
                ColumnTransformer(
                    transformers=[
                        ("base_features", "passthrough", slice(0, cnn_feature_start)),
                        (
                            "cnn_pca",
                            Pipeline(
                                [
                                    ("scaler", StandardScaler()),
                                    ("pca", PCA(n_components=RF_CNN_PCA_COMPONENTS, random_state=seed)),
                                ]
                            ),
                            slice(cnn_feature_start, None),
                        ),
                    ]
                ),
            ),
            (
                "model",
                RandomForestClassifier(
                    n_estimators=int(params["model__n_estimators"]),
                    max_depth=None if params["model__max_depth"] in {None, "None"} else int(params["model__max_depth"]),
                    min_samples_leaf=int(params["model__min_samples_leaf"]),
                    max_features="sqrt",
                    class_weight="balanced_subsample",
                    n_jobs=-1,
                    random_state=seed,
                ),
            ),
        ]
    )


def _hyperparameter_rows_for_knn() -> list[dict[str, Any]]:
    return [
        {
            "model__n_neighbors": neighbors,
            "model__weights": weights,
        }
        for neighbors in (3, 5, 7, 9)
        for weights in ("uniform", "distance",)
    ]


def _hyperparameter_rows_for_random_forest() -> list[dict[str, Any]]:
    return [
        {
            "model__n_estimators": estimators,
            "model__max_depth": max_depth,
            "model__min_samples_leaf": min_samples_leaf,
        }
        for estimators in (100, 200, 300)
        for max_depth in (None, 20)
        for min_samples_leaf in (1, 2)
    ]


def _cross_validate_candidates(
    model_name: str,
    build_estimator: Any,
    candidates: list[dict[str, Any]],
    features: np.ndarray,
    labels: np.ndarray,
    class_count: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    logger = get_logger()
    splitter = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=VECTOR_RANDOM_SEED)
    results: list[dict[str, Any]] = []
    logger.info(
        "Starting hyperparameter search for %s: candidates=%s folds=%s samples=%s",
        model_name,
        len(candidates),
        CV_FOLDS,
        len(labels),
    )

    for candidate_index, candidate in enumerate(candidates, start=1):
        fold_metrics: list[dict[str, float]] = []
        fit_durations: list[float] = []
        logger.info(
            "Evaluating candidate %s/%s for %s: %s",
            candidate_index,
            len(candidates),
            model_name,
            candidate,
        )

        for fold_index, (train_indices, validation_indices) in enumerate(splitter.split(features, labels), start=1):
            estimator = build_estimator(candidate)
            started_at = time.perf_counter()
            estimator.fit(features[train_indices], labels[train_indices])
            fit_durations.append(time.perf_counter() - started_at)
            predictions, probabilities, estimator_classes, _ = _predict_with_timing(estimator, features[validation_indices])
            fold_metric = _compute_metrics(
                labels[validation_indices],
                predictions,
                probabilities,
                estimator_classes,
                class_count,
            )
            fold_metrics.append(fold_metric)
            logger.info(
                "Candidate %s/%s fold %s/%s for %s: fit_seconds=%.3f accuracy=%.4f macro_f1=%.4f balanced_accuracy=%.4f top3_accuracy=%.4f",
                candidate_index,
                len(candidates),
                fold_index,
                CV_FOLDS,
                model_name,
                fit_durations[-1],
                fold_metric["accuracy"],
                fold_metric["macro_f1"],
                fold_metric["balanced_accuracy"],
                fold_metric["top3_accuracy"],
            )

        result = {
            "params": candidate,
            "cv_accuracy_mean": float(np.mean([metric["accuracy"] for metric in fold_metrics])),
            "cv_accuracy_std": float(np.std([metric["accuracy"] for metric in fold_metrics])),
            "cv_macro_f1_mean": float(np.mean([metric["macro_f1"] for metric in fold_metrics])),
            "cv_macro_f1_std": float(np.std([metric["macro_f1"] for metric in fold_metrics])),
            "cv_balanced_accuracy_mean": float(np.mean([metric["balanced_accuracy"] for metric in fold_metrics])),
            "cv_balanced_accuracy_std": float(np.std([metric["balanced_accuracy"] for metric in fold_metrics])),
            "cv_fit_seconds_mean": float(np.mean(fit_durations)),
        }
        results.append(result)
        logger.info(
            "Candidate %s/%s summary for %s: cv_accuracy_mean=%.4f cv_macro_f1_mean=%.4f cv_balanced_accuracy_mean=%.4f mean_fit_seconds=%.3f",
            candidate_index,
            len(candidates),
            model_name,
            result["cv_accuracy_mean"],
            result["cv_macro_f1_mean"],
            result["cv_balanced_accuracy_mean"],
            result["cv_fit_seconds_mean"],
        )

    table_rows = [
        [
            ", ".join(f"{key}={value}" for key, value in item["params"].items()),
            f"{item['cv_accuracy_mean']:.4f} +/- {item['cv_accuracy_std']:.4f}",
            f"{item['cv_macro_f1_mean']:.4f} +/- {item['cv_macro_f1_std']:.4f}",
            f"{item['cv_balanced_accuracy_mean']:.4f} +/- {item['cv_balanced_accuracy_std']:.4f}",
            f"{item['cv_fit_seconds_mean']:.3f}",
        ]
        for item in results
    ]
    logger.info(
        "Hyperparameter search for %s\n%s",
        model_name,
        _format_table(
            ["Parameters", "CV accuracy", "CV macro F1", "CV balanced acc", "Mean fit sec"],
            table_rows,
        ),
    )

    best_result = max(results, key=lambda item: (item["cv_macro_f1_mean"], item["cv_accuracy_mean"]))
    return results, best_result


async def run_development_evaluation(service: ImageVectorService) -> None:
    logger = get_logger()
    _seed_everything(VECTOR_RANDOM_SEED)
    logger.info(
        "Development evaluation mode enabled with fixed random seed %s and deterministic split ratios train=%.2f val=%.2f test=%.2f",
        VECTOR_RANDOM_SEED,
        VECTOR_TRAIN_RATIO,
        VECTOR_VAL_RATIO,
        VECTOR_TEST_RATIO,
    )
    logger.info("Development evaluation uses only the first %s sorted Caltech-101 images", VECTOR_DEV_DATASET_LIMIT)

    dataset_size = len(service.test_records)
    logger.info("Development evaluation pipeline started with dataset_size=%s", dataset_size)
    if dataset_size == 0:
        logger.warning("Skipping development evaluation because the fixed dataset is empty")
        return

    logger.info("Stage 1/7: building structured features")
    label_names, structured_features = _build_structured_features(service)
    label_encoder = LabelEncoder()
    encoded_labels = label_encoder.fit_transform(label_names)
    logger.info("Structured features ready: feature_shape=%s class_count=%s", structured_features.shape, len(label_encoder.classes_))

    logger.info("Stage 2/7: generating stratified train/validation/test split")
    split_indices = _build_stratified_split(encoded_labels, VECTOR_RANDOM_SEED)

    train_indices = split_indices["train"]
    validation_indices = split_indices["validation"]
    test_indices = split_indices["test"]
    train_validation_indices = np.concatenate([train_indices, validation_indices])
    class_count = len(label_encoder.classes_)

    if service.hist_index is None or service.hist_index.shape[0] < dataset_size:
        logger.warning("Development evaluation detected an incomplete feature index; rebuilding before evaluation")
        await service.rebuild_index()

    if service.hist_index is None or service.cnn_index is None or service.cnn_index.shape[0] < dataset_size:
        raise RuntimeError("Feature indices are unavailable after rebuild in development mode.")

    logger.info("Stage 3/7: loading pretrained feature matrices from the rebuilt search index")
    pretrained_cnn_features = service.cnn_index[:dataset_size].astype(np.float32)

    if service.hist_index is None:
        raise RuntimeError("Color histogram index is unavailable after rebuild in development mode.")

    logger.info("Stage 4/7: fine-tuning ResNet-18 on the training split and extracting updated embeddings")
    finetuned_cnn_features, resnet_finetune_metadata = _fine_tune_resnet_and_extract_embeddings(
        service,
        encoded_labels,
        train_indices,
        validation_indices,
        class_count,
    )
    hist_features = service.hist_index[:dataset_size].astype(np.float32)
    random_forest_features = np.hstack([hist_features, structured_features, finetuned_cnn_features]).astype(np.float32)
    random_forest_cnn_feature_start = hist_features.shape[1] + structured_features.shape[1]
    logger.info(
        "Feature matrices ready: hist_shape=%s pretrained_cnn_shape=%s finetuned_cnn_shape=%s random_forest_shape=%s",
        hist_features.shape,
        pretrained_cnn_features.shape,
        finetuned_cnn_features.shape,
        random_forest_features.shape,
    )

    split_payload = {
        "seed": VECTOR_RANDOM_SEED,
        "strategy": "stratified split by class labels; temporal split is not applicable because the dataset has no timestamp field",
        "counts": {
            "dataset": int(dataset_size),
            "train": int(len(train_indices)),
            "validation": int(len(validation_indices)),
            "test": int(len(test_indices)),
        },
    }
    logger.info(
        "Stratified split prepared: train=%s validation=%s test=%s",
        len(train_indices),
        len(validation_indices),
        len(test_indices),
    )

    model_specs = [
        {
            "name": "Baseline histogram kNN",
            "features": hist_features,
            "build_estimator": _build_knn_estimator,
            "candidates": _hyperparameter_rows_for_knn(),
        },
        {
            "name": "ResNet-18 embedding kNN (pretrained)",
            "features": pretrained_cnn_features,
            "build_estimator": _build_knn_estimator,
            "candidates": _hyperparameter_rows_for_knn(),
        },
        {
            "name": "ResNet-18 embedding kNN (fine-tuned)",
            "features": finetuned_cnn_features,
            "build_estimator": _build_knn_estimator,
            "candidates": _hyperparameter_rows_for_knn(),
            "extraTrainSeconds": resnet_finetune_metadata["trainingSeconds"],
            "extraModelSizeKb": resnet_finetune_metadata["modelSizeKb"],
            "featureTraining": resnet_finetune_metadata,
        },
        {
            "name": "RandomForestClassifier ensemble",
            "features": random_forest_features,
            "build_estimator": lambda params: _build_random_forest_estimator(
                VECTOR_RANDOM_SEED,
                params,
                random_forest_cnn_feature_start,
            ),
            "candidates": _hyperparameter_rows_for_random_forest(),
        },
    ]

    report_models: list[dict[str, Any]] = []
    comparative_rows: list[list[str]] = []

    fine_tuned_plot_context: dict[str, Any] | None = None

    logger.info("Stage 5/8: running model selection and validation across %s model families", len(model_specs))
    for model_index, spec in enumerate(model_specs, start=1):
        logger.info("Model pipeline %s/%s started: %s", model_index, len(model_specs), spec["name"])
        feature_matrix = spec["features"]
        candidate_results, best_candidate = _cross_validate_candidates(
            spec["name"],
            spec["build_estimator"],
            spec["candidates"],
            feature_matrix[train_indices],
            encoded_labels[train_indices],
            class_count,
        )

        validation_estimator = spec["build_estimator"](best_candidate["params"])
        validation_estimator.fit(feature_matrix[train_indices], encoded_labels[train_indices])
        validation_predictions, validation_probabilities, validation_classes, _ = _predict_with_timing(
            validation_estimator,
            feature_matrix[validation_indices],
        )
        validation_metrics = _compute_metrics(
            encoded_labels[validation_indices],
            validation_predictions,
            validation_probabilities,
            validation_classes,
            class_count,
        )
        logger.info(
            "Validation metrics for %s with best params %s: accuracy=%.4f macro_f1=%.4f balanced_accuracy=%.4f top3_accuracy=%.4f",
            spec["name"],
            best_candidate["params"],
            validation_metrics["accuracy"],
            validation_metrics["macro_f1"],
            validation_metrics["balanced_accuracy"],
            validation_metrics["top3_accuracy"],
        )

        logger.info("Stage 6/8 for %s: fitting final estimator on train+validation and scoring on test", spec["name"])
        final_estimator = spec["build_estimator"](best_candidate["params"])
        fit_started_at = time.perf_counter()
        final_estimator.fit(feature_matrix[train_validation_indices], encoded_labels[train_validation_indices])
        train_seconds = time.perf_counter() - fit_started_at
        total_train_seconds = train_seconds + float(spec.get("extraTrainSeconds", 0.0))
        test_predictions, test_probabilities, test_classes, prediction_seconds = _predict_with_timing(
            final_estimator,
            feature_matrix[test_indices],
        )
        test_metrics = _compute_metrics(
            encoded_labels[test_indices],
            test_predictions,
            test_probabilities,
            test_classes,
            class_count,
        )
        confidence_intervals = _bootstrap_confidence_intervals(
            encoded_labels[test_indices],
            test_predictions,
            test_probabilities,
            test_classes,
            class_count,
            VECTOR_RANDOM_SEED,
        )
        retrieval_report = _evaluate_retrieval(
            feature_matrix[test_indices],
            feature_matrix[train_validation_indices],
            encoded_labels[test_indices],
            encoded_labels[train_validation_indices],
            int(best_candidate["params"].get("model__n_neighbors", 1)),
            RETRIEVAL_TOP_K,
        )
        model_size_kb = len(pickle.dumps(final_estimator)) / 1024.0
        prediction_milliseconds = (prediction_seconds / max(1, len(test_indices))) * 1000.0
        logger.info(
            "Test metrics for %s: accuracy=%.4f macro_f1=%.4f balanced_accuracy=%.4f top3_accuracy=%.4f train_seconds=%.3f prediction_ms_per_sample=%.3f model_size_kb=%.1f retrieval_p10=%.4f retrieval_map10=%.4f",
            spec["name"],
            test_metrics["accuracy"],
            test_metrics["macro_f1"],
            test_metrics["balanced_accuracy"],
            test_metrics["top3_accuracy"],
            total_train_seconds,
            prediction_milliseconds,
            model_size_kb + float(spec.get("extraModelSizeKb", 0.0)),
            retrieval_report["metrics"]["precisionAt10"],
            retrieval_report["metrics"]["meanAveragePrecisionAt10"],
        )

        report_entry = {
            "name": spec["name"],
            "bestParams": best_candidate["params"],
            "candidateResults": candidate_results,
            "validationMetrics": validation_metrics,
            "testMetrics": test_metrics,
            "testConfidenceIntervals": confidence_intervals,
            "retrievalMetrics": retrieval_report["metrics"],
            "retrievalConfidenceIntervals": retrieval_report["confidenceIntervals"],
            "trainSeconds": total_train_seconds,
            "predictionMillisecondsPerSample": prediction_milliseconds,
            "modelSizeKb": model_size_kb + float(spec.get("extraModelSizeKb", 0.0)),
            "featureTraining": spec.get("featureTraining"),
        }
        report_models.append(report_entry)

        if spec["name"] == "ResNet-18 embedding kNN (fine-tuned)":
            fine_tuned_plot_context = {
                "featureMatrix": feature_matrix,
                "bestParams": best_candidate["params"],
                "candidateResults": candidate_results,
                "featureTraining": spec.get("featureTraining") or {},
                "retrieval": retrieval_report,
                "testPredictions": test_predictions,
                "testProbabilities": test_probabilities,
                "testClasses": test_classes,
                "finalEstimator": final_estimator,
                "encodedLabels": encoded_labels,
                "alignedTestProbabilities": _align_probabilities_to_global_classes(
                    test_probabilities,
                    test_classes,
                    class_count,
                ),
            }

        comparative_rows.append(
            [
                spec["name"],
                f"{test_metrics['accuracy']:.4f} [{confidence_intervals['accuracy']['low']:.4f}, {confidence_intervals['accuracy']['high']:.4f}]",
                f"{test_metrics['macro_f1']:.4f} [{confidence_intervals['macro_f1']['low']:.4f}, {confidence_intervals['macro_f1']['high']:.4f}]",
                f"{test_metrics['balanced_accuracy']:.4f} [{confidence_intervals['balanced_accuracy']['low']:.4f}, {confidence_intervals['balanced_accuracy']['high']:.4f}]",
                f"{test_metrics['top3_accuracy']:.4f} [{confidence_intervals['top3_accuracy']['low']:.4f}, {confidence_intervals['top3_accuracy']['high']:.4f}]",
                f"{total_train_seconds:.3f}",
                f"{prediction_milliseconds:.3f}",
                f"{model_size_kb + float(spec.get('extraModelSizeKb', 0.0)):.1f}",
            ]
        )
        logger.info("Model pipeline %s/%s finished: %s", model_index, len(model_specs), spec["name"])

    if fine_tuned_plot_context is None:
        raise RuntimeError("Fine-tuned ResNet-18 evaluation results are missing; plot generation cannot continue.")

    logger.info("Stage 7/8: generating development plots")
    plot_bundle = generate_development_plots(
        service=service,
        report_models=report_models,
        fine_tuned_plot_context=fine_tuned_plot_context,
        label_classes=label_encoder.classes_,
        encoded_test_labels=encoded_labels[test_indices],
        test_indices=test_indices,
        train_validation_indices=train_validation_indices,
        class_count=class_count,
    )

    fine_tuned_entry = next(item for item in report_models if item["name"] == "ResNet-18 embedding kNN (fine-tuned)")
    fine_tuned_entry["plots"] = plot_bundle["fineTunedPlots"]

    logger.info("Stage 8/8: writing comparative report artifact")
    logger.info(
        "Comparative model table\n%s",
        _format_table(
            [
                "Model",
                "Accuracy (95% CI)",
                "Macro F1 (95% CI)",
                "Balanced acc (95% CI)",
                "Top-3 acc (95% CI)",
                "Train sec",
                "Pred ms/sample",
                "Size KB",
            ],
            comparative_rows,
        ),
    )

    report_payload = {
        "seed": VECTOR_RANDOM_SEED,
        "datasetSize": int(dataset_size),
        "split": split_payload,
        "models": report_models,
        "plots": {
            "directory": str(DEV_PLOTS_DIR),
            "items": plot_bundle["allPlots"],
        },
    }
    ensure_directory(DEV_EVALUATION_PATH.parent)
    write_json(DEV_EVALUATION_PATH, report_payload)
    logger.info(
        "Development evaluation report saved to %s with %s models",
        DEV_EVALUATION_PATH,
        len(report_models),
    )