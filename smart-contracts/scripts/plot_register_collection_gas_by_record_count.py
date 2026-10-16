from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt


ROOT_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT_DIR / "reports"
INPUT_PATH = REPORTS_DIR / "register-collection-gas-by-record-count.json"
OUTPUT_PATH = REPORTS_DIR / "register-collection-gas-by-record-count.svg"


def load_measurements() -> list[dict[str, int]]:
    payload = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    measurements = payload.get("measurements", [])
    if not measurements:
        raise RuntimeError("No measurement data found in reports/register-collection-gas-by-record-count.json")
    return measurements


def render_plot(measurements: list[dict[str, int]]) -> None:
    x_values = [int(item["collectionCountAfterRegistration"]) for item in measurements]
    y_values = [int(item["gasUsed"]) for item in measurements]

    figure, axis = plt.subplots(figsize=(13.8, 7.6), constrained_layout=True)
    figure.patch.set_facecolor("#f8fafc")
    axis.set_facecolor("#f8fafc")

    axis.plot(
        x_values,
        y_values,
        color="#2563eb",
        linewidth=2.6,
        marker="o",
        markersize=6,
        markerfacecolor="#2563eb",
        markeredgecolor="#ffffff",
        markeredgewidth=1.0,
    )

    axis.set_title(
        "registerCollection Gas vs Stored Collection Count\nLocal Hardhat network, repeated writes into a single ImageRegistry contract",
        fontsize=18,
        fontweight="bold",
        color="#1f2937",
        pad=18,
    )
    axis.set_xlabel("Collection count after registration", fontsize=12, fontweight="bold", color="#374151")
    axis.set_ylabel("Gas used", fontsize=12, fontweight="bold", color="#374151")
    axis.grid(color="#d1d5db", linestyle="--", linewidth=0.9, alpha=0.9)
    axis.set_axisbelow(True)

    for spine in axis.spines.values():
        spine.set_color("#374151")

    axis.tick_params(colors="#4b5563")

    for x_value, y_value in zip(x_values, y_values):
        axis.annotate(
            f"{y_value:,}",
            xy=(x_value, y_value),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            fontsize=9,
            color="#1f2937",
        )

    figure.savefig(OUTPUT_PATH, format="svg")
    plt.close(figure)


def main() -> int:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    measurements = load_measurements()
    render_plot(measurements)
    print(f"Saved gas-by-record-count chart to: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())