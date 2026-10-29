"""TABIA TECH: SQLite transaction service (v1.0).

All financial arithmetic uses decimal.Decimal, never float. Amounts are stored as
integer micro-units of the local currency and weight as integer micrograms.
Service-level operations enforce cross-row invariants that SQLite CHECK cannot.
"""
from __future__ import annotations
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, getcontext
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

getcontext().prec = 45
M = 1000000
D = Decimal


def now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')

def dec(x):
    z = D(str(x))
    if not z.is_finite():
        raise ValueError('Non-finite decimal amount')
    return z

def micro(x):
    return int((dec(x) * M).quantize(D('1'), rounding=ROUND_HALF_UP))

def unmicro(x):
    return D(int(x)) / M

def money_text(x):
    return format((unmicro(x)).quantize(D('0.01'),rounding=ROUND_HALF_UP),'f')

def j(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,default=str)

def split_amount(total, weights):
    """Apportion integer micro-amount exactly using largest remainders."""
    if not weights or sum(weights)<=0: raise ValueError('Missing output weight')
    tw = sum(weights)
    floor = [(total*w)//tw for w in weights]
    rem = total - sum(floor)
    ix = sorted(range(len(weights)),key=lambda i:(-(total*weights[i] % tw),i))
    for k in ix[:rem]:floor[k]+=1
    return floor

def reconcile_cents(line_micro):
    """Largest remainder to displayed cents, while retained accounting is exact micros."""
    floors=[a//10000 for a in line_micro]
    grand=int((D(sum(line_micro))/10000).quantize(D(1),rounding=ROUND_HALF_UP))
    rem=grand-sum(floors)
    ordering=sorted(range(len(line_micro)),key=lambda i:(-(line_micro[i]%10000),i))
    for i in ordering[:rem]:floors[i]+=1
    return floors

class TabiaDB:
    def __init__(self, path):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, isolation_level=None,timeout=15)
        self.db.row_factory = sqlite3.Row
        # Python 3.8 x86 for Windows 7 may ship SQLite without JSON1.
        # Register json_valid locally to preserve JSON CHECK constraints.
        def _json_valid(value):
            try:
                json.loads(value)
                return 1
            except (TypeError, ValueError):
                return 0
        self.db.create_function('json_valid', 1, _json_valid)
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA busy_timeout=15000')
        if self.path != ':memory:': self.db.execute('PRAGMA journal_mode=WAL')

    def close(self, backup_dir=None):
        """App must call close(backup_dir=...) for automatic backup on normal exit."""
        if backup_dir is not None:
            self.backup(backup_dir)
        self.db.close()

    @contextmanager
    def tx(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
        except BaseException:
            self.db.execute('ROLLBACK')
            raise
        else:
            self.db.execute('COMMIT')

    def op(self, key, kind):
        if not key: key = str(uuid.uuid4())
        try:
            cur=self.db.execute('INSERT INTO operation_requests(idempotency_key,operation_kind) VALUES (?,?)',(key,kind))
        except sqlite3.IntegrityError as e:
            raise ValueError('Duplicate idempotency key; request was already committed') from e
        return cur.lastrowid

    def finish(self, operation_id):
        self.db.execute('UPDATE operation_requests SET committed_at_utc=? WHERE id=?',(now(),operation_id))

    def audit(self, operation_id, typ, entity_id, action, old, new):
        self.db.execute('INSERT INTO audit_events(operation_request_id,entity_type,entity_id,action,previous_json,new_json) VALUES(?,?,?,?,?,?)',
                        (operation_id,typ,entity_id,action,j(old) if old is not None else None,j(new) if new is not None else None))

    def one(self, sql, args=()):
        row=self.db.execute(sql,args).fetchone()
        if row is None: raise ValueError('Record not found: '+sql.split('FROM')[0].strip())
        return row

    def initialize(self, schema_path=None):
        schema_path=Path(schema_path or Path(__file__).with_name('TABIA_TECH_schema.sql'))
        if self.db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()[0]:
            raise ValueError('Database has already been initialized')
        sql=schema_path.read_text('utf-8')
        self.db.executescript(sql)
        with self.tx():
            self.db.execute("INSERT INTO currencies(code,name,symbol,is_local) VALUES('YER','ريال يمني','ر.ي',1)")
            self.db.execute("INSERT INTO exchange_rate_history(currency_id,valid_from,rate_local_per_unit) VALUES(1,'1900-01-01','1')")
            self.db.executemany('INSERT INTO expense_categories(code,name) VALUES(?,?)',[
                ('CLEANING','تنظيف'),('SIFTING','غربلة'),('OTHER','مصاريف أخرى')])
            self.db.executemany('INSERT INTO packaging_sizes(label,weight_micrograms) VALUES(?,?)',[
                ('1 كجم',micro(1000)),('500 جرام',micro(500)),('250 جرام',micro(250))])
            self.db.execute('INSERT INTO app_settings(key,value) VALUES(?,?)',('backup_keep_count','10'))
            self.db.execute('INSERT INTO schema_migrations(version,applied_at_utc,description,checksum) VALUES(?,?,?,?)',
                 (1,now(),'Initial approved TABIA TECH schema',hashlib.sha256(sql.encode()).hexdigest()))

    def add_material(self, code, name, units, max_waste_ratio=0, key=None):
        """units: exactly three (name, grams_per_unit) tuples; first unit is base 1 gram."""
        if len(units)!=3 or dec(units[0][1])!=1:raise ValueError('Three units required; first is gram base')
        if not 0<=dec(max_waste_ratio)<=100:raise ValueError('Invalid waste ratio')
        with self.tx():
            o=self.op(key,'CREATE_MATERIAL')
            cur=self.db.execute('INSERT INTO raw_materials(code,name,max_waste_ratio) VALUES(?,?,?)',
                                (code,name,str(dec(max_waste_ratio))))
            mid=cur.lastrowid
            for slot,(label,factor) in enumerate(units,1):
                if dec(factor)<=0:raise ValueError('Invalid conversion factor')
                self.db.execute('INSERT INTO material_units(material_id,slot,name,factor_to_gram_decimal,is_base) VALUES(?,?,?,?,?)',
                                (mid,slot,label,str(dec(factor)),1 if slot==1 else 0))
            self.audit(o,'raw_materials',mid,'CREATE',None,{'code':code,'name':name,'units':units})
            self.finish(o)
            return mid

    def add_worker(self, code, name, contact=None, key=None):
        with self.tx():
            o=self.op(key,'CREATE_WORKER')
            c=self.db.execute('INSERT INTO workers(code,name,contact) VALUES(?,?,?)',(code,name,contact))
            self.audit(o,'workers',c.lastrowid,'CREATE',None,{'code':code,'name':name});self.finish(o)
            return c.lastrowid

    def add_currency(self, code, name, symbol='', key=None):
        with self.tx():
            o=self.op(key,'ADD_CURRENCY')
            c=self.db.execute('INSERT INTO currencies(code,name,symbol) VALUES(?,?,?)',(code,name,symbol))
            self.audit(o,'currencies',c.lastrowid,'CREATE',None,{'code':code});self.finish(o)
            return c.lastrowid

    def set_exchange_rate(self, currency_code, effective_from, rate, key=None):
        if dec(rate)<=0:raise ValueError('Exchange rate must be positive')
        with self.tx():
            o=self.op(key,'SET_FX')
            cid=self.one('SELECT id,is_local FROM currencies WHERE code=?',(currency_code,))
            if cid['is_local'] and dec(rate)!=1:raise ValueError('Local rate must equal 1')
            c=self.db.execute('INSERT INTO exchange_rate_history(currency_id,valid_from,rate_local_per_unit) VALUES(?,?,?)',
                              (cid['id'],effective_from,str(dec(rate))))
            self.audit(o,'exchange_rate_history',c.lastrowid,'CREATE',None,{'rate':str(dec(rate))});self.finish(o)
            return c.lastrowid

    def add_packaging_size(self, label, weight_grams, key=None):
        if micro(weight_grams)<=0:raise ValueError('Invalid packaging size')
        with self.tx():
            op=self.op(key,'CREATE_PACKAGING_SIZE')
            c=self.db.execute('INSERT INTO packaging_sizes(label,weight_micrograms) VALUES(?,?)',
                              (label,micro(weight_grams)))
            self.audit(op,'packaging_sizes',c.lastrowid,'CREATE',None,{'label':label,'weight_grams':str(dec(weight_grams))})
            self.finish(op);return c.lastrowid

    def update_material_unit(self, material_id, slot, name, factor_to_grams, key=None):
        if dec(factor_to_grams)<=0 or (slot==1 and dec(factor_to_grams)!=1):
            raise ValueError('Invalid conversion factor / base factor must remain 1')
        with self.tx():
            op=self.op(key,'UPDATE_UNIT')
            old=self.one('SELECT * FROM material_units WHERE material_id=? AND slot=?',(material_id,slot))
            self.db.execute('UPDATE material_units SET name=?,factor_to_gram_decimal=? WHERE id=?',
                            (name,str(dec(factor_to_grams)),old['id']))
            self.audit(op,'material_units',old['id'],'UPDATE',
                       {'name':old['name'],'factor':old['factor_to_gram_decimal']},
                       {'name':name,'factor':str(dec(factor_to_grams))})
            self.finish(op);return old['id']

    def add_expense_category(self, code, name, key=None):
        with self.tx():
            op=self.op(key,'CREATE_EXPENSE_CATEGORY')
            c=self.db.execute('INSERT INTO expense_categories(code,name) VALUES(?,?)',(code,name))
            self.audit(op,'expense_categories',c.lastrowid,'CREATE',None,{'code':code,'name':name})
            self.finish(op);return c.lastrowid

    def set_packaging_fee(self, size_id, effective_from, fee_local, key=None):
        if dec(fee_local)<0:raise ValueError('Fee must not be negative')
        with self.tx():
            o=self.op(key,'SET_FEE')
            c=self.db.execute('INSERT INTO packaging_fee_history(packaging_size_id,effective_from,fee_micro_local) VALUES(?,?,?)',
                              (size_id,effective_from,micro(fee_local)))
            self.audit(o,'packaging_fee_history',c.lastrowid,'CREATE',None,{'size_id':size_id,'fee':str(dec(fee_local))});self.finish(o)
            return c.lastrowid

    def _unit(self, material_id, slot):
        rs=self.db.execute('SELECT id,factor_to_gram_decimal FROM material_units WHERE material_id=? AND slot=?',
                           (material_id,slot)).fetchall()
        if len(rs)!=1 or self.db.execute('SELECT COUNT(*) FROM material_units WHERE material_id=?',(material_id,)).fetchone()[0]!=3:
            raise ValueError('Material must have three valid units')
        return rs[0]

    def _quantity(self, material_id, qty, slot):
        u=self._unit(material_id,slot)
        if dec(qty)<=0:raise ValueError('Quantity must be positive')
        q=micro(dec(qty)*dec(u['factor_to_gram_decimal']))
        if q<=0:raise ValueError('Quantity below storage precision')
        return u,q

    def _latest_price(self, material_id):
        r=self.db.execute('SELECT id,unit_price_local_per_gram_decimal FROM purchase_invoices WHERE material_id=? AND status="ACTIVE" ORDER BY purchase_date DESC,id DESC LIMIT 1', (material_id,)).fetchone()
        return (r['id'],r['unit_price_local_per_gram_decimal']) if r else (None,None)

    def _price_event(self, material_id, old, new, op_id, reason):
        if old==new:return
        self.db.execute('INSERT INTO material_price_events(material_id,source_purchase_id,previous_price_decimal,new_price_decimal,previous_source_id,new_source_id,reason,operation_request_id) VALUES(?,?,?,?,?,?,?,?)',
                        (material_id,new[0],old[1],new[1],old[0],new[0],reason,op_id))

    def _fx(self,currency_code, purchase_date, explicit_rate):
        currency=self.one('SELECT id,is_local FROM currencies WHERE code=? AND is_active=1',(currency_code,))
        if currency['is_local']:
            if explicit_rate is not None and dec(explicit_rate)!=1:raise ValueError('Local currency rate must be 1')
            return currency,D(1)
        if explicit_rate is not None: rate=dec(explicit_rate)
        else:
            r=self.db.execute('SELECT rate_local_per_unit FROM exchange_rate_history WHERE currency_id=? AND valid_from<=? ORDER BY valid_from DESC LIMIT 1',(currency['id'],purchase_date)).fetchone()
            if r is None:raise ValueError('Exchange rate not configured for date')
            rate=dec(r[0])
        if rate<=0:raise ValueError('Invalid exchange rate')
        return currency,rate

    def purchase(self, invoice_number, purchase_date, material_id, quantity, unit_slot, total_amount,
                 currency_code='YER', fx_rate=None, key=None):
        unit, qty=self._quantity(material_id,quantity,unit_slot)
        if dec(total_amount)<0:raise ValueError('Purchase amount negative')
        with self.tx():
            op=self.op(key,'PURCHASE')
            ccy,fx=self._fx(currency_code,purchase_date,fx_rate)
            before=self._latest_price(material_id)
            amt=micro(total_amount); local=micro(unmicro(amt)*fx)
            price=str(unmicro(local)/unmicro(qty))
            c=self.db.execute('''INSERT INTO purchase_invoices(invoice_number,purchase_date,material_id,unit_id,
            entered_quantity_decimal,factor_snapshot_decimal,quantity_micrograms,currency_id,final_amount_micro_currency,
            fx_rate_snapshot_decimal,final_amount_micro_local,unit_price_local_per_gram_decimal,supply_seq)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (invoice_number,purchase_date,material_id,unit['id'],str(dec(quantity)),unit['factor_to_gram_decimal'],qty,
             ccy['id'],amt,str(fx),local,price,op))
            pid=c.lastrowid
            state={'quantity_micrograms':qty,'total_micro_currency':amt,'total_micro_local':local,'fx':str(fx)}
            rc=self.db.execute('''INSERT INTO purchase_invoice_revisions(purchase_id,revision_no,change_kind,new_values_json,delta_quantity_micrograms,operation_request_id)
               VALUES(?,1,'CREATE',?,?,?)''',(pid,j(state),qty,op))
            self.db.execute('UPDATE purchase_invoices SET current_revision_id=? WHERE id=?',(rc.lastrowid,pid))
            self.db.execute("INSERT INTO raw_inventory_movements(material_id,quantity_delta_micrograms,movement_type,purchase_revision_id,operation_request_id) VALUES(?,?,'PURCHASE',?,?)",(material_id,qty,rc.lastrowid,op))
            self._price_event(material_id,before,self._latest_price(material_id),op,'NEW_PURCHASE')
            self._rebuild_fifo(material_id,op,'PURCHASE')
            self.audit(op,'purchase_invoices',pid,'CREATE',None,state);self.finish(op)
            return pid

    def update_purchase(self, purchase_id, quantity=None, total_amount=None, key=None):
        if quantity is None and total_amount is None:raise ValueError('No changes specified')
        with self.tx():
            op=self.op(key,'UPDATE_PURCHASE')
            p=self.one('SELECT * FROM purchase_invoices WHERE id=? AND status="ACTIVE"',(purchase_id,))
            before=self._latest_price(p['material_id'])
            oldqty=p['quantity_micrograms']; oldamt=p['final_amount_micro_currency']
            if quantity is not None:
                u=self.one('SELECT factor_to_gram_decimal FROM material_units WHERE id=?',(p['unit_id'],))
                if dec(quantity)<=0:raise ValueError('Invalid quantity')
                newqty=micro(dec(quantity)*dec(p['factor_snapshot_decimal']))
                if newqty<=0:raise ValueError('Below precision')
            else:newqty=oldqty
            newamt=micro(total_amount) if total_amount is not None else oldamt
            if newamt<0:raise ValueError('Negative purchase price')
            if newqty==oldqty and newamt==oldamt:raise ValueError('No effective change')
            if newamt != oldamt and self.db.execute('SELECT EXISTS(SELECT 1 FROM fifo_allocations WHERE purchase_id=?)',(purchase_id,)).fetchone()[0]:
                raise ValueError('Cannot change price of a purchase lot ever consumed in FIFO')
            local=micro(unmicro(newamt)*dec(p['fx_rate_snapshot_decimal']))
            unitprice=str(unmicro(local)/unmicro(newqty))
            old={'quantity_micrograms':oldqty,'total_micro_currency':oldamt,'total_micro_local':p['final_amount_micro_local']}
            new={'quantity_micrograms':newqty,'total_micro_currency':newamt,'total_micro_local':local}
            rev=self.one('SELECT COALESCE(MAX(revision_no),0)+1 next_no FROM purchase_invoice_revisions WHERE purchase_id=?',(purchase_id,))['next_no']
            change=('QUANTITY_AND_PRICE' if oldqty!=newqty and oldamt!=newamt else 'QUANTITY' if oldqty!=newqty else 'PRICE')
            r=self.db.execute('''INSERT INTO purchase_invoice_revisions(purchase_id,revision_no,change_kind,old_values_json,new_values_json,delta_quantity_micrograms,operation_request_id)
            VALUES(?,?,?,?,?,?,?)''',(purchase_id,rev,change,j(old),j(new),newqty-oldqty,op))
            self.db.execute('''UPDATE purchase_invoices SET quantity_micrograms=?,entered_quantity_decimal=?,final_amount_micro_currency=?,
            final_amount_micro_local=?,unit_price_local_per_gram_decimal=?,current_revision_id=? WHERE id=?''',
            (newqty,str(unmicro(newqty)/dec(p['factor_snapshot_decimal'])),newamt,local,unitprice,r.lastrowid,purchase_id))
            if newqty!=oldqty:
                self.db.execute("INSERT INTO raw_inventory_movements(material_id,quantity_delta_micrograms,movement_type,purchase_revision_id,operation_request_id) VALUES(?,?,'PURCHASE_ADJUST',?,?)",(p['material_id'],newqty-oldqty,r.lastrowid,op))
            self._price_event(p['material_id'],before,self._latest_price(p['material_id']),op,'PURCHASE_REVISION')
            self._rebuild_fifo(p['material_id'],op,'PURCHASE_REVISION')
            self.audit(op,'purchase_invoices',purchase_id,'UPDATE',old,new);self.finish(op)
            return rev

    def _line_spec(self, packages):
        values=[]
        for sizeid,count in packages:
            if not isinstance(count,int) or count<=0:raise ValueError('Invalid package count')
            size=self.one('SELECT id,weight_micrograms FROM packaging_sizes WHERE id=? AND is_active=1',(sizeid,))
            if sizeid in [r[0] for r in values]:raise ValueError('Duplicate packaging weight')
            values.append((sizeid,count,size['weight_micrograms']))
        if not values:raise ValueError('Output packages required')
        return values

    def _expense_spec(self, expenses):
        values=[]
        for cat,amount in expenses:
            self.one('SELECT id FROM expense_categories WHERE id=? AND is_active=1',(cat,))
            v=micro(amount)
            if v<0:raise ValueError('Negative expense')
            values.append((cat,v))
        return values

    def create_draft(self, number, order_date, material_id, worker_id, input_quantity,
                     input_unit_slot, packages, expenses=(), key=None):
        u,qty=self._quantity(material_id,input_quantity,input_unit_slot)
        lines=self._line_spec(packages);costs=self._expense_spec(expenses)
        weight=sum(n*w for _,n,w in lines)
        with self.tx():
            op=self.op(key,'DRAFT_ORDER')
            c=self.db.execute('INSERT INTO production_orders(order_number,order_date,material_id,worker_id) VALUES(?,?,?,?)',(number,order_date,material_id,worker_id))
            order_id=c.lastrowid
            cv=self.db.execute('''INSERT INTO production_versions(order_id,version_no,kind,input_quantity_micrograms,input_unit_id,factor_snapshot_decimal,
            output_weight_micrograms,waste_micrograms,operation_request_id) VALUES(?,1,'DRAFT',?,?,?,?,?,?)''',
            (order_id,qty,u['id'],u['factor_to_gram_decimal'],weight,qty-weight,op))
            vid=cv.lastrowid
            self.db.executemany('INSERT INTO production_packaging_lines(version_id,packaging_size_id,weight_micrograms_snapshot,package_count) VALUES(?,?,?,?)',
                                [(vid,s,w,n) for s,n,w in lines])
            self.db.executemany('INSERT INTO production_expense_lines(version_id,expense_category_id,amount_micro_local) VALUES(?,?,?)',
                                [(vid,c,a) for c,a in costs])
            self.db.execute('UPDATE production_orders SET current_version_id=? WHERE id=?',(vid,order_id))
            self.audit(op,'production_orders',order_id,'DRAFT',None,{'input_micrograms':qty,'output_micrograms':weight});self.finish(op)
            return order_id

    def _all_current_fees(self):
        # "At approval" means fees that have become effective as of today's local-business date.
        # Date is passed by application clock; for tests, set past effective dates.
        today=date.today().isoformat()
        fees={}
        for size in self.db.execute('SELECT id FROM packaging_sizes WHERE is_active=1'):
            r=self.db.execute('''SELECT id,fee_micro_local FROM packaging_fee_history WHERE packaging_size_id=? AND effective_from<=?
            ORDER BY effective_from DESC,id DESC LIMIT 1''',(size['id'],today)).fetchone()
            if r:fees[size['id']]=(r['fee_micro_local'],r['id'])
        return fees

    def _post_version(self, op, order, previous, kind, qty, input_unit_id, factor,
                      lines, expenses, price, price_source, frozen_fees, recovered_qty=0):
        if qty<=0:raise ValueError('Input must be positive')
        weights=[n*w for sid,n,w in lines]
        output=sum(weights)
        if output<=0:raise ValueError('Output zero')
        for sid,_,_ in lines:
            if sid not in frozen_fees:
                raise ValueError('Size has no original fee snapshot; do not apply modern tariff retrospectively')
        raw=micro(unmicro(qty)*dec(price))
        expense_total=sum(amount for _,amount in expenses)
        wages=sum(n*frozen_fees[sid][0] for sid,n,w in lines)
        total=raw+expense_total+wages
        old_seq=previous['version_no'] if previous else 0
        waste=qty-output
        maxratio=dec(self.one('SELECT max_waste_ratio FROM raw_materials WHERE id=?',(order['material_id'],))['max_waste_ratio'])
        flags=[]
        if waste<0:flags.append('OUTPUT_EXCEEDS_INPUT')
        if waste>0 and dec(waste)*100/dec(qty)>maxratio:flags.append('WASTE_LIMIT_EXCEEDED')
        stock=self.db.execute('SELECT COALESCE(SUM(quantity_delta_micrograms),0) FROM raw_inventory_movements WHERE material_id=?',(order['material_id'],)).fetchone()[0]
        # On edit, previous quantity will be reversed in the same transaction.
        if stock+recovered_qty-qty<0:flags.append('NEGATIVE_INVENTORY')
        ver=self.db.execute('''INSERT INTO production_versions(order_id,version_no,kind,previous_version_id,input_quantity_micrograms,input_unit_id,
        factor_snapshot_decimal,raw_price_snapshot_per_gram_decimal,raw_price_source_purchase_id,raw_cost_micro_local,
        shared_expenses_micro_local,wages_micro_local,total_cost_micro_local,output_weight_micrograms,waste_micrograms,
        warning_flags_json,operation_request_id,posted_at_utc)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (order['id'],old_seq+1,kind,previous['id'] if previous else None,qty,input_unit_id,str(factor),str(price),price_source,
         raw,expense_total,wages,total,output,waste,j(flags),op,now()))
        vid=ver.lastrowid
        rawshares=split_amount(raw,weights); expshares=split_amount(expense_total,weights)
        line_amounts=[r+e+n*frozen_fees[sid][0] for (sid,n,w),r,e in zip(lines,rawshares,expshares)]
        # Cent reconciliation is independent from micro-currency accounting.
        rounded_cents=reconcile_cents(line_amounts)
        for i,(sid,n,w) in enumerate(lines):
            fee,fee_hist=frozen_fees[sid]
            wage=n*fee; lt=line_amounts[i]
            self.db.execute('''INSERT INTO production_packaging_lines(version_id,packaging_size_id,weight_micrograms_snapshot,
            package_count,fee_per_pack_micro_local_snapshot,raw_share_micro_local,expense_share_micro_local,wage_total_micro_local,
            rounding_adjustment_micro_local,line_total_micro_local,display_line_total_cents,unit_cost_precise_decimal)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
            (vid,sid,w,n,fee,rawshares[i],expshares[i],wage,rounded_cents[i]*10000-lt,lt,rounded_cents[i],str(unmicro(lt)/n)))
        for cat,amt in expenses:
            self.db.execute('INSERT INTO production_expense_lines(version_id,expense_category_id,amount_micro_local) VALUES(?,?,?)',(vid,cat,amt))
        for sid,(fee,fid) in frozen_fees.items():
            self.db.execute('INSERT INTO production_fee_snapshots(version_id,packaging_size_id,fee_per_pack_micro_local,source_fee_history_id) VALUES(?,?,?,?)',(vid,sid,fee,fid))
        return vid,wages,total,flags

    def _rebuild_fifo(self, material_id, op, reason):
        """Full replay at original posting sequence. Retains previous runs unchanged."""
        events=[]
        for p in self.db.execute('SELECT id,supply_seq,quantity_micrograms FROM purchase_invoices WHERE material_id=? AND status="ACTIVE"',(material_id,)):
            events.append((p['supply_seq'],0,p['id'],p['quantity_micrograms']))
        for p in self.db.execute('''SELECT o.first_post_seq,v.id version_id,v.input_quantity_micrograms
                  FROM production_orders o JOIN production_versions v ON v.id=o.current_version_id
                  WHERE o.material_id=? AND o.status='POSTED' ''',(material_id,)):
            events.append((p['first_post_seq'],1,p['version_id'],p['input_quantity_micrograms']))
        events.sort()
        available=deque(); deficits=deque(); alloc=[];initial={}; short_remaining={}
        for seq,kind,ref,qty in events:
            rem=qty
            if kind==0: # purchase: cover past shortages first
                while rem and deficits:
                    v,need=deficits[0]; used=min(rem,need)
                    alloc.append((ref,v,used,1))
                    rem-=used;need-=used
                    if need: deficits[0]=(v,need)
                    else:deficits.popleft()
                if rem:available.append((ref,rem))
            else:
                while rem and available:
                    purchase,avail=available[0]; used=min(rem,avail)
                    alloc.append((purchase,ref,used,0))
                    rem-=used;avail-=used
                    if avail:available[0]=(purchase,avail)
                    else:available.popleft()
                if rem:
                    initial[ref]=rem
                    deficits.append((ref,rem))
        short_remaining=dict(deficits)
        self.db.execute('UPDATE fifo_rebuild_runs SET is_current=0 WHERE material_id=? AND is_current=1',(material_id,))
        run=self.db.execute('INSERT INTO fifo_rebuild_runs(material_id,reason,operation_request_id,is_current) VALUES(?,?,?,1)',
                            (material_id,reason,op)).lastrowid
        self.db.executemany('INSERT INTO fifo_allocations(run_id,purchase_id,production_version_id,allocated_micrograms,is_later_shortage_coverage) VALUES(?,?,?,?,?)',
                            [(run,*x) for x in alloc])
        self.db.executemany('INSERT INTO fifo_shortages(run_id,production_version_id,initial_uncovered_micrograms,remaining_uncovered_micrograms) VALUES(?,?,?,?)',
                            [(run,ref,initial_qty,short_remaining.get(ref,0)) for ref,initial_qty in initial.items()])
        # verify current runs against absolute stock journal and active documents.
        expected=sum(q if kind==0 else -q for _,kind,_,q in events)
        journal=self.db.execute('SELECT COALESCE(SUM(quantity_delta_micrograms),0) FROM raw_inventory_movements WHERE material_id=?',(material_id,)).fetchone()[0]
        if expected!=journal:raise AssertionError('FIFO replay vs journal balance mismatch')
        if sum(short_remaining.values())!=max(0,-expected):raise AssertionError('FIFO pending shortages mismatch')
        purchases=defaultdict(int); orders=defaultdict(int)
        for purchase,version,qty,later in alloc:
            purchases[purchase]+=qty;orders[version]+=qty
        for _,kind,ref,qty in events:
            if kind==0 and purchases[ref]>qty:raise AssertionError('FIFO overspent lot')
            if kind==1 and orders[ref]+short_remaining.get(ref,0)!=qty:raise AssertionError('FIFO order sum error')
        return run

    def approve(self, order_id, key=None):
        with self.tx():
            op=self.op(key,'APPROVE_ORDER')
            order=self.one('SELECT * FROM production_orders WHERE id=? AND status="DRAFT"',(order_id,))
            draft=self.one('SELECT * FROM production_versions WHERE id=?',(order['current_version_id'],))
            lines=[(r['packaging_size_id'],r['package_count'],r['weight_micrograms_snapshot']) for r in self.db.execute('SELECT * FROM production_packaging_lines WHERE version_id=? ORDER BY id',(draft['id'],))]
            expenses=[(r['expense_category_id'],r['amount_micro_local']) for r in self.db.execute('SELECT * FROM production_expense_lines WHERE version_id=?',(draft['id'],))]
            source,price=self._latest_price(order['material_id'])
            if price is None:raise ValueError('No purchase price exists for material')
            fees=self._all_current_fees()
            ver,wages,tot,flags=self._post_version(op,order,draft,'APPROVE',draft['input_quantity_micrograms'],draft['input_unit_id'],draft['factor_snapshot_decimal'],
                                                    lines,expenses,price,source,fees)
            self.db.execute("INSERT INTO raw_inventory_movements(material_id,quantity_delta_micrograms,movement_type,production_version_id,operation_request_id) VALUES(?,?,'PRODUCTION_CONSUME',?,?)",
                            (order['material_id'],-draft['input_quantity_micrograms'],ver,op))
            if wages:
                self.db.execute("INSERT INTO worker_ledger(worker_id,ledger_kind,signed_amount_micro_local,production_version_id,operation_request_id) VALUES(?,'EARNED',?,?,?)",
                                (order['worker_id'],wages,ver,op))
            self.db.execute("UPDATE production_orders SET status='POSTED',first_post_seq=?,current_version_id=? WHERE id=?",(op,ver,order_id))
            self._rebuild_fifo(order['material_id'],op,'APPROVE_ORDER')
            self.audit(op,'production_orders',order_id,'APPROVE',{'status':'DRAFT'},{'version':ver,'total_micro_local':tot,'warnings':flags})
            self.finish(op);return ver

    def edit_order(self, order_id, input_quantity, input_unit_slot, packages, expenses=(),worker_id=None,key=None):
        lines=self._line_spec(packages);xp=self._expense_spec(expenses)
        with self.tx():
            op=self.op(key,'EDIT_ORDER')
            order=self.one('SELECT * FROM production_orders WHERE id=? AND status="POSTED"',(order_id,))
            prev=self.one('SELECT * FROM production_versions WHERE id=?',(order['current_version_id'],))
            orig=self.one("SELECT * FROM production_versions WHERE order_id=? AND kind='APPROVE' ORDER BY version_no LIMIT 1",(order_id,))
            unit,qty=self._quantity(order['material_id'],input_quantity,input_unit_slot)
            fees={r['packaging_size_id']:(r['fee_per_pack_micro_local'],r['source_fee_history_id']) for r in self.db.execute('SELECT * FROM production_fee_snapshots WHERE version_id=?',(orig['id'],))}
            target=worker_id if worker_id is not None else order['worker_id']
            self.one('SELECT id FROM workers WHERE id=?',(target,))
            # Create immutable new version first, then journal both compensation and replacement.
            vid,wages,tot,flags=self._post_version(op,order,prev,'EDIT',qty,unit['id'],unit['factor_to_gram_decimal'],lines,xp,
                                                  orig['raw_price_snapshot_per_gram_decimal'],orig['raw_price_source_purchase_id'],fees,
                                                  recovered_qty=prev['input_quantity_micrograms'])
            self.db.execute("INSERT INTO raw_inventory_movements(material_id,quantity_delta_micrograms,movement_type,production_version_id,operation_request_id) VALUES(?,?,'PRODUCTION_REVERSE',?,?)",
                            (order['material_id'],prev['input_quantity_micrograms'],vid,op))
            self.db.execute("INSERT INTO raw_inventory_movements(material_id,quantity_delta_micrograms,movement_type,production_version_id,operation_request_id) VALUES(?,?,'PRODUCTION_CONSUME',?,?)",
                            (order['material_id'],-qty,vid,op))
            if prev['wages_micro_local']:
                self.db.execute("INSERT INTO worker_ledger(worker_id,ledger_kind,signed_amount_micro_local,production_version_id,operation_request_id) VALUES(?,'REVERSE_EARNED',?,?,?)",
                                (order['worker_id'],-prev['wages_micro_local'],vid,op))
            if wages:
                self.db.execute("INSERT INTO worker_ledger(worker_id,ledger_kind,signed_amount_micro_local,production_version_id,operation_request_id) VALUES(?,'EARNED',?,?,?)",
                                (target,wages,vid,op))
            self.db.execute('UPDATE production_orders SET worker_id=?,current_version_id=? WHERE id=?',(target,vid,order_id))
            self._rebuild_fifo(order['material_id'],op,'EDIT_ORDER')
            self.audit(op,'production_orders',order_id,'EDIT',{'version':prev['id'],'wages':prev['wages_micro_local']},
                       {'version':vid,'wages':wages,'total':tot,'warnings':flags});self.finish(op)
            return vid

    def cancel_order(self, order_id, key=None):
        with self.tx():
            op=self.op(key,'CANCEL_ORDER')
            order=self.one('SELECT * FROM production_orders WHERE id=? AND status="POSTED"',(order_id,))
            prev=self.one('SELECT * FROM production_versions WHERE id=?',(order['current_version_id'],))
            v=self.db.execute('''INSERT INTO production_versions(order_id,version_no,kind,previous_version_id,
            input_quantity_micrograms,input_unit_id,factor_snapshot_decimal,raw_price_snapshot_per_gram_decimal,
            raw_price_source_purchase_id,raw_cost_micro_local,shared_expenses_micro_local,wages_micro_local,total_cost_micro_local,
            output_weight_micrograms,waste_micrograms,operation_request_id,posted_at_utc)
            VALUES(?,?,"CANCEL",?,?,?,?,?,?,0,0,0,0,?,?,?,?)''',
            (order_id,prev['version_no']+1,prev['id'],prev['input_quantity_micrograms'],prev['input_unit_id'],prev['factor_snapshot_decimal'],
             prev['raw_price_snapshot_per_gram_decimal'],prev['raw_price_source_purchase_id'],prev['output_weight_micrograms'],prev['waste_micrograms'],op,now()))
            vid=v.lastrowid
            self.db.execute("INSERT INTO raw_inventory_movements(material_id,quantity_delta_micrograms,movement_type,production_version_id,operation_request_id) VALUES(?,?,'PRODUCTION_REVERSE',?,?)",
                            (order['material_id'],prev['input_quantity_micrograms'],vid,op))
            if prev['wages_micro_local']:
                self.db.execute("INSERT INTO worker_ledger(worker_id,ledger_kind,signed_amount_micro_local,production_version_id,operation_request_id) VALUES(?,'REVERSE_EARNED',?,?,?)",
                                (order['worker_id'],-prev['wages_micro_local'],vid,op))
            self.db.execute("UPDATE production_orders SET status='CANCELED',current_version_id=? WHERE id=?",(vid,order_id))
            self._rebuild_fifo(order['material_id'],op,'CANCEL_ORDER')
            self.audit(op,'production_orders',order_id,'CANCEL',{'version':prev['id']},{'version':vid});self.finish(op)
            return vid

    def worker_payment(self,worker_id,payment_date,amount,payment_kind='PAYMENT',reference=None,notes=None,key=None):
        if payment_kind not in ('PAYMENT','ADVANCE') or micro(amount)<=0:raise ValueError('Invalid payment')
        with self.tx():
            op=self.op(key,'WORKER_PAYMENT')
            p=self.db.execute('''INSERT INTO worker_payments(worker_id,payment_date,payment_kind,amount_micro_local,reference_number,notes,operation_request_id)
            VALUES(?,?,?,?,?,?,?)''',(worker_id,payment_date,payment_kind,micro(amount),reference,notes,op))
            self.db.execute('INSERT INTO worker_ledger(worker_id,ledger_kind,signed_amount_micro_local,payment_id,reference,operation_request_id) VALUES(?,?,?,?,?,?)',
                            (worker_id,payment_kind,-micro(amount),p.lastrowid,reference,op))
            self.audit(op,'worker_payments',p.lastrowid,'CREATE',None,{'amount':micro(amount),'kind':payment_kind});self.finish(op)
            return p.lastrowid

    def worker_adjustment(self,worker_id,amount,kind='ADJUSTMENT',reference=None,key=None):
        """Post one signed opening balance or correction, not a production expense."""
        if kind not in ('OPENING','ADJUSTMENT') or micro(amount)==0:raise ValueError('Invalid ledger adjustment')
        with self.tx():
            op=self.op(key,'WORKER_ADJUSTMENT')
            self.one('SELECT id FROM workers WHERE id=?',(worker_id,))
            if kind=='OPENING' and self.db.execute("SELECT EXISTS(SELECT 1 FROM worker_ledger WHERE worker_id=? AND ledger_kind='OPENING')",(worker_id,)).fetchone()[0]:
                raise ValueError('Worker already has opening balance')
            c=self.db.execute('INSERT INTO worker_ledger(worker_id,ledger_kind,signed_amount_micro_local,reference,operation_request_id) VALUES(?,?,?,?,?)',
                              (worker_id,kind,micro(amount),reference,op))
            self.audit(op,'worker_ledger',c.lastrowid,'CREATE',None,{'worker':worker_id,'kind':kind,'amount':micro(amount)})
            self.finish(op);return c.lastrowid

    def worker_statement(self,worker_id,start_utc=None,end_utc=None):
        rows=self.db.execute('SELECT * FROM worker_ledger WHERE worker_id=? ORDER BY id',(worker_id,)).fetchall()
        opening=sum(r['signed_amount_micro_local'] for r in rows if start_utc and r['created_at_utc']<start_utc)
        active=[r for r in rows if (not start_utc or r['created_at_utc']>=start_utc) and (not end_utc or r['created_at_utc']<=end_utc)]
        bal=opening;results=[]
        for r in active:
            bal+=r['signed_amount_micro_local'];results.append({'id':r['id'],'kind':r['ledger_kind'],'amount':money_text(r['signed_amount_micro_local']),'balance':money_text(bal)})
        return {'opening':money_text(opening),'transactions':results,'closing':money_text(bal)}

    def inventory_valuation(self,material_id):
        row=self.one('SELECT balance_micrograms FROM v_material_stock WHERE material_id=?',(material_id,))
        source,price=self._latest_price(material_id)
        return {'balance_grams':str(unmicro(row['balance_micrograms'])),
                'price_per_gram':price,'valuation_local':str(unmicro(row['balance_micrograms'])*dec(price)) if price else None}

    def test_restore(self, backup_path):
        """Exercise actual SQLite recovery into an independent temporary database."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'restored.db'
            src=sqlite3.connect(str(backup_path))
            try:
                with sqlite3.connect(str(target)) as restored:
                    src.backup(restored)
                check=sqlite3.connect(str(target))
                try:
                    ok=check.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
                    keys=check.execute('PRAGMA foreign_key_check').fetchall()==[]
                finally:check.close()
            finally:src.close()
        if ok and keys:
            with self.tx():
                self.db.execute('UPDATE backup_registry SET restore_test_at_utc=? WHERE backup_path=?',(now(),str(backup_path)))
        return ok and keys

    def backup(self, backup_dir):
        if self.path==':memory:':raise ValueError('Cannot create persistent backup from memory-only DB')
        out=Path(backup_dir);out.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        dest=out / f'TABIA_TECH_{stamp}.db'
        with sqlite3.connect(str(dest)) as saved:
            self.db.backup(saved)
        check=sqlite3.connect(str(dest))
        try:ok=check.execute('PRAGMA integrity_check').fetchone()[0]
        finally:check.close()
        if ok!='ok':
            dest.unlink(missing_ok=True)
            raise RuntimeError('Backup integrity_check failed: '+ok)
        digest=hashlib.sha256(dest.read_bytes()).hexdigest()
        with self.tx():
            self.db.execute('INSERT INTO backup_registry(backup_at_utc,backup_path,file_checksum,integrity_status) VALUES(?,?,?,?)',
                            (now(),str(dest),digest,'OK'))
            records=self.db.execute('SELECT id,backup_path FROM backup_registry WHERE integrity_status="OK" ORDER BY id DESC').fetchall()
            remove=list(records[10:])
            for r in remove:self.db.execute('DELETE FROM backup_registry WHERE id=?',(r['id'],))
        for r in remove:Path(r['backup_path']).unlink(missing_ok=True)
        return str(dest)



    def update_material(self, material_id, code, name, max_waste_ratio, key=None):
        """Update the material master without rewriting historical transaction snapshots."""
        if not code.strip() or not name.strip(): raise ValueError('Material code and name required')
        if not 0 <= dec(max_waste_ratio) <= 100: raise ValueError('Invalid allowed waste ratio')
        with self.tx():
            op=self.op(key,'UPDATE_MATERIAL')
            old=self.one('SELECT * FROM raw_materials WHERE id=?',(material_id,))
            updated={'code':code.strip(),'name':name.strip(),'max_waste_ratio':str(dec(max_waste_ratio))}
            before={'code':old['code'],'name':old['name'],'max_waste_ratio':old['max_waste_ratio']}
            if updated==before: raise ValueError('No changes specified')
            self.db.execute('UPDATE raw_materials SET code=?,name=?,max_waste_ratio=? WHERE id=?',
                            (updated['code'],updated['name'],updated['max_waste_ratio'],material_id))
            self.audit(op,'raw_materials',material_id,'UPDATE',before,updated)
            self.finish(op)
            return material_id

    def update_worker(self, worker_id, code, name, contact=None, key=None):
        """Update worker descriptive fields; ledger and old production entries remain intact."""
        if not code.strip() or not name.strip(): raise ValueError('Worker code and name required')
        with self.tx():
            op=self.op(key,'UPDATE_WORKER')
            old=self.one('SELECT * FROM workers WHERE id=?',(worker_id,))
            updated={'code':code.strip(),'name':name.strip(),'contact':contact or None}
            before={'code':old['code'],'name':old['name'],'contact':old['contact']}
            if updated==before: raise ValueError('No changes specified')
            self.db.execute('UPDATE workers SET code=?,name=?,contact=? WHERE id=?',
                            (updated['code'],updated['name'],updated['contact'],worker_id))
            self.audit(op,'workers',worker_id,'UPDATE',before,updated)
            self.finish(op)
            return worker_id

def create_blank_db(db_path, schema_path=None):
    f=Path(db_path)
    if f.exists():raise FileExistsError(f)
    f.parent.mkdir(parents=True,exist_ok=True)
    app=TabiaDB(db_path)
    try:app.initialize(schema_path)
    finally:app.close()
    return str(f)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description='TABIA TECH SQLite database generator')
    p.add_argument('database_path');p.add_argument('--schema')
    a=p.parse_args()
    print('Created:',create_blank_db(a.database_path,a.schema))
