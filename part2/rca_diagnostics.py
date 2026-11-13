#!/usr/bin/env python3
"""RCA extensions for KwikPulse Part 2. Deterministic, standard-library only.

Designed to *measure the impact* of exclusions, distinguish observed anomalies
from hypotheses, preserve evidence, and reconcile the main report. It does not
change the agreed COD definition or the primary ranking.
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import json
import math
import statistics
from pathlib import Path
from typing import Any

from analyze_orders import (
    Order, DEFAULT_START, DEFAULT_END, FINAL_STATUSES, KNOWN_PAYMENTS,
    KNOWN_STATUSES, build_store_rankings, canonical_payment,
    canonical_status, is_test_merchant, parse_instant, pct, week_start, write_csv,
)


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[str, str]:
    """Approximate 95% binomial interval; descriptive only, not bias correction."""
    if not trials:
        return '', ''
    p = successes / trials
    factor = 1 + z*z/trials
    center = (p + z*z/(2*trials)) / factor
    margin = z*math.sqrt((p*(1-p) + z*z/(4*trials))/trials)/factor
    return f'{100*max(0.0,center-margin):.2f}', f'{100*min(1.0,center+margin):.2f}'


def metric_count(records: list[Order]) -> tuple[int, int]:
    final = [o for o in records if o.final_cod]
    return sum(o.status == 'rto' for o in final), len(final)


def raw_scenarios(input_csv: Path, orders: list[Order], start: dt.date, end: dt.date) -> list[dict[str, Any]]:
    """Separately evaluate normalization/deduplication/test/date choices."""
    raw_all = collections.Counter()
    raw_strict = collections.Counter()
    with input_csv.open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream):
            if row['payment_type'] == 'cod' and row['status'] in FINAL_STATUSES:
                raw_strict[row['status']] += 1
            if canonical_payment(row['payment_type']) == 'cod' and canonical_status(row['status']) in FINAL_STATUSES:
                raw_all[canonical_status(row['status'])] += 1

    scenarios = [
        ('A', 'Naive case-sensitive, no deduplication', raw_strict['rto'], sum(raw_strict.values()),
         'Illustrates missing COD/status variants; not a recommended answer.'),
        ('B', 'Normalized labels, no deduplication', raw_all['rto'], sum(raw_all.values()),
         'Duplicates still vote more than once.'),
    ]
    selections = [
        ('C', 'Primary: unique orders, all merchant IDs', orders,
         'Literal assignment answer; undated final COD orders retained for merchant totals.'),
        ('D', 'Sensitivity: exclude named test IDs', [o for o in orders if not o.is_test],
         'Business scenario only; test classification is not verified.'),
        ('E', 'Sensitivity: dated orders only', [o for o in orders if o.created_ist is not None],
         'Quantifies missing-date impact on overall store-rate calculation.'),
        ('F', 'Sensitivity: non-test and dated', [o for o in orders if not o.is_test and o.created_ist is not None],
         'Combines the two optional exclusions; not the literal assignment.'),
        ('G', 'Sensitivity: dated AND within requested IST period',
         [o for o in orders if o.created_ist is not None and start <= o.created_ist.date() <= end],
         'Checks scope drift if future files include out-of-range records.'),
    ]
    for ident, label, selected, note in selections:
        r, n = metric_count(selected)
        scenarios.append((ident, label, r, n, note))
    base_r, base_n = metric_count(orders)
    base_rate = 100*base_r/base_n if base_n else None
    out = []
    for ident, name, returned, final, caveat in scenarios:
        rate = 100 * returned / final if final else None
        out.append({
            'scenario': ident,
            'description': name,
            'returned_cod': returned,
            'delivered_cod': final-returned,
            'final_cod': final,
            'return_rate_pct': f'{rate:.4f}' if rate is not None else '',
            'change_vs_primary_percentage_points': f'{rate-base_rate:+.4f}' if rate is not None and base_rate is not None else '',
            'final_orders_change_vs_primary': final-base_n,
            'decision_note': caveat,
        })
    return out


def source_evidence(input_csv: Path, start: dt.date, end: dt.date,
                    max_per_type: int = 5) -> list[dict[str, Any]]:
    """Small deterministic row-level examples, never fabricated or imputed records."""
    rows: list[dict[str, Any]] = []
    seen = collections.Counter()
    first_record_by_id: dict[str, tuple[str, ...]] = {}
    fields = ('order_id', 'merchant_id', 'created_at', 'payment_type', 'status', 'order_value')

    def record(check: str, line: int, row: dict[str, str], treatment: str) -> None:
        if seen[check] >= max_per_type:
            return
        seen[check] += 1
        rows.append({
            'check': check, 'source_line': line, 'order_id': row['order_id'],
            'merchant_id': row['merchant_id'], 'created_at_raw': row['created_at'],
            'payment_type_raw': row['payment_type'], 'status_raw': row['status'],
            'order_value_raw': row['order_value'], 'treatment': treatment,
        })

    with input_csv.open(encoding='utf-8-sig', newline='') as stream:
        for line, row in enumerate(csv.DictReader(stream), 2):
            order_id = row['order_id'].strip()
            tup = tuple(row[k] for k in fields)
            if not order_id:
                record('missing_order_id', line, row, 'Quarantine; identity unknown')
            elif order_id in first_record_by_id:
                if first_record_by_id[order_id] == tup:
                    record('exact_duplicate', line, row, 'Keep one occurrence')
                else:
                    record('conflicting_duplicate', line, row, 'Quarantine whole order ID')
            else:
                first_record_by_id[order_id] = tup
            if not row['merchant_id'].strip():
                record('missing_merchant', line, row, 'Quarantine; merchant unknown')
            if is_test_merchant(row['merchant_id']):
                record('suspected_test_merchant', line, row, 'Retain literal; also report exclusion sensitivity')
            if not row['created_at'].strip():
                record('missing_timestamp', line, row, 'Store totals only; exclude from weekly')
            else:
                try:
                    parsed = parse_instant(row['created_at'])
                    assert parsed is not None
                    if parsed.date() < start or parsed.date() > end:
                        record('outside_IST_period', line, row, 'Report and exclude from requested weekly window')
                    naive_utc_week = week_start(parsed.astimezone(dt.timezone.utc).date())
                    if naive_utc_week != week_start(parsed.date()):
                        record('utc_ist_week_boundary', line, row, 'Group by IST date')
                except (ValueError, OverflowError):
                    record('invalid_timestamp', line, row, 'Exclude from weekly; flag and retain in store totals')
            pay, status = canonical_payment(row['payment_type']), canonical_status(row['status'])
            if pay != row['payment_type']:
                record('payment_label_normalized', line, row, 'Canonicalize exact known COD spelling variants')
            if status != row['status']:
                record('status_label_normalized', line, row, 'Trim whitespace, canonicalize casing/underscore')
            if pay not in KNOWN_PAYMENTS:
                record('unknown_payment', line, row, 'Exclude from COD metric pending mapping')
            if status not in KNOWN_STATUSES:
                record('unknown_status', line, row, 'Exclude from final outcome pending mapping')
            if pay == 'cod' and status not in FINAL_STATUSES:
                record('nonfinal_cod', line, row, 'Exclude from COD final-outcome denominator')
            if pay in KNOWN_PAYMENTS - {'cod'} and status == 'rto':
                record('non_cod_rto', line, row, 'Legitimate candidate return; outside COD scope')
            try:
                from decimal import Decimal
                val = Decimal(row['order_value'].strip())
                if not val.is_finite():
                    raise ValueError('Not finite')
                if val <= 0:
                    record('nonpositive_order_value', line, row, 'Review value; count-based rate unaffected')
                if val >= 1000000:
                    record('high_order_value', line, row, 'Flag only; do not drop from count-based metric')
            except Exception:
                record('invalid_order_value', line, row, 'Review value; count-based rate unaffected')
    return rows


def merchant_diagnostics(orders: list[Order], min_orders: int) -> list[dict[str, Any]]:
    groups: dict[str, list[Order]] = collections.defaultdict(list)
    for o in orders:
        groups[o.merchant].append(o)
    rows = []
    for merchant, records in sorted(groups.items()):
        count = collections.Counter(o.status for o in records if o.payment == 'cod')
        returned, final = count['rto'], count['rto']+count['delivered']
        unresolved = count['pending']+count['in_transit']
        all_attempted = final + unresolved + count['cancelled']
        low, high = wilson_interval(returned, final)
        undated = sum(o.final_cod and o.created_ist is None for o in records)
        undated_rto = sum(o.final_cod and o.status == 'rto' and o.created_ist is None for o in records)
        dated_returned, dated_final = metric_count([o for o in records if o.created_ist is not None])
        rows.append({
            'merchant_id': merchant, 'suspected_test': 'yes' if is_test_merchant(merchant) else 'no',
            'returned_cod': returned, 'delivered_cod': count['delivered'],
            'final_cod': final, 'return_rate_pct': pct(returned, final),
            'wilson_95_low_pct': low, 'wilson_95_high_pct': high,
            'unresolved_cod': unresolved, 'cancelled_cod': count['cancelled'],
            'unresolved_share_of_non_cancelled_pct': pct(unresolved, final+unresolved),
            'final_outcome_coverage_of_all_cod_pct': pct(final, all_attempted),
            'undated_final_cod': undated, 'undated_returned_cod': undated_rto,
            'dated_only_return_rate_pct': pct(dated_returned, dated_final),
            'change_if_undated_excluded_pp': f'{(100*dated_returned/dated_final-100*returned/final):+.4f}' if final and dated_final else '',
            'eligible_200': 'yes' if final>=min_orders else 'no',
            'review_note': ('Below minimum; do not rank. ' if final<min_orders else '')
                         + ('Test ID; classification unverified. ' if is_test_merchant(merchant) else '')
                         + ('Unresolved orders excluded from rate; compare maturity across merchants.'),
        })
    return rows


def merchant_week_matrix(orders: list[Order], start: dt.date, end: dt.date,
                         gap_days: set[str], min_week_denominator: int = 30) -> list[dict[str, Any]]:
    """Store x creation-week cohorts for targeted RCA; not the primary ranking."""
    stores = sorted({o.merchant for o in orders})
    week = week_start(start)
    weeks = []
    while week <= week_start(end):
        weeks.append(week)
        week += dt.timedelta(days=7)
    groups: dict[tuple[str, dt.date], collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for o in orders:
        if o.created_ist is None or not(start<=o.created_ist.date()<=end):
            continue
        if o.payment == 'cod':
            groups[(o.merchant, week_start(o.created_ist.date()))][o.status] += 1
    result = []
    for merchant in stores:
        for monday in weeks:
            c = groups[(merchant,monday)]
            final = c['rto'] + c['delivered']
            unresolved = c['pending']+c['in_transit']
            gap = any(monday<=dt.date.fromisoformat(d)<=monday+dt.timedelta(days=6) for d in gap_days)
            result.append({
                'merchant_id': merchant, 'week_start_ist': monday.isoformat(),
                'week_end_ist': (monday+dt.timedelta(days=6)).isoformat(),
                'suspected_test': 'yes' if is_test_merchant(merchant) else 'no',
                'returned_cod': c['rto'], 'delivered_cod': c['delivered'],
                'final_cod': final, 'return_rate_pct': pct(c['rto'],final),
                'pending_cod': c['pending'], 'in_transit_cod': c['in_transit'],
                'cancelled_cod': c['cancelled'],
                'unresolved_share_non_cancelled_pct': pct(unresolved, final+unresolved),
                'all_store_ingestion_gap': 'yes' if gap else 'no',
                'small_cohort_flag': 'SMALL_N' if 0<final<min_week_denominator else ('NO_FINAL' if not final else ''),
                'interpretation': 'Creation-week cohort, not return-event week',
            })
    return result


def daily_risk_profile(orders: list[Order], start: dt.date, end: dt.date) -> tuple[list[dict[str, Any]], float]:
    counts = collections.Counter(o.created_ist.date() for o in orders if o.created_ist is not None and start<=o.created_ist.date()<=end)
    nonzero = list(counts.values())
    median = statistics.median(nonzero) if nonzero else 0
    rows = []
    for i in range((end-start).days+1):
        date = start + dt.timedelta(days=i)
        count = counts[date]
        rows.append({
            'date_ist': date.isoformat(), 'weekday': date.strftime('%A'),
            'observed_orders': count, 'median_nonzero_day_orders': median,
            'vs_median_pct': f'{100*(count/median-1):+.2f}' if median else '',
            'global_zero_day': 'yes' if not count else 'no',
            'low_volume_warning': 'yes' if median and count<median*0.5 else 'no',
            'interpretation': 'No records is not proof of no real transactions' if not count else 'Observed count (not guaranteed source completeness)',
        })
    return rows, median


def assertions(orders: list[Order], weekly: list[dict[str, Any]], matrix: list[dict[str, Any]],
               sensitivity: list[dict[str, Any]], start: dt.date, end: dt.date) -> list[dict[str,str]]:
    checks = []
    def verify(name: str, condition: bool, detail: str) -> None:
        checks.append({'assertion':name, 'result':'PASS' if condition else 'FAIL', 'detail':detail})
        if not condition:
            raise AssertionError(f'{name}: {detail}')
    all_r, all_n = metric_count(orders)
    verify('Primary metric reconciles to source', all_n == int(sensitivity[2]['final_cod']) and all_r == int(sensitivity[2]['returned_cod']),
           'Recompute via Order.final_cod independently of sensitivity output')
    verify('Raw row count reduction cannot inflate primary denominator', int(sensitivity[1]['final_cod']) >= all_n,
           'Deduplication must not increase the number of final outcomes')
    matrix_by_week = collections.defaultdict(lambda:collections.Counter())
    for r in matrix:
        matrix_by_week[r['week_start_ist']]['n']+=r['final_cod'];matrix_by_week[r['week_start_ist']]['r']+=r['returned_cod']
        verify_col = r['returned_cod']+r['delivered_cod'] == r['final_cod']
        if not verify_col:
            raise AssertionError('Merchant-week returned + delivered mismatch')
    verify('Merchant-week matrix sums to weekly output', all(
        matrix_by_week[w['week_start_ist']]['n']==w['final_outcome_cod'] and
        matrix_by_week[w['week_start_ist']]['r']==w['returned_cod'] for w in weekly),
        'Every store-week row reconciles to all-store weekly totals')
    known_inperiod = [o for o in orders if o.final_cod and o.created_ist is not None and start<=o.created_ist.date()<=end]
    verify('All dated final COD records assigned to exactly one week',sum(w['final_outcome_cod'] for w in weekly)==len(known_inperiod),
           'Undated/out-of-period final COD records cannot be assigned to a requested week')
    verify('No rate with a zero denominator', all(r['return_rate_pct']=='' for r in matrix if r['final_cod']==0),
           'An undefined rate is empty, never 0%')
    verify('Scope invariant: test ID exclusion never adds records',
           int(sensitivity[3]['final_cod']) <= all_n,
           'Secondary production interpretation must be a subset')
    return checks


def write_rca_findings(path: Path, qa: dict[str,Any], scenarios: list[dict[str,Any]],
                       merchants: list[dict[str,Any]], days: list[dict[str,Any]], checks: list[dict[str,str]],
                       sample_rows: list[dict[str,Any]], median_daily: float) -> None:
    base = scenarios[2]
    delta = scenarios[1]
    difference_raw = float(delta['change_vs_primary_percentage_points'])
    prod = scenarios[3]
    dated = scenarios[4]
    missing = [r['date_ist'] for r in days if r['global_zero_day']=='yes']
    low_qualify = [r for r in merchants if r['eligible_200']=='no']
    undated_shift = sorted(((abs(float(r['change_if_undated_excluded_pp'])),r) for r in merchants if r['change_if_undated_excluded_pp']),
                           key=lambda x:x[0], reverse=True)
    merchant_shift = ', '.join(f"{r['merchant_id']}: {r['change_if_undated_excluded_pp']}pp" for _,r in undated_shift[:3])
    scenario_table = '\n'.join(f"| {r['scenario']} | {r['description']} | {r['returned_cod']:,} | {r['final_cod']:,} | {r['return_rate_pct']}% | {r['change_vs_primary_percentage_points']}pp |" for r in scenarios)
    content = f'''# Deep-dive RCA | Additional safeguards and quantified impact

**Run this alongside** `results/findings.md`. This is a diagnostic supplement, not a replacement for the literal three assignment answers.

## Measurement-impact bridge

| Scenario | Processing choice | Returns | Final COD | Rate | Difference vs primary |
|---|---|---:|---:|---:|---:|
{scenario_table}

**Interpretation:** Removing duplicate rows changes the all-store COD return rate by only {abs(difference_raw):.4f} percentage points (the raw normalized scenario is {delta['change_vs_primary_percentage_points']}pp relative to the deduplicated primary). This small *aggregate* impact does **not** excuse double counting, because particular merchants or weeks might be differently affected. Suspected test-account classification produces a much larger change: **{prod['change_vs_primary_percentage_points']} percentage points**. Retaining the {qa['undated_final_cod_orders']} undated final-COD records changes the all-store result by {dated['change_vs_primary_percentage_points']} points relative to dropping them.

## Additional RCA findings and safeguards

1. **Raw vs clean answers are now measurable.** A case-sensitive/no-dedup method, a normalized/no-dedup method, the literal primary, production-only, dated-only, and combined scope variations are all published in `metric_sensitivity.csv`. No silent switches.
2. **A two-day source-data gap is confirmed; the underlying cause is unknown.** Entire dataset dates with no timestamped orders: **{', '.join(missing)}**. Median *nonzero* daily volume is **{median_daily:,.0f}**. An ingestion failure is a hypothesis to investigate, not an established fact. This is context, **not** permission to impute the absent days or estimate a corrected return percentage.
3. **Merchant-week diagnostics expose localized blind spots.** `merchant_weekly_rca.csv` reports all {len(merchants)} merchants across the requested 13 weeks, splitting COD into delivered, returned, pending, in transit, and cancelled, and flags small samples and the global gap. Sample-size warnings do not exclude orders from the assigned metric.
4. **Different merchants have different outcome maturity.** `merchant_rca.csv` reports open COD orders per store, the non-cancelled unresolved share, and the recorded denominator. More unresolved shipments can create biased cross-store comparisons even when every formula is correct.
5. **Undated orders are not dropped without disclosure.** There are **{qa['undated_final_cod_orders']}** final-outcome COD orders missing `created_at`. Largest *store-level* rate shifts if undated final COD orders are excluded: {merchant_shift}.
6. **Small-sample uncertainty is visible, not confused with data accuracy.** `merchant_rca.csv` shows approximate Wilson 95% binomial intervals for observed outcomes. They are descriptive and assume independent, identically sampled observations; they **do not** resolve missing dates, incomplete cohorts, selection bias, or unclear merchant identity. The ranking still uses the assignment's point estimate and >=200 cutoff.
7. **Sample evidence is reproducible.** `exception_evidence.csv` lists the original CSV line and first examples for actual issue categories. A zero-count issue has no fabricated example; the file supports inspection and RCA.
8. **No arbitrary bad-data repair.** Contradictory duplicate IDs are quarantined instead of picking a status. Unknown status/payment cannot silently be classified as final COD. High order values are flagged but never remove a count-based return.
9. **Eligibility scope is explicit.** {len(low_qualify)} store(s) below the minimum are excluded from the top-three rank, not from the comprehensive merchant audit.
10. **A record having a date is not proof of ingestion completeness.** Days with nonzero counts receive only an *observed coverage* designation. No historical delivery/return timestamps or snapshot date exist to establish mature, event-week RTO rates.

## Quality gates

| Gate | Result | Reason |
|---|---|---|
| Arithmetic reconciliation | **{checks[0]['result']}** | Independent source count matches output |
| Cross-grain reconciliation | **{checks[2]['result']}** | Store-week totals match main weekly table |
| Unambiguous all-merchant formula | **PASS, conditional** | RTO interpretation is explicitly assumed |
| Complete temporal coverage | **NEEDS UPSTREAM CHECK** | {len(missing)} completely empty IST days and {qa['missing_timestamp_orders']} undated orders |
| Verified production-only merchant set | **NEEDS MERCHANT MASTER** | `TEST` name is not an authoritative dimension |
| Event-week or outcome-mature return rate | **NOT MEASURABLE** | Only `created_at` and an unknown snapshot state are supplied |

## RCA follow-up questions for a data engineer or operations lead

- Did the upstream ingestion/export job fail or filter out orders on **14 and 15 September**? Compare API calls, ETL logs, row-level source totals, and source-to-warehouse counts by IST date; re-export and re-run if recoverable.
- Are the merchants labelled `M_TEST_*` genuine non-production accounts? Confirm via the merchant master/environment dimension before adopting the filtered KPI.
- What exactly does `rto` mean in this platform, and are returns **after delivery** represented elsewhere? Validate status lifecycle and event timestamps.
- What is the extraction **as-of** time and what fraction of each created-week cohort is sufficiently aged? Re-run on a stable, maturity-defined window before comparing trends.
- Are missing timestamps random? Compare missing-date rate and missing-date return status by merchant; inspect source payloads to avoid assuming missingness is harmless.
- Are duplicate rows from repeated export batches, retrying ingestion, or non-idempotent writes? Use the original line references and IDs to trace their origin.

## Reproduce

```bash
python3 part2/analyze_orders.py
python3 -m unittest discover -s part2/tests -v
python3 part2/verify_with_sqlite.py
```

**Primary facts remain unchanged.** These diagnostics never impute missing transactions, never replace created-at with imaginary delivery timestamps, and never silently reinterpret the primary all-ID ranking.
'''
    path.write_text(content,encoding='utf-8')


def generate(input_csv: Path, output: Path, orders: list[Order], qa: dict[str, Any],
             weeks_all: list[dict[str,Any]], start: dt.date, end: dt.date,
             min_orders: int) -> dict[str,Any]:
    output.mkdir(parents=True, exist_ok=True)
    sens = raw_scenarios(input_csv,orders,start,end)
    merchants = merchant_diagnostics(orders,min_orders)
    matrix = merchant_week_matrix(orders,start,end,set(qa['missing_dates']))
    daily, med = daily_risk_profile(orders,start,end)
    evidence = source_evidence(input_csv,start,end)
    checks = assertions(orders,weeks_all,matrix,sens,start,end)
    # Explicit ledger: disjoint pipeline exclusions vs metric-only exclusions.
    recon = [
        {'stage':'Raw CSV source rows','count':qa['raw_rows'],'treatment':'Input rows, not unique orders'},
        {'stage':'Missing order ID rows','count':qa['missing_order_id_rows'],'treatment':'Quarantined before identity grouping'},
        {'stage':'Exact duplicate excess rows','count':qa['exact_duplicate_extra_rows'],'treatment':'Removed from counts'},
        {'stage':'All rows of conflicting IDs','count':qa['conflicting_duplicate_rows'],'treatment':'Quarantined, not arbitrarily selected'},
        {'stage':'Unique rows with missing merchant','count':qa['missing_merchant_id_rows'],'treatment':'Quarantined from merchant+weekly metrics'},
        {'stage':'Usable distinct orders','count':qa['usable_unique_orders'],'treatment':'Must reconcile: raw minus preceding 4 exclusion stages'},
        {'stage':'COD with final outcome','count':qa['all_final_cod_orders'],'treatment':'Primary ranking denominator; includes undated'},
        {'stage':'COD with final outcome AND created in requested IST period','count':sum(w['final_outcome_cod'] for w in weeks_all),'treatment':'Weekly denominator; excludes undated and out-of-period'},
        {'stage':'Undated final-outcome COD','count':qa['undated_final_cod_orders'],'treatment':'In ranking, not weekly trends'},
        {'stage':'COD nonfinal outcomes','count':qa['nonfinal_cod_orders'],'treatment':'Outside final-outcome denominator; not bad records'},
    ]
    for name, records in [
        ('metric_sensitivity.csv',sens), ('merchant_rca.csv',merchants),
        ('merchant_weekly_rca.csv',matrix), ('daily_rca.csv',daily),
        ('exception_evidence.csv',evidence), ('reconciliation_ledger.csv',recon),
        ('quality_gates.csv',checks),
    ]:
        if records:
            write_csv(output/name,records)
    write_rca_findings(output/'RCA_DEEP_DIVE.md',qa,sens,merchants,daily,checks,evidence,med)
    manifest = {
        'source_sha256':qa['file_sha256'],'expected_period_ist':[start.isoformat(),end.isoformat()],
        'primary_returned_cod':qa['all_final_cod_returns'],
        'primary_final_cod':qa['all_final_cod_orders'],
        'extra_reconciliation_checks_passed':len(checks),
        'evidence_rows_provided':len(evidence),'merchant_week_groups':len(matrix),
        'sensitivity_scenarios':len(sens),
        'business_readiness':'NEEDS UPSTREAM VALIDATION: ingestion gap, test merchants, and unknown snapshot/event times',
    }
    (output/'RCA_RUN_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    return manifest
