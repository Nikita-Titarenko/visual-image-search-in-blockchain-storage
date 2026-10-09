from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import matplotlib
import numpy as np
from sklearn.inspection import permutation_importance
from sklearn.metrics import auc, confusion_matrix, precision_recall_curve, roc_curve
from sklearn.preprocessing import label_binarize

from config import DEV_PLOTS_DIR, VECTOR_RANDOM_SEED
from utils import ensure_directory


matplotlib.use("Agg")
from matplotlib import pyplot as plt


if TYPE_CHECKING:
    from service import ImageVectorService


PLOT_QUERY_EXAMPLES = 4
PERMUTATION_IMPORTANCE_REPEATS = 5
PERMUTATION_IMPORTANCE_TOP_FEATURES = 20
PERMUTATION_IMPORTANCE_SAMPLE_LIMIT = 256


def _compute_micro_curves(y_true: np.ndarray, y_prob: np.ndarray, class_count: int) -> dict[str, Any]:
    y_true_binarized = label_binarize(y_true, classes=np.arange(class_count))
    flattened_true = y_true_binarized.ravel()
    flattened_prob = y_prob.ravel()
    roc_fpr, roc_tpr, _ = roc_curve(flattened_true, flattened_prob)
    pr_precision, pr_recall, _ = precision_recall_curve(flattened_true, flattened_prob)
    return {
        "rocFpr": roc_fpr,
        "rocTpr": roc_tpr,
        "rocAuc": float(auc(roc_fpr, roc_tpr)),
        "prPrecision": pr_precision,
        "prRecall": pr_recall,
        "averagePrecision": float(np.trapezoid(pr_precision[::-1], pr_recall[::-1])),
    }


def _save_plot(figure: Any, destination: Path) -> None:
    figure.tight_layout()
    figure.savefig(destination, dpi=200, bbox_inches="tight")
    plt.close(figure)


def _save_learning_curve_plot(destination: Path, epoch_history: list[dict[str, float]]) -> None:
    epochs = [int(item["epoch"]) for item in epoch_history]
    train_loss = [float(item["trainLoss"]) for item in epoch_history]
    validation_loss = [float(item["validationLoss"]) for item in epoch_history]
    figure, axis = plt.subplots(figsize=(8, 5))
    axis.plot(epochs, train_loss, marker="o", linewidth=2, label="Train loss")
    axis.plot(epochs, validation_loss, marker="s", linewidth=2, label="Validation loss")
    axis.set_title("Fine-tuned ResNet-18 learning curve")
    axis.set_xlabel("Epoch")
    axis.set_ylabel("Loss")
    axis.grid(alpha=0.3)
    axis.legend()
    _save_plot(figure, destination)


def _save_confusion_matrix_plot(destination: Path, matrix: np.ndarray, class_names: np.ndarray) -> None:
    class_count = len(class_names)
    figure, axis = plt.subplots(figsize=(max(18, class_count * 0.22), max(16, class_count * 0.22)))
    image = axis.imshow(matrix, interpolation="nearest", cmap="Blues")
    figure.colorbar(image, ax=axis, fraction=0.02, pad=0.02)
    axis.set_title("Fine-tuned ResNet-18 retrieval confusion matrix")
    axis.set_xlabel("Predicted class")
    axis.set_ylabel("True class")
    ticks = np.arange(class_count)
    axis.set_xticks(ticks)
    axis.set_yticks(ticks)
    axis.set_xticklabels(class_names, rotation=90, fontsize=5)
    axis.set_yticklabels(class_names, fontsize=5)
    _save_plot(figure, destination)


def _save_curve_plot(
    destination: Path,
    x_values: np.ndarray,
    y_values: np.ndarray,
    title: str,
    x_label: str,
    y_label: str,
    legend_label: str,
) -> None:
    figure, axis = plt.subplots(figsize=(7, 5))
    axis.plot(x_values, y_values, linewidth=2, label=legend_label)
    axis.set_title(title)
    axis.set_xlabel(x_label)
    axis.set_ylabel(y_label)
    axis.grid(alpha=0.3)
    axis.legend()
    _save_plot(figure, destination)


def _save_feature_importance_plot(destination: Path, importances: np.ndarray) -> None:
    top_indices = np.argsort(importances)[-PERMUTATION_IMPORTANCE_TOP_FEATURES:][::-1]
    top_values = importances[top_indices]
    labels = [f"dim_{index}" for index in top_indices.tolist()]
    figure, axis = plt.subplots(figsize=(10, 6))
    axis.bar(np.arange(len(labels)), top_values, color="#2f6db2")
    axis.set_title("Fine-tuned ResNet-18 embedding feature importance")
    axis.set_xlabel("Embedding dimension")
    axis.set_ylabel("Permutation importance (macro F1 drop)")
    axis.set_xticks(np.arange(len(labels)))
    axis.set_xticklabels(labels, rotation=60, ha="right", fontsize=8)
    axis.grid(axis="y", alpha=0.3)
    _save_plot(figure, destination)


