#!/usr/bin/env python3
"""KwikPulse Part 2 | reproducible COD return-rate analysis.

Python 3.9+ standard library only; no data changes or external requests.
Run: python3 part2/analyze_orders.py --input part2/orders.csv --output part2/results
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import html
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo('Asia/Kolkata')
REQUIRED_FIELDS = ('order_id', 'merchant_id', 'created_at', 'payment_type', 'status', 'order_value')
FINAL_STATUSES = {'delivered', 'rto'}
KNOWN_STATUSES = {'delivered', 'rto', 'cancelled', 'pending', 'in_transit'}
KNOWN_PAYMENTS = {'cod', 'upi', 'card', 'netbanking'}
DEFAULT_START = dt.date(2026, 7, 27)
DEFAULT_END = dt.date(2026, 10, 25)
MIN_ELIGIBLE = 200


@dataclass(frozen=True)
class Order:
    order_id: str
    merchant: str
    created_ist: dt.datetime | None
    payment: str
    status: str
    value: Decimal | None
    original_created_at: str

    @property
    def final_cod(self) -> bool:
        return self.payment == 'cod' and self.status in FINAL_STATUSES

    @property
    def is_test(self) -> bool:
        return is_test_merchant(self.merchant)


def is_test_merchant(merchant: str) -> bool:
    """Explicit convention observed in supplied dataset, not a general ML guess."""
    return bool(re.search(r'(^|[_-])TEST(?=$|[_-]|\d)', merchant, flags=re.I))


def canonical_payment(raw: str) -> str:
    value = re.sub(r'\s+', ' ', (raw or '').strip()).casefold()
    return 'cod' if value in ('cod', 'cash on delivery', 'cash-on-delivery') else value


def canonical_status(raw: str) -> str:
    value = re.sub(r'\s+', '_', (raw or '').strip()).casefold()
    return value.replace('-', '_')


def parse_instant(raw: str) -> dt.datetime | None:
    value = (raw or '').strip()
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value[:-1] + '+00:00' if value.endswith(('Z', 'z')) else value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('Timestamp has no timezone offset')
    return parsed.astimezone(IST)


def week_start(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def pct(numerator: int, denominator: int) -> str:
    return f'{numerator * 100 / denominator:.2f}' if denominator else ''


def read_and_audit(path: Path, start: dt.date, end: dt.date) -> tuple[list[Order], dict[str, Any]]:
    qa: dict[str, Any] = {
        'file_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'raw_rows': 0,
        'exact_duplicate_extra_rows': 0,
        'conflicting_duplicate_order_ids': 0,
        'conflicting_duplicate_rows': 0,
        'missing_order_id_rows': 0,
        'missing_merchant_id_rows': 0,
        'missing_timestamp_orders': 0,
        'invalid_timestamp_orders': 0,
        'outside_expected_period_orders': 0,
        'payment_labels_normalized': 0,
        'status_labels_normalized': 0,
        'unknown_payment_orders': 0,
        'unknown_status_orders': 0,
        'invalid_value_orders': 0,
        'nonpositive_value_orders': 0,
        'million_plus_value_orders': 0,
        'utc_ist_week_migrations': 0,
        'utc_ist_day_migrations': 0,
        'test_merchant_orders': 0,
        'prepaid_rto_orders': 0,
        'raw_payment_values': {},
        'raw_status_values': {},
        'missing_dates': [],
        'invalid_examples': {},
    }
    by_id: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
    row_ids_missing: list[int] = []
    with path.open('r', encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError('Missing CSV header or duplicate column names')
        missing_fields = set(REQUIRED_FIELDS) - set(reader.fieldnames)
        if missing_fields:
            raise ValueError(f'Missing required columns: {sorted(missing_fields)}')
        if set(reader.fieldnames) != set(REQUIRED_FIELDS):
            raise ValueError(f'Unexpected CSV columns: {reader.fieldnames}')
        for line_number, row in enumerate(reader, start=2):
            qa['raw_rows'] += 1
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f'Broken CSV field count at line {line_number}')
            order_id = row['order_id'].strip()
            if not order_id:
                qa['missing_order_id_rows'] += 1
                row_ids_missing.append(line_number)
                continue
            by_id[order_id].append(row)
    qa['unique_order_ids_observed'] = len(by_id)
    raw_payment_counts: collections.Counter[str] = collections.Counter()
    raw_status_counts: collections.Counter[str] = collections.Counter()
    orders: list[Order] = []
    for order_id, records in by_id.items():
        different = {tuple(r[k] for k in REQUIRED_FIELDS) for r in records}
        if len(different) > 1:
            # No arbitrary first/last-wins for contradictory duplicate transaction IDs.
            qa['conflicting_duplicate_order_ids'] += 1
            qa['conflicting_duplicate_rows'] += len(records)
            continue
        qa['exact_duplicate_extra_rows'] += len(records) - 1
        raw = records[0]
        merchant = raw['merchant_id'].strip()
        if not merchant:
            qa['missing_merchant_id_rows'] += 1
            continue
        raw_payment_counts[raw['payment_type']] += 1
        raw_status_counts[raw['status']] += 1
        payment = canonical_payment(raw['payment_type'])
        status = canonical_status(raw['status'])
        if payment != raw['payment_type']:
            qa['payment_labels_normalized'] += 1
        if status != raw['status']:
            qa['status_labels_normalized'] += 1
        if payment not in KNOWN_PAYMENTS:
            qa['unknown_payment_orders'] += 1
        if status not in KNOWN_STATUSES:
            qa['unknown_status_orders'] += 1
        try:
            moment = parse_instant(raw['created_at'])
        except (ValueError, OverflowError):
            moment = None
            qa['invalid_timestamp_orders'] += 1
        if moment is None and not raw['created_at'].strip():
            qa['missing_timestamp_orders'] += 1
        if moment is not None:
            if not (start <= moment.date() <= end):
                qa['outside_expected_period_orders'] += 1
            as_utc = moment.astimezone(dt.timezone.utc)
            qa['utc_ist_day_migrations'] += as_utc.date() != moment.date()
            qa['utc_ist_week_migrations'] += week_start(as_utc.date()) != week_start(moment.date())
        raw_value = raw['order_value'].strip()
        try:
            value = Decimal(raw_value)
            if not value.is_finite():
                raise InvalidOperation('not finite')
        except (InvalidOperation, ValueError):
            value = None
            qa['invalid_value_orders'] += 1
        if value is not None:
            if value <= 0:
                qa['nonpositive_value_orders'] += 1
            if value >= Decimal('1000000'):
                qa['million_plus_value_orders'] += 1
        if is_test_merchant(merchant):
            qa['test_merchant_orders'] += 1
        if payment in KNOWN_PAYMENTS - {'cod'} and status == 'rto':
            qa['prepaid_rto_orders'] += 1
        orders.append(Order(order_id, merchant, moment, payment, status, value, raw['created_at']))
    qa['usable_unique_orders'] = len(orders)
    qa['raw_payment_values'] = dict(sorted(raw_payment_counts.items()))
    qa['raw_status_values'] = dict(sorted(raw_status_counts.items()))
    qa['unique_merchants'] = len({o.merchant for o in orders})
    qa['production_merchants'] = len({o.merchant for o in orders if not o.is_test})
    qa['test_merchants'] = sorted({o.merchant for o in orders if o.is_test})
    qa['dated_orders_in_period'] = sum(o.created_ist is not None and start <= o.created_ist.date() <= end for o in orders)
    qa['dated_orders_outside_period'] = qa['outside_expected_period_orders']
    qa['undated_final_cod_orders'] = sum(o.final_cod and o.created_ist is None for o in orders)
    qa['undated_final_cod_test_orders'] = sum(o.final_cod and o.created_ist is None and o.is_test for o in orders)
    qa['nonfinal_cod_orders'] = sum(o.payment == 'cod' and o.status not in FINAL_STATUSES for o in orders)
    qa['all_final_cod_orders'] = sum(o.final_cod for o in orders)
    qa['all_final_cod_returns'] = sum(o.final_cod and o.status == 'rto' for o in orders)
    qa['production_final_cod_orders'] = sum(o.final_cod and not o.is_test for o in orders)
    qa['production_final_cod_returns'] = sum(o.final_cod and not o.is_test and o.status == 'rto' for o in orders)
    observed_days = {o.created_ist.date() for o in orders if o.created_ist is not None}
    qa['missing_dates'] = [(start + dt.timedelta(days=i)).isoformat()
                           for i in range((end - start).days + 1)
                           if start + dt.timedelta(days=i) not in observed_days]
    qa['observed_days'] = (end - start).days + 1 - len(qa['missing_dates'])
    qa['period_days'] = (end - start).days + 1
    return orders, qa


def build_weekly(orders: list[Order], start: dt.date, end: dt.date, production_only: bool,
                 gap_dates: set[str]) -> list[dict[str, Any]]:
    first, last = week_start(start), week_start(end)
    current = first
    grouped: dict[dt.date, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    while current <= last:
        grouped[current] = collections.Counter()
        current += dt.timedelta(days=7)
    # A test-only date may be populated in the all-store scope but entirely
    # absent in production. Independently derive those filtered-scope gaps.
    if production_only:
        observed_production_dates = {o.created_ist.date() for o in orders
                                     if not o.is_test and o.created_ist is not None
                                     and start <= o.created_ist.date() <= end}
        gap_dates = set(gap_dates) | {(start+dt.timedelta(days=i)).isoformat()
                         for i in range((end-start).days+1)
                         if start+dt.timedelta(days=i) not in observed_production_dates}
    for o in orders:
        if production_only and o.is_test:
            continue
        if o.created_ist is None or not (start <= o.created_ist.date() <= end):
            continue
        key = week_start(o.created_ist.date())
        metrics = grouped[key]
        metrics['all_orders'] += 1
        if o.payment == 'cod':
            metrics['cod_orders'] += 1
            metrics[f'cod_{o.status}'] += 1
    out = []
    for monday, m in sorted(grouped.items()):
        sunday = monday + dt.timedelta(days=6)
        returned = m['cod_rto']
        delivered = m['cod_delivered']
        denominator = returned + delivered
        gaps = [day for day in gap_dates if monday <= dt.date.fromisoformat(day) <= sunday]
        out.append({
            'week_start_ist': monday.isoformat(),
            'week_end_ist': sunday.isoformat(),
            'delivered_cod': delivered,
            'returned_cod': returned,
            'final_outcome_cod': denominator,
            'return_rate_pct': pct(returned, denominator),
            'cod_cancelled_excluded': m['cod_cancelled'],
            'cod_pending_excluded': m['cod_pending'],
            'cod_in_transit_excluded': m['cod_in_transit'],
            'cod_unknown_status_excluded': sum(v for k, v in m.items()
                                               if k.startswith('cod_') and k not in
                                               {'cod_orders', 'cod_delivered', 'cod_rto', 'cod_cancelled',
                                                'cod_pending', 'cod_in_transit'}),
            'all_dated_orders': m['all_orders'],
            'missing_calendar_days': '|'.join(sorted(gaps)),
            'coverage_flag': 'DATA_GAP' if gaps else 'NO_OBSERVED_DAY_GAP',
        })
    return out


def build_store_rankings(orders: list[Order], min_orders: int, production_only: bool) -> list[dict[str, Any]]:
    groups: dict[str, list[Order]] = collections.defaultdict(list)
    for o in orders:
        if production_only and o.is_test:
            continue
        groups[o.merchant].append(o)
    result = []
    for merchant, records in groups.items():
        cod = [o for o in records if o.payment == 'cod']
        delivered = sum(o.status == 'delivered' for o in cod)
        rto = sum(o.status == 'rto' for o in cod)
        final = delivered + rto
        result.append({
            'merchant_id': merchant,
            'is_test_merchant': 'yes' if is_test_merchant(merchant) else 'no',
            'all_orders': len(records),
            'cod_orders': len(cod),
            'delivered_cod': delivered,
            'returned_cod': rto,
            'final_outcome_cod': final,
            'return_rate_pct': pct(rto, final),
            'undated_final_cod_included': sum(o.final_cod and o.created_ist is None for o in cod),
            'eligible_minimum': 'yes' if final >= min_orders else 'no',
            'rank_among_eligible': '',
        })
    result.sort(key=lambda r: (r['final_outcome_cod'] < min_orders,
                               -Fraction(r['returned_cod'], r['final_outcome_cod']) if r['final_outcome_cod'] else Fraction(0, 1),
                               -r['final_outcome_cod'], r['merchant_id']))
    rank = 0
    for row in result:
        if row['final_outcome_cod'] >= min_orders:
            rank += 1
            row['rank_among_eligible'] = rank
    return result


def build_daily(orders: list[Order], start: dt.date, end: dt.date) -> list[dict[str, Any]]:
    counts: dict[dt.date, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for o in orders:
        if o.created_ist is None or not start <= o.created_ist.date() <= end:
            continue
        key = o.created_ist.date()
        counts[key]['total_orders'] += 1
        if o.is_test:
            counts[key]['test_orders'] += 1
        if o.final_cod:
            counts[key]['final_cod'] += 1
            if o.status == 'rto':
                counts[key]['returned_cod'] += 1
    result = []
    for i in range((end-start).days + 1):
        date = start + dt.timedelta(days=i)
        c = counts[date]
        result.append({'date_ist': date.isoformat(), 'weekday': date.strftime('%A'),
                       'all_dated_orders': c['total_orders'], 'test_orders': c['test_orders'],
                       'final_cod': c['final_cod'], 'returned_cod': c['returned_cod'],
                       'zero_orders_flag': 'CHECK_GAP' if not c['total_orders'] else ''})
    return result


def audit_issue_rows(qa: dict[str, Any], ranking: list[dict[str, Any]], min_orders: int) -> list[dict[str, Any]]:
    low = [r['merchant_id'] for r in ranking if r['eligible_minimum'] == 'no']
    rows = [
        ('HIGH', 'Duplicate order_id records', qa['exact_duplicate_extra_rows'],
         'Remove exact duplicate extra rows; one vote per distinct order_id.'),
        ('HIGH', 'Conflicting records for the same order_id', qa['conflicting_duplicate_order_ids'],
         'Quarantine all versions of conflicting IDs, never pick an arbitrary winner.'),
        ('HIGH', 'Missing created_at', qa['missing_timestamp_orders'],
         'Exclude from weekly trend; include in all-time store rank if payment/status/merchant are valid.'),
        ('HIGH', 'Invalid or unzoned created_at', qa['invalid_timestamp_orders'],
         'Same treatment as undated; warn separately.'),
        ('HIGH', 'Zero-order days across all stores (IST)', len(qa['missing_dates']),
         'Flag affected weeks as incomplete; do not assume zero real-world demand.'),
        ('HIGH', 'Likely test merchants', len(qa['test_merchants']),
         'Publish literal all-merchant results AND separate production-only sensitivity; do not silently drop.'),
        ('HIGH', 'Missing delivery/return event-time columns (schema fields)', 2,
         'Cannot attribute actual return events to their occurrence week; report created-at cohorts only.'),
        ('HIGH', 'Missing extract/as-of timestamp (schema field)', 1,
         'Cannot independently establish outcome maturity or when statuses were observed.'),
        ('MEDIUM', 'No authoritative test/production store flag (schema field)', 1,
         'Test exclusion is an explicitly labelled sensitivity based only on merchant ID patterns.'),
        ('MEDIUM', 'Status labels needing normalization', qa['status_labels_normalized'],
         'Strip whitespace and standardize case; RTO maps to returned, delivered maps to delivered.'),
        ('MEDIUM', 'Payment labels needing normalization', qa['payment_labels_normalized'],
         'Map cod, COD and Cash on Delivery to COD; ignore non-COD for the requested metric.'),
        ('MEDIUM', 'Order weeks changed by UTC to IST conversion', qa['utc_ist_week_migrations'],
         'Convert timestamp to Asia/Kolkata before Monday-to-Sunday grouping.'),
        ('MEDIUM', 'COD orders with non-final status', qa['nonfinal_cod_orders'],
         'Exclude pending, in_transit and cancelled from the denominator.'),
        ('MEDIUM', f'Merchants below {min_orders} final-outcome COD orders', len(low),
         'Show in store audit table, but disqualify from top three.'),
        ('LOW', 'Suspicious order_value >= 1,000,000', qa['million_plus_value_orders'],
         'Flag as possible sentinel/outlier; rate counts orders, never values, so retain.'),
        ('INFO', 'RTO records with non-COD payment', qa['prepaid_rto_orders'],
         'Legitimate possible prepaid returns; exclude by COD-only definition (not flagged invalid).'),
        ('INFO', 'Undated final-outcome COD orders', qa['undated_final_cod_orders'],
         'Included in store lifetime rankings; cannot be assigned to a specific week.'),
        ('INFO', 'Unknown payment categories', qa['unknown_payment_orders'],
         'Exclude from COD metric and flag for mapping review.'),
        ('INFO', 'Unknown outcome categories', qa['unknown_status_orders'],
         'Exclude from final-outcome denominator and flag for mapping review.'),
        ('INFO', 'Missing order identifiers (rows)', qa['missing_order_id_rows'],
         'Cannot reliably deduplicate; exclude and flag.'),
        ('INFO', 'Missing merchant identifiers (unique orders)', qa['missing_merchant_id_rows'],
         'Exclude from merchant and weekly report and flag.'),
        ('INFO', 'Timestamps outside declared assignment period', qa['outside_expected_period_orders'],
         'Exclude from specified weekly period; leave in all-time ranking with disclosure.'),
        ('INFO', 'Invalid order_value', qa['invalid_value_orders'],
         'Flag but keep record in count-based return metric.'),
        ('INFO', 'Nonpositive order_value', qa['nonpositive_value_orders'],
         'Flag but keep record in count-based return metric.'),
    ]
    return [{'severity': level, 'check': name, 'affected_count': count, 'treatment': treatment}
            for level, name, count, treatment in rows]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f'Cannot create empty output: {path}')
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def assert_invariants(orders: list[Order], qa: dict[str, Any], weeks: list[dict[str, Any]],
                      ranking: list[dict[str, Any]], start: dt.date, end: dt.date, min_orders: int) -> None:
    assert qa['raw_rows'] == (qa['missing_order_id_rows'] + qa['exact_duplicate_extra_rows']
                              + qa['conflicting_duplicate_rows'] + qa['missing_merchant_id_rows']
                              + len(orders)), 'Deduplication accounting failed'
    assert sum(r['final_outcome_cod'] for r in ranking) == qa['all_final_cod_orders']
    assert sum(r['returned_cod'] for r in ranking) == qa['all_final_cod_returns']
    assert sum(w['final_outcome_cod'] for w in weeks) == sum(
        o.final_cod and o.created_ist is not None and start <= o.created_ist.date() <= end for o in orders)
    assert sum(w['returned_cod'] for w in weeks) == sum(
        o.final_cod and o.status == 'rto' and o.created_ist is not None
        and start <= o.created_ist.date() <= end for o in orders)
    assert all(w['returned_cod'] + w['delivered_cod'] == w['final_outcome_cod'] for w in weeks)
    assert all(r['returned_cod'] + r['delivered_cod'] == r['final_outcome_cod'] for r in ranking)
    assert all(r['eligible_minimum'] == ('yes' if r['final_outcome_cod'] >= min_orders else 'no')
               for r in ranking)


def write_findings_md(path: Path, qa: dict[str, Any], all_weeks: list[dict[str, Any]],
                      all_stores: list[dict[str, Any]], production_stores: list[dict[str, Any]],
                      issue_rows: list[dict[str, Any]], start: dt.date, end: dt.date, min_orders: int) -> None:
    prod_weeks = None
    all_top = [r for r in all_stores if r['eligible_minimum'] == 'yes'][:3]
    prod_top = [r for r in production_stores if r['eligible_minimum'] == 'yes'][:3]
    def format_top(rows: list[dict[str, Any]]) -> str:
        return '\n'.join(f"| {i} | `{r['merchant_id']}` | {r['returned_cod']:,} | {r['final_outcome_cod']:,} | {r['return_rate_pct']}% |"
                         for i, r in enumerate(rows, 1))
    week_table = '\n'.join(
        f"| {w['week_start_ist']} to {w['week_end_ist']} | {w['returned_cod']:,} | {w['delivered_cod']:,} | {w['final_outcome_cod']:,} | {w['return_rate_pct']}% | {'⚠ GAP' if w['coverage_flag']=='DATA_GAP' else 'Observed 7d'} |"
        for w in all_weeks)
    issues = '\n'.join(f"| {r['severity']} | {r['check']} | {r['affected_count']:,} | {r['treatment']} |"
                       for r in issue_rows)
    content = f"""# Part 2 | Can these numbers be trusted?

