from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CostBar:
    label: str
    network: str
    gas_price_gwei: int
    native_cost: float
    usd_cost: float
    color: str


ROOT_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT_DIR / "reports"
SVG_REPORT_PATH = REPORTS_DIR / "network-deploy-costs.svg"

TOTAL_GAS = 3_589_738
POL_PRICE_USD = 0.0078
ETH_PRICE_USD = 0.184


def format_usd(value: float) -> str:
    if value >= 100:
        return f"${value:,.0f}"
    if value >= 1:
        return f"${value:,.2f}"
    return f"${value:,.3f}"


def build_cost_bars() -> list[CostBar]:
    scenarios = [
        ("Normal", 20),
        ("High", 50),
    ]
    bars: list[CostBar] = []

    for scenario_label, gas_price_gwei in scenarios:
        native_cost = TOTAL_GAS * gas_price_gwei / 1_000_000_000
        bars.append(
            CostBar(
                label=f"{scenario_label} POL",
                network="POL",
                gas_price_gwei=gas_price_gwei,
                native_cost=native_cost,
                usd_cost=native_cost * POL_PRICE_USD,
                color="#2563eb",
            )
        )
        bars.append(
            CostBar(
                label=f"{scenario_label} ETH",
                network="ETH",
                gas_price_gwei=gas_price_gwei,
                native_cost=native_cost,
                usd_cost=native_cost * ETH_PRICE_USD,
                color="#f97316",
            )
        )

    return bars


def build_svg(bars: list[CostBar]) -> str:
    width = 1320
    height = 760
    margin_top = 110
    margin_right = 60
    margin_bottom = 230
    margin_left = 110
    chart_width = width - margin_left - margin_right
    chart_height = height - margin_top - margin_bottom
    max_usd = max(bar.usd_cost for bar in bars)
    bar_gap = 40
    bar_width = (chart_width - bar_gap * (len(bars) - 1)) / len(bars)
    grid_steps = 5
    x_axis_y = margin_top + chart_height

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<style>',
        'text { font-family: "Segoe UI", Arial, sans-serif; fill: #1f2937; }',
        '.title { font-size: 28px; font-weight: 700; }',
        '.subtitle { font-size: 14px; fill: #4b5563; }',
        '.axis { stroke: #374151; stroke-width: 2; }',
        '.grid { stroke: #d1d5db; stroke-width: 1; stroke-dasharray: 4 6; }',
        '.bar-label { font-size: 13px; font-weight: 600; text-anchor: middle; }',
        '.x-label { font-size: 14px; font-weight: 600; text-anchor: middle; }',
        '.x-sub-label { font-size: 12px; fill: #6b7280; text-anchor: middle; }',
        '.y-label { font-size: 12px; fill: #6b7280; }',
        '.axis-label { font-size: 16px; font-weight: 600; fill: #374151; }',
        '</style>',
        '<rect width="100%" height="100%" fill="#f8fafc" />',
        f'<text x="{margin_left}" y="42" class="title">Deployment Cost Comparison for POL and ETH</text>',
        f'<text x="{margin_left}" y="66" class="subtitle">Based on {TOTAL_GAS:,} gas with normal (20 Gwei) and high (50 Gwei) scenarios</text>',
        f'<text x="{margin_left}" y="86" class="subtitle">POL price = {format_usd(POL_PRICE_USD)}, ETH price = {format_usd(ETH_PRICE_USD)}</text>',
    ]

    for step in range(grid_steps + 1):
        usd_value = max_usd * step / grid_steps
        y = margin_top + chart_height - (chart_height * step / grid_steps)
        svg_parts.append(
            f'<line x1="{margin_left}" y1="{y:.2f}" x2="{width - margin_right}" y2="{y:.2f}" class="grid" />'
        )
        svg_parts.append(
            f'<text x="{margin_left - 12}" y="{y + 4:.2f}" text-anchor="end" class="y-label">${usd_value:,.2f}</text>'
        )

    svg_parts.append(
        f'<line x1="{margin_left}" y1="{x_axis_y}" x2="{width - margin_right}" y2="{x_axis_y}" class="axis" />'
    )
    svg_parts.append(
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{x_axis_y}" class="axis" />'
    )
    svg_parts.append(
        f'<text x="{margin_left + chart_width / 2:.2f}" y="{height - 28}" class="axis-label" text-anchor="middle">Scenario</text>'
    )
    svg_parts.append(
        f'<text x="30" y="{margin_top + chart_height / 2:.2f}" class="axis-label" text-anchor="middle" transform="rotate(-90 30 {margin_top + chart_height / 2:.2f})">Deployment cost in USD</text>'
    )

    for index, bar in enumerate(bars):
        x = margin_left + index * (bar_width + bar_gap)
        bar_height = chart_height * (bar.usd_cost / max_usd)
        y = x_axis_y - bar_height
        label_y = max(y - 12, margin_top - 18)
        escaped_label = html.escape(bar.label)

        svg_parts.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" height="{bar_height:.2f}" rx="10" fill="{bar.color}" />'
        )
        svg_parts.append(
            f'<text x="{x + bar_width / 2:.2f}" y="{label_y:.2f}" class="bar-label">${bar.usd_cost:,.4f}</text>'
        )
        svg_parts.append(
            f'<text x="{x + bar_width / 2:.2f}" y="{x_axis_y + 28:.2f}" class="x-label">{escaped_label}</text>'
        )
        svg_parts.append(
            f'<text x="{x + bar_width / 2:.2f}" y="{x_axis_y + 48:.2f}" class="x-sub-label">{bar.native_cost:.4f} {bar.network}</text>'
        )
        svg_parts.append(
            f'<text x="{x + bar_width / 2:.2f}" y="{x_axis_y + 66:.2f}" class="x-sub-label">{bar.gas_price_gwei} Gwei</text>'
        )

    svg_parts.append('</svg>')
    return "\n".join(svg_parts)


def main() -> int:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    bars = build_cost_bars()
    SVG_REPORT_PATH.write_text(build_svg(bars), encoding="utf-8")
    print(f"Saved deploy cost chart to: {SVG_REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())