def _save_hyperparameter_impact_plot(destination: Path, candidate_results: list[dict[str, Any]]) -> None:
    sorted_candidates = sorted(candidate_results, key=lambda item: int(item["params"]["model__n_neighbors"]))
    x_values = np.array([int(item["params"]["model__n_neighbors"]) for item in sorted_candidates], dtype=np.int64)
    y_values = np.array([float(item["cv_macro_f1_mean"]) for item in sorted_candidates], dtype=np.float64)
    y_errors = np.array([float(item["cv_macro_f1_std"]) for item in sorted_candidates], dtype=np.float64)
    figure, axis = plt.subplots(figsize=(7, 5))
    axis.errorbar(x_values, y_values, yerr=y_errors, marker="o", linewidth=2, capsize=5)
    axis.set_title("Impact of n_neighbors on CV macro F1")
    axis.set_xlabel("n_neighbors")
    axis.set_ylabel("Cross-validation macro F1")
    axis.grid(alpha=0.3)
    _save_plot(figure, destination)


def _save_error_examples_plot(
    destination: Path,
    service: ImageVectorService,
    query_indices: np.ndarray,
    predicted_labels: np.ndarray,
    true_labels: np.ndarray,
    neighbor_indices: np.ndarray,
    class_names: np.ndarray,
) -> None:
    misclassified_positions = np.where(predicted_labels != true_labels)[0][:PLOT_QUERY_EXAMPLES]
    positions = misclassified_positions if misclassified_positions.size > 0 else np.arange(min(PLOT_QUERY_EXAMPLES, len(query_indices)))
    rows = len(positions)
    figure, axes = plt.subplots(rows, 4, figsize=(14, max(4, rows * 3.2)))
    if rows == 1:
        axes = np.expand_dims(axes, axis=0)

    for row_index, position in enumerate(positions.tolist()):
        query_record = service.test_records[int(query_indices[position])]
        query_image = service.extractor.decode_image(query_record.file_path.read_bytes())
        axes[row_index, 0].imshow(query_image)
        axes[row_index, 0].set_title(
            f"Query\ntrue={class_names[int(true_labels[position])]}\npred={class_names[int(predicted_labels[position])]}",
            fontsize=8,
        )
        axes[row_index, 0].axis("off")

        for neighbor_rank in range(3):
            neighbor_index = int(neighbor_indices[position, neighbor_rank])
            neighbor_record = service.test_records[neighbor_index]
            neighbor_image = service.extractor.decode_image(neighbor_record.file_path.read_bytes())
            neighbor_label = PurePosixPath(neighbor_record.relative_path).parts[-2]
            axes[row_index, neighbor_rank + 1].imshow(neighbor_image)
            axes[row_index, neighbor_rank + 1].set_title(
                f"Rank {neighbor_rank + 1}\n{neighbor_label}",
                fontsize=8,
            )
            axes[row_index, neighbor_rank + 1].axis("off")

    figure.suptitle("Fine-tuned ResNet-18 wrong retrieval examples", fontsize=14)
    _save_plot(figure, destination)


def _save_similarity_distribution_plot(destination: Path, correct_scores: np.ndarray, incorrect_scores: np.ndarray) -> None:
    figure, axis = plt.subplots(figsize=(8, 5))
    axis.hist(correct_scores, bins=30, alpha=0.7, label="Correct class pairs", color="#2a9d8f", density=True)
    axis.hist(incorrect_scores, bins=30, alpha=0.7, label="Incorrect class pairs", color="#e76f51", density=True)
    axis.set_title("Cosine similarity distribution for correct vs incorrect pairs")
    axis.set_xlabel("Cosine similarity")
    axis.set_ylabel("Density")
    axis.grid(alpha=0.3)
    axis.legend()
    _save_plot(figure, destination)


def _save_model_comparison_plot(destination: Path, model_reports: list[dict[str, Any]]) -> None:
    ordered_metrics = [
        ("precisionAt1", "P@1"),
        ("precisionAt5", "P@5"),
        ("precisionAt10", "P@10"),
        ("meanAveragePrecisionAt10", "mAP@10"),
    ]
    model_names = [str(item["name"]) for item in model_reports]
    x = np.arange(len(ordered_metrics))
    width = 0.18
    figure, axis = plt.subplots(figsize=(11, 6))

    for model_index, model_report in enumerate(model_reports):
        offsets = x + (model_index - (len(model_reports) - 1) / 2.0) * width
        values = [float(model_report["retrievalMetrics"][metric_name]) for metric_name, _ in ordered_metrics]
        lower_errors = [
            float(model_report["retrievalMetrics"][metric_name]) - float(model_report["retrievalConfidenceIntervals"][metric_name]["low"])
            for metric_name, _ in ordered_metrics
        ]
        upper_errors = [
            float(model_report["retrievalConfidenceIntervals"][metric_name]["high"]) - float(model_report["retrievalMetrics"][metric_name])
            for metric_name, _ in ordered_metrics
        ]
        axis.bar(
            offsets,
            values,
            width=width,
            yerr=np.vstack([lower_errors, upper_errors]),
            capsize=4,
            label=model_names[model_index],
        )

    axis.set_title("Retrieval metrics comparison across all models")
    axis.set_ylabel("Score")
    axis.set_ylim(0.0, 1.05)
    axis.set_xticks(x)
    axis.set_xticklabels([label for _, label in ordered_metrics])
    axis.grid(axis="y", alpha=0.3)
    axis.legend(fontsize=8)
    _save_plot(figure, destination)