**Scope:** {start.isoformat()} to {end.isoformat()}, Monday–Sunday **Asia/Kolkata** weeks.
**Input:** `orders.csv` (SHA-256 `{qa['file_sha256']}`); Python standard library.
**Rate:** `100 * number_of_COD_orders_status_RTO / (number_COD_RTO + number_COD_delivered)`.

## Executive answer

- **{qa['raw_rows']:,} raw rows**, **{qa['exact_duplicate_extra_rows']:,} exact excess duplicates**, **{qa['usable_unique_orders']:,} unique usable orders**, **{qa['unique_merchants']} merchant IDs** ({qa['production_merchants']} non-test and {len(qa['test_merchants'])} named tests).
- All-time, all-merchant **{pct(qa['all_final_cod_returns'], qa['all_final_cod_orders'])}%** = {qa['all_final_cod_returns']:,} / {qa['all_final_cod_orders']:,} COD final outcomes.
- All-time, *non-test* **{pct(qa['production_final_cod_returns'], qa['production_final_cod_orders'])}%** = {qa['production_final_cod_returns']:,} / {qa['production_final_cod_orders']:,} COD final outcomes.
- **{qa['missing_timestamp_orders']:,} unique orders missing timestamps**, including **{qa['undated_final_cod_orders']:,} final-outcome COD**. These count for all-time merchant ranking but not weekly trends.
- **{len(qa['missing_dates'])} days with zero date-stamped orders**, {', '.join(qa['missing_dates'])}. The affected weekly rate is **incomplete**, not a reliably full-week rate.
- The only available date field is **order creation time**, not return/delivery event time. Weekly rates are **order-created cohorts with their recorded final status**, not returns occurring that week. Outcome snapshot time is undocumented, so right-censoring is possible.

