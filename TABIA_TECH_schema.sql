-- TABIA TECH | SQLite >= 3.25 (Windows 7 Python 3.8 compatibility) | v1.0 | 2026-10-29
-- Money: integer micro-units of LOCAL currency (1 YER = 1,000,000).
-- Weight: integer micrograms (1 gram = 1,000,000).
-- Decimal TEXT columns are calculated with Python Decimal, NEVER SQLite REAL.
-- Set PRAGMA foreign_keys=ON in EACH application connection.
PRAGMA foreign_keys=ON;

CREATE TABLE app_settings (
 key TEXT PRIMARY KEY, value TEXT NOT NULL,
 updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE currencies (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 symbol TEXT, is_local INTEGER NOT NULL DEFAULT 0 CHECK(is_local IN (0,1)),
 is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1))
);
CREATE UNIQUE INDEX ux_one_local_currency ON currencies(is_local) WHERE is_local=1;
CREATE TABLE exchange_rate_history (
 id INTEGER PRIMARY KEY, currency_id INTEGER NOT NULL REFERENCES currencies(id) ON DELETE RESTRICT,
 valid_from TEXT NOT NULL CHECK(date(valid_from)=valid_from),
 rate_local_per_unit TEXT NOT NULL CHECK(CAST(rate_local_per_unit AS REAL)>0),
 recorded_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 UNIQUE(currency_id,valid_from)
);
CREATE INDEX ix_fx_lookup ON exchange_rate_history(currency_id,valid_from DESC);
CREATE TABLE raw_materials (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 max_waste_ratio TEXT NOT NULL DEFAULT '0' CHECK(CAST(max_waste_ratio AS REAL) BETWEEN 0 AND 100),
 is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1))
);
CREATE TABLE material_units (
 id INTEGER PRIMARY KEY, material_id INTEGER NOT NULL REFERENCES raw_materials(id) ON DELETE RESTRICT,
 slot INTEGER NOT NULL CHECK(slot BETWEEN 1 AND 3), name TEXT NOT NULL,
 factor_to_gram_decimal TEXT NOT NULL CHECK(CAST(factor_to_gram_decimal AS REAL)>0),
 is_base INTEGER NOT NULL DEFAULT 0 CHECK(is_base IN (0,1)),
 UNIQUE(material_id,slot), UNIQUE(material_id,name), UNIQUE(id,material_id)
);
CREATE UNIQUE INDEX ux_one_base_unit_per_material ON material_units(material_id) WHERE is_base=1;
CREATE TABLE workers (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 contact TEXT, is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1))
);
CREATE TABLE packaging_sizes (
 id INTEGER PRIMARY KEY, label TEXT NOT NULL,
 weight_micrograms INTEGER NOT NULL UNIQUE CHECK(weight_micrograms>0),
 is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1))
);
CREATE TABLE packaging_fee_history (
 id INTEGER PRIMARY KEY, packaging_size_id INTEGER NOT NULL REFERENCES packaging_sizes(id) ON DELETE RESTRICT,
 effective_from TEXT NOT NULL CHECK(date(effective_from)=effective_from),
 fee_micro_local INTEGER NOT NULL CHECK(fee_micro_local>=0),
 created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 UNIQUE(packaging_size_id,effective_from)
);
CREATE INDEX ix_fees_lookup ON packaging_fee_history(packaging_size_id,effective_from DESC);
CREATE TABLE expense_categories (
 id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1))
);
CREATE TABLE operation_requests (
 id INTEGER PRIMARY KEY AUTOINCREMENT, idempotency_key TEXT NOT NULL UNIQUE,
 operation_kind TEXT NOT NULL, created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 committed_at_utc TEXT
);
CREATE TABLE purchase_invoices (
 id INTEGER PRIMARY KEY, invoice_number TEXT NOT NULL UNIQUE,
 purchase_date TEXT NOT NULL CHECK(date(purchase_date)=purchase_date),
 material_id INTEGER NOT NULL REFERENCES raw_materials(id) ON DELETE RESTRICT,
 unit_id INTEGER NOT NULL, entered_quantity_decimal TEXT NOT NULL,
 factor_snapshot_decimal TEXT NOT NULL, quantity_micrograms INTEGER NOT NULL CHECK(quantity_micrograms>0),
 currency_id INTEGER NOT NULL REFERENCES currencies(id) ON DELETE RESTRICT,
 final_amount_micro_currency INTEGER NOT NULL CHECK(final_amount_micro_currency>=0),
 fx_rate_snapshot_decimal TEXT NOT NULL, final_amount_micro_local INTEGER NOT NULL CHECK(final_amount_micro_local>=0),
 unit_price_local_per_gram_decimal TEXT NOT NULL,
 supply_seq INTEGER NOT NULL UNIQUE REFERENCES operation_requests(id) ON DELETE RESTRICT,
 status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','VOID')),
 current_revision_id INTEGER,
 created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 FOREIGN KEY(unit_id,material_id) REFERENCES material_units(id,material_id) ON DELETE RESTRICT
);
CREATE INDEX ix_purchases_latest ON purchase_invoices(material_id,purchase_date DESC,id DESC) WHERE status='ACTIVE';
CREATE INDEX ix_purchase_fifo ON purchase_invoices(material_id,supply_seq) WHERE status='ACTIVE';
CREATE TABLE purchase_invoice_revisions (
 id INTEGER PRIMARY KEY, purchase_id INTEGER NOT NULL REFERENCES purchase_invoices(id) ON DELETE RESTRICT,
 revision_no INTEGER NOT NULL CHECK(revision_no>0),
 change_kind TEXT NOT NULL CHECK(change_kind IN ('CREATE','QUANTITY','PRICE','QUANTITY_AND_PRICE')),
 old_values_json TEXT, new_values_json TEXT NOT NULL CHECK(json_valid(new_values_json)),
 delta_quantity_micrograms INTEGER NOT NULL,
 operation_request_id INTEGER NOT NULL UNIQUE REFERENCES operation_requests(id),
 changed_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 UNIQUE(purchase_id,revision_no)
);
CREATE INDEX ix_purchrev_purchase ON purchase_invoice_revisions(purchase_id,revision_no DESC);
CREATE TABLE material_price_events (
 id INTEGER PRIMARY KEY, material_id INTEGER NOT NULL REFERENCES raw_materials(id),
 source_purchase_id INTEGER REFERENCES purchase_invoices(id),
 previous_price_decimal TEXT, new_price_decimal TEXT,
 previous_source_id INTEGER REFERENCES purchase_invoices(id),
 new_source_id INTEGER REFERENCES purchase_invoices(id),
 reason TEXT NOT NULL,
 operation_request_id INTEGER NOT NULL REFERENCES operation_requests(id),
 event_time_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE production_orders (
 id INTEGER PRIMARY KEY, order_number TEXT NOT NULL UNIQUE,
 order_date TEXT NOT NULL CHECK(date(order_date)=order_date),
 material_id INTEGER NOT NULL REFERENCES raw_materials(id), worker_id INTEGER NOT NULL REFERENCES workers(id),
 status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','POSTED','CANCELED')),
 first_post_seq INTEGER UNIQUE REFERENCES operation_requests(id),
 current_version_id INTEGER,
 created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX ix_orders_material_post ON production_orders(material_id,first_post_seq) WHERE status='POSTED';
CREATE INDEX ix_orders_date_worker ON production_orders(order_date,worker_id,status);
CREATE TABLE production_versions (
 id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES production_orders(id),
 version_no INTEGER NOT NULL CHECK(version_no>0),
 kind TEXT NOT NULL CHECK(kind IN ('DRAFT','APPROVE','EDIT','CANCEL')),
 previous_version_id INTEGER REFERENCES production_versions(id),
 input_quantity_micrograms INTEGER NOT NULL CHECK(input_quantity_micrograms>0),
 input_unit_id INTEGER NOT NULL, factor_snapshot_decimal TEXT NOT NULL,
 raw_price_snapshot_per_gram_decimal TEXT, raw_price_source_purchase_id INTEGER REFERENCES purchase_invoices(id),
 raw_cost_micro_local INTEGER CHECK(raw_cost_micro_local>=0),
 shared_expenses_micro_local INTEGER CHECK(shared_expenses_micro_local>=0),
 wages_micro_local INTEGER CHECK(wages_micro_local>=0),
 total_cost_micro_local INTEGER CHECK(total_cost_micro_local>=0),
 output_weight_micrograms INTEGER NOT NULL CHECK(output_weight_micrograms>0),
 waste_micrograms INTEGER NOT NULL,
 warning_flags_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(warning_flags_json)),
 operation_request_id INTEGER NOT NULL UNIQUE REFERENCES operation_requests(id),
 posted_at_utc TEXT,
 UNIQUE(order_id,version_no),
 FOREIGN KEY(input_unit_id) REFERENCES material_units(id),
 CHECK (kind='DRAFT' OR (raw_price_snapshot_per_gram_decimal IS NOT NULL AND raw_cost_micro_local IS NOT NULL AND shared_expenses_micro_local IS NOT NULL AND wages_micro_local IS NOT NULL AND total_cost_micro_local IS NOT NULL AND posted_at_utc IS NOT NULL))
);
CREATE INDEX ix_versions_order ON production_versions(order_id,version_no DESC);
CREATE TABLE production_packaging_lines (
 id INTEGER PRIMARY KEY, version_id INTEGER NOT NULL REFERENCES production_versions(id),
 packaging_size_id INTEGER NOT NULL REFERENCES packaging_sizes(id),
 weight_micrograms_snapshot INTEGER NOT NULL CHECK(weight_micrograms_snapshot>0),
 package_count INTEGER NOT NULL CHECK(package_count>0),
 fee_per_pack_micro_local_snapshot INTEGER CHECK(fee_per_pack_micro_local_snapshot>=0),
 raw_share_micro_local INTEGER CHECK(raw_share_micro_local>=0),
 expense_share_micro_local INTEGER CHECK(expense_share_micro_local>=0),
 wage_total_micro_local INTEGER CHECK(wage_total_micro_local>=0),
 rounding_adjustment_micro_local INTEGER NOT NULL DEFAULT 0,
 line_total_micro_local INTEGER CHECK(line_total_micro_local>=0),
 display_line_total_cents INTEGER,
 unit_cost_precise_decimal TEXT,
 UNIQUE(version_id,packaging_size_id)
);
CREATE INDEX ix_packlines_version ON production_packaging_lines(version_id);
CREATE TABLE production_expense_lines (
 id INTEGER PRIMARY KEY, version_id INTEGER NOT NULL REFERENCES production_versions(id),
 expense_category_id INTEGER NOT NULL REFERENCES expense_categories(id),
 description TEXT, amount_micro_local INTEGER NOT NULL CHECK(amount_micro_local>=0)
);
CREATE TABLE production_fee_snapshots (
 id INTEGER PRIMARY KEY, version_id INTEGER NOT NULL REFERENCES production_versions(id),
 packaging_size_id INTEGER NOT NULL REFERENCES packaging_sizes(id),
 fee_per_pack_micro_local INTEGER NOT NULL CHECK(fee_per_pack_micro_local>=0),
 source_fee_history_id INTEGER NOT NULL REFERENCES packaging_fee_history(id),
 UNIQUE(version_id,packaging_size_id)
);
CREATE TABLE raw_inventory_movements (
 id INTEGER PRIMARY KEY, material_id INTEGER NOT NULL REFERENCES raw_materials(id),
 quantity_delta_micrograms INTEGER NOT NULL CHECK(quantity_delta_micrograms<>0),
 movement_type TEXT NOT NULL CHECK(movement_type IN ('PURCHASE','PURCHASE_ADJUST','PRODUCTION_CONSUME','PRODUCTION_REVERSE')),
 purchase_revision_id INTEGER REFERENCES purchase_invoice_revisions(id),
 production_version_id INTEGER REFERENCES production_versions(id),
 operation_request_id INTEGER NOT NULL REFERENCES operation_requests(id),
 created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK ((movement_type IN ('PURCHASE','PURCHASE_ADJUST') AND purchase_revision_id IS NOT NULL AND production_version_id IS NULL AND quantity_delta_micrograms>0 OR
         movement_type='PURCHASE_ADJUST' AND purchase_revision_id IS NOT NULL AND production_version_id IS NULL) OR
        (movement_type IN ('PRODUCTION_CONSUME','PRODUCTION_REVERSE') AND purchase_revision_id IS NULL AND production_version_id IS NOT NULL AND
         ((movement_type='PRODUCTION_CONSUME' AND quantity_delta_micrograms<0) OR (movement_type='PRODUCTION_REVERSE' AND quantity_delta_micrograms>0))))
);
CREATE UNIQUE INDEX ux_inventory_revision ON raw_inventory_movements(purchase_revision_id) WHERE purchase_revision_id IS NOT NULL;
CREATE UNIQUE INDEX ux_inventory_version_type ON raw_inventory_movements(production_version_id,movement_type) WHERE production_version_id IS NOT NULL;
CREATE INDEX ix_inventory_material_time ON raw_inventory_movements(material_id,created_at_utc,id);
CREATE TABLE fifo_rebuild_runs (
 id INTEGER PRIMARY KEY, material_id INTEGER NOT NULL REFERENCES raw_materials(id),
 reason TEXT NOT NULL, operation_request_id INTEGER NOT NULL REFERENCES operation_requests(id),
 rebuild_time_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 is_current INTEGER NOT NULL CHECK(is_current IN (0,1))
);
CREATE UNIQUE INDEX ux_fifo_current ON fifo_rebuild_runs(material_id) WHERE is_current=1;
CREATE INDEX ix_fifo_runs ON fifo_rebuild_runs(material_id,id DESC);
CREATE TABLE fifo_allocations (
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES fifo_rebuild_runs(id),
 purchase_id INTEGER NOT NULL REFERENCES purchase_invoices(id),
 production_version_id INTEGER NOT NULL REFERENCES production_versions(id),
 allocated_micrograms INTEGER NOT NULL CHECK(allocated_micrograms>0),
 is_later_shortage_coverage INTEGER NOT NULL CHECK(is_later_shortage_coverage IN (0,1)),
 UNIQUE(run_id,purchase_id,production_version_id)
);
CREATE INDEX ix_alloc_run_purchase ON fifo_allocations(run_id,purchase_id);
CREATE INDEX ix_alloc_run_version ON fifo_allocations(run_id,production_version_id);
CREATE TABLE fifo_shortages (
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES fifo_rebuild_runs(id),
 production_version_id INTEGER NOT NULL REFERENCES production_versions(id),
 initial_uncovered_micrograms INTEGER NOT NULL CHECK(initial_uncovered_micrograms>0),
 remaining_uncovered_micrograms INTEGER NOT NULL CHECK(remaining_uncovered_micrograms>=0),
 UNIQUE(run_id,production_version_id),
 CHECK(remaining_uncovered_micrograms<=initial_uncovered_micrograms)
);
CREATE TABLE worker_payments (
 id INTEGER PRIMARY KEY, worker_id INTEGER NOT NULL REFERENCES workers(id),
 payment_date TEXT NOT NULL CHECK(date(payment_date)=payment_date),
 payment_kind TEXT NOT NULL CHECK(payment_kind IN ('PAYMENT','ADVANCE')),
 amount_micro_local INTEGER NOT NULL CHECK(amount_micro_local>0),
 reference_number TEXT, notes TEXT,
 operation_request_id INTEGER NOT NULL UNIQUE REFERENCES operation_requests(id)
);
CREATE TABLE worker_ledger (
 id INTEGER PRIMARY KEY, worker_id INTEGER NOT NULL REFERENCES workers(id),
 ledger_kind TEXT NOT NULL CHECK(ledger_kind IN ('OPENING','EARNED','REVERSE_EARNED','PAYMENT','ADVANCE','ADJUSTMENT')),
 signed_amount_micro_local INTEGER NOT NULL CHECK(signed_amount_micro_local<>0),
 production_version_id INTEGER REFERENCES production_versions(id),
 payment_id INTEGER REFERENCES worker_payments(id),
 reference TEXT,
 operation_request_id INTEGER NOT NULL REFERENCES operation_requests(id),
 created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 CHECK ((ledger_kind IN ('EARNED','REVERSE_EARNED') AND production_version_id IS NOT NULL AND payment_id IS NULL) OR
        (ledger_kind IN ('PAYMENT','ADVANCE') AND payment_id IS NOT NULL AND production_version_id IS NULL) OR
        (ledger_kind IN ('OPENING','ADJUSTMENT') AND payment_id IS NULL AND production_version_id IS NULL)),
 CHECK ((ledger_kind='EARNED' AND signed_amount_micro_local>0) OR
        (ledger_kind IN ('REVERSE_EARNED','PAYMENT','ADVANCE') AND signed_amount_micro_local<0) OR
        ledger_kind IN ('OPENING','ADJUSTMENT'))
);
CREATE UNIQUE INDEX ux_worker_ledger_version_kind ON worker_ledger(production_version_id,ledger_kind) WHERE production_version_id IS NOT NULL;
CREATE UNIQUE INDEX ux_worker_ledger_payment ON worker_ledger(payment_id) WHERE payment_id IS NOT NULL;
CREATE UNIQUE INDEX ux_worker_opening ON worker_ledger(worker_id) WHERE ledger_kind='OPENING';
CREATE INDEX ix_worker_statement ON worker_ledger(worker_id,created_at_utc,id);
CREATE TABLE audit_events (
 id INTEGER PRIMARY KEY, operation_request_id INTEGER NOT NULL REFERENCES operation_requests(id),
 entity_type TEXT NOT NULL, entity_id INTEGER NOT NULL, action TEXT NOT NULL,
 previous_json TEXT CHECK(previous_json IS NULL OR json_valid(previous_json)),
 new_json TEXT CHECK(new_json IS NULL OR json_valid(new_json)),
 occurred_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 device_label TEXT
);
CREATE INDEX ix_audit_lookup ON audit_events(entity_type,entity_id,occurred_at_utc);
CREATE TABLE backup_registry (
 id INTEGER PRIMARY KEY, backup_at_utc TEXT NOT NULL,
 backup_path TEXT NOT NULL UNIQUE, file_checksum TEXT NOT NULL,
 integrity_status TEXT NOT NULL CHECK(integrity_status IN ('OK','FAILED')),
 restore_test_at_utc TEXT
);
CREATE TABLE schema_migrations (
 version INTEGER PRIMARY KEY, applied_at_utc TEXT NOT NULL,
 description TEXT NOT NULL, checksum TEXT NOT NULL
);
-- APPEND-ONLY journals: only corrections via compensating entries, no physical delete.
CREATE TRIGGER check_invoice_revision_owner BEFORE UPDATE OF current_revision_id ON purchase_invoices
WHEN NEW.current_revision_id IS NOT NULL AND NOT EXISTS
  (SELECT 1 FROM purchase_invoice_revisions r WHERE r.id=NEW.current_revision_id AND r.purchase_id=NEW.id)
BEGIN SELECT RAISE(ABORT,'revision belongs to another invoice'); END;
CREATE TRIGGER check_order_version_owner BEFORE UPDATE OF current_version_id ON production_orders
WHEN NEW.current_version_id IS NOT NULL AND NOT EXISTS
  (SELECT 1 FROM production_versions v WHERE v.id=NEW.current_version_id AND v.order_id=NEW.id)
BEGIN SELECT RAISE(ABORT,'version belongs to another order'); END;
CREATE TRIGGER protect_fee_hist_u BEFORE UPDATE ON packaging_fee_history BEGIN SELECT RAISE(ABORT,'fee history is append-only'); END;
CREATE TRIGGER protect_fee_hist_d BEFORE DELETE ON packaging_fee_history BEGIN SELECT RAISE(ABORT,'fee history is append-only'); END;
CREATE TRIGGER protect_fx_hist_u BEFORE UPDATE ON exchange_rate_history BEGIN SELECT RAISE(ABORT,'exchange history is append-only'); END;
CREATE TRIGGER protect_fx_hist_d BEFORE DELETE ON exchange_rate_history BEGIN SELECT RAISE(ABORT,'exchange history is append-only'); END;
CREATE TRIGGER protect_packlines_u BEFORE UPDATE ON production_packaging_lines BEGIN SELECT RAISE(ABORT,'production package snapshots are immutable'); END;
CREATE TRIGGER protect_packlines_d BEFORE DELETE ON production_packaging_lines BEGIN SELECT RAISE(ABORT,'production package snapshots are immutable'); END;
CREATE TRIGGER protect_explines_u BEFORE UPDATE ON production_expense_lines BEGIN SELECT RAISE(ABORT,'production expense snapshots are immutable'); END;
CREATE TRIGGER protect_explines_d BEFORE DELETE ON production_expense_lines BEGIN SELECT RAISE(ABORT,'production expense snapshots are immutable'); END;
CREATE TRIGGER protect_feesnap_u BEFORE UPDATE ON production_fee_snapshots BEGIN SELECT RAISE(ABORT,'production fee snapshots are immutable'); END;
CREATE TRIGGER protect_feesnap_d BEFORE DELETE ON production_fee_snapshots BEGIN SELECT RAISE(ABORT,'production fee snapshots are immutable'); END;
CREATE TRIGGER protect_payments_u BEFORE UPDATE ON worker_payments BEGIN SELECT RAISE(ABORT,'worker payments are append-only'); END;
CREATE TRIGGER protect_payments_d BEFORE DELETE ON worker_payments BEGIN SELECT RAISE(ABORT,'worker payments are append-only'); END;
CREATE TRIGGER protect_inventory_u BEFORE UPDATE ON raw_inventory_movements BEGIN SELECT RAISE(ABORT,'inventory journal is append-only'); END;
CREATE TRIGGER protect_inventory_d BEFORE DELETE ON raw_inventory_movements BEGIN SELECT RAISE(ABORT,'inventory journal is append-only'); END;
CREATE TRIGGER protect_ledger_u BEFORE UPDATE ON worker_ledger BEGIN SELECT RAISE(ABORT,'worker ledger is append-only'); END;
CREATE TRIGGER protect_ledger_d BEFORE DELETE ON worker_ledger BEGIN SELECT RAISE(ABORT,'worker ledger is append-only'); END;
CREATE TRIGGER protect_revisions_u BEFORE UPDATE ON purchase_invoice_revisions BEGIN SELECT RAISE(ABORT,'purchase revisions immutable'); END;
CREATE TRIGGER protect_revisions_d BEFORE DELETE ON purchase_invoice_revisions BEGIN SELECT RAISE(ABORT,'purchase revisions immutable'); END;
CREATE TRIGGER protect_versions_u BEFORE UPDATE ON production_versions BEGIN SELECT RAISE(ABORT,'production versions immutable'); END;
CREATE TRIGGER protect_versions_d BEFORE DELETE ON production_versions BEGIN SELECT RAISE(ABORT,'production versions immutable'); END;
CREATE TRIGGER protect_audit_u BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT,'audit is append-only'); END;
CREATE TRIGGER protect_audit_d BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT,'audit is append-only'); END;
CREATE TRIGGER protect_price_u BEFORE UPDATE ON material_price_events BEGIN SELECT RAISE(ABORT,'price history is append-only'); END;
CREATE TRIGGER protect_price_d BEFORE DELETE ON material_price_events BEGIN SELECT RAISE(ABORT,'price history is append-only'); END;
CREATE TRIGGER protect_purchalloc_u BEFORE UPDATE ON fifo_allocations BEGIN SELECT RAISE(ABORT,'FIFO history is append-only'); END;
CREATE TRIGGER protect_purchalloc_d BEFORE DELETE ON fifo_allocations BEGIN SELECT RAISE(ABORT,'FIFO history is append-only'); END;
CREATE TRIGGER protect_shortage_u BEFORE UPDATE ON fifo_shortages BEGIN SELECT RAISE(ABORT,'FIFO history is append-only'); END;
CREATE TRIGGER protect_shortage_d BEFORE DELETE ON fifo_shortages BEGIN SELECT RAISE(ABORT,'FIFO history is append-only'); END;

