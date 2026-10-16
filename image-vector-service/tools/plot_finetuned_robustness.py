from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image


SERVICE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = SERVICE_DIR / "state"
INPUT_PATH = STATE_DIR / "fine_tuned_robustness_evaluation.json"
DISTORTED_MANIFEST_PATH = STATE_DIR / "distorted_caltech" / "manifest.json"
TEST_OUTPUT_PATH = STATE_DIR / "fine_tuned_robustness_test_metrics.svg"
RETRIEVAL_OUTPUT_PATH = STATE_DIR / "fine_tuned_robustness_retrieval_metrics.svg"
PREVIEW_OUTPUT_PATH = STATE_DIR / "fine_tuned_robustness_distortion_preview.svg"

TEST_METRICS = [
    ("accuracy", "Accuracy"),
    ("macro_f1", "Macro F1"),
    ("balanced_accuracy", "Balanced accuracy"),
    ("top3_accuracy", "Top-3 accuracy"),
]
RETRIEVAL_METRICS = [
    ("precisionAt1", "Precision@1"),
    ("precisionAt5", "Precision@5"),
    ("precisionAt10", "Precision@10"),
    ("meanAveragePrecisionAt10", "mAP@10"),
]
METRIC_COLORS = ["#2563eb", "#f97316", "#059669", "#dc2626"]


@dataclass(frozen=True)
class RobustnessLevel:
    label: str
    metrics: dict[str, float]
    confidence_intervals: dict[str, dict[str, float]]


@dataclass(frozen=True)
class DistortionPreviewLevel:
    label: str
    directory: Path


def load_payload() -> dict[str, object]:
    payload = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    if not payload.get("levels"):
        raise RuntimeError(f"No robustness evaluation levels found in {INPUT_PATH}")
    return payload


def load_distorted_manifest() -> dict[str, object]:
    payload = json.loads(DISTORTED_MANIFEST_PATH.read_text(encoding="utf-8"))
    if not payload.get("levels"):
        raise RuntimeError(f"No distorted dataset levels found in {DISTORTED_MANIFEST_PATH}")
    return payload


def load_levels(payload: dict[str, object], metrics_key: str, interval_key: str) -> list[RobustnessLevel]:
    levels_payload = payload.get("levels", [])
    levels: list[RobustnessLevel] = []
    for item in levels_payload:
        if not isinstance(item, dict):
            continue
        levels.append(
            RobustnessLevel(
                label=str(item.get("displayName", item.get("level", "Unknown"))),
                metrics=dict(item[metrics_key]),
                confidence_intervals=dict(item[interval_key]),
            )
        )
    if not levels:
        raise RuntimeError(f"No robustness level entries could be parsed from {INPUT_PATH}")
    return levels


def load_preview_levels(manifest_payload: dict[str, object]) -> list[DistortionPreviewLevel]:
    preview_levels: list[DistortionPreviewLevel] = []
    for item in manifest_payload.get("levels", []):
        if not isinstance(item, dict):
            continue
        preview_levels.append(
            DistortionPreviewLevel(
                label=str(item.get("displayName", item.get("slug", "Unknown"))),
                directory=Path(str(item["directory"])),
            )
        )
    if len(preview_levels) < 3:
        raise RuntimeError(f"Expected at least three distorted preview levels in {DISTORTED_MANIFEST_PATH}")
    return preview_levels[:3]


def load_preview_source_paths(manifest_payload: dict[str, object], count: int = 3) -> list[Path]:
    source_root = Path(str(manifest_payload["sourceDatasetPath"]))
    image_paths = sorted(
        path
        for path in source_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
    )
    selected_paths: list[Path] = []
    seen_classes: set[str] = set()
    for path in image_paths:
        relative_path = path.relative_to(source_root)
        class_name = relative_path.parts[-2] if len(relative_path.parts) >= 2 else path.stem
        if class_name in seen_classes:
            continue
        selected_paths.append(path)
        seen_classes.add(class_name)
        if len(selected_paths) == count:
            break

    if len(selected_paths) < count:
        raise RuntimeError(
            f"Expected at least {count} images from distinct classes in {source_root}, found {len(selected_paths)}"
        )
    return selected_paths


def compute_axis_bounds(
    clean_reference: dict[str, float],
    levels: list[RobustnessLevel],
    metrics: list[tuple[str, str]],
) -> tuple[float, float]:
    lower_values: list[float] = []
    upper_values: list[float] = []
    for metric_key, _ in metrics:
        lower_values.append(float(clean_reference[metric_key]))
        upper_values.append(float(clean_reference[metric_key]))
        for level in levels:
            interval = level.confidence_intervals[metric_key]
            lower_values.append(float(interval["low"]))
            upper_values.append(float(interval["high"]))

    lower_bound = max(0.0, min(lower_values) - 0.04)
    upper_bound = min(1.02, max(upper_values) + 0.04)
    if upper_bound <= lower_bound:
        upper_bound = min(1.02, lower_bound + 0.1)
    return lower_bound, upper_bound