## Answer 1: Weekly COD return rates (literal all 26 merchant IDs)

| Week (IST) | Returned | Delivered | Final COD | Return rate | Coverage |
|:---|---:|---:|---:|---:|:---|
{week_table}

> Each week is based on **created_at converted to IST**. `2026-09-14` and `2026-09-15` have no orders across any merchant, making the September 14 week incomplete. The week's rate is an *observed-subset* rate and should not be treated as an uncontaminated full-week statistic.

A production-only weekly view is provided in `results/weekly_cod_production_only.csv` to disclose the effect of removing obvious test-store IDs.

## Answer 2: The top 3 stores (at least {min_orders} final-outcome COD orders)

### Literal assignment interpretation: include all 26 IDs

| Rank | Store | Returned COD | Final COD | Return rate |
|---:|:---|---:|---:|---:|
{format_top(all_top)}

Two stores contain `TEST` in their IDs. They have **not** been silently excluded from the literal result.

### Business interpretation: exclude named test accounts

| Rank | Production store | Returned COD | Final COD | Return rate |
|---:|:---|---:|---:|---:|
{format_top(prod_top)}

The **test-merchant exclusion is an assumption inferred from the merchant IDs**, not corroborated by a store master table; confirm with the business before using the production-only view as an official KPI. `M117` fails the {min_orders}-order minimum even though its rate is high. The full list, including ineligible stores, is in the ranking CSVs.

