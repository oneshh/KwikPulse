"""Deeper regression checks for RCA, sensitivity, sampling and lineage."""
import csv
import datetime as dt
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analyze_orders import Order, read_and_audit, build_weekly
from rca_diagnostics import (
    wilson_interval, raw_scenarios, source_evidence, merchant_diagnostics,
    merchant_week_matrix, daily_risk_profile, assertions, generate,
)

START = dt.date(2026,7,27)
END = dt.date(2026,8,2)
FIELDS = ('order_id','merchant_id','created_at','payment_type','status','order_value')


def rec(order_id, merchant='M100', created='2026-07-27T00:00:00Z',
        payment='cod', status='rto', value='100'):
    return dict(zip(FIELDS,(order_id,merchant,created,payment,status,value)))


class TestRCADiagnostics(unittest.TestCase):
    def dataset(self, records):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = Path(tmp.name)/'orders.csv'
        with p.open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(records)
        orders, qa = read_and_audit(p,START,END)
        return p,orders,qa

    def test_wilson_not_normal_approx_for_small_n(self):
        low, high = wilson_interval(1, 2)
        self.assertTrue(0 < float(low) < 50)
        self.assertTrue(50 < float(high) < 100)

    def test_zero_denominator_has_no_interval(self):
        self.assertEqual(wilson_interval(0,0), ('',''))

    def test_wilson_extreme_rates_are_bounded(self):
        for ret in (0,100):
            low,high = wilson_interval(ret,100)
            self.assertGreaterEqual(float(low),0)
            self.assertLessEqual(float(high),100)

    def test_naive_case_sensitive_does_not_equal_canonical(self):
        p,orders,_=self.dataset([rec('A',status='rto'),rec('B',payment='COD',status='RTO'),
                                  rec('C',payment='Cash on Delivery',status=' delivered ')])
        s=raw_scenarios(p,orders,START,END)
        self.assertEqual((s[0]['returned_cod'],s[0]['final_cod']),(1,1))
        self.assertEqual((s[2]['returned_cod'],s[2]['final_cod']),(2,3))

    def test_duplicate_bias_measurable_without_changing_primary(self):
        x=rec('A',status='rto')
        p,orders,_=self.dataset([x,x,rec('B',status='delivered')])
        s=raw_scenarios(p,orders,START,END)
        self.assertEqual((s[1]['returned_cod'],s[1]['final_cod']),(2,3))
        self.assertEqual((s[2]['returned_cod'],s[2]['final_cod']),(1,2))
        self.assertEqual(s[2]['return_rate_pct'],'50.0000')

    def test_test_id_is_only_optional_scenario(self):
        p,orders,_=self.dataset([rec('A',merchant='M_TEST_01',status='rto'),
                                  rec('B',merchant='M100',status='delivered')])
        s=raw_scenarios(p,orders,START,END)
        self.assertEqual(s[2]['return_rate_pct'],'50.0000')
        self.assertEqual(s[3]['return_rate_pct'],'0.0000')
        self.assertEqual(s[3]['final_cod'],1)

    def test_undated_records_count_store_but_not_week(self):
        p,orders,_=self.dataset([rec('A',created='',status='rto'),
                                  rec('B',status='delivered')])
        s=raw_scenarios(p,orders,START,END)
        self.assertEqual(s[2]['final_cod'],2)
        self.assertEqual(s[4]['final_cod'],1)
        self.assertEqual(s[6]['final_cod'],1)

    def test_out_of_period_order_stays_in_primary_but_not_cohort(self):
        p,orders,_=self.dataset([rec('A',created='2026-08-03T12:00:00Z',status='rto'),
                                  rec('B',status='delivered')])
        s=raw_scenarios(p,orders,START,END)
        self.assertEqual(s[2]['final_cod'],2)
        self.assertEqual(s[6]['final_cod'],1)

    def test_merchant_maturity_and_undated_shift(self):
        _,orders,_=self.dataset([rec('A',created='',status='rto'),
                                  rec('B',status='delivered'),rec('C',status='pending'),
                                  rec('D',status='in_transit'),rec('E',status='cancelled')])
        x=merchant_diagnostics(orders,min_orders=2)[0]
        self.assertEqual(x['final_cod'],2)
        self.assertEqual(x['unresolved_cod'],2)
        self.assertEqual(x['unresolved_share_of_non_cancelled_pct'],'50.00')
        self.assertEqual(x['change_if_undated_excluded_pp'],'-50.0000')

    def test_small_sample_29_flagged_30_not(self):
        rows=[rec(f'A{i}',merchant='M100') for i in range(29)]
        rows += [rec(f'B{i}',merchant='M101') for i in range(30)]
        _,orders,_=self.dataset(rows)
        matrix=merchant_week_matrix(orders,START,END,set())
        self.assertEqual(next(r for r in matrix if r['merchant_id']=='M100')['small_cohort_flag'],'SMALL_N')
        self.assertEqual(next(r for r in matrix if r['merchant_id']=='M101')['small_cohort_flag'],'')

    def test_week_with_no_final_does_not_claim_zero_return_rate(self):
        _,orders,_=self.dataset([rec('A',status='pending')])
        m=merchant_week_matrix(orders,START,END,set())
        self.assertEqual(m[0]['return_rate_pct'],'')
        self.assertEqual(m[0]['small_cohort_flag'],'NO_FINAL')

    def test_global_zero_days_are_observed_not_imputed(self):
        _,orders,_=self.dataset([rec('A',created='2026-07-27T02:00:00Z'),
                                  rec('B',created='2026-07-28T02:00:00Z')])
        days,med=daily_risk_profile(orders,START,END)
        self.assertEqual(sum(d['global_zero_day']=='yes' for d in days),5)
        self.assertEqual(sum(d['observed_orders'] for d in days),2)
        self.assertEqual(med,1)

    def test_evidence_tracks_original_source_lines_and_limit(self):
        x=rec('A',payment='COD',status=' Rto ')
        p,_,_=self.dataset([x,x,x,rec('B',created=''),rec('C',created='bad time')])
        ev=source_evidence(p,START,END,max_per_type=1)
        checks={r['check'] for r in ev}
        self.assertTrue({'exact_duplicate','missing_timestamp','invalid_timestamp','status_label_normalized','payment_label_normalized'}<=checks)
        self.assertEqual(len([r for r in ev if r['check']=='exact_duplicate']),1)
        self.assertEqual(next(r['source_line'] for r in ev if r['check']=='exact_duplicate'),3)

    def test_gap_flag_on_every_merchant_week_without_inventing_orders(self):
        _,orders,_=self.dataset([rec('A',merchant='M100'),rec('B',merchant='M101')])
        m=merchant_week_matrix(orders,START,END,{'2026-07-30'})
        self.assertTrue(all(r['all_store_ingestion_gap']=='yes' for r in m))
        self.assertEqual(sum(r['final_cod'] for r in m),2)

    def test_cross_grain_reconciliation_and_manifest(self):
        p,orders,qa=self.dataset([rec('A'),rec('B',status='delivered'),rec('C',created='')])
        weekly=build_weekly(orders,START,END,False,set(qa['missing_dates']))
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            manifest=generate(p,out,orders,qa,weekly,START,END,1)
            self.assertEqual(manifest['primary_final_cod'],3)
            self.assertEqual(manifest['extra_reconciliation_checks_passed'],6)
            self.assertTrue((out/'RCA_DEEP_DIVE.md').exists())
            with (out/'merchant_weekly_rca.csv').open(newline='') as f:
                m=list(csv.DictReader(f))
            self.assertEqual(sum(int(r['final_cod']) for r in m),2)
            with (out/'quality_gates.csv').open(newline='') as f:
                gates=list(csv.DictReader(f))
            self.assertTrue(all(g['result']=='PASS' for g in gates))


