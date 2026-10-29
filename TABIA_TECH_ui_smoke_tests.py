"""Automated widget/report smoke tests on an isolated temporary SQLite database."""
import tempfile
from pathlib import Path
import tkinter as tk
from decimal import Decimal
from TABIA_TECH_desktop import TabiaApp
from TABIA_TECH_engine import TabiaDB


def main():
    with tempfile.TemporaryDirectory() as tmp:
        target=Path(tmp)/'data'/'test.db'
        target.parent.mkdir()
        src=TabiaDB(target)
        src.initialize()
        material=src.add_material('MILK','حليب بودرة',[('جرام',1),('كجم',1000),('كيس 25 كجم',25000)],5)
        worker=src.add_worker('W01','أحمد محمد')
        src.set_packaging_fee(1,'2026-01-01',70)
        src.set_packaging_fee(2,'2026-01-01',65)
        src.set_packaging_fee(3,'2026-01-01',65)
        pid=src.purchase('B-001','2026-10-26',material,25,2,197125)
        oid=src.create_draft('PROD-001','2026-10-27',material,worker,25,2,[(1,10),(2,20),(3,20)])
        src.approve(oid)
        src.worker_payment(worker,'2026-10-28',1000)
        src.close()
        root=tk.Tk()
        app=TabiaApp(root,target)
        pages=['dashboard','materials','purchases','production','workers','inventory','reports','settings','audit']
        for pg in pages:
            app.nav(pg)
            root.update_idletasks(); root.update()
            assert root.winfo_exists(), pg
            print('PASS PAGE:',pg)
        for name in app.REPORT_NAMES:
            mat=material if name not in ('أرصدة العمال','كشف حساب عامل') else None
            wk=worker if name=='كشف حساب عامل' else None
            headers,rows=app.build_report(name,material=mat,worker=wk)
            assert headers and isinstance(rows,list),(name,headers)
            print(f'PASS REPORT: {name} - {len(rows)} rows')
        head,rows=app.build_report('تكاليف أوامر الإنتاج',material,worker)
        assert rows[0][-1]=='200,425.00',rows
        head,rows=app.build_report('تكلفة العبوات حسب الوزن',material,worker)
        assert len(rows)==3,rows
        assert {r[3]:r[5] for r in rows}=={'1 كجم':'7,955.00','500 جرام':'4,007.50','250 جرام':'2,036.25'},rows
        print('PASS reference cost / 3 package costs')
        assert not app.svc.db.execute('PRAGMA foreign_key_check').fetchall()
        assert app.svc.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        print('PASS DB integrity')
        # Open/close all transaction dialogs without writing any demo data.
        dialogs=[
            ('edit material',lambda:app.open_edit_material(material)),
            ('edit unit',lambda:app.open_edit_unit(material)),
            ('edit purchase',lambda:app.open_edit_purchase(pid)),
            ('edit posted order',lambda:app.open_edit_order(oid)),
            ('order cost details',lambda:app.show_cost_detail(oid)),
            ('edit worker',lambda:app.open_edit_worker(worker)),
            ('worker adjustment',lambda:app.open_worker_adjustment()),
        ]
        for label,call in dialogs:
            call()
            root.update_idletasks(); root.update()
            windows=[w for w in root.winfo_children() if isinstance(w,tk.Toplevel)]
            assert windows,label
            for w in windows:w.destroy()
            root.update()
            print('PASS DIALOG:',label)
        # Test report exports with no external browser or file chooser interactions.
        import TABIA_TECH_desktop as desktop
        old_exports=desktop.EXPORTS
        old_backups=desktop.BACKUPS
        desktop.EXPORTS=Path(tmp)/'exports'
        desktop.BACKUPS=Path(tmp)/'backups'
        old_save=desktop.filedialog.asksaveasfilename
        old_browser=desktop.webbrowser.open
        try:
            app.report_data=app.build_report('تكاليف أوامر الإنتاج',material,worker)
            app.report_heading='تكاليف أوامر الإنتاج'
            app.report_filter='بيانات اختبار محلية'
            desktop.filedialog.asksaveasfilename=lambda **kw:str(Path(tmp)/'report.csv')
            desktop.webbrowser.open=lambda url:True
            app.export_csv()
            app.export_html()
            contents=(Path(tmp)/'report.csv').read_text(encoding='utf-8-sig')
            assert '200,425.00' in contents
            assert list((Path(tmp)/'exports').glob('*.html'))
            print('PASS exports: Excel-compatible CSV and printable HTML/PDF')
        finally:
            desktop.filedialog.asksaveasfilename=old_save
            desktop.webbrowser.open=old_browser
        # Exercise restoration from an actual SQLite backup in the UI.
        backup=app.svc.backup(Path(tmp)/'backup')
        old_open=desktop.filedialog.askopenfilename
        old_ask=desktop.messagebox.askyesno
        old_show=desktop.messagebox.showinfo
        try:
            desktop.filedialog.askopenfilename=lambda **kw:backup
            desktop.messagebox.askyesno=lambda *a,**kw:True
            desktop.messagebox.showinfo=lambda *a,**kw:None
            app.restore_backup()
            assert app.svc.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            print('PASS UI restore backup')
        finally:
            desktop.filedialog.askopenfilename=old_open
            desktop.messagebox.askyesno=old_ask
            desktop.messagebox.showinfo=old_show

        desktop.EXPORTS=old_exports
        desktop.BACKUPS=old_backups
        root.destroy()
        app.svc.close()
    print('ALL UI SMOKE TESTS PASSED')

if __name__=='__main__':main()
