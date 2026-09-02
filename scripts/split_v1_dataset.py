"""Create deterministic, family-safe splits for the V1 case dataset."""

import argparse
import json
import random
import tempfile
from collections import Counter, defaultdict
from pathlib import Path


ALLOWED_LABELS = {"fraud", "normal", "insufficient"}
SPLIT_RATIOS = {"development": 0.6, "validation": 0.2, "test": 0.2}


def load_cases(input_dir: Path) -> list[dict]:
    """Load approved JSON cases in filename order and validate split fields."""
    cases: list[dict] = []
    seen_case_ids: set[str] = set()

    for path in sorted(input_dir.glob("*.json")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"无法读取 {path}: {error}") from error

        if not isinstance(case, dict):
            raise ValueError(f"{path}: 顶层必须是 JSON 对象")

        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"{path}: 缺少有效 case_id")
        if case_id in seen_case_ids:
            raise ValueError(f"重复 case_id: {case_id}")
        seen_case_ids.add(case_id)

        if case.get("review_status") != "approved":
            raise ValueError(f"{case_id}: review_status 必须是 approved")
        if not isinstance(case.get("real_case_id"), str) or not case["real_case_id"]:
            raise ValueError(f"{case_id}: 缺少有效 real_case_id")
        if not isinstance(case.get("source_id"), str) or not case["source_id"]:
            raise ValueError(f"{case_id}: 缺少有效 source_id")
        if case.get("label") not in ALLOWED_LABELS:
            raise ValueError(f"{case_id}: label 不合法: {case.get('label')!r}")

        cases.append(case)

    return cases


def group_cases(cases: list[dict]) -> dict[str, list[dict]]:
    """Group cases connected by real_case_id or source_id."""
    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        if parent[node] != node:
            parent[node] = find(parent[node])
        return parent[node]

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for case in cases:
        union(f"real:{case['real_case_id']}", f"source:{case['source_id']}")

    components: dict[str, list[dict]] = {}
    for case in cases:
        root = find(f"real:{case['real_case_id']}")
        components.setdefault(root, []).append(case)

    groups: dict[str, list[dict]] = {}
    for component in components.values():
        group_id = min(case["real_case_id"] for case in component)
        groups[group_id] = component
    return groups


def split_groups(
    groups: dict[str, list[dict]], seed: int = 20260901
) -> dict[str, str]:
    """Assign linked groups to deterministic, approximately balanced splits."""
    if len(groups) < len(SPLIT_RATIOS):
        raise ValueError("至少需要3个来源关联组才能划分三个集合")

    group_ids = sorted(groups)
    total_cases = sum(len(group) for group in groups.values())
    total_labels = Counter(
        case["label"] for group in groups.values() for case in group
    )
    total_fraud_types = Counter(
        case.get("fraud_type")
        for group in groups.values()
        for case in group
        if case["label"] == "fraud" and case.get("fraud_type")
    )
    fraud_type_group_counts = Counter()
    for group in groups.values():
        fraud_types = {
            case.get("fraud_type")
            for case in group
            if case["label"] == "fraud" and case.get("fraud_type")
        }
        fraud_type_group_counts.update(fraud_types)

    def score(assignment: dict[str, str]) -> float:
        split_cases = Counter()
        split_labels = {name: Counter() for name in SPLIT_RATIOS}
        split_fraud_types = {name: Counter() for name in SPLIT_RATIOS}

        for group_id, split in assignment.items():
            for case in groups[group_id]:
                split_cases[split] += 1
                split_labels[split][case["label"]] += 1
                fraud_type = case.get("fraud_type")
                if case["label"] == "fraud" and fraud_type:
                    split_fraud_types[split][fraud_type] += 1

        result = 0.0
        for split, ratio in SPLIT_RATIOS.items():
            result += 5 * abs(split_cases[split] - total_cases * ratio) / total_cases
            for label, total in total_labels.items():
                result += 3 * abs(split_labels[split][label] - total * ratio) / total
            for fraud_type, total in total_fraud_types.items():
                result += 0.1 * abs(
                    split_fraud_types[split][fraud_type] - total * ratio
                ) / total
                if (
                    fraud_type_group_counts[fraud_type] >= len(SPLIT_RATIOS)
                    and split_fraud_types[split][fraud_type] == 0
                ):
                    result += 100
        return result

    rng = random.Random(seed)
    split_names = list(SPLIT_RATIOS)
    split_weights = list(SPLIT_RATIOS.values())
    best_assignment: dict[str, str] | None = None
    best_score = float("inf")

    for _ in range(5000):
        shuffled = group_ids.copy()
        rng.shuffle(shuffled)
        guaranteed_splits = split_names.copy()
        rng.shuffle(guaranteed_splits)
        assignment = {
            group_id: guaranteed_splits[index]
            for index, group_id in enumerate(shuffled[: len(split_names)])
        }
        for group_id in shuffled[len(split_names) :]:
            assignment[group_id] = rng.choices(
                split_names, weights=split_weights, k=1
            )[0]

        candidate_score = score(assignment)
        if candidate_score < best_score:
            best_score = candidate_score
            best_assignment = assignment

    if best_assignment is None:
        raise RuntimeError("无法生成数据划分")
    return {group_id: best_assignment[group_id] for group_id in group_ids}


