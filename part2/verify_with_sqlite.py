#!/usr/bin/env python3
"""Independent, read-only SQLite check of the Python CSV outputs.

Standard library only. Loads the source directly, deduplicates via SQL ROW_NUMBER,
recalculates IST-week counts with SQLite GROUP BY, and compares each output.
"""
import argparse
import csv
import datetime as dt
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo


def read_output(file):
    with open(file, encoding='utf-8', newline='') as f:
        return list(csv.DictReader(f))


def verify(inp: Path, out: Path):
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE raw (order_id TEXT, merchant_id TEXT, created_at TEXT, payment_type TEXT, status TEXT, order_value TEXT, week_ist TEXT)')
    i = 0
    with inp.open(encoding='utf-8-sig', newline='') as f:
        batch = []
        for r in csv.DictReader(f):
            time = r['created_at'].strip()
            date = None
            if time:
                moment = dt.datetime.fromisoformat(time.replace('Z','+00:00')).astimezone(ZoneInfo('Asia/Kolkata'))
                day = moment.date()
                date = (day-dt.timedelta(days=day.weekday())).isoformat()
            batch.append((r['order_id'],r['merchant_id'],r['created_at'],r['payment_type'],r['status'],r['order_value'],date))
            i += 1
        conn.executemany('INSERT INTO raw VALUES(?,?,?,?,?,?,?)', batch)
    # Validate duplicate order IDs represent identical raw records, so SQL's first-wins is safe on this dataset.
    conflict_count = conn.execute('''
      SELECT count(*) FROM (
       SELECT order_id FROM raw GROUP BY order_id
       HAVING MIN(merchant_id)<>MAX(merchant_id) OR MIN(created_at)<>MAX(created_at)
         OR MIN(payment_type)<>MAX(payment_type) OR MIN(status)<>MAX(status)
         OR MIN(order_value)<>MAX(order_value)
      )''').fetchone()[0]
    assert conflict_count == 0, 'SQLite audit detected conflicting duplicate IDs; manual reconciliation required'
    conn.execute('''CREATE TEMP VIEW unique_orders AS
      SELECT merchant_id,week_ist,
       CASE WHEN lower(trim(payment_type)) IN ('cod','cash on delivery') THEN 'cod' ELSE lower(trim(payment_type)) END AS payment,
       lower(trim(status)) AS outcome
      FROM (SELECT *, row_number() OVER (PARTITION BY order_id ORDER BY rowid) AS rn FROM raw)
      WHERE rn=1''')
    # Independently count only the two final statuses and COD.
    where = "payment='cod' AND outcome IN ('delivered','rto')"
    daily_sql = f'''SELECT week_ist, sum(outcome='rto') AS returns, count(*) AS final
       FROM unique_orders WHERE {where} AND week_ist IS NOT NULL
       GROUP BY week_ist ORDER BY week_ist'''
    merchant_sql = f'''SELECT merchant_id, sum(outcome='rto') AS returns, count(*) AS final
       FROM unique_orders WHERE {where} GROUP BY merchant_id ORDER BY merchant_id'''
    for name, statement, key, records in (
        ('weekly_cod_all_merchants.csv', daily_sql, 'week_start_ist', ['returned_cod','final_outcome_cod']),
        ('store_rankings_all_merchants.csv', merchant_sql, 'merchant_id', ['returned_cod','final_outcome_cod']),
    ):
        actual = {str(row[0]): (int(row[1]),int(row[2])) for row in conn.execute(statement)}
        published = {r[key]: (int(r[records[0]]),int(r[records[1]])) for r in read_output(out/name)}
        assert actual == published, f'Disagreement in {name}: {[(k,actual.get(k),published.get(k)) for k in actual if actual.get(k)!=published.get(k)]}'
        print(f'PASS {name}: {len(published)} groups, counts match independent SQLite computation')
    where_prod = " AND merchant_id NOT LIKE '%TEST%'"
    for name, statement, key, records in (
        ('weekly_cod_production_only.csv', daily_sql.replace('GROUP BY', where_prod+' GROUP BY'), 'week_start_ist', ['returned_cod','final_outcome_cod']),
        ('store_rankings_production_only.csv', merchant_sql.replace('GROUP BY', where_prod+' GROUP BY'), 'merchant_id', ['returned_cod','final_outcome_cod']),
    ):
        actual = {str(row[0]): (int(row[1]),int(row[2])) for row in conn.execute(statement)}
        published = {r[key]: (int(r[records[0]]),int(r[records[1]])) for r in read_output(out/name)}
        assert actual == published, f'Disagreement in {name}'
        print(f'PASS {name}: {len(published)} groups, counts match independent SQLite computation')
    print(f'PASS source row scan: {i:,} rows. SQLite verification complete.')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--input', type=Path, default=Path(__file__).with_name('orders.csv'))
    p.add_argument('--output', type=Path, default=Path(__file__).with_name('results'))
    args = p.parse_args()
    verify(args.input, args.output)
