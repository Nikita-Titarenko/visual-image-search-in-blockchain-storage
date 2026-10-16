from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


SERVICE_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = SERVICE_DIR / "state"
INPUT_PATH = STATE_DIR / "fine_tuned_train_size_evaluation.json"
OUTPUT_PATH = STATE_DIR / "fine_tuned_train_size_metrics.svg"

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
class TrainSizeLevel:
    fraction: float
    sample_count: int
    test_metrics: dict[str, float]
    test_confidence_intervals: dict[str, dict[str, float]]
    retrieval_metrics: dict[str, float]
    retrieval_confidence_intervals: dict[str, dict[str, float]]


def load_levels() -> tuple[dict[str, object], list[TrainSizeLevel]]:
    payload = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    levels_payload = payload.get("levels", [])
    if not levels_payload:
        raise RuntimeError(f"No train-size evaluation levels found in {INPUT_PATH}")

    levels = [
        TrainSizeLevel(
            fraction=float(item["trainFraction"]),
            sample_count=int(item["trainSampleCount"]),
            test_metrics=dict(item["testMetrics"]),
            test_confidence_intervals=dict(item["testConfidenceIntervals"]),
            retrieval_metrics=dict(item["retrievalMetrics"]),
            retrieval_confidence_intervals=dict(item["retrievalConfidenceIntervals"]),
        )
        for item in levels_payload
    ]
    return payload, levels


def _render_axis(
    axis: plt.Axes,
    levels: list[TrainSizeLevel],
    metrics: list[tuple[str, str]],
    metric_source: str,
    interval_source: str,
    title: str,
) -> None:
    x_values = np.array([level.sample_count for level in levels], dtype=float)
    x_labels = [f"{level.sample_count}\n({level.fraction:.0%})" for level in levels]

    lower_values: list[float] = []
    upper_values: list[float] = []
    for color, (metric_key, metric_label) in zip(METRIC_COLORS, metrics, strict=True):
        y_values = np.array([float(getattr(level, metric_source)[metric_key]) for level in levels], dtype=float)
        lower_errors = np.array(
            [y_value - float(getattr(level, interval_source)[metric_key]["low"]) for level, y_value in zip(levels, y_values, strict=True)],
            dtype=float,
        )
        upper_errors = np.array(
            [float(getattr(level, interval_source)[metric_key]["high"]) - y_value for level, y_value in zip(levels, y_values, strict=True)],
            dtype=float,
        )
        lower_values.extend((y_values - lower_errors).tolist())
        upper_values.extend((y_values + upper_errors).tolist())

        axis.errorbar(
            x_values,
            y_values,
            yerr=np.vstack([lower_errors, upper_errors]),
            color=color,
            marker="o",
            markersize=6,
            linewidth=2.2,
            capsize=4,
            label=metric_label,
        )

    axis.set_title(title, fontsize=15, fontweight="bold", color="#1f2937", pad=14)
    axis.set_xlabel("Training samples from fixed train split", fontsize=11, fontweight="bold", color="#374151")
    axis.set_ylabel("Score", fontsize=11, fontweight="bold", color="#374151")
    axis.set_xticks(x_values)
    axis.set_xticklabels(x_labels)
    axis.grid(axis="y", color="#d1d5db", linestyle="--", linewidth=0.9, alpha=0.9)
    axis.set_axisbelow(True)
    axis.set_ylim(max(0.0, min(lower_values) - 0.04), min(1.02, max(upper_values) + 0.04))
    for spine in axis.spines.values():
        spine.set_color("#374151")
    axis.tick_params(colors="#4b5563")


def main() -> int:
    _, levels = load_levels()

    figure, axes = plt.subplots(1, 2, figsize=(18, 7.5), sharex=False)
    figure.patch.set_facecolor("#f8fafc")
    for axis in axes:
        axis.set_facecolor("#f8fafc")

    _render_axis(
        axes[0],
        levels,
        TEST_METRICS,
        "test_metrics",
        "test_confidence_intervals",
        "Fine-tuned ResNet-18: Test Metrics vs Train Size",
    )
    _render_axis(
        axes[1],
        levels,
        RETRIEVAL_METRICS,
        "retrieval_metrics",
        "retrieval_confidence_intervals",
        "Fine-tuned ResNet-18: Retrieval Metrics vs Train Size",
    )

    handles, labels = axes[1].get_legend_handles_labels()
    figure.legend(handles, labels, frameon=False, loc="upper center", ncol=4, bbox_to_anchor=(0.5, 1.02))
    figure.tight_layout(rect=(0, 0, 1, 0.95))
    figure.savefig(OUTPUT_PATH, format="svg", bbox_inches="tight")
    plt.close(figure)

    print("Saved fine-tuned train-size chart to:")
    print(OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())