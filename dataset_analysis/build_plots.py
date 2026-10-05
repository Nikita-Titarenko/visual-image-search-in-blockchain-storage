from __future__ import annotations

from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image, ImageOps


SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}


def build_dataset_plots(dataset_path: Path, output_dir: Path) -> list[Path]:
    image_paths = _collect_image_paths(dataset_path)
    if not image_paths:
        raise ValueError(f"No image files were found in {dataset_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    feature_frame = _build_feature_frame(image_paths)
    generated_files = [
        _plot_feature_distributions(feature_frame, output_dir),
        _plot_class_balance(feature_frame, output_dir),
        _plot_brightness_time_series(image_paths, output_dir),
        _plot_missing_values(feature_frame, output_dir),
        _plot_correlation_matrix(feature_frame, output_dir),
        _plot_outliers(feature_frame, output_dir),
    ]
    plt.close("all")
    return generated_files


def _collect_image_paths(dataset_path: Path) -> list[Path]:
    return sorted(
        file_path
        for file_path in dataset_path.rglob("*")
        if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def _build_feature_frame(image_paths: list[Path]) -> pd.DataFrame:
    rows: list[dict[str, float | int | str]] = []

    for image_path in image_paths:
        with Image.open(image_path) as image:
            rgb_image = image.convert("RGB")
            grayscale_image = ImageOps.grayscale(rgb_image)
            image_array = np.asarray(rgb_image, dtype=np.float32)
            grayscale_array = np.asarray(grayscale_image, dtype=np.float32)

        width, height = rgb_image.size
        rows.append(
            {
                "class_name": image_path.parent.name,
                "width": width,
                "height": height,
                "aspect_ratio": width / height if height else 0.0,
                "mean_brightness": float(grayscale_array.mean()),
                "mean_red": float(image_array[:, :, 0].mean()),
                "mean_green": float(image_array[:, :, 1].mean()),
                "mean_blue": float(image_array[:, :, 2].mean()),
            }
        )

    return pd.DataFrame(rows)


def _plot_feature_distributions(feature_frame: pd.DataFrame, output_dir: Path) -> Path:
    figure, axes = plt.subplots(2, 2, figsize=(14, 10))
    plots = [
        ("width", "Width distribution", "steelblue"),
        ("height", "Height distribution", "darkorange"),
        ("aspect_ratio", "Aspect ratio distribution", "seagreen"),
        ("mean_brightness", "Mean brightness distribution", "firebrick"),
    ]

    for axis, (column, title, color) in zip(axes.flat, plots):
        axis.hist(feature_frame[column], bins=30, color=color, edgecolor="black", alpha=0.8)
        axis.set_title(title)
        axis.set_xlabel(column.replace("_", " ").title())
        axis.set_ylabel("Count")

    figure.suptitle("Distributions of key image features", fontsize=16)
    figure.tight_layout()
    output_path = output_dir / "feature_distributions.png"
    figure.savefig(output_path, dpi=200, bbox_inches="tight")
    return output_path


def _plot_class_balance(feature_frame: pd.DataFrame, output_dir: Path) -> Path:
    class_counts = Counter(feature_frame["class_name"])
    sorted_counts = dict(sorted(class_counts.items(), key=lambda item: item[1], reverse=True))

    figure, axis = plt.subplots(figsize=(16, 8))
    axis.bar(sorted_counts.keys(), sorted_counts.values(), color="slateblue")
    axis.set_title("Class balance")
    axis.set_xlabel("Class")
    axis.set_ylabel("Images")
    axis.tick_params(axis="x", rotation=90)
    figure.tight_layout()

    output_path = output_dir / "class_balance.png"
    figure.savefig(output_path, dpi=200, bbox_inches="tight")
    return output_path


def _plot_brightness_time_series(image_paths: list[Path], output_dir: Path) -> Path:
    normalized_profiles: list[np.ndarray] = []
    target_width = 100

    for image_path in image_paths:
        with Image.open(image_path) as image:
            grayscale_image = ImageOps.grayscale(image)
            resized_image = grayscale_image.resize((target_width, grayscale_image.height))
            grayscale_array = np.asarray(resized_image, dtype=np.float32)

        normalized_profiles.append(grayscale_array.mean(axis=0))

    brightness_series = np.mean(normalized_profiles, axis=0)
    x_axis = np.arange(len(brightness_series))

    figure, axis = plt.subplots(figsize=(14, 6))
    axis.plot(x_axis, brightness_series, color="teal", linewidth=2)
    axis.set_title("Average brightness profile across the dataset")
    axis.set_xlabel("Normalized horizontal position")
    axis.set_ylabel("Average brightness")
    axis.grid(alpha=0.3)
    figure.tight_layout()

    output_path = output_dir / "brightness_time_series.png"
    figure.savefig(output_path, dpi=200, bbox_inches="tight")
    return output_path


def _plot_missing_values(feature_frame: pd.DataFrame, output_dir: Path) -> Path:
    missing_counts = feature_frame.isna().sum().sort_values(ascending=False)

    figure, axis = plt.subplots(figsize=(12, 6))
    axis.bar(missing_counts.index, missing_counts.values, color="goldenrod", edgecolor="black")
    axis.set_title("Missing values by feature")
    axis.set_xlabel("Feature")
    axis.set_ylabel("Missing values")
    axis.tick_params(axis="x", rotation=45)
    figure.tight_layout()

    output_path = output_dir / "missing_values.png"
    figure.savefig(output_path, dpi=200, bbox_inches="tight")
    return output_path


def _plot_correlation_matrix(feature_frame: pd.DataFrame, output_dir: Path) -> Path:
    numeric_frame = feature_frame.select_dtypes(include=[np.number])
    correlation_matrix = numeric_frame.corr()

    figure, axis = plt.subplots(figsize=(10, 8))
    heatmap = axis.imshow(correlation_matrix, cmap="coolwarm", vmin=-1, vmax=1)
    axis.set_title("Correlation matrix of numeric features")
    axis.set_xticks(range(len(correlation_matrix.columns)))
    axis.set_xticklabels(correlation_matrix.columns, rotation=45, ha="right")
    axis.set_yticks(range(len(correlation_matrix.index)))
    axis.set_yticklabels(correlation_matrix.index)

    for row_index, row_name in enumerate(correlation_matrix.index):
        for column_index, column_name in enumerate(correlation_matrix.columns):
            axis.text(
                column_index,
                row_index,
                f"{correlation_matrix.loc[row_name, column_name]:.2f}",
                ha="center",
                va="center",
                color="black",
            )

    figure.colorbar(heatmap, ax=axis, fraction=0.046, pad=0.04)
    figure.tight_layout()

    output_path = output_dir / "correlation_matrix.png"
    figure.savefig(output_path, dpi=200, bbox_inches="tight")
    return output_path


def _plot_outliers(feature_frame: pd.DataFrame, output_dir: Path) -> Path:
    numeric_columns = ["width", "height", "aspect_ratio", "mean_brightness"]

    figure, axes = plt.subplots(2, 2, figsize=(12, 8))

    for axis, column in zip(axes.flat, numeric_columns):
        axis.boxplot(
            feature_frame[column].dropna(),
            tick_labels=[column.replace("_", " ").title()],
            patch_artist=True,
            boxprops={"facecolor": "lightcoral", "alpha": 0.7},
            medianprops={"color": "black"},
        )
        axis.set_title(column.replace("_", " ").title())
        axis.set_ylabel("Value")

    figure.suptitle("Outlier analysis for key numeric features", fontsize=16)
    figure.tight_layout()

    output_path = output_dir / "outliers.png"
    figure.savefig(output_path, dpi=200, bbox_inches="tight")
    return output_path