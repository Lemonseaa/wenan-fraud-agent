import json
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from scripts.split_v1_dataset import (
    build_manifest,
    build_report,
    group_cases,
    load_cases,
    split_groups,
    write_outputs,
)


def make_case(
    case_id: str,
    real_case_id: str = "RC0001",
    source_id: str = "SRC0001",
    label: str = "fraud",
    review_status: str = "approved",
    fraud_type: Optional[str] = None,
) -> dict:
    case = {
        "case_id": case_id,
        "real_case_id": real_case_id,
        "source_id": source_id,
        "label": label,
        "review_status": review_status,
    }
    if fraud_type is not None:
        case["fraud_type"] = fraud_type
    return case


class LoadCasesTests(unittest.TestCase):
    def write_case(self, directory: Path, filename: str, case: dict) -> None:
        (directory / filename).write_text(
            json.dumps(case, ensure_ascii=False), encoding="utf-8"
        )

    def test_load_cases_reads_json_files_in_filename_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            self.write_case(directory, "C0002-F01.json", make_case("C0002-F01"))
            self.write_case(directory, "C0001-F01.json", make_case("C0001-F01"))
            (directory / "notes.txt").write_text("ignore", encoding="utf-8")

            cases = load_cases(directory)

        self.assertEqual(
            [case["case_id"] for case in cases], ["C0001-F01", "C0002-F01"]
        )

    def test_load_cases_rejects_pending_case(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            self.write_case(
                directory,
                "C0001-F01.json",
                make_case("C0001-F01", review_status="pending"),
            )

            with self.assertRaisesRegex(ValueError, "C0001-F01.*approved"):
                load_cases(directory)

    def test_load_cases_rejects_duplicate_case_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            self.write_case(directory, "first.json", make_case("C0001-F01"))
            self.write_case(directory, "second.json", make_case("C0001-F01"))

            with self.assertRaisesRegex(ValueError, "重复 case_id.*C0001-F01"):
                load_cases(directory)

    def test_load_cases_rejects_missing_real_case_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            case = make_case("C0001-F01")
            del case["real_case_id"]
            self.write_case(directory, "C0001-F01.json", case)

            with self.assertRaisesRegex(ValueError, "C0001-F01.*real_case_id"):
                load_cases(directory)

    def test_load_cases_rejects_missing_source_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            case = make_case("C0001-F01")
            del case["source_id"]
            self.write_case(directory, "C0001-F01.json", case)

            with self.assertRaisesRegex(ValueError, "C0001-F01.*source_id"):
                load_cases(directory)

    def test_load_cases_rejects_unknown_label(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            self.write_case(
                directory,
                "C0001-F01.json",
                make_case("C0001-F01", label="unknown"),
            )

            with self.assertRaisesRegex(ValueError, "C0001-F01.*label"):
                load_cases(directory)

    def test_load_cases_reports_invalid_json_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            path = directory / "broken.json"
            path.write_text("{", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "broken.json"):
                load_cases(directory)


class GroupCasesTests(unittest.TestCase):
    def test_group_cases_keeps_family_together(self):
        cases = [
            make_case("C0001-F01", real_case_id="RC0001", label="fraud"),
            make_case("C0001-N01", real_case_id="RC0001", label="normal"),
            make_case(
                "C0002-F01",
                real_case_id="RC0002",
                source_id="SRC0002",
                label="fraud",
            ),
        ]

        groups = group_cases(cases)

        self.assertEqual(list(groups), ["RC0001", "RC0002"])
        self.assertEqual(
            [case["case_id"] for case in groups["RC0001"]],
            ["C0001-F01", "C0001-N01"],
        )

    def test_group_cases_keeps_same_source_together(self):
        cases = [
            make_case(
                "C0001-F01", real_case_id="RC0001", source_id="SRC0001"
            ),
            make_case(
                "C0002-F01", real_case_id="RC0002", source_id="SRC0001"
            ),
            make_case(
                "C0003-F01", real_case_id="RC0003", source_id="SRC0002"
            ),
        ]

        groups = group_cases(cases)

        self.assertEqual(list(groups), ["RC0001", "RC0003"])
        self.assertEqual(
            [case["case_id"] for case in groups["RC0001"]],
            ["C0001-F01", "C0002-F01"],
        )


class SplitGroupsTests(unittest.TestCase):
    def setUp(self):
        labels = ["fraud", "normal", "insufficient"]
        self.groups = {}
        for index in range(15):
            real_case_id = f"RC{index + 1:04d}"
            label = labels[index % len(labels)]
            self.groups[real_case_id] = [
                make_case(
                    f"C{index + 1:04d}-F01",
                    real_case_id=real_case_id,
                    source_id=f"SRC{index + 1:04d}",
                    label=label,
                )
            ]

    def test_split_groups_is_deterministic_and_complete(self):
        first = split_groups(self.groups, seed=20260901)
        second = split_groups(self.groups, seed=20260901)

        self.assertEqual(first, second)
        self.assertEqual(set(first), set(self.groups))
        self.assertEqual(
            set(first.values()), {"development", "validation", "test"}
        )

    def test_split_groups_keeps_label_counts_near_target(self):
        assignment = split_groups(self.groups, seed=20260901)
        counts = {
            split: {"fraud": 0, "normal": 0, "insufficient": 0}
            for split in ("development", "validation", "test")
        }
        for group_id, split in assignment.items():
            label = self.groups[group_id][0]["label"]
            counts[split][label] += 1

        self.assertEqual(counts["development"], {
            "fraud": 3,
            "normal": 3,
            "insufficient": 3,
        })
        self.assertEqual(counts["validation"], {
            "fraud": 1,
            "normal": 1,
            "insufficient": 1,
        })
        self.assertEqual(counts["test"], {
            "fraud": 1,
            "normal": 1,
            "insufficient": 1,
        })

    def test_split_groups_covers_fraud_type_when_three_groups_exist(self):
        groups = {}
        for index in range(3):
            group_id = f"RC{index + 1:04d}"
            groups[group_id] = [
                make_case(
                    f"C{index + 1:04d}-F01",
                    real_case_id=group_id,
                    source_id=f"SRC{index + 1:04d}",
                    fraud_type="target_type",
                )
            ]
        for index in range(3, 15):
            group_id = f"RC{index + 1:04d}"
            groups[group_id] = [
                make_case(
                    f"C{index + 1:04d}-N01",
                    real_case_id=group_id,
                    source_id=f"SRC{index + 1:04d}",
                    label="normal",
                )
            ]

        assignment = split_groups(groups, seed=20260901)
        covered_splits = {
            assignment[group_id]
            for group_id in ("RC0001", "RC0002", "RC0003")
        }

        self.assertEqual(
            covered_splits, {"development", "validation", "test"}
        )

    def test_real_dataset_keeps_each_label_within_eight_cases_of_target(self):
        repository_root = Path(__file__).resolve().parents[1]
        cases = load_cases(repository_root / "data/review/public_cases/structured")
        groups = group_cases(cases)
        assignment = split_groups(groups, seed=20260901)
        ratios = {"development": 0.6, "validation": 0.2, "test": 0.2}

        total_labels = {
            label: sum(case["label"] == label for case in cases)
            for label in ("fraud", "normal", "insufficient")
        }
        actual = {
            split: {label: 0 for label in total_labels}
            for split in ratios
        }
        for group_id, split in assignment.items():
            for case in groups[group_id]:
                actual[split][case["label"]] += 1

        for split, ratio in ratios.items():
            for label, total in total_labels.items():
                with self.subTest(split=split, label=label):
                    self.assertLessEqual(
                        abs(actual[split][label] - total * ratio), 8
                    )


class ManifestAndReportTests(unittest.TestCase):
    def setUp(self):
        cases = [
            make_case(
                "C0002-F01", real_case_id="RC0002", source_id="SRC0002"
            ),
            make_case(
                "C0001-F01", real_case_id="RC0001", source_id="SRC0001"
            ),
            make_case(
                "C0003-N01",
                real_case_id="RC0003",
                source_id="SRC0003",
                label="normal",
            ),
        ]
        self.groups = group_cases(cases)
        self.assignment = {
            "RC0001": "development",
            "RC0002": "validation",
            "RC0003": "test",
        }

    def test_manifest_has_fixed_fields_and_case_id_order(self):
        manifest = build_manifest(self.groups, self.assignment)

        self.assertEqual(
            [row["case_id"] for row in manifest],
            ["C0001-F01", "C0002-F01", "C0003-N01"],
        )
        self.assertTrue(
            all(
                set(row) == {"case_id", "real_case_id", "split"}
                for row in manifest
            )
        )

    def test_report_counts_splits_and_detects_no_leakage(self):
        manifest = build_manifest(self.groups, self.assignment)
        report = build_report(
            self.groups, manifest, seed=20260901, data_version="v1"
        )

        self.assertEqual(report["total_cases"], 3)
        self.assertEqual(report["total_groups"], 3)
        self.assertEqual(report["splits"]["development"]["case_count"], 1)
        self.assertEqual(report["checks"]["source_leakage_count"], 0)
        self.assertEqual(report["checks"]["family_leakage_count"], 0)

    def test_write_outputs_creates_valid_jsonl_and_json(self):
        manifest = build_manifest(self.groups, self.assignment)
        report = build_report(self.groups, manifest)

        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            manifest_path = directory / "nested/v1_split.jsonl"
            report_path = directory / "nested/v1_split_report.json"

            write_outputs(manifest_path, report_path, manifest, report)

            written_manifest = [
                json.loads(line)
                for line in manifest_path.read_text(encoding="utf-8").splitlines()
            ]
            written_report = json.loads(report_path.read_text(encoding="utf-8"))

        self.assertEqual(written_manifest, manifest)
        self.assertEqual(written_report, report)


if __name__ == "__main__":
    unittest.main()
