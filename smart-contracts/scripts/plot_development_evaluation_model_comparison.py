from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


SMART_CONTRACTS_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = SMART_CONTRACTS_DIR.parent
REPORTS_DIR = SMART_CONTRACTS_DIR / "reports"
INPUT_PATH = ROOT_DIR / "image-vector-service" / "state" / "development_evaluation.json"
TEST_OUTPUT_PATH = REPORTS_DIR / "development-evaluation-test-metrics.svg"
RETRIEVAL_OUTPUT_PATH = REPORTS_DIR / "development-evaluation-retrieval-metrics.svg"

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
MODEL_COLORS = [
    "#2563eb",
    "#f97316",
    "#059669",
    "#dc2626",
    "#7c3aed",
    "#0891b2",
]


@dataclass(frozen=True)
class ModelSeries:
    name: str
    metrics: dict[str, float]
    confidence_intervals: dict[str, dict[str, float]]
    color: str


def load_model_series() -> list[ModelSeries]:
    payload = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    models = payload.get("models", [])
    if not models:
        raise RuntimeError(f"No model evaluation data found in {INPUT_PATH}")

    series: list[ModelSeries] = []
    for index, model in enumerate(models):
        series.append(
            ModelSeries(
                name=str(model["name"]),
                metrics=dict(model["testMetrics"]),
                confidence_intervals=dict(model["testConfidenceIntervals"]),
                color=MODEL_COLORS[index % len(MODEL_COLORS)],
            )
        )

    return series


def load_retrieval_series() -> list[ModelSeries]:
    payload = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    models = payload.get("models", [])
    if not models:
        raise RuntimeError(f"No model evaluation data found in {INPUT_PATH}")

    series: list[ModelSeries] = []
    for index, model in enumerate(models):
        series.append(
            ModelSeries(
                name=str(model["name"]),
                metrics=dict(model["retrievalMetrics"]),
                confidence_intervals=dict(model["retrievalConfidenceIntervals"]),
                color=MODEL_COLORS[index % len(MODEL_COLORS)],
            )
        )

    return series


def compute_axis_upper_bound(series: list[ModelSeries], metrics: list[tuple[str, str]]) -> float:
    upper_bounds: list[float] = []
    for model in series:
        for metric_key, _ in metrics:
            interval = model.confidence_intervals[metric_key]
            upper_bounds.append(float(interval["high"]))
    maximum = max(upper_bounds) if upper_bounds else 1.0
    return min(1.05, maximum * 1.08 if maximum > 0 else 1.0)


def render_metric_chart(
    series: list[ModelSeries],
    metrics: list[tuple[str, str]],
    output_path: Path,
    title: str,
) -> None:
    figure, axis = plt.subplots(figsize=(15, 8))
    figure.patch.set_facecolor("#f8fafc")
    axis.set_facecolor("#f8fafc")

    metric_positions = np.arange(len(metrics), dtype=float)
    bar_width = 0.72 / max(1, len(series))
    offsets = np.linspace(
        -bar_width * (len(series) - 1) / 2,
        bar_width * (len(series) - 1) / 2,
        len(series),
    )

    for model, offset in zip(series, offsets):
        values = [float(model.metrics[metric_key]) for metric_key, _ in metrics]
        lower_errors = [
            value - float(model.confidence_intervals[metric_key]["low"])
            for value, (metric_key, _) in zip(values, metrics)
        ]
        upper_errors = [
            float(model.confidence_intervals[metric_key]["high"]) - value
            for value, (metric_key, _) in zip(values, metrics)
        ]
        x_positions = metric_positions + offset

        bars = axis.bar(
            x_positions,
            values,
            width=bar_width,
            color=model.color,
            alpha=0.88,
            edgecolor="#ffffff",
            linewidth=1.2,
            label=model.name,
            yerr=np.array([lower_errors, upper_errors]),
            capsize=4,
            error_kw={"elinewidth": 1.2, "ecolor": "#334155"},
        )

        for bar, value in zip(bars, values):
            axis.text(
                bar.get_x() + bar.get_width() / 2,
                value,
                f"{value:.3f}",
                ha="center",
                va="bottom",
                fontsize=8,
                color="#1f2937",
            )

    axis.set_title(title, fontsize=18, fontweight="bold", color="#1f2937", pad=16)
    axis.set_xlabel("Metric", fontsize=12, fontweight="bold", color="#374151")
    axis.set_ylabel("Score", fontsize=12, fontweight="bold", color="#374151")
    axis.set_xticks(metric_positions)
    axis.set_xticklabels([label for _, label in metrics])
    axis.set_ylim(0, compute_axis_upper_bound(series, metrics))
    axis.grid(axis="y", color="#d1d5db", linestyle="--", linewidth=0.9, alpha=0.9)
    axis.set_axisbelow(True)
    axis.legend(frameon=False, loc="upper left", bbox_to_anchor=(1.01, 1.0))

    for spine in axis.spines.values():
        spine.set_color("#374151")

    axis.tick_params(colors="#4b5563")

    figure.tight_layout()
    figure.savefig(output_path, format="svg", bbox_inches="tight")
    plt.close(figure)


def main() -> int:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    test_series = load_model_series()
    retrieval_series = load_retrieval_series()

    render_metric_chart(
        test_series,
        TEST_METRICS,
        TEST_OUTPUT_PATH,
        "Image Vector Model Comparison: Test Metrics with Confidence Intervals",
    )
    render_metric_chart(
        retrieval_series,
        RETRIEVAL_METRICS,
        RETRIEVAL_OUTPUT_PATH,
        "Image Vector Model Comparison: Retrieval Metrics with Confidence Intervals",
    )

    print("Saved development evaluation comparison charts to:")
    print(TEST_OUTPUT_PATH)
    print(RETRIEVAL_OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())