def build_manifest(
    groups: dict[str, list[dict]], assignment: dict[str, str]
) -> list[dict]:
    """Build a stable case-level split manifest without copying case content."""
    if set(assignment) != set(groups):
        raise ValueError("划分结果必须完整覆盖所有来源关联组")

    rows: list[dict] = []
    for group_id, group in groups.items():
        split = assignment[group_id]
        if split not in SPLIT_RATIOS:
            raise ValueError(f"{group_id}: split 不合法: {split!r}")
        for case in group:
            rows.append(
                {
                    "case_id": case["case_id"],
                    "real_case_id": case["real_case_id"],
                    "split": split,
                }
            )
    return sorted(rows, key=lambda row: row["case_id"])


def build_report(
    groups: dict[str, list[dict]],
    manifest: list[dict],
    seed: int = 20260901,
    data_version: str = "v1",
) -> dict:
    """Summarize split balance and independently check leakage."""
    cases = [case for group in groups.values() for case in group]
    case_by_id = {case["case_id"]: case for case in cases}
    manifest_ids = [row["case_id"] for row in manifest]
    split_by_case = {row["case_id"]: row["split"] for row in manifest}

    source_splits: dict[str, set[str]] = defaultdict(set)
    family_splits: dict[str, set[str]] = defaultdict(set)
    for case_id, split in split_by_case.items():
        case = case_by_id.get(case_id)
        if case is None:
            continue
        source_splits[case["source_id"]].add(split)
        family_splits[case["real_case_id"]].add(split)

    split_stats = {}
    for split in SPLIT_RATIOS:
        split_cases = [
            case
            for case in cases
            if split_by_case.get(case["case_id"]) == split
        ]
        split_group_count = sum(
            1
            for group in groups.values()
            if {split_by_case.get(case["case_id"]) for case in group} == {split}
        )
        split_stats[split] = {
            "case_count": len(split_cases),
            "group_count": split_group_count,
            "label_distribution": dict(
                sorted(Counter(case["label"] for case in split_cases).items())
            ),
            "fraud_type_distribution": dict(
                sorted(
                    Counter(
                        case["fraud_type"]
                        for case in split_cases
                        if case["label"] == "fraud" and case.get("fraud_type")
                    ).items()
                )
            ),
        }

    manifest_id_counts = Counter(manifest_ids)
    return {
        "data_version": data_version,
        "seed": seed,
        "total_cases": len(cases),
        "total_groups": len(groups),
        "splits": split_stats,
        "checks": {
            "duplicate_case_id_count": sum(
                count - 1 for count in manifest_id_counts.values() if count > 1
            ),
            "missing_case_count": len(set(case_by_id) - set(manifest_ids)),
            "unknown_case_count": len(set(manifest_ids) - set(case_by_id)),
            "source_leakage_count": sum(
                len(splits) > 1 for splits in source_splits.values()
            ),
            "family_leakage_count": sum(
                len(splits) > 1 for splits in family_splits.values()
            ),
        },
    }


def write_outputs(
    manifest_path: Path,
    report_path: Path,
    manifest: list[dict],
    report: dict,
) -> None:
    """Atomically replace the manifest and report after both are written."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    manifest_text = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in manifest
    )
    report_text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    temporary_paths: list[Path] = []

    try:
        for destination, content in (
            (manifest_path, manifest_text),
            (report_path, report_text),
        ):
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                delete=False,
            ) as temporary_file:
                temporary_file.write(content)
                temporary_paths.append(Path(temporary_file.name))

        temporary_paths[0].replace(manifest_path)
        temporary_paths[1].replace(report_path)
    finally:
        for temporary_path in temporary_paths:
            temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="划分问安智鉴V1数据集")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260901)
    args = parser.parse_args()

    cases = load_cases(args.input)
    groups = group_cases(cases)
    assignment = split_groups(groups, seed=args.seed)
    manifest = build_manifest(groups, assignment)
    report = build_report(groups, manifest, seed=args.seed, data_version="v1")

    if any(report["checks"].values()):
        raise RuntimeError(f"划分检查失败: {report['checks']}")

    write_outputs(args.manifest, args.report, manifest, report)
    print(
        f"已划分 {report['total_cases']} 条案例、{report['total_groups']} 个来源关联组"
    )


if __name__ == "__main__":
    main()