CREATE VIEW v_material_stock AS
SELECT m.id material_id,m.code,m.name,
 COALESCE((SELECT SUM(i.quantity_delta_micrograms) FROM raw_inventory_movements i WHERE i.material_id=m.id),0) balance_micrograms,
 ROUND(COALESCE((SELECT SUM(i.quantity_delta_micrograms) FROM raw_inventory_movements i WHERE i.material_id=m.id),0)/1000000.0,3) balance_grams_display
FROM raw_materials m;
CREATE VIEW v_material_last_price AS
SELECT m.id material_id, p.id purchase_id, p.invoice_number, p.purchase_date,
 p.unit_price_local_per_gram_decimal price_local_per_gram_decimal
FROM raw_materials m LEFT JOIN purchase_invoices p ON p.id=(
 SELECT p2.id FROM purchase_invoices p2 WHERE p2.material_id=m.id AND p2.status='ACTIVE'
 ORDER BY p2.purchase_date DESC,p2.id DESC LIMIT 1);
-- Financial reports must compute valuations with Decimal in service, not REAL SQL.
CREATE VIEW v_inventory_valuation AS
SELECT s.material_id,s.code,s.name,s.balance_micrograms,
 pr.purchase_id,pr.price_local_per_gram_decimal,
 CASE WHEN s.balance_micrograms<0 THEN 1 ELSE 0 END has_negative_inventory
