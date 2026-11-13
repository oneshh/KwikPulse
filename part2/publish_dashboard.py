#!/usr/bin/env python3
"""Copy the Part 2 offline dashboard into existing KwikPulse GitHub Pages source.

Use after analyze_orders.py. This does not alter docs/index.html, docs/data,
or the existing Part 1 collector/workflow; it only updates docs/part2/.
"""
from pathlib import Path
from shutil import copy2

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = HERE / 'results'
DST = ROOT / 'docs' / 'part2'


def publish() -> None:
    DST.mkdir(parents=True, exist_ok=True)
    (DST / 'results').mkdir(exist_ok=True)
    for file in [HERE / 'index.html']:
        copy2(file, DST / file.name)
    for name in ('weekly_cod_all_merchants.csv', 'weekly_cod_production_only.csv',
                 'store_rankings_all_merchants.csv', 'store_rankings_production_only.csv',
                 'data_quality_issues.csv', 'findings.md', 'metrics.json',
                 'RCA_DEEP_DIVE.md', 'RCA_RUN_MANIFEST.json', 'metric_sensitivity.csv',
                 'merchant_rca.csv', 'merchant_weekly_rca.csv', 'daily_rca.csv',
                 'exception_evidence.csv', 'reconciliation_ledger.csv', 'quality_gates.csv'):
        copy2(SRC / name, DST / 'results' / name)
    print(f'Published static Part 2 assets to {DST} (Part 1 files untouched)')


if __name__ == '__main__':
    publish()