## Answer 3: Complete observed data audit and action log

| Severity | Check or finding | Count | Treatment |
|:---|:---|---:|:---|
{issues}

**Data completeness and definition limits:**

1. No `delivered_at`, `returned_at`, delivery-attempt history or snapshot timestamp. Cannot compute *returns occurring during each week*, actual return delays, full cohort maturity, or distinguish late returns from final delivered outcomes.
2. `status='rto'` is treated as **returned to the store**. Confirm business interpretation; RTO can be operationally different from a customer return after delivery.
3. No independent store master, so `M_TEST_01` and `M_TEST_02` are **suspected** test accounts based on IDs, not verified test environments.
4. A complete-looking date is not proof of complete ingestion. Two **globally empty** IST dates are observed, but the actual upstream missing-order volume cannot be recovered.
5. Missing `created_at` cannot be imputed safely; those orders stay in store-level aggregates only.
6. Non-COD RTO records can be legitimate. They are excluded for **metric scope**, not deleted as bad orders.
7. `order_value` is not part of this order-count-based metric. Three conspicuous high values are retained, flagged, and have **no effect** on rates.
8. Any recent week may have unresolved shipments. Excluding pending/in-transit is exactly what the formula requires, but older and newer weekly cohorts may have different completion maturity. Therefore rates are descriptive, not a causal trend claim.
9. Raw status/payment spelling variants were mapped only through an explicit, documented rule; unknown values would be flagged, not guessed.