def build_plot_manifest(paths: list[Path]) -> list[dict[str, str]]:
    return [{"name": path.stem, "path": str(path)} for path in paths]


def generate_development_plots(
    *,
    service: ImageVectorService,
    report_models: list[dict[str, Any]],
    fine_tuned_plot_context: dict[str, Any],
    label_classes: np.ndarray,
    encoded_test_labels: np.ndarray,
    test_indices: np.ndarray,
    train_validation_indices: np.ndarray,
    class_count: int,
) -> dict[str, Any]:
    ensure_directory(DEV_PLOTS_DIR)
    fine_tuned_y_prob = fine_tuned_plot_context["alignedTestProbabilities"]
    micro_curves = _compute_micro_curves(encoded_test_labels, fine_tuned_y_prob, class_count)
    confusion = confusion_matrix(
        encoded_test_labels,
        fine_tuned_plot_context["retrieval"]["predictions"],
        labels=np.arange(class_count),
    )

    permutation_sample_indices = test_indices
    if len(permutation_sample_indices) > PERMUTATION_IMPORTANCE_SAMPLE_LIMIT:
        sampled_positions = np.random.default_rng(VECTOR_RANDOM_SEED).choice(
            len(permutation_sample_indices),
            size=PERMUTATION_IMPORTANCE_SAMPLE_LIMIT,
            replace=False,
        )
        permutation_sample_indices = permutation_sample_indices[np.sort(sampled_positions)]
    permutation_result = permutation_importance(
        fine_tuned_plot_context["finalEstimator"],
        fine_tuned_plot_context["featureMatrix"][permutation_sample_indices],
        fine_tuned_plot_context["encodedLabels"][permutation_sample_indices],
        scoring="f1_macro",
        n_repeats=PERMUTATION_IMPORTANCE_REPEATS,
        random_state=VECTOR_RANDOM_SEED,
        n_jobs=1,
    )

    correct_similarity_scores = fine_tuned_plot_context["retrieval"]["neighborScores"][
        fine_tuned_plot_context["retrieval"]["neighborLabels"] == encoded_test_labels[:, None]
    ]
    incorrect_similarity_scores = fine_tuned_plot_context["retrieval"]["neighborScores"][
        fine_tuned_plot_context["retrieval"]["neighborLabels"] != encoded_test_labels[:, None]
    ]

    plot_paths = [
        DEV_PLOTS_DIR / "01_learning_curve.png",
        DEV_PLOTS_DIR / "02_confusion_matrix.png",
        DEV_PLOTS_DIR / "03_roc_curve.png",
        DEV_PLOTS_DIR / "04_pr_curve.png",
        DEV_PLOTS_DIR / "05_feature_importance.png",
        DEV_PLOTS_DIR / "06_model_comparison.png",
        DEV_PLOTS_DIR / "07_hyperparameter_impact.png",
        DEV_PLOTS_DIR / "08_error_examples.png",
        DEV_PLOTS_DIR / "09_similarity_distribution.png",
    ]

    _save_learning_curve_plot(plot_paths[0], fine_tuned_plot_context["featureTraining"].get("epochHistory", []))
    _save_confusion_matrix_plot(plot_paths[1], confusion, label_classes)
    _save_curve_plot(
        plot_paths[2],
        micro_curves["rocFpr"],
        micro_curves["rocTpr"],
        f"Fine-tuned ResNet-18 ROC curve (micro AUC={micro_curves['rocAuc']:.4f})",
        "False positive rate",
        "True positive rate",
        "Micro-average ROC",
    )
    _save_curve_plot(
        plot_paths[3],
        micro_curves["prRecall"],
        micro_curves["prPrecision"],
        f"Fine-tuned ResNet-18 PR curve (micro AP={micro_curves['averagePrecision']:.4f})",
        "Recall",
        "Precision",
        "Micro-average PR",
    )
    _save_feature_importance_plot(plot_paths[4], permutation_result.importances_mean)
    _save_model_comparison_plot(plot_paths[5], report_models)
    _save_hyperparameter_impact_plot(plot_paths[6], fine_tuned_plot_context["candidateResults"])
    _save_error_examples_plot(
        plot_paths[7],
        service,
        test_indices,
        fine_tuned_plot_context["retrieval"]["predictions"],
        encoded_test_labels,
        train_validation_indices[fine_tuned_plot_context["retrieval"]["neighborIndices"]],
        label_classes,
    )
    _save_similarity_distribution_plot(plot_paths[8], correct_similarity_scores, incorrect_similarity_scores)

    return {
        "plotPaths": plot_paths,
        "allPlots": build_plot_manifest(plot_paths),
        "fineTunedPlots": build_plot_manifest(plot_paths[:1] + plot_paths[1:2] + plot_paths[2:5] + plot_paths[6:9]),
    }
