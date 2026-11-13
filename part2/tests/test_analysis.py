"""Synthetic edge-case tests. Run from repository root:
python3 -m unittest discover -s part2/tests -v
"""
import csv
import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analyze_orders import (
    Order, IST, build_daily, build_store_rankings, build_weekly, canonical_payment,
    canonical_status, is_test_merchant, parse_instant, pct, read_and_audit, week_start,
)

START = dt.date(2026, 7, 27)
END = dt.date(2026, 8, 2)
FIELDS = ('order_id', 'merchant_id', 'created_at', 'payment_type', 'status', 'order_value')


def make_raw(order_id='X1', merchant='M100', created='2026-07-26T18:31:00Z',
             payment='cod', status='rto', value='350.00'):
    return dict(zip(FIELDS, (order_id, merchant, created, payment, status, value)))


def make_order(id_, merchant, date, pay, status):
    created = parse_instant(date) if date else None
    return Order(id_, merchant, created, pay, status, 100, date)


class TestNormalization(unittest.TestCase):
    def test_cod_variants(self):
        for value in ('COD', 'cod', ' Cash on Delivery ', 'cash-on-delivery', '\tCoD\n'):
            self.assertEqual(canonical_payment(value), 'cod')

    def test_status_variants(self):
        self.assertEqual(canonical_status(' Rto '), 'rto')
        self.assertEqual(canonical_status(' Delivered '), 'delivered')
        self.assertEqual(canonical_status('In Transit'), 'in_transit')
        self.assertEqual(canonical_status('CANCELLED'), 'cancelled')
        self.assertEqual(canonical_status('Unrecognized'), 'unrecognized')

    def test_ist_cross_midnight_to_monday(self):
        time = parse_instant('2026-07-26T18:30:01Z')
        self.assertEqual(time.date(), dt.date(2026, 7, 27))
        self.assertEqual(week_start(time.date()), START)
        self.assertEqual(time.hour, 0)

    def test_sunday_last_minute_stays_same_week(self):
        time = parse_instant('2026-08-02T18:29:59Z')
        self.assertEqual(time.date(), END)
        self.assertEqual(week_start(time.date()), START)
        self.assertEqual(time.hour, 23)

    def test_sunday_utc_evening_is_next_ist_week(self):
        time = parse_instant('2026-08-02T18:30:00Z')
        self.assertEqual(time.date(), dt.date(2026, 8, 3))

    def test_reject_naive_datetime(self):
        with self.assertRaises(ValueError):
            parse_instant('2026-07-27T12:00:00')

    def test_zero_denominator_is_undefined(self):
        self.assertEqual(pct(0, 0), '')

    def test_test_merchant_pattern_not_overbroad(self):
        self.assertTrue(is_test_merchant('M_TEST_01'))
        self.assertFalse(is_test_merchant('M_CONTEST'))