## Reproducibility and checks

```bash
python3 part2/analyze_orders.py --input part2/orders.csv --output part2/results
python3 -m unittest discover -s part2/tests -v
```

Files: weekly results (all and production-only), full merchant rankings (all and production-only), daily coverage, quality issues, metrics JSON, and a self-contained HTML dashboard. Internal assertions reconcile all weekly and merchant COD numerators and denominators to their underlying records.

**Trust verdict:** Store-level counts are reproducible **conditional on supplied records and definitions**. The September 14 cohort week is **known incomplete**. Test-account treatment and outcome-event dating require a business definition or upstream data before an official production return-rate dashboard is certified.
"""
    path.write_text(content, encoding='utf-8')


def write_html(path: Path, qa: dict[str, Any], weeks_all: list[dict[str, Any]],
               weeks_prod: list[dict[str, Any]], all_stores: list[dict[str, Any]],
               prod_stores: list[dict[str, Any]], issues: list[dict[str, Any]],
               min_orders: int) -> None:
    # Self-contained HTML. CSS / SVG, no external libraries, fonts or CDNs.
    payload = json.dumps({'qa': qa, 'weeksAll': weeks_all, 'weeksProd': weeks_prod,
                          'storesAll': all_stores, 'storesProd': prod_stores,
                          'issues': issues, 'minOrders': min_orders}, separators=(',', ':'))
    # Escape 5tities and < to avoid terminating script for unusual input.
    payload = payload.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    document = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>KwikPulse | COD data integrity</title>
<style>
:root{color-scheme:dark;--bg:#080f14;--panel:#101c23;--panel2:#15262d;--stroke:#244049;--muted:#9bb0b7;--text:#eafbfc;--green:#60edb2;--amber:#ffc87b;--blue:#8fc9ff;--red:#ff9b90}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 80% 0%,#13352e 0%,transparent 38%),var(--bg);font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,Arial;color:var(--text);line-height:1.55}a{color:var(--green)}main{max-width:1150px;margin:0 auto;padding:36px 22px 80px}.top{display:flex;justify-content:space-between;gap:16px;align-items:center;padding-bottom:26px;border-bottom:1px solid var(--stroke)}.brand{font-size:16px;font-weight:800;letter-spacing:.6px}.brand span{color:var(--green)}.pill{border:1px solid var(--stroke);border-radius:30px;padding:7px 12px;color:var(--muted);font-size:12px}h1{font-size:clamp(35px,5vw,58px);line-height:1.06;letter-spacing:-2px;margin:42px 0 14px;max-width:730px}h1 em{font-style:normal;color:var(--green)}.intro{max-width:800px;color:var(--muted);font-size:15px;margin-bottom:28px}.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:24px 0}.toggle{display:flex;background:#091419;border:1px solid var(--stroke);border-radius:12px;padding:4px;gap:3px}.toggle button{color:var(--muted);border:0;background:transparent;padding:9px 14px;border-radius:8px;cursor:pointer;font-weight:700}.toggle button.active{color:#041b13;background:var(--green)}.download{display:inline-flex;text-decoration:none;padding:9px 13px;border:1px solid var(--stroke);border-radius:10px;font-size:13px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:26px 0}.kpi,.panel{background:linear-gradient(150deg,var(--panel),#0b161c);border:1px solid var(--stroke);border-radius:17px}.kpi{padding:21px}.kpi label{display:block;font-size:12px;color:var(--muted);margin-bottom:12px}.kpi strong{display:block;font-size:31px;letter-spacing:-1px}.kpi small{font-size:12px;color:var(--muted)}.panel{padding:25px;margin:18px 0}.heading{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}.heading h2{margin:0;font-size:21px;letter-spacing:-.5px}.subtitle{color:var(--muted);font-size:13px;margin:7px 0 20px}.flags{display:flex;gap:8px;flex-wrap:wrap}.flag{background:#30251c;color:var(--amber);font-size:11px;border-radius:30px;padding:5px 9px;border:1px solid #655039}.flag.good{background:#122a25;border-color:#294e42;color:var(--green)}.chart{width:100%;overflow-x:auto}.chart svg{display:block;min-width:680px;width:100%;height:auto}.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:660px;text-align:left;font-size:13px}th{font-size:11px;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);font-weight:700;border-bottom:1px solid var(--stroke);padding:12px 11px}td{padding:12px 11px;border-bottom:1px solid #1c323a}tr:last-child td{border-bottom:0}.mono{font-variant-numeric:tabular-nums;font-feature-settings:'tnum'}.pct{color:var(--green);font-weight:800}.warn{color:var(--amber);font-weight:800}.muted{color:var(--muted)}.note{padding:15px 18px;border:1px solid #55452f;background:#241e16;color:#ffe3b8;border-radius:11px;font-size:13px;margin-top:17px}.small{font-size:12px;color:var(--muted)}.row2{display:grid;grid-template-columns:1fr 1fr;gap:16px}.bullet{border-top:1px solid var(--stroke);padding:15px 0;display:flex;gap:12px;font-size:13px}.bullet b{min-width:95px}.accent{color:var(--green)}.footer{font-size:12px;color:var(--muted);margin-top:30px;border-top:1px solid var(--stroke);padding-top:20px}.sev{font-size:11px;padding:3px 8px;border-radius:30px;border:1px solid var(--stroke)}.sev.HIGH{color:var(--red)}.sev.MEDIUM{color:var(--amber)}.sev.LOW,.sev.INFO{color:var(--blue)}.bars{display:grid;gap:10px}.bar{display:grid;grid-template-columns:94px 1fr 80px;gap:15px;align-items:center;font-size:13px}.track{height:10px;background:#1d3339;border-radius:20px;overflow:hidden}.fill{height:100%;background:linear-gradient(90deg,#2ea776,var(--green));border-radius:20px}.metrics{font-size:12px;color:var(--muted);margin-top:16px}.switch{text-decoration:underline;text-decoration-color:var(--green);cursor:pointer} @media(max-width:750px){main{padding:20px 14px 55px}.grid{grid-template-columns:repeat(2,1fr)}.row2{grid-template-columns:1fr}.kpi{padding:15px}.kpi strong{font-size:25px}.top{align-items:flex-start;flex-direction:column}.panel{padding:16px}.toolbar{align-items:stretch}}
</style></head><body><main>
<header class="top"><div class="brand">KWIK<span>PULSE</span> <span class="pill">PART 02 · DATA TRUST</span></div><div class="pill">26 merchant IDs · 27 JUL–25 OCT 2026 · IST</div></header>
<h1>Can these <em>numbers</em> be trusted?</h1>
<p class="intro">Reproducible COD return-rate analysis with the dirty-data decisions visible. Monday–Sunday cohorts, duplicates removed, known gaps flagged, and no silent test-store exclusions.</p>
<div class="toolbar"><div class="toggle" role="group" aria-label="Merchant scope"><button id="allBtn" class="active" onclick="scopeSelect('all')">All 26 IDs · literal</button><button id="prodBtn" onclick="scopeSelect('prod')">24 non-test stores</button></div><a id="dlWeeks" class="download" href="results/weekly_cod_all_merchants.csv" download>↓ Weekly CSV</a><a id="dlStore" class="download" href="results/store_rankings_all_merchants.csv" download>↓ Ranking CSV</a><a class="download" href="results/data_quality_issues.csv" download>↓ Audit CSV</a></div>
<div class="grid" id="kpis"></div>
<div class="panel"><div class="heading"><h2>Weekly COD return rate</h2><span class="pill">Created-date cohorts · Asia/Kolkata</span></div><p class="subtitle">Each point is RTO / (RTO + delivered). Hover for counts; amber highlight marks an observed ingestion gap.</p><div class="chart" id="chart"></div><div class="table-wrap" id="weeklyTable"></div><p class="note">⚠ Sep 14–15: zero timestamped orders across ALL merchants. The Sep 14–20 calculation reflects the five observed days only. It is not a trustworthy complete-week rate. Missing timestamp orders also cannot be assigned to any week.</p></div>
<div class="row2"><section class="panel"><div class="heading"><h2>Top eligible stores</h2><span class="pill">Min 200 final-outcome COD orders</span></div><p class="subtitle" id="storeSubtitle">Eligible only. Rank by returned COD / final COD.</p><div id="rankBars"></div><p class="metrics">All-time store rankings include final-outcome COD records missing timestamps. The 200-order rule applies to the denominator, not total store traffic.</p></section><section class="panel"><div class="heading"><h2>What changes the answer?</h2></div><div class="bullet"><b class="warn">Test IDs</b><div>Two IDs explicitly contain <code>TEST</code> and have unusually high RTO rates. Shown in the literal result; separately excluded in the non-test interpretation.</div></div><div class="bullet"><b class="warn">Cohort time</b><div><code>created_at</code> is when the order was created, not when it was delivered/returned. Event-week returns cannot be computed from this file.</div></div><div class="bullet"><b class="warn">Missing days</b><div>Two entire IST dates have no records. Recover upstream data before using the affected week's rate for decisions.</div></div><div class="bullet"><b class="accent">Formula</b><div>Only COD + final delivery outcome. Cancelled, pending and in-transit orders do not enter the denominator.</div></div></section></div>
<div class="panel"><div class="heading"><h2>Data-quality audit</h2><span class="pill" id="auditMeta"></span></div><p class="subtitle">Every observed exception or high-value validation check, with a stated treatment. Counts refer to unique orders unless labelled raw rows, stores, days, or missing schema fields.</p><div class="table-wrap"><table><thead><tr><th>Severity</th><th>Finding</th><th>Affected</th><th>What we did</th></tr></thead><tbody id="issuesTable"></tbody></table></div></div>
<div class="panel"><div class="heading"><h2>Trust verdict</h2><span class="pill">Qualified / not unconditional</span></div><p>The store-level arithmetic is reproducible on the supplied snapshot. The week of 14 September is incomplete. Named test merchants materially change rankings, and no delivery/return event timestamps or snapshot date are supplied. Treat this as <strong>order-cohort outcome analysis</strong>, not a certified operational return-event dashboard.</p><p class="small">For exact methodology, exclusions, full store rankings, data quality counts, and tests: see <code>results/findings.md</code>, <code>analyze_orders.py</code> and <code>tests/</code>. No external services required.</p></div>
<footer class="footer">KwikPulse · Part 2 · Free Python standard-library build · source audit SHA-256 in results/metrics.json · All rates from raw supplied order IDs (exact duplicates removed).</footer>
</main><script>
const DATA=__DATA__;
let scope='all';
function el(id){return document.getElementById(id)};
function num(v){return Number(v).toLocaleString('en-IN')};
function scopeSelect(s){scope=s;el('allBtn').classList.toggle('active',s==='all');el('prodBtn').classList.toggle('active',s==='prod');el('dlWeeks').href='results/weekly_cod_'+(s==='all'?'all_merchants':'production_only')+'.csv';el('dlStore').href='results/store_rankings_'+(s==='all'?'all_merchants':'production_only')+'.csv';render()}
function h(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))};
function render(){let ws=scope==='all'?DATA.weeksAll:DATA.weeksProd,stores=scope==='all'?DATA.storesAll:DATA.storesProd;let den=stores.reduce((a,b)=>a+b.final_outcome_cod,0),ret=stores.reduce((a,b)=>a+b.returned_cod,0),eligible=stores.filter(x=>x.eligible_minimum==='yes');let k=[['Overall final-outcome COD return',den?(100*ret/den).toFixed(2)+'%':'n/a',num(ret)+' / '+num(den)+' orders'],['Eligible stores',num(eligible.length),'at least '+DATA.minOrders+' final COD orders'],['Exact duplicate rows removed',num(DATA.qa.exact_duplicate_extra_rows),'one row per order ID'],['Unassignable weekly dates',num(DATA.qa.missing_timestamp_orders),'orders without created_at']];el('kpis').innerHTML=k.map(x=>`<div class="kpi"><label>${h(x[0])}</label><strong>${h(x[1])}</strong><small>${h(x[2])}</small></div>`).join('');let entries=eligible.slice(0,3);el('storeSubtitle').textContent=(scope==='all'?'Literal 26-ID leaderboard: test merchants included.':'24-ID business sensitivity: named test merchants omitted.')+' Min '+DATA.minOrders+' final-outcome COD orders.';el('rankBars').innerHTML='<div class="bars">'+entries.map((r,i)=>`<div class="bar"><strong>#${i+1} ${h(r.merchant_id)}</strong><div class="track"><div class="fill" style="width:${Math.min(100,Number(r.return_rate_pct))}%"></div></div><strong class="pct mono">${h(r.return_rate_pct)}%</strong></div><div class="small" style="margin-left:109px;margin-top:-7px;margin-bottom:10px">${num(r.returned_cod)} RTO of ${num(r.final_outcome_cod)} final COD</div>`).join('')+'</div>';let ticks=[0,10,20,30,40,50,60,70,80,90,100],minY=0,maxY=Math.max(45,Math.ceil(Math.max(...ws.map(x=>Number(x.return_rate_pct))) /10)*10),left=56,right=25,top=26,bottom=62,width=1020,height=340,spanX=width-left-right,spanY=height-top-bottom;let ypos=v=>top+spanY*(1-v/maxY),xpos=i=>left+spanX*i/(ws.length-1);let grid='';for(let t=0;t<=maxY;t+=10)grid+=`<line x1="${left}" y1="${ypos(t)}" x2="${width-right}" y2="${ypos(t)}" stroke="#27434b" stroke-dasharray="4 5"/><text x="${left-13}" y="${ypos(t)+4}" fill="#9bb0b7" font-size="12" text-anchor="end">${t}%</text>`;let points=ws.map((r,i)=>`${xpos(i)},${ypos(Number(r.return_rate_pct))}`).join(' ');let dots=ws.map((r,i)=>{let xx=xpos(i),yy=ypos(Number(r.return_rate_pct)),gap=r.coverage_flag==='DATA_GAP';return `<circle cx="${xx}" cy="${yy}" r="${gap?8:5.5}" fill="${gap?'#ffc87b':'#60edb2'}" stroke="#09171b" stroke-width="2"><title>${h(r.week_start_ist)} to ${h(r.week_end_ist)}: ${h(r.return_rate_pct)}% (${num(r.returned_cod)} / ${num(r.final_outcome_cod)})${gap?' | INCOMPLETE DATA':''}</title></circle><text x="${xx}" y="${height-20}" fill="${gap?'#ffc87b':'#9bb0b7'}" font-size="11" text-anchor="middle">${h(r.week_start_ist.slice(5))}</text>`}).join('');el('chart').innerHTML=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Weekly COD return rate line chart; Sep 14 data gap highlighted">${grid}<polyline points="${points}" fill="none" stroke="#60edb2" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>${dots}</svg>`;el('weeklyTable').innerHTML='<table><thead><tr><th>IST week starts</th><th>Returned COD</th><th>Delivered COD</th><th>Final COD</th><th>Return rate</th><th>Coverage</th></tr></thead><tbody>'+ws.map(x=>`<tr><td class="mono">${h(x.week_start_ist)}</td><td class="mono">${num(x.returned_cod)}</td><td class="mono">${num(x.delivered_cod)}</td><td class="mono">${num(x.final_outcome_cod)}</td><td class="pct mono">${h(x.return_rate_pct)}%</td><td>${x.coverage_flag==='DATA_GAP'?'<span class="warn">⚠ Missing days</span>':'<span class="muted">Observed 7d</span>'}</td></tr>`).join('')+'</tbody></table>'}
el('issuesTable').innerHTML=DATA.issues.map(x=>`<tr><td><span class="sev ${h(x.severity)}">${h(x.severity)}</span></td><td>${h(x.check)}</td><td class="mono">${num(x.affected_count)}</td><td class="muted">${h(x.treatment)}</td></tr>`).join('');el('auditMeta').textContent=DATA.issues.filter(x=>x.affected_count>0).length+' checks with observed exceptions';render();
</script></body></html>'''
    path.write_text(document.replace('__DATA__', payload), encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description='COD weekly cohorts and exhaustive supplied-file audit')
    parser.add_argument('--input', type=Path, default=Path(__file__).with_name('orders.csv'))
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('results'))
    parser.add_argument('--start', type=dt.date.fromisoformat, default=DEFAULT_START,
                        help='Expected first IST date (default: 2026-07-27)')
    parser.add_argument('--end', type=dt.date.fromisoformat, default=DEFAULT_END,
                        help='Expected last IST date (default: 2026-10-25)')
    parser.add_argument('--min-orders', type=int, default=MIN_ELIGIBLE)
    args = parser.parse_args()
    if args.start > args.end or args.min_orders < 1:
        parser.error('start must be <= end and min-orders must be >= 1')
    args.output.mkdir(parents=True, exist_ok=True)
    orders, qa = read_and_audit(args.input, args.start, args.end)
    gaps = set(qa['missing_dates'])
    all_week = build_weekly(orders, args.start, args.end, production_only=False, gap_dates=gaps)
    prod_week = build_weekly(orders, args.start, args.end, production_only=True, gap_dates=gaps)
    all_rank = build_store_rankings(orders, args.min_orders, production_only=False)
    prod_rank = build_store_rankings(orders, args.min_orders, production_only=True)
    daily = build_daily(orders, args.start, args.end)
    issues = audit_issue_rows(qa, all_rank, args.min_orders)
    assert_invariants(orders, qa, all_week, all_rank, args.start, args.end, args.min_orders)
    for name, data in [
        ('weekly_cod_all_merchants.csv', all_week),
        ('weekly_cod_production_only.csv', prod_week),
        ('store_rankings_all_merchants.csv', all_rank),
        ('store_rankings_production_only.csv', prod_rank),
        ('daily_coverage.csv', daily),
        ('data_quality_issues.csv', issues),
    ]:
        write_csv(args.output / name, data)
    qa.update({'analysis_start_ist': args.start.isoformat(), 'analysis_end_ist': args.end.isoformat(),
               'minimum_eligible_cod_orders': args.min_orders,
               'weekly_cod_final_in_period': sum(w['final_outcome_cod'] for w in all_week),
               'weekly_cod_returns_in_period': sum(w['returned_cod'] for w in all_week),
               'weekly_production_cod_final_in_period': sum(w['final_outcome_cod'] for w in prod_week),
               'weekly_production_cod_returns_in_period': sum(w['returned_cod'] for w in prod_week)})
    (args.output / 'metrics.json').write_text(json.dumps(qa, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    write_findings_md(args.output / 'findings.md', qa, all_week, all_rank, prod_rank, issues,
                      args.start, args.end, args.min_orders)
    # RCA extension: extra diagnostics and explicit impact calculations. This does
    # not modify the primary rate, deduplicated orders, or all-ID ranking.
    from rca_diagnostics import generate as generate_rca
    rca = generate_rca(args.input, args.output, orders, qa, all_week,
                       args.start, args.end, args.min_orders)
    write_html(args.output.parent / 'index.html', qa, all_week, prod_week, all_rank, prod_rank,
               issues, args.min_orders)
    # Place a small deep-dive navigation panel beside the main verdict. Dashboard
    # remains self-contained, without external scripts or a separate server.
    dashboard = args.output.parent / 'index.html'
    doc = dashboard.read_text(encoding='utf-8')
    rca_panel = ('''<div class="panel"><div class="heading"><h2>RCA deep dive · Impact and evidence</h2><span class="pill">Auditable extensions</span></div>
    <p class="subtitle">Compare naive vs cleaned numbers; inspect merchant-by-week maturity, original CSV line evidence, and reconciliation checks. The primary answer remains unchanged.</p>
    <div class="bullet"><b class="accent">Impact bridge</b><div><a href="results/metric_sensitivity.csv">Metric sensitivity CSV</a> compares 7 processing choices in percentage points.</div></div>
    <div class="bullet"><b class="accent">Merchant RCA</b><div><a href="results/merchant_rca.csv">Store diagnostics</a> and <a href="results/merchant_weekly_rca.csv">store-week matrix</a> show unresolved orders, denominator size and test-merchant flags.</div></div>
    <div class="bullet"><b class="accent">Traceability</b><div><a href="results/exception_evidence.csv">Original-row examples</a>, <a href="results/reconciliation_ledger.csv">reconciliation ledger</a>, and <a href="results/quality_gates.csv">quality gates</a>.</div></div>
    <p class="small">Full explanation: <a href="results/RCA_DEEP_DIVE.md">RCA_DEEP_DIVE.md</a>. Some issues remain unresolvable with this source file alone.</p></div>''')
    doc = doc.replace('</main><script>', rca_panel + '</main><script>', 1)
    dashboard.write_text(doc, encoding='utf-8')
    print(f"RCA evidence: {rca['evidence_rows_provided']} sampled records; " 
          f"{rca['extra_reconciliation_checks_passed']} additional assertions passed.")
    print(f"Loaded {qa['raw_rows']:,} rows; {qa['usable_unique_orders']:,} unique usable orders; ")
    print(f"{qa['all_final_cod_returns']:,}/{qa['all_final_cod_orders']:,} = {pct(qa['all_final_cod_returns'],qa['all_final_cod_orders'])}% all-store COD RTO")
    print('Top 3 all:', [(r['merchant_id'], r['return_rate_pct']) for r in all_rank if r['eligible_minimum']=='yes'][:3])
    print('Top 3 non-test:', [(r['merchant_id'], r['return_rate_pct']) for r in prod_rank if r['eligible_minimum']=='yes'][:3])
    print(f'Wrote {args.output} and {args.output.parent / "index.html"}')


if __name__ == '__main__':
    main()
