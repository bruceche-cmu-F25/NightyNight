"""
evaluate_stories.py
-------------------
Runs the saved StoryGuard models against every .txt story in the stories/ folder.

The filename must encode the true age group using one of these patterns:
  _4-6_    → true label: 4-6
  _7-12_   → true label: 7-12
  _13+_    → true label: 13+
  _adult   → true label: adult (non-child; no child guard applied)

Files that match none of the above are skipped with a warning.

Usage:
    cd /Users/bruce/CountingStars/notebooks
    python evaluate_stories.py

    # or point to a different stories dir / model dir:
    python evaluate_stories.py --stories ../stories --models .
"""

import argparse
import re
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_STORIES_DIR = Path(__file__).parent.parent / "stories"
DEFAULT_MODEL_DIR   = Path(__file__).parent          # notebooks/

TEXT_FEATURES = [
    "log_word_count", "sentence_count", "avg_sentence_length",
    "avg_word_length", "unique_word_ratio", "exclamation_ratio",
    "question_ratio", "flesch_score",
]

ID_TO_AGE = {0: "4-6", 1: "7-12", 2: "13+"}

# Regex patterns to extract true label from filename
_LABEL_PATTERNS = [
    (re.compile(r"_4-6_"),  "4-6"),
    (re.compile(r"_7-12_"), "7-12"),
    (re.compile(r"_13\+_"), "13+"),
    (re.compile(r"_adult"), "adult"),
]


# ── Feature extraction (mirrors notebook Section 4) ──────────────────────────

def _count_sentences(text):
    parts = re.split(r"[.!?]+", text)
    return max(len([p for p in parts if p.strip()]), 1)


def _extract_words(text):
    return re.findall(r"[a-zA-Z]+", text.lower())


def _approx_syllables(word):
    return max(len(re.findall(r"[aeiouy]+", word.lower())), 1)


def _flesch(text):
    words = _extract_words(text)
    n_w   = max(len(words), 1)
    n_s   = _count_sentences(text)
    n_syl = sum(_approx_syllables(w) for w in words)
    return round(206.835 - 1.015 * (n_w / n_s) - 84.6 * (n_syl / n_w), 2)


def extract_features(text):
    text   = re.sub(r"\s+", " ", text.strip())
    words  = _extract_words(text)
    n_w    = max(len(words), 1)
    n_s    = _count_sentences(text)
    lens   = [len(w) for w in words]
    return {
        "log_word_count":      round(np.log1p(n_w), 4),
        "sentence_count":      n_s,
        "avg_sentence_length": round(n_w / n_s, 2),
        "avg_word_length":     round(float(np.mean(lens)), 2),
        "unique_word_ratio":   round(len(set(words)) / n_w, 2),
        "exclamation_ratio":   round(text.count("!") / n_w, 4),
        "question_ratio":      round(text.count("?") / n_w, 4),
        "flesch_score":        _flesch(text),
        "raw_word_count":      n_w,
    }


def feature_matrix(features):
    return pd.DataFrame([features])[TEXT_FEATURES].values


# ── Model loading ─────────────────────────────────────────────────────────────

def load_model(model_dir, filename):
    path = Path(model_dir) / filename
    if not path.exists():
        print(f"[WARN] Model not found: {path}")
        return None
    try:
        m = joblib.load(path)
        print(f"[OK]   Loaded {filename}")
        return m
    except Exception as exc:
        print(f"[WARN] Could not load {filename}: {exc}")
        return None


# ── Label extraction ──────────────────────────────────────────────────────────