FROM v_material_stock s LEFT JOIN v_material_last_price pr ON pr.material_id=s.material_id;
CREATE VIEW v_fifo_lot_usage AS
SELECT p.id purchase_id,p.material_id,p.invoice_number,p.quantity_micrograms,
 COALESCE((SELECT SUM(a.allocated_micrograms) FROM fifo_allocations a JOIN fifo_rebuild_runs r ON a.run_id=r.id
 WHERE r.is_current=1 AND a.purchase_id=p.id),0) allocated_micrograms,
 p.quantity_micrograms-COALESCE((SELECT SUM(a.allocated_micrograms) FROM fifo_allocations a JOIN fifo_rebuild_runs r ON a.run_id=r.id
 WHERE r.is_current=1 AND a.purchase_id=p.id),0) remaining_micrograms
FROM purchase_invoices p WHERE p.status='ACTIVE';
CREATE VIEW v_fifo_pending_shortages AS
SELECT r.material_id, s.production_version_id, o.id order_id, o.order_number,
 s.initial_uncovered_micrograms,s.remaining_uncovered_micrograms
FROM fifo_shortages s JOIN fifo_rebuild_runs r ON r.id=s.run_id
 JOIN production_versions v ON v.id=s.production_version_id
 JOIN production_orders o ON o.id=v.order_id
