"""Train, evaluate, and publish the Renvue recovery policy.

    PYTHONPATH=src .venv/bin/python scripts/train_policy.py

The simulator is synthetic and the report says so. The script is deterministic
for a fixed seed and writes a dataset hash into every artifact.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
SRC = BACKEND / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ml.evaluation import (  # noqa: E402
    ARTIFACT_DIR,
    benchmark,
    render_model_card,
    render_report,
    save_metrics,
)
from ml.models import save_bundle, train_policy  # noqa: E402
from ml.sim import SimConfig, generate_dataset, generate_sensitivity  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="small smoke run; do not ship artifacts")
    args = parser.parse_args()

    if args.quick:
        config = SimConfig(train_per_world=1_500, val_per_world=500, test_per_world=500, rct_per_world=300)
        sensitivity_n = 600
    else:
        config = SimConfig()
        sensitivity_n = 2_000

    print(f"[1/5] Generating simulator data (seed={config.seed})...")
    data = generate_dataset(config)
    print(f"      train={data['meta']['train_rows']:,} val={data['meta']['val_rows']:,} "
          f"test={data['meta']['test_episodes']:,} potential={data['meta']['test_potential_rows']:,} "
          f"hash={data['meta']['dataset_hash']}")

    print("[2/5] Generating sensitivity worlds...")
    data["sensitivity"] = generate_sensitivity(config, n=sensitivity_n)

    print("[3/5] Training M1 propensity + M2 action-response models...")
    bundle, metrics = train_policy(data)
    path = save_bundle(bundle)
    print(f"      artifact={path} ({path.stat().st_size / 1_048_576:.2f} MB)")
    print(f"      AUROC={metrics['auroc']:.3f} AUPRC={metrics['auprc']:.3f} "
          f"Brier={metrics['brier']:.3f} ECE={metrics['ece']:.3f}")

    print("[4/5] Benchmarking held-out policies...")
    results = benchmark(data, bundle)
    metrics_path = save_metrics(results)
    print(f"      metrics={metrics_path}")
    for name in ("no_contact", "rules", "ml_ev", "oracle"):
        row = results["policies"][name]
        print(f"      {name:12s} ${row['net_per_1000']:>9,.0f}/1k  "
              f"recovery={row['recovery_rate_pct']:.1f}%  "
              f"guardrail_changes={row['guardrail_changes']}")
    print(f"      ML vs rules: ${results['lift']['ml_vs_rules_per_1000']:,.0f}/1k "
          f"CI {results['lift']['ml_vs_rules_ci']}")
    print(f"      oracle gap closed: {results['lift']['oracle_gap_closed_pct']}%")

    print("[5/5] Writing model card and evaluation report...")
    report = render_report(results)
    card = render_model_card(bundle, results)
    print(f"      report={report}")
    print(f"      card={card}")
    print("Done. The live server loads the artifact on its next request (or restart).")


if __name__ == "__main__":
    main()