def true_label_from_filename(name):
    """Extract true age-group label from filename. Returns None if unrecognised."""
    for pattern, label in _LABEL_PATTERNS:
        if pattern.search(name):
            return label
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def run(stories_dir, model_dir):
    print(f"\nStories dir : {stories_dir}")
    print(f"Model dir   : {model_dir}\n")

    binary_model = load_model(model_dir, "child_friendly_gb.joblib")
    multi_model  = load_model(model_dir, "age_group_gb.joblib")
    print()

    story_files = sorted(Path(stories_dir).rglob("*.txt"))
    if not story_files:
        print("No .txt files found.")
        sys.exit(1)

    rows = []
    skipped = []

    for path in story_files:
        true_label = true_label_from_filename(path.name)
        if true_label is None:
            skipped.append(path.name)
            continue

        text     = path.read_text(encoding="utf-8")
        features = extract_features(text)
        X        = feature_matrix(features)

        # Binary prediction (suitable for 4-6?)
        if binary_model is not None:
            binary_pred  = int(binary_model.predict(X)[0])
            binary_prob  = round(float(binary_model.predict_proba(X)[0][1]), 3)
            binary_label = "4-6" if binary_pred == 1 else "not-4-6"
        else:
            binary_prob  = None
            binary_label = "n/a (model missing)"

        # Multiclass prediction
        if multi_model is not None:
            multi_idx  = int(multi_model.predict(X)[0])
            multi_probs = multi_model.predict_proba(X)[0]
            multi_pred  = ID_TO_AGE[multi_idx]
            prob_str    = "  ".join(
                f"P({ID_TO_AGE[i]})={round(float(p), 3):.3f}"
                for i, p in enumerate(multi_probs)
            )
        else:
            multi_pred = "n/a"
            prob_str   = ""

        rows.append({
            "file":            path.name,
            "topic":           path.parent.name,
            "true_label":      true_label,
            "binary_pred":     binary_label,
            "binary_prob_4_6": binary_prob,
            "multi_pred":      multi_pred,
            "prob_4_6":        round(float(multi_probs[0]), 3) if multi_model else None,
            "prob_7_12":       round(float(multi_probs[1]), 3) if multi_model else None,
            "prob_13+":        round(float(multi_probs[2]), 3) if multi_model else None,
            "flesch":          features["flesch_score"],
            "avg_word_len":    features["avg_word_length"],
            "raw_words":       features["raw_word_count"],
        })

    results = pd.DataFrame(rows)

    # ── Per-story table ───────────────────────────────────────────────────────
    print("=" * 90)
    print("PER-STORY RESULTS")
    print("=" * 90)
    for _, r in results.iterrows():
        binary_ok = (
            (r["true_label"] == "4-6"   and r["binary_pred"] == "4-6") or
            (r["true_label"] != "4-6"   and r["binary_pred"] == "not-4-6") or
            r["true_label"] == "adult"
        )
        multi_ok = r["true_label"] == r["multi_pred"] or r["true_label"] == "adult"

        print(
            f"  {r['file'][:55]:<55}"
            f"  true={r['true_label']:<5}"
            f"  binary={'✓' if binary_ok else '✗'} ({r['binary_pred']}, p={r['binary_prob_4_6']})"
            f"  multi={'✓' if multi_ok else '✗'} ({r['multi_pred']})"
            f"  flesch={r['flesch']}"
        )

    # ── Accuracy (child stories only) ────────────────────────────────────────
    child_rows = results[results["true_label"].isin(["4-6", "7-12", "13+"])].copy()

    if not child_rows.empty:
        # Binary: correct if true==4-6 ↔ pred==4-6
        child_rows["binary_correct"] = (
            (child_rows["true_label"] == "4-6") == (child_rows["binary_pred"] == "4-6")
        )
        # Multiclass: correct if true_label == multi_pred
        child_rows["multi_correct"] = child_rows["true_label"] == child_rows["multi_pred"]

        binary_acc = child_rows["binary_correct"].mean()
        multi_acc  = child_rows["multi_correct"].mean()

        print("\n" + "=" * 90)
        print("ACCURACY ON GENERATED STORIES (child audiences only)")
        print("=" * 90)
        print(f"  Binary  (suitable-4-6 vs. not):  {binary_acc:.1%}  "
              f"({child_rows['binary_correct'].sum()}/{len(child_rows)})")
        print(f"  Multiclass (age group match):     {multi_acc:.1%}  "
              f"({child_rows['multi_correct'].sum()}/{len(child_rows)})")

        # Per-age-group breakdown
        print("\n  Multiclass breakdown by true age group:")
        for age in ["4-6", "7-12", "13+"]:
            grp = child_rows[child_rows["true_label"] == age]
            if grp.empty:
                continue
            acc = grp["multi_correct"].mean()
            print(f"    {age:<5}  {acc:.1%}  ({grp['multi_correct'].sum()}/{len(grp)})")

        # Confusion: where does each group land?
        print("\n  Predicted distribution per true age group (multiclass):")
        confusion = pd.crosstab(
            child_rows["true_label"],
            child_rows["multi_pred"],
            rownames=["true"],
            colnames=["predicted"],
        ).reindex(index=["4-6","7-12","13+"], columns=["4-6","7-12","13+"], fill_value=0)
        print(confusion.to_string())

    # ── Feature summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 90)
    print("MEAN FEATURES BY TRUE AGE GROUP (generated stories)")
    print("=" * 90)
    if not child_rows.empty:
        summary = child_rows.groupby("true_label")[
            ["flesch", "avg_word_len", "raw_words"]
        ].mean().round(2).reindex(["4-6", "7-12", "13+"])
        print(summary.to_string())

    # ── Skipped ───────────────────────────────────────────────────────────────
    if skipped:
        print(f"\nSkipped (no age label in filename): {skipped}")

    # ── Save CSV ──────────────────────────────────────────────────────────────
    out_path = Path(model_dir) / "story_evaluation_results.csv"
    results.to_csv(out_path, index=False)
    print(f"\nFull results saved to: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate StoryGuard models on generated stories")
    parser.add_argument("--stories", default=str(DEFAULT_STORIES_DIR),
                        help="Path to stories directory")
    parser.add_argument("--models",  default=str(DEFAULT_MODEL_DIR),
                        help="Path to directory containing .joblib model files")
    args = parser.parse_args()

    run(args.stories, args.models)