WHERE r.is_current=1 AND s.remaining_uncovered_micrograms>0;
CREATE VIEW v_production_costs AS
SELECT o.id order_id,o.order_number,o.order_date,o.material_id,o.worker_id,o.status,
 v.id version_id,v.version_no,v.input_quantity_micrograms,v.output_weight_micrograms,
 v.waste_micrograms,v.raw_cost_micro_local,v.shared_expenses_micro_local,
 v.wages_micro_local,v.total_cost_micro_local,v.warning_flags_json
FROM production_orders o JOIN production_versions v ON v.id=o.current_version_id;
CREATE VIEW v_waste_alerts AS
SELECT c.*,m.max_waste_ratio,
 CASE WHEN c.waste_micrograms<0 THEN 1 ELSE 0 END outputs_exceed_inputs,
 CASE WHEN c.input_quantity_micrograms>0 AND
 (CAST(c.waste_micrograms AS REAL)*100/c.input_quantity_micrograms)>CAST(m.max_waste_ratio AS REAL)
 THEN 1 ELSE 0 END exceeds_material_waste_limit
FROM v_production_costs c JOIN raw_materials m ON c.material_id=m.id
WHERE c.status='POSTED';
CREATE VIEW v_worker_statement AS
SELECT l.id ledger_id,l.worker_id,w.name worker_name,l.ledger_kind,l.reference,l.created_at_utc,
 l.signed_amount_micro_local,
 SUM(l.signed_amount_micro_local) OVER (PARTITION BY l.worker_id ORDER BY l.id ROWS UNBOUNDED PRECEDING) running_balance_micro_local
FROM worker_ledger l JOIN workers w ON l.worker_id=w.id;
CREATE VIEW v_purchase_price_timeline AS
SELECT e.id event_id,e.material_id,m.name material_name,e.reason,e.previous_price_decimal,
 e.new_price_decimal,e.previous_source_id,e.new_source_id,e.event_time_utc
FROM material_price_events e JOIN raw_materials m ON m.id=e.material_id;
CREATE VIEW v_audit_history AS SELECT * FROM audit_events;
