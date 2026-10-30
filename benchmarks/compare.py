#!/usr/bin/env python3
"""Compare validated, same-ROM benchmark reports; never compare failed runs."""
import argparse
import json
from pathlib import Path


def compare(old, new):
    if old.get("status") != "passed" or new.get("status") != "passed":
        raise ValueError("both benchmark reports must have passed")
    if not old.get("control_sha256") or old["control_sha256"] != new.get("control_sha256"):
        raise ValueError("control ROM hashes differ or are missing")
    if old.get("input_mode") != new.get("input_mode"):
        raise ValueError("input configurations differ")
    previous = {case["case"]: case for case in old["results"]}
    result = []
    for current in new["results"]:
        name = current["case"]
        if name not in previous:
            continue
        before = previous[name]
        if before["parameters"] != current["parameters"] or before["expected_sha256"] != current["expected_sha256"]:
            raise ValueError(f"different workload/expected result: {name}")
        for language, now in current["languages"].items():
            was = before["languages"][language]
            if not now["verified"] or not was["verified"]:
                raise ValueError(f"unverified result: {name}/{language}")
            a, b = was["measurements"][0], now["measurements"][0]
            if a["raw_cycles"] <= 0 or b["raw_cycles"] <= 0:
                raise ValueError("execution cycles must be positive")
            if any(m["raw_cycles"] != a["raw_cycles"] for m in was["measurements"]):
                raise ValueError("nondeterministic baseline")
            if any(m["raw_cycles"] != b["raw_cycles"] for m in now["measurements"]):
                raise ValueError("nondeterministic candidate")
            row = {"case": name, "language": language, "old_cycles": a["raw_cycles"],
                   "new_cycles": b["raw_cycles"], "delta_cycles": b["raw_cycles"]-a["raw_cycles"],
                   "delta_percent": 100*(b["raw_cycles"]/a["raw_cycles"]-1),
                   "source_changed": was["source_sha256"] != now["source_sha256"]}
            for key in ["dictionary_bytes", "compiled_dictionary_bytes"]:
                if key in a and key in b:
                    row[key + "_delta"] = b[key] - a[key]
            if "phases" in a and "phases" in b:
                row["phase_deltas"] = {key: b["phases"][key]-a["phases"][key] for key in a["phases"]}
            if "memory" in a and "memory" in b:
                row["memory_deltas"] = {key: b["memory"][key]-a["memory"][key]
                                        for key in a["memory"] if key in b["memory"]}
            result.append(row)
    if not result:
        raise ValueError("no common benchmark cases")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    rows = compare(json.loads(args.baseline.read_text()), json.loads(args.candidate.read_text()))
    for row in rows:
        note = " (source changed)" if row["source_changed"] else ""
        if "dictionary_bytes_delta" in row:
            note += f"; dictionary {row['dictionary_bytes_delta']:+d} B"
        if "compiled_dictionary_bytes_delta" in row:
            note += f"; compiled {row['compiled_dictionary_bytes_delta']:+d} B"
        if "phase_deltas" in row:
            note += f"; compile {row['phase_deltas']['compile']:+d} cycles"
        print(f"{row['case']:12} {row['language']:5} {row['old_cycles']:>12,} -> {row['new_cycles']:>12,}"
              f"  {row['delta_percent']:+.3f}%{note}")


if __name__ == "__main__":
    main()
