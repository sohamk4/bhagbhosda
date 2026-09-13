from pathlib import Path


def find_csv_files(dataset_dir: Path) -> list[Path]:

    csv_files = []

    for file in dataset_dir.glob("*.csv"):

        # The dataset contains an output.csv template.
        # We don't want to use that as financial input.
        if file.name.lower() == "output.csv":
            continue

        csv_files.append(file)

    return sorted(csv_files)