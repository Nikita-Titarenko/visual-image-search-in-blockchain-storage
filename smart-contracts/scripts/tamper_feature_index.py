from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


SMART_CONTRACTS_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = SMART_CONTRACTS_DIR.parent
DEFAULT_INPUT_PATH = ROOT_DIR / "image-vector-service" / "state" / "feature_index.npz"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Slightly modify an image-vector-service feature index for verification testing.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Path to the source feature_index.npz file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Where to write the modified index. Defaults to a sibling *.tampered.npz file.",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Overwrite the input file instead of writing a separate tampered copy.",
    )
    parser.add_argument(
        "--target",
        choices=("cnn", "hist", "both"),
        default="both",
        help="Which array to perturb.",
    )
    parser.add_argument(
        "--delta",
        type=float,
        default=1e-3,
        help="Small value added to the selected element(s).",
    )
    parser.add_argument(
        "--row",
        type=int,
        default=0,
        help="Row index to modify inside the target array.",
    )
    parser.add_argument(
        "--column",
        type=int,
        default=0,
        help="Column index to modify inside the target array.",
    )
    return parser.parse_args()


def resolve_output_path(input_path: Path, output_path: Path | None, in_place: bool) -> Path:
    if in_place:
        return input_path
    if output_path is not None:
        return output_path
    return input_path.with_name(f"{input_path.stem}.tampered{input_path.suffix}")


def validate_coordinates(array: np.ndarray, row: int, column: int, label: str) -> None:
    if array.ndim != 2:
        raise RuntimeError(f"Expected {label} to be a 2D array, got shape {array.shape!r}.")
    if not (0 <= row < array.shape[0]):
        raise RuntimeError(f"Row {row} is out of range for {label} with shape {array.shape}.")
    if not (0 <= column < array.shape[1]):
        raise RuntimeError(f"Column {column} is out of range for {label} with shape {array.shape}.")


def perturb_array(array: np.ndarray, row: int, column: int, delta: float, label: str) -> np.ndarray:
    validate_coordinates(array, row, column, label)
    updated = np.array(array, copy=True)
    updated[row, column] = updated[row, column] + np.array(delta, dtype=updated.dtype)
    return updated


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    if not input_path.exists():
        raise RuntimeError(f"Feature index file not found: {input_path}")

    output_path = resolve_output_path(input_path, args.output.resolve() if args.output else None, args.in_place)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = np.load(input_path)
    cnn = np.array(payload["cnn"], copy=True)
    hist = np.array(payload["hist"], copy=True)
    model_hash = np.array(payload["model_hash"], copy=True)
    corpus_kind = np.array(payload["corpus_kind"], copy=True)

    modified_targets: list[str] = []
    if args.target in {"cnn", "both"}:
        cnn = perturb_array(cnn, args.row, args.column, args.delta, "cnn")
        modified_targets.append("cnn")
    if args.target in {"hist", "both"}:
        hist = perturb_array(hist, args.row, args.column, args.delta, "hist")
        modified_targets.append("hist")

    np.savez_compressed(
        output_path,
        cnn=cnn,
        hist=hist,
        model_hash=model_hash,
        corpus_kind=corpus_kind,
    )

    print(f"Input index: {input_path}")
    print(f"Output index: {output_path}")
    print(f"Modified targets: {', '.join(modified_targets)}")
    print(f"Applied delta: {args.delta} at row={args.row}, column={args.column}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())