from __future__ import annotations

import html
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MethodGasStat:
    contract: str
    method: str
    avg_gas: int


ROOT_DIR = Path(__file__).resolve().parents[1]
REPORTS_DIR = ROOT_DIR / "reports"
RAW_REPORT_PATH = REPORTS_DIR / "hardhat-gas-report.txt"
SVG_REPORT_PATH = REPORTS_DIR / "gas-methods-chart.svg"
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def run_hardhat_tests() -> str:
    command = ["npx.cmd", "hardhat", "test"]
    result = subprocess.run(
        command,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    output = result.stdout + ("\n" + result.stderr if result.stderr else "")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    RAW_REPORT_PATH.write_text(output, encoding="utf-8")

    if result.returncode != 0:
        raise RuntimeError(
            "hardhat test failed. See reports/hardhat-gas-report.txt for the full output."
        )

    return output


def parse_method_stats(report_text: str) -> list[MethodGasStat]:
    rows: list[MethodGasStat] = []
    in_methods_table = False

    for raw_line in report_text.splitlines():
        line = ANSI_ESCAPE_RE.sub("", raw_line)
        if "|  Methods" in line:
            in_methods_table = True
            continue
        if in_methods_table and "|  Deployments" in line:
            break
        if not in_methods_table or "|" not in line or "·" not in line:
            continue

        columns = [part.strip() for part in line.split("·")]
        if len(columns) < 6:
            continue

        contract = _clean_cell(columns[0])
        method = _clean_cell(columns[1])
        avg_cell = _clean_cell(columns[4])

        if not contract or not method or contract == "Contract" or avg_cell in {"Avg", "-"}:
            continue
        if not re.fullmatch(r"[\d,]+", avg_cell):
            continue

        rows.append(
            MethodGasStat(
                contract=contract,
                method=method,
                avg_gas=int(avg_cell.replace(",", "")),
            )
        )

    if not rows:
        raise RuntimeError(
            "Could not parse method gas stats from the Hardhat output. "
            "See reports/hardhat-gas-report.txt for the captured report."
        )

    return rows


def _clean_cell(cell: str) -> str:
    return cell.replace("|", " ").replace("│", " ").strip()


def build_svg(stats: list[MethodGasStat]) -> str:
    sorted_stats = sorted(stats, key=lambda item: item.avg_gas, reverse=True)

    width = 1400
    height = 760
    title_y = 40
    subtitle_y = 62
    top_label_padding = 26
    margin_top = 100
    margin_right = 40
    margin_bottom = 250
    margin_left = 90
    chart_width = width - margin_left - margin_right
    chart_height = height - margin_top - margin_bottom
    bar_gap = 20
    bar_width = max(36, (chart_width - bar_gap * (len(sorted_stats) - 1)) // max(len(sorted_stats), 1))
    max_gas = max(item.avg_gas for item in sorted_stats)
    grid_steps = 5

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<style>',
        'text { font-family: "Segoe UI", Arial, sans-serif; fill: #1f2937; }',
        '.title { font-size: 28px; font-weight: 700; }',
        '.subtitle { font-size: 14px; fill: #4b5563; }',
        '.axis { stroke: #374151; stroke-width: 2; }',
        '.grid { stroke: #d1d5db; stroke-width: 1; stroke-dasharray: 4 6; }',
        '.bar { fill: #2563eb; }',
        '.bar-label { font-size: 13px; font-weight: 600; text-anchor: middle; }',
        '.x-label { font-size: 12px; }',
        '.y-label { font-size: 12px; fill: #6b7280; }',
        '.axis-label { font-size: 16px; font-weight: 600; fill: #374151; }',
        '</style>',
        '<rect width="100%" height="100%" fill="#f8fafc" />',
        f'<text x="{margin_left}" y="{title_y}" class="title">Hardhat Gas Report by Method</text>',
        f'<text x="{margin_left}" y="{subtitle_y}" class="subtitle">Average gas from the latest hardhat test run</text>',
    ]

    for step in range(grid_steps + 1):
        gas_value = round(max_gas * step / grid_steps)
        y = margin_top + chart_height - (chart_height * step / grid_steps)
        svg_parts.append(
            f'<line x1="{margin_left}" y1="{y:.2f}" x2="{width - margin_right}" y2="{y:.2f}" class="grid" />'
        )
        svg_parts.append(
            f'<text x="{margin_left - 12}" y="{y + 4:.2f}" text-anchor="end" class="y-label">{gas_value:,}</text>'
        )

    x_axis_y = margin_top + chart_height
    svg_parts.append(
        f'<line x1="{margin_left}" y1="{x_axis_y}" x2="{width - margin_right}" y2="{x_axis_y}" class="axis" />'
    )
    svg_parts.append(
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{x_axis_y}" class="axis" />'
    )
    svg_parts.append(
        f'<text x="{margin_left + chart_width / 2:.2f}" y="{height - 28}" text-anchor="middle" class="axis-label">Functions</text>'
    )
    svg_parts.append(
        f'<text x="28" y="{margin_top + chart_height / 2:.2f}" text-anchor="middle" class="axis-label" transform="rotate(-90 28 {margin_top + chart_height / 2:.2f})">Average gas used</text>'
    )

    for index, item in enumerate(sorted_stats):
        x = margin_left + index * (bar_width + bar_gap)
        bar_height = chart_height * item.avg_gas / max_gas
        y = x_axis_y - bar_height
        label_y = max(y - 10, margin_top - top_label_padding)

        svg_parts.append(
            f'<rect x="{x}" y="{y:.2f}" width="{bar_width}" height="{bar_height:.2f}" rx="8" class="bar" />'
        )
        svg_parts.append(
            f'<text x="{x + bar_width / 2:.2f}" y="{label_y:.2f}" class="bar-label">{item.avg_gas:,}</text>'
        )

        label_x = x + bar_width / 2
        label_y = x_axis_y + 24
        method_label = html.escape(item.method)
        contract_label = html.escape(item.contract)

        svg_parts.append(
            f'<g transform="translate({label_x:.2f},{label_y}) rotate(45)">'
            f'<text class="x-label">{method_label}</text>'
            f'<text class="x-label" y="18" fill="#6b7280">{contract_label}</text>'
            '</g>'
        )

    svg_parts.append('</svg>')
    return "\n".join(svg_parts)


def main() -> int:
    try:
        report_text = run_hardhat_tests()
        stats = parse_method_stats(report_text)
        SVG_REPORT_PATH.write_text(build_svg(stats), encoding="utf-8")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Saved raw gas report to: {RAW_REPORT_PATH}")
    print(f"Saved gas chart to: {SVG_REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())