def render_metric_progression_chart(
    clean_reference: dict[str, float],
    levels: list[RobustnessLevel],
    metrics: list[tuple[str, str]],
    output_path: Path,
    title: str,
) -> None:
    figure, axis = plt.subplots(figsize=(14, 8))
    figure.patch.set_facecolor("#f8fafc")
    axis.set_facecolor("#f8fafc")

    x_labels = ["Clean", *[level.label for level in levels]]
    x_positions = np.arange(len(x_labels), dtype=float)

    for color, (metric_key, metric_label) in zip(METRIC_COLORS, metrics, strict=True):
        y_values = [float(clean_reference[metric_key]), *[float(level.metrics[metric_key]) for level in levels]]
        lower_errors = [0.0]
        upper_errors = [0.0]
        for level in levels:
            value = float(level.metrics[metric_key])
            interval = level.confidence_intervals[metric_key]
            lower_errors.append(value - float(interval["low"]))
            upper_errors.append(float(interval["high"]) - value)

        axis.errorbar(
            x_positions,
            y_values,
            yerr=np.array([lower_errors, upper_errors]),
            color=color,
            marker="o",
            markersize=7,
            linewidth=2.3,
            capsize=4,
            label=metric_label,
        )

        for position, value in zip(x_positions, y_values, strict=True):
            axis.text(
                position,
                value + 0.008,
                f"{value:.3f}",
                ha="center",
                va="bottom",
                fontsize=8,
                color="#1f2937",
            )

    axis.set_title(title, fontsize=18, fontweight="bold", color="#1f2937", pad=16)
    axis.set_xlabel("Distortion level", fontsize=12, fontweight="bold", color="#374151")
    axis.set_ylabel("Score", fontsize=12, fontweight="bold", color="#374151")
    axis.set_xticks(x_positions)
    axis.set_xticklabels(x_labels)
    axis.set_ylim(*compute_axis_bounds(clean_reference, levels, metrics))
    axis.grid(axis="y", color="#d1d5db", linestyle="--", linewidth=0.9, alpha=0.9)
    axis.set_axisbelow(True)
    axis.legend(frameon=False, loc="upper right")

    for spine in axis.spines.values():
        spine.set_color("#374151")
    axis.tick_params(colors="#4b5563")

    figure.tight_layout()
    figure.savefig(output_path, format="svg", bbox_inches="tight")
    plt.close(figure)


def render_distortion_preview_chart(
    source_paths: list[Path],
    source_root: Path,
    preview_levels: list[DistortionPreviewLevel],
    output_path: Path,
) -> None:
    figure, axes = plt.subplots(len(source_paths), len(preview_levels) + 1, figsize=(16, 11))
    figure.patch.set_facecolor("#f8fafc")
    if isinstance(axes, np.ndarray) and axes.ndim == 1:
        axes = axes.reshape(1, -1)

    column_titles = ["Original", *[level.label for level in preview_levels]]
    for column_index, title in enumerate(column_titles):
        axes[0, column_index].set_title(title, fontsize=14, fontweight="bold", color="#1f2937", pad=14)

    for row_index, source_path in enumerate(source_paths):
        relative_path = source_path.relative_to(source_root)
        row_label = "/".join(relative_path.parts[-2:]) if len(relative_path.parts) >= 2 else relative_path.name

        original_array = np.asarray(Image.open(source_path).convert("RGB"))
        axes[row_index, 0].imshow(original_array)
        axes[row_index, 0].set_ylabel(row_label, fontsize=10, fontweight="bold", color="#374151")

        for column_index, level in enumerate(preview_levels, start=1):
            distorted_path = level.directory / relative_path
            if not distorted_path.exists():
                raise FileNotFoundError(f"Missing distorted preview image: {distorted_path}")
            distorted_array = np.asarray(Image.open(distorted_path).convert("RGB"))
            axes[row_index, column_index].imshow(distorted_array)

        for column_index in range(len(preview_levels) + 1):
            axis = axes[row_index, column_index]
            axis.set_xticks([])
            axis.set_yticks([])
            axis.set_facecolor("#e5e7eb")
            for spine in axis.spines.values():
                spine.set_color("#cbd5e1")

    figure.suptitle(
        "Fine-tuned Robustness Preview: Original and Distorted Caltech Samples",
        fontsize=18,
        fontweight="bold",
        color="#1f2937",
        y=0.98,
    )
    figure.tight_layout(rect=(0, 0, 1, 0.96))
    figure.savefig(output_path, format="svg", bbox_inches="tight")
    plt.close(figure)


def main() -> int:
    payload = load_payload()
    distorted_manifest = load_distorted_manifest()
    clean_reference = dict(payload["cleanReference"])
    test_levels = load_levels(payload, "testMetrics", "testConfidenceIntervals")
    retrieval_levels = load_levels(payload, "retrievalMetrics", "retrievalConfidenceIntervals")
    preview_levels = load_preview_levels(distorted_manifest)
    source_root = Path(str(distorted_manifest["sourceDatasetPath"]))
    source_paths = load_preview_source_paths(distorted_manifest, count=3)

    render_metric_progression_chart(
        dict(clean_reference["testMetrics"]),
        test_levels,
        TEST_METRICS,
        TEST_OUTPUT_PATH,
        "Fine-tuned ResNet-18 Robustness: Test Metrics Across Distortion Levels",
    )
    render_metric_progression_chart(
        dict(clean_reference["retrievalMetrics"]),
        retrieval_levels,
        RETRIEVAL_METRICS,
        RETRIEVAL_OUTPUT_PATH,
        "Fine-tuned ResNet-18 Robustness: Retrieval Metrics Across Distortion Levels",
    )
    render_distortion_preview_chart(
        source_paths,
        source_root,
        preview_levels,
        PREVIEW_OUTPUT_PATH,
    )

    print("Saved robustness charts to:")
    print(TEST_OUTPUT_PATH)
    print(RETRIEVAL_OUTPUT_PATH)
    print(PREVIEW_OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())