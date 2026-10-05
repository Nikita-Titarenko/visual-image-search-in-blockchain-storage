from pathlib import Path

from build_plots import build_dataset_plots
from download_dataset import download_caltech101


def main() -> None:
    dataset_path = download_caltech101()
    output_dir = Path("plots")
    generated_files = build_dataset_plots(dataset_path, output_dir=output_dir)

    print(f"Dataset path: {dataset_path}")
    print("Generated plots:")
    for file_path in generated_files:
        print(f"- {file_path}")


if __name__ == "__main__":
    main()