if __name__=='__main__':
    unittest.main()

# Additional regression scenarios: subset-specific completeness and stable ties.
class TestTieAndCompleteness(unittest.TestCase):
    def test_equal_fraction_rank_tiebreak_denom_then_id(self):
        from analyze_orders import build_store_rankings, parse_instant
        # Same exact 50% return rate, different sample sizes, deterministic ranking.
        def mk(k,m,s):
            return Order(k,m,parse_instant('2026-07-28T00:00:00Z'),'cod',s,100,'2026-07-28T00:00:00Z')
        records = [mk(f'a{i}','M100', 'rto' if i<100 else 'delivered') for i in range(200)]
        records += [mk(f'b{i}','M101', 'rto' if i<150 else 'delivered') for i in range(300)]
        ranked = build_store_rankings(records,200,False)
        self.assertEqual([r['merchant_id'] for r in ranked],['M101','M100'])
        self.assertEqual([r['return_rate_pct'] for r in ranked],['50.00','50.00'])

    def test_production_scope_marks_test_only_date_as_gap(self):
        from analyze_orders import parse_instant
        x = Order('x','M_TEST_01',parse_instant('2026-07-26T18:31:00Z'),'cod','rto',100,'2026-07-26T18:31:00Z')
        y = Order('y','M100',parse_instant('2026-07-27T18:31:00Z'),'cod','delivered',100,'2026-07-27T18:31:00Z')
        all_rows = build_weekly([x,y],START,END,False,set())
        prod_rows = build_weekly([x,y],START,END,True,set())
        self.assertEqual(all_rows[0]['missing_calendar_days'],'')
        self.assertIn('2026-07-27',prod_rows[0]['missing_calendar_days'])
