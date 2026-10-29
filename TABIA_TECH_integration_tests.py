"""Run: python TABIA_TECH_integration_tests.py -- verbose integration checks on real SQLite."""
import sqlite3
import tempfile
from pathlib import Path
from decimal import Decimal as D
from TABIA_TECH_engine import TabiaDB, micro, money_text

passed=[]
def check(name, ok):
    assert ok,name
    passed.append(name)
    print(f'PASS {len(passed):02}  {name}')

def must_fail(fn, message=''):
    try:fn()
    except (ValueError,sqlite3.IntegrityError,sqlite3.OperationalError):return True
    return False

with tempfile.TemporaryDirectory() as td:
    fn=Path(td)/'test.db'
    db=TabiaDB(fn)
    db.initialize()
    check('SQLite schema 27 tables / 10 reports', db.db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchone()[0]==27 and db.db.execute("SELECT count(*) FROM sqlite_master WHERE type='view'").fetchone()[0]==10)
    check('Integrity & foreign keys', db.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and db.db.execute('PRAGMA foreign_key_check').fetchall()==[])
    material=db.add_material('MILK','حليب بودرة',[('جرام',1),('كجم',1000),('كيس 25 كجم',25000)],max_waste_ratio=5)
    worker=db.add_worker('W01','عامل التجربة')
    check('Exactly three material units',db.db.execute('SELECT COUNT(*) FROM material_units WHERE material_id=?',(material,)).fetchone()[0]==3)
    db.set_packaging_fee(1,'2020-01-01',70)
    db.set_packaging_fee(2,'2020-01-01',65)
    db.set_packaging_fee(3,'2020-01-01',65)
    invoice=db.purchase('INV-001','2026-10-26',material,25,2,197125,key='purchase-1')
    check('Purchase stock 25kg, price 7885/kg', db.inventory_valuation(material)['balance_grams']=='25000' and D(db._latest_price(material)[1])*1000==D(7885))
    check('Duplicate purchase save blocked',must_fail(lambda:db.purchase('INV-XX','2026-10-27',material,1,2,8000,key='purchase-1')))
    draft=db.create_draft('PROD-001','2026-10-27',material,worker,25,2,[(1,10),(2,20),(3,20)])
    check('Draft does not deduct inventory or accrue wages',D(db.inventory_valuation(material)['balance_grams'])==25000 and db.db.execute('SELECT COALESCE(SUM(signed_amount_micro_local),0) FROM worker_ledger').fetchone()[0]==0)
    vid=db.approve(draft)
    v=db.one('SELECT * FROM production_versions WHERE id=?',(vid,))
    check('Reference costs 197125 raw + 3300 wages = 200425',v['raw_cost_micro_local']==micro(197125) and v['wages_micro_local']==micro(3300) and v['total_cost_micro_local']==micro(200425))
    lines=db.db.execute('SELECT * FROM production_packaging_lines WHERE version_id=? ORDER BY packaging_size_id',(vid,)).fetchall()
    check('Reference per-pack price 7955/4007.50/2036.25',[D(r['unit_cost_precise_decimal']) for r in lines]==[D(7955),D('4007.5'),D('2036.25')])
    check('Zero balance, no negative shortage',D(db.inventory_valuation(material)['balance_grams'])==0 and not db.db.execute('SELECT 1 FROM v_fifo_pending_shortages').fetchone())
    db.set_packaging_fee(1,'2026-10-28',200)
    db.set_packaging_fee(2,'2026-10-28',150)
    db.set_packaging_fee(3,'2026-10-28',100)
    edit=db.edit_order(draft,25,2,[(1,10),(2,20),(3,20)],[(1,1500)])
    ev=db.one('SELECT * FROM production_versions WHERE id=?',(edit,))
    check('Cleaning 1500 => total 201925; wages kept frozen',ev['total_cost_micro_local']==micro(201925) and ev['wages_micro_local']==micro(3300))
    edit_lines=db.db.execute('SELECT * FROM production_packaging_lines WHERE version_id=? ORDER BY packaging_size_id',(edit,)).fetchall()
    check('Cleaning by weight: 8015, 4037.50, 2051.25',[D(r['unit_cost_precise_decimal']) for r in edit_lines]==[D(8015),D('4037.5'),D('2051.25')])
    check('Exact line total and cent reconciliation',sum(r['line_total_micro_local'] for r in edit_lines)==ev['total_cost_micro_local'] and sum(r['display_line_total_cents'] for r in edit_lines)==20192500)
    check('Edit does not duplicate warehouse or wages',db.one('SELECT balance_micrograms FROM v_material_stock WHERE material_id=?',(material,))['balance_micrograms']==0 and db.one('SELECT SUM(signed_amount_micro_local) amount FROM worker_ledger WHERE worker_id=?',(worker,))['amount']==micro(3300))
    check('Spent invoice price edit prohibited',must_fail(lambda:db.update_purchase(invoice,total_amount=197500)))
    db.worker_payment(worker,'2026-10-28',4000)
    check('Overpayment permitted, negative balance -700',db.worker_statement(worker)['closing']=='-700.00')
    db.cancel_order(draft)
    check('Cancellation restores stock, reverse earned only; payment persists',db.inventory_valuation(material)['balance_grams']=='25000' and db.worker_statement(worker)['closing']=='-4000.00')
    check('Cancelled production no longer allocated FIFO',db.db.execute('SELECT count(*) FROM fifo_allocations a JOIN fifo_rebuild_runs r ON a.run_id=r.id WHERE r.is_current=1').fetchone()[0]==0)
    # Separate flow: shortage and later purchase with full FIFO replay.
    d2=db.create_draft('PROD-002','2026-10-28',material,worker,40,2,[(1,20),(2,20),(3,40)])
    db.approve(d2)
    check('40kg taken from 25kg => -15kg and outstanding shortage',db.inventory_valuation(material)['balance_grams']=='-15000' and db.db.execute('SELECT SUM(remaining_uncovered_micrograms) FROM v_fifo_pending_shortages').fetchone()[0]==micro(15000))
    second=db.purchase('INV-002','2026-10-29',material,30,2,300000)
    check('Later purchase closes shortage and leaves 15kg',db.inventory_valuation(material)['balance_grams']=='15000' and db.db.execute('SELECT SUM(remaining_uncovered_micrograms) FROM v_fifo_pending_shortages').fetchone()[0] is None)
    beforeprice=db.one('SELECT raw_price_snapshot_per_gram_decimal FROM production_versions WHERE id=?',(db.one('SELECT current_version_id FROM production_orders WHERE id=?',(d2,))['current_version_id'],))[0]
    db.update_purchase(invoice,quantity=5)
    check('Old invoice qty adjustment restores correct  -5kg difference',db.inventory_valuation(material)['balance_grams']=='-5000')
    lots=db.db.execute('''SELECT p.invoice_number,a.allocated_micrograms,a.is_later_shortage_coverage
             FROM fifo_allocations a JOIN fifo_rebuild_runs r ON r.id=a.run_id
             JOIN purchase_invoices p ON a.purchase_id=p.id WHERE r.is_current=1 ORDER BY p.id''').fetchall()
    check('FIFO reallocated 5kg older + 30kg newer; remaining shortage 5kg',[(r['invoice_number'],r['allocated_micrograms']) for r in lots]==[('INV-001',micro(5000)),('INV-002',micro(30000))] and db.db.execute('SELECT SUM(remaining_uncovered_micrograms) FROM v_fifo_pending_shortages').fetchone()[0]==micro(5000))
    check('Historical production price never revalued by FIFO edits',db.one('SELECT raw_price_snapshot_per_gram_decimal FROM production_versions WHERE id=?',(db.one('SELECT current_version_id FROM production_orders WHERE id=?',(d2,))['current_version_id'],))[0]==beforeprice)
    # Latest-price policy: use a second material without consumption for a clean unused-lot test.
    m2=db.add_material('SUGAR','سكر',[('جرام',1),('كجم',1000),('كيس',25000)])
    third=db.purchase('INV-003','2026-10-01',m2,2,2,20000)
    newer=db.purchase('INV-004','2026-10-20',m2,3,2,33000)
    latestbefore=db._latest_price(m2)
    db.update_purchase(third,total_amount=25000)
    check('Changing older unused invoice leaves latest price unchanged',db._latest_price(m2)==latestbefore)
    db.update_purchase(newer,total_amount=36000)
    check('Changing newest unused invoice updates current price',D(db._latest_price(m2)[1])*1000==D(12000))
    prior=db.one('SELECT quantity_micrograms,factor_snapshot_decimal FROM purchase_invoices WHERE id=?',(third,))
    db.update_material_unit(m2,2,'وحدة جديدة',1200)
    check('Editing units preserves old purchase quantity and historical factor',
          db.one('SELECT quantity_micrograms,factor_snapshot_decimal FROM purchase_invoices WHERE id=?',(third,))['quantity_micrograms']==prior['quantity_micrograms'] and
          db.one('SELECT factor_snapshot_decimal FROM purchase_invoices WHERE id=?',(third,))['factor_snapshot_decimal']=='1000')
    db.update_purchase(third,quantity=3)
    check('Revising old invoice uses frozen conversion factor, not new factor',
          db.one('SELECT quantity_micrograms FROM purchase_invoices WHERE id=?',(third,))['quantity_micrograms']==micro(3000))
    new_size=db.add_packaging_size('300 جرام',300)
    pre_version_count=db.db.execute('SELECT COUNT(*) FROM production_versions').fetchone()[0]
    pre_stock=db.inventory_valuation(material)['balance_grams']
    check('Failed edit lacking original fee snapshot rolls back atomically',
          must_fail(lambda:db.edit_order(d2,40,2,[(new_size,100)])) and
          db.db.execute('SELECT COUNT(*) FROM production_versions').fetchone()[0]==pre_version_count and
          db.inventory_valuation(material)['balance_grams']==pre_stock)
    another_worker=db.add_worker('W02','عامل أرصدة افتتاحية')
    db.worker_adjustment(another_worker,-1200,'OPENING',reference='مستحق سابق')
    check('Opening balances may be negative; only one opening per worker',
          db.worker_statement(another_worker)['closing']=='-1200.00' and
          must_fail(lambda:db.worker_adjustment(another_worker,1,'OPENING')))
    db.worker_adjustment(another_worker,200,'ADJUSTMENT')
    check('Worker adjustment changes ledger, not production expense',
          db.worker_statement(another_worker)['closing']=='-1000.00')
    # FX snapshot and later change of rate.
    db.add_currency('SAR','ريال سعودي')
    db.set_exchange_rate('SAR','2026-10-01',150)
    foreign=db.purchase('INV-FOREIGN','2026-10-29',material,1,2,100,'SAR')
    fx_before=db.one('SELECT final_amount_micro_local FROM purchase_invoices WHERE id=?',(foreign,))[0]
    db.set_exchange_rate('SAR','2026-10-30',200)
    check('Foreign purchase exchange rate snapshot preserved',fx_before==micro(15000) and db.one('SELECT final_amount_micro_local FROM purchase_invoices WHERE id=?',(foreign,))[0]==fx_before)
    check('Immutable inventory journal rejects physical updates',must_fail(lambda:db.db.execute('UPDATE raw_inventory_movements SET quantity_delta_micrograms=2 WHERE id=1')))
    check('Immutable production version rejects physical deletes',must_fail(lambda:db.db.execute('DELETE FROM production_versions WHERE id=?',(vid,))))
    check('FK prevents orphan material units',must_fail(lambda:db.db.execute("INSERT INTO material_units(material_id,slot,name,factor_to_gram_decimal) VALUES(999999,1,'bad','1')")))
    check('One local currency enforcement',must_fail(lambda:db.db.execute("INSERT INTO currencies(code,name,is_local) VALUES('XYZ','another',1)")))
    check('Final integrity and foreign keys',db.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and db.db.execute('PRAGMA foreign_key_check').fetchall()==[])
    # Backup API snapshot and check files.
    backup=db.backup(Path(td)/'backups')
    check('Verified SQLite backup',Path(backup).is_file() and sqlite3.connect(backup).execute('PRAGMA integrity_check').fetchone()[0]=='ok')
    check('Actual backup restoration test',db.test_restore(backup) and db.one('SELECT restore_test_at_utc FROM backup_registry WHERE backup_path=?',(backup,))[0] is not None)
    for i in range(11):db.backup(Path(td)/'backups')
    check('Only ten backup files retained',len(list((Path(td)/'backups').glob('*.db')))==10 and db.db.execute('SELECT COUNT(*) FROM backup_registry').fetchone()[0]==10)
    db.close()
    print(f'\nRESULT: {len(passed)} / {len(passed)} SQLite integration tests passed.')
