from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt


ROOT_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT_DIR / "reports"
INPUT_PATH = REPORTS_DIR / "local-system-benchmark.json"
OUTPUT_PATH = REPORTS_DIR / "local-system-scenario-times-10-users.svg"
TARGET_USERS = 10
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
OPERATION_LABELS = {
    "oracle/encrypt-upload": "Encrypt upload",
    "pinata/upload": "Pinata upload",
    "pinata/pin-json(image-metadata)": "Pin image metadata",
    "registerImage": "Register image",
    "pinata/pin-json(terms-metadata)": "Pin terms metadata",
    "configureLicenseOffer": "Configure license",
    "buyLicense": "Buy license",
    "oracle/download": "Oracle download",
    "vector/search?top_k=10": "Vector search top-10",
}


def load_target_entry() -> dict[str, object]:
    payload = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    load_levels = payload.get("loadLevels", [])
    for entry in load_levels:
        if entry.get("users") == TARGET_USERS:
            return entry
    raise RuntimeError(f"No benchmark data found for users={TARGET_USERS} in {INPUT_PATH}")


def render_plot(entry: dict[str, object]) -> None:
    operations = entry["operations"]
    labels = [OPERATION_LABELS[name] for name in OPERATIONS]
    avg_values = [operations[name]["avgMs"] for name in OPERATIONS]
    p95_values = [operations[name]["p95Ms"] for name in OPERATIONS]

    figure, axis = plt.subplots(figsize=(14, 8))
    figure.patch.set_facecolor("#f8fafc")
    axis.set_facecolor("#f8fafc")

    x_positions = list(range(len(OPERATIONS)))
    bars = axis.bar(
        x_positions,
        avg_values,
        color="#2563eb",
        alpha=0.88,
        edgecolor="#ffffff",
        linewidth=1.2,
        label="Average latency",
    )
    axis.plot(
        x_positions,
        p95_values,
        color="#dc2626",
        marker="o",
        linewidth=2.2,
        label="P95 latency",
    )

    max_value = max(max(avg_values), max(p95_values)) if avg_values else 0
    axis.set_ylim(0, max_value * 1.18 if max_value > 0 else 1)

    for bar, value in zip(bars, avg_values):
        axis.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{value:.1f}",
            ha="center",
            va="bottom",
            fontsize=9,
            color="#1f2937",
        )

    axis.set_title(
        f"Local System Scenario Times for {TARGET_USERS} Virtual Users\nTotal scenario duration: {entry['durationMs']} ms",
        fontsize=18,
        fontweight="bold",
        color="#1f2937",
        pad=18,
    )
    axis.set_xlabel("Scenario step", fontsize=12, fontweight="bold", color="#374151")
    axis.set_ylabel("Latency (ms)", fontsize=12, fontweight="bold", color="#374151")
    axis.set_xticks(x_positions)
    axis.set_xticklabels(labels, rotation=25, ha="right")
    axis.grid(axis="y", color="#d1d5db", linestyle="--", linewidth=0.9, alpha=0.9)
    axis.set_axisbelow(True)
    axis.legend(frameon=False)

    for spine in axis.spines.values():
        spine.set_color("#374151")

    axis.tick_params(colors="#4b5563")
    figure.tight_layout()
    figure.savefig(OUTPUT_PATH, format="svg")
    plt.close(figure)


def main() -> int:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    entry = load_target_entry()
    render_plot(entry)
    print(f"Saved 10-user scenario chart to: {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())