from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt


ROOT_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT_DIR / "reports"
INPUT_PATH = REPORTS_DIR / "register-collection-confirmation.json"
OUTPUT_PATH_TEMPLATE = REPORTS_DIR / "register-collection-confirmation-{network}.svg"


@dataclass(frozen=True)
class ConfirmationSeries:
    label: str
    values_ms: list[int]
    color: str


def load_series() -> list[ConfirmationSeries]:
    payload = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    colors = {
        "hardhat": "#2563eb",
        "amoy": "#f97316",
    }

    series: list[ConfirmationSeries] = []
    for result in payload.get("results", []):
        durations = [int(entry["confirmationTimeMs"]) for entry in result.get("measurements", [])]
        if not durations:
            continue
        series.append(
            ConfirmationSeries(
                label=result["network"],
                values_ms=durations,
                color=colors.get(result["network"], "#64748b"),
            )
        )

    if not series:
        raise RuntimeError("No measurement data found in reports/register-collection-confirmation.json")

    return series


def render_chart(item: ConfirmationSeries) -> Path:
    figure, axis = plt.subplots(figsize=(14, 7.6))
    figure.patch.set_facecolor("#f8fafc")
    axis.set_facecolor("#f8fafc")
    figure.subplots_adjust(top=0.82)

    figure.suptitle(
        f"registerCollection Confirmation Time by Run\n{item.label} measurements saved by the Hardhat script",
        fontsize=18,
        fontweight="bold",
        color="#1f2937",
        y=0.97,
    )

    run_positions = list(range(1, len(item.values_ms) + 1))
    axis.bar(
        run_positions,
        item.values_ms,
        width=0.56,
        color=item.color,
        alpha=0.88,
        edgecolor="#ffffff",
        linewidth=1.2,
        label=item.label,
    )
    for x_position, value in zip(run_positions, item.values_ms):
        axis.text(x_position, value, str(value), ha="center", va="bottom", fontsize=9, color="#1f2937")

    max_value = max(item.values_ms)
    axis.set_ylim(0, max_value * 1.18 if max_value > 0 else 1)

    axis.set_xlabel("Measurement run", fontsize=12, fontweight="bold", color="#374151")
    axis.set_ylabel("Confirmation time (ms)", fontsize=12, fontweight="bold", color="#374151")
    axis.set_xticks(run_positions)
    axis.set_xticklabels([f"Run {run}" for run in run_positions])
    axis.grid(axis="y", color="#d1d5db", linestyle="--", linewidth=0.9, alpha=0.9)
    axis.set_axisbelow(True)
    axis.legend(frameon=False)

    for spine in axis.spines.values():
        spine.set_color("#374151")

    axis.tick_params(colors="#4b5563")

    output_path = Path(str(OUTPUT_PATH_TEMPLATE).format(network=item.label))
    figure.savefig(output_path, format="svg")
    plt.close(figure)
    return output_path


def main() -> int:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    series = load_series()
    output_paths = [render_chart(item) for item in series]
    print("Saved confirmation charts to:")
    for output_path in output_paths:
        print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())