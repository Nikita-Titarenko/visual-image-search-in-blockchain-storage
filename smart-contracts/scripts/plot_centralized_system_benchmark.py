from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt


ROOT_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT_DIR / "reports"
INPUT_PATH = REPORTS_DIR / "centralized-system-benchmark.json"
OUTPUT_PATH = REPORTS_DIR / "centralized-system-benchmark.svg"
OPERATIONS = [
    "oracle/encrypt-upload",
    "pinata/upload",
    "pinata/pin-json(image-metadata)",
    "registerImage",
    "pinata/pin-json(terms-metadata)",
    "configureLicenseOffer",
    "buyLicense",
    "oracle/download",
    "vector/search?top_k=10",
]


def load_report() -> dict[str, object]:
    payload = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    if not payload.get("loadLevels"):
        raise RuntimeError("No benchmark data found in reports/centralized-system-benchmark.json")
    return payload


def render_plot(report: dict[str, object]) -> None:
    load_levels = report["loadLevels"]
    users = [entry["users"] for entry in load_levels]
    throughput = [entry["throughputUsersPerSecond"] for entry in load_levels]
    success_rate = [
        (entry["completedUsers"] / entry["users"] * 100) if entry["users"] else 0
        for entry in load_levels
    ]

    figure, axes = plt.subplots(4, 1, figsize=(14, 20), constrained_layout=True)
    figure.patch.set_facecolor("#f8fafc")

    axes[0].set_facecolor("#f8fafc")
    axes[0].plot(users, throughput, marker="o", linewidth=2.8, color="#2563eb")
    axes[0].set_title("Centralized System Throughput by Virtual User Load", fontsize=17, fontweight="bold", color="#1f2937")
    axes[0].set_xlabel("Virtual users", fontsize=11, fontweight="bold", color="#374151")
    axes[0].set_ylabel("Completed workflows / sec", fontsize=11, fontweight="bold", color="#374151")
    axes[0].grid(color="#d1d5db", linestyle="--", linewidth=0.9, alpha=0.9)

    axes[1].set_facecolor("#f8fafc")
    axes[1].plot(users, success_rate, marker="o", linewidth=2.8, color="#059669")
    axes[1].set_title("Success Rate by Virtual User Load", fontsize=17, fontweight="bold", color="#1f2937")
    axes[1].set_xlabel("Virtual users", fontsize=11, fontweight="bold", color="#374151")
    axes[1].set_ylabel("Successful workflows (%)", fontsize=11, fontweight="bold", color="#374151")
    axes[1].set_ylim(0, 105)
    axes[1].grid(color="#d1d5db", linestyle="--", linewidth=0.9, alpha=0.9)

    for operation in OPERATIONS:
        avg_values = [entry["operations"][operation]["avgMs"] for entry in load_levels]
        axes[2].plot(users, avg_values, marker="o", linewidth=2.0, label=operation)
    axes[2].set_facecolor("#f8fafc")
    axes[2].set_title("Average Latency by Operation", fontsize=17, fontweight="bold", color="#1f2937")
    axes[2].set_xlabel("Virtual users", fontsize=11, fontweight="bold", color="#374151")
    axes[2].set_ylabel("Average latency (ms)", fontsize=11, fontweight="bold", color="#374151")
    axes[2].grid(color="#d1d5db", linestyle="--", linewidth=0.9, alpha=0.9)
    axes[2].legend(frameon=False, ncol=2)

    for operation in OPERATIONS:
        p95_values = [entry["operations"][operation]["p95Ms"] for entry in load_levels]
        axes[3].plot(users, p95_values, marker="o", linewidth=2.0, label=operation)
    axes[3].set_facecolor("#f8fafc")
    axes[3].set_title("P95 Latency by Operation", fontsize=17, fontweight="bold", color="#1f2937")
    axes[3].set_xlabel("Virtual users", fontsize=11, fontweight="bold", color="#374151")
    axes[3].set_ylabel("P95 latency (ms)", fontsize=11, fontweight="bold", color="#374151")
    axes[3].grid(color="#d1d5db", linestyle="--", linewidth=0.9, alpha=0.9)

    for axis in axes:
        axis.set_axisbelow(True)
        axis.tick_params(colors="#4b5563")
        for spine in axis.spines.values():
            spine.set_color("#374151")

    for entry in load_levels:
        bottleneck = entry["bottleneckOperation"]
        axes[3].annotate(
            f"bottleneck: {bottleneck}",
            xy=(entry["users"], entry["operations"][bottleneck]["p95Ms"]),
            xytext=(10, 10),
            textcoords="offset points",
            fontsize=9,
            color="#991b1b",
            bbox={"boxstyle": "round,pad=0.25", "facecolor": "#fee2e2", "edgecolor": "#fca5a5"},
        )

    figure.savefig(OUTPUT_PATH, format="svg")
    plt.close(figure)


def main() -> int:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = load_report()
    render_plot(report)
    print(f"Saved benchmark chart to: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())