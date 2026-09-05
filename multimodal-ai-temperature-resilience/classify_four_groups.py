from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_MODEL = (
    SCRIPT_DIR / "models" / "four_group_temperature_resilience_model.joblib"
)
if not DEFAULT_MODEL.exists():
    DEFAULT_MODEL = SCRIPT_DIR / "four_group_temperature_resilience_model.joblib"


def component_series(frame: pd.DataFrame, component: dict) -> pd.Series:
    values = frame[component["columns"]].apply(pd.to_numeric, errors="coerce")
    if component["aggregation"] == "identity":
        return values.iloc[:, 0]
    if component["aggregation"] == "row_mean":
        return values.mean(axis=1)
    raise ValueError(f"Unknown aggregation: {component['aggregation']}")


def score(frame: pd.DataFrame, reference: dict[str, dict]) -> pd.Series:
    components = {}
    for name, component in reference.items():
        raw = component_series(frame, component)
        robust_z = (
            (raw - component["median"]) / component["scale"]
        ).clip(-component["clip"], component["clip"])
        components[name] = component["sign"] * robust_z
    return pd.DataFrame(components, index=frame.index).mean(axis=1)


def classify(
    frame: pd.DataFrame,
    model_path: Path = DEFAULT_MODEL,
) -> pd.DataFrame:
    bundle = joblib.load(model_path)
    heat = score(frame, bundle["heat_reference"])
    cold = score(frame, bundle["cold_reference"])
    if "profile_rule" in bundle:
        rule = bundle["profile_rule"]
        penalty = rule["dominance_penalty"]
        dual_score = pd.Series(
            np.minimum(heat, cold),
            index=frame.index,
        )
        heat_profile_score = heat - penalty * cold
        cold_profile_score = cold - penalty * heat
        dual = dual_score >= rule["dual_threshold"]
        heat_profile = (
            (~dual)
            & (heat_profile_score >= rule["heat_profile_threshold"])
        )
        cold_profile = (
            (~dual)
            & (~heat_profile)
            & (
                cold_profile_score
                >= rule["cold_profile_threshold"]
            )
        )
        group_id = np.select(
            [cold_profile, heat_profile, dual],
            [1, 2, 3],
            default=4,
        ).astype(int)
        distance = np.minimum.reduce(
            [
                np.abs(dual_score - rule["dual_threshold"]),
                np.abs(
                    heat_profile_score
                    - rule["heat_profile_threshold"]
                ),
                np.abs(
                    cold_profile_score
                    - rule["cold_profile_threshold"]
                ),
            ]
        )
    else:
        heat_ok = heat >= bundle["heat_threshold"]
        cold_ok = cold >= bundle["cold_threshold"]
        group_id = np.select(
            [
                cold_ok & ~heat_ok,
                heat_ok & ~cold_ok,
                heat_ok & cold_ok,
            ],
            [1, 2, 3],
            default=4,
        ).astype(int)
        distance = np.minimum(
            np.abs(heat - bundle["heat_threshold"]),
            np.abs(cold - bundle["cold_threshold"]),
        )
        dual_score = np.minimum(heat, cold)
        heat_profile_score = heat
        cold_profile_score = cold
    output = pd.DataFrame(
        {
            "heat_resilience_index": heat,
            "cold_resilience_index": cold,
            "dual_profile_score": dual_score,
            "heat_profile_score": heat_profile_score,
            "cold_profile_score": cold_profile_score,
            "group_id": group_id,
            "group_name_ru": pd.Series(group_id, index=frame.index).map(
                bundle["group_names_ru"]
            ),
            "group_name_en": pd.Series(group_id, index=frame.index).map(
                bundle.get("group_names_en", {})
            ),
            "borderline_review": distance <= bundle["borderline_margin"],
        }
    )
    if "subject_id" in frame.columns:
        output.insert(0, "subject_id", frame["subject_id"].values)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assign four heat/cold resilience groups."
    )
    parser.add_argument("input_csv", type=Path)
    parser.add_argument("output_csv", type=Path)
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    frame = pd.read_csv(args.input_csv)
    result = classify(frame, args.model)
    result.to_csv(args.output_csv, index=False)
    print(f"Saved {len(result)} classifications to {args.output_csv}")


if __name__ == "__main__":
    main()