class TestDataAudit(unittest.TestCase):
    def audited(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'example.csv'
            with path.open('w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            return read_and_audit(path, START, END)

    def test_identical_duplicates_are_removed(self):
        x = make_raw()
        orders, audit = self.audited([x, x, make_raw(order_id='X2')])
        self.assertEqual(len(orders), 2)
        self.assertEqual(audit['exact_duplicate_extra_rows'], 1)
        self.assertEqual(audit['conflicting_duplicate_order_ids'], 0)

    def test_conflicting_duplicate_ids_quarantined(self):
        x = make_raw()
        x2 = dict(x, status='delivered')
        orders, audit = self.audited([x, x2, make_raw(order_id='X2')])
        self.assertEqual(len(orders), 1)
        self.assertEqual(audit['conflicting_duplicate_order_ids'], 1)
        self.assertEqual(audit['conflicting_duplicate_rows'], 2)

    def test_missing_date_in_store_rank_not_weekly(self):
        rows = [make_raw(order_id='X1', created='', status='rto'),
                make_raw(order_id='X2', status='delivered')]
        orders, audit = self.audited(rows)
        ranks = build_store_rankings(orders, min_orders=1, production_only=False)
        weeks = build_weekly(orders, START, END, False, set(audit['missing_dates']))
        self.assertEqual(ranks[0]['final_outcome_cod'], 2)
        self.assertEqual(weeks[0]['final_outcome_cod'], 1)
        self.assertEqual(audit['undated_final_cod_orders'], 1)

    def test_prepaid_return_excluded(self):
        rows = [make_raw(order_id='X1', payment='upi', status='rto'),
                make_raw(order_id='X2', payment='cod', status='delivered')]
        orders, audit = self.audited(rows)
        self.assertEqual(audit['prepaid_rto_orders'], 1)
        weeks = build_weekly(orders, START, END, False, set())
        self.assertEqual(weeks[0]['returned_cod'], 0)
        self.assertEqual(weeks[0]['final_outcome_cod'], 1)
        self.assertEqual(weeks[0]['return_rate_pct'], '0.00')

    def test_nonfinal_orders_excluded(self):
        orders, audit = self.audited([make_raw(order_id='X1', status='cancelled'),
                                     make_raw(order_id='X2', status='in_transit'),
                                     make_raw(order_id='X3', status='pending'),
                                     make_raw(order_id='X4', status='rto')])
        weeks = build_weekly(orders, START, END, False, set())
        self.assertEqual(weeks[0]['final_outcome_cod'], 1)
        self.assertEqual(weeks[0]['return_rate_pct'], '100.00')
        self.assertEqual(weeks[0]['cod_cancelled_excluded'], 1)
        self.assertEqual(weeks[0]['cod_in_transit_excluded'], 1)
        self.assertEqual(weeks[0]['cod_pending_excluded'], 1)

    def test_min_200_applies_to_final_cod_only(self):
        orders = ([make_order(f'f{i}', 'M200', '2026-07-28T10:00:00Z', 'cod', 'rto') for i in range(199)]
                  + [make_order('nonfinal', 'M200', '2026-07-28T10:00:00Z', 'cod', 'cancelled')]
                  + [make_order(f'g{i}', 'M201', '2026-07-28T10:00:00Z', 'cod', 'delivered') for i in range(200)])
        ranks = build_store_rankings(orders, 200, False)
        r = {x['merchant_id']: x for x in ranks}
        self.assertEqual(r['M200']['eligible_minimum'], 'no')
        self.assertEqual(r['M201']['eligible_minimum'], 'yes')
        self.assertEqual(r['M200']['return_rate_pct'], '100.00')

    def test_test_store_is_kept_in_literal_but_removed_in_sensitivity(self):
        orders = [make_order('X1', 'M_TEST_01', '2026-07-28T10:00:00Z', 'cod', 'rto'),
                  make_order('X2', 'M101', '2026-07-28T10:00:00Z', 'cod', 'delivered')]
        all_week = build_weekly(orders, START, END, False, set())
        prod_week = build_weekly(orders, START, END, True, set())
        self.assertEqual(all_week[0]['return_rate_pct'], '50.00')
        self.assertEqual(prod_week[0]['return_rate_pct'], '0.00')

    def test_no_activity_day_flag(self):
        orders = [make_order('X1','M101','2026-07-26T18:31:00Z','cod','rto')]
        daily = build_daily(orders, START, END)
        self.assertEqual(len(daily), 7)
        self.assertEqual(sum(bool(row['zero_orders_flag']) for row in daily), 6)

    def test_high_amount_never_excludes_valid_return(self):
        orders, qa = self.audited([make_raw(value='9999999')])
        self.assertEqual(qa['million_plus_value_orders'], 1)
        self.assertEqual(qa['all_final_cod_returns'], 1)

    def test_unknown_categories_do_not_inflate_denominator(self):
        orders, qa = self.audited([make_raw(order_id='X1', payment='crypto', status='rto'),
                                  make_raw(order_id='X2', payment='cod', status='refunded')])
        self.assertEqual(qa['unknown_status_orders'], 1)
        self.assertEqual(qa['unknown_payment_orders'], 1)
        self.assertEqual(qa['all_final_cod_orders'], 0)


if __name__ == '__main__':
    unittest.main()
