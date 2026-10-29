"""TABIA TECH Desktop — Arabic, offline, Windows-friendly Tkinter application.

Business mutations are delegated to TABIA_TECH_engine.TabiaDB. Reports read
SQLite views only; the UI never writes directly to stock, FIFO or worker ledger.
Python 3.8+ on Windows 7 (x86), stdlib only. Run: python TABIA_TECH_desktop.py
"""
from __future__ import annotations
import csv
from contextlib import closing
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import html
import re
import unicodedata
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import webbrowser
from TABIA_TECH_engine import TabiaDB, micro, unmicro, dec, money_text, connect_sqlite

# PyInstaller places read-only seed resources in sys._MEIPASS.
BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
# Keep the live database outside installation folder so upgrades and uninstalls
# cannot overwrite it. This directory is writable for standard Win7 users.
if os.environ.get('TABIA_TECH_DATA_DIR'):
    DATA = Path(os.environ['TABIA_TECH_DATA_DIR']).expanduser()
elif sys.platform == 'win32':
    DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'TABIA_TECH'
else:
    DATA = BASE / 'data'
DBFILE = DATA / 'TABIA_TECH.db'
BACKUPS = DATA / 'backups'
EXPORTS = DATA / 'exports'
NAVY = '#112942'
BLUE = '#156AC5'
GREEN = '#159477'
BG = '#F2F6FB'
INK = '#20334B'
MUTED = '#68819B'
WHITE = '#FFFFFF'
WARN = '#AE4A20'
TODAY = date.today().isoformat()


# Tk 8.6 on many systems lacks complete Arabic shaping/bidirectional text.
# Keep stored values logical; shape only display surfaces. Set
# TABIA_TECH_RTL_FIX=0 to disable this compatibility layer if a newer Tk
# already handles Arabic natively.
RTL_FIX=os.environ.get('TABIA_TECH_RTL_FIX','1')!='0'
_AR_FORMS={}
if RTL_FIX:
    for _cp in (*range(0xFB50,0xFE00),*range(0xFE70,0xFF00)):
        _char=chr(_cp)
        _decomp=unicodedata.decomposition(_char).split()
        if len(_decomp)==2 and _decomp[0] in ('<isolated>','<final>','<initial>','<medial>'):
            _AR_FORMS.setdefault(chr(int(_decomp[1],16)),{})[_decomp[0][1:-1]]=_char
_AR_WORDS=re.compile(r'[\u0621-\u064a]+(?: +[\u0621-\u064a]+)*')

def visual_text(value):
    if not RTL_FIX or not isinstance(value,str):return value
    def shape(match):
        segment=match.group(0)
        result=[]
        for i,ch in enumerate(segment):
            forms=_AR_FORMS.get(ch,{})
            right=(i>0 and 'initial' in _AR_FORMS.get(segment[i-1],{}) and 'final' in forms)
            left=(i<len(segment)-1 and 'initial' in forms and 'final' in _AR_FORMS.get(segment[i+1],{}))
            state='medial' if right and left else 'final' if right else 'initial' if left else 'isolated'
            result.append(forms.get(state,ch))
        return ''.join(reversed(result))
    return _AR_WORDS.sub(shape,value)

_OriginalLabel=tk.Label
class ArabicLabel(_OriginalLabel):
    def __init__(self,*args,**kwargs):
        if 'text' in kwargs:kwargs['text']=visual_text(kwargs['text'])
        super().__init__(*args,**kwargs)
tk.Label=ArabicLabel

_OriginalButton=tk.Button
class ArabicTkButton(_OriginalButton):
    def __init__(self,*args,**kwargs):
        if 'text' in kwargs:kwargs['text']=visual_text(kwargs['text'])
        super().__init__(*args,**kwargs)
tk.Button=ArabicTkButton

class ArabicCombo(ttk.Combobox):
    def __init__(self,*args,**kwargs):
        values=kwargs.pop('values',[])
        self._logic_values=[]
        self._visual_to_logic={}
        super().__init__(*args,**kwargs)
        self.configure(values=values)

    def configure(self,cnf=None,**kwargs):
        if 'values' in kwargs:
            self._logic_values=list(kwargs['values'])
            transformed=[visual_text(str(v)) for v in self._logic_values]
            self._visual_to_logic=dict(zip(transformed,self._logic_values))
            kwargs['values']=transformed
        return super().configure(cnf,**kwargs)

    config=configure

    def get(self):
        val=super().get()
        return self._visual_to_logic.get(val,val)

    def __getitem__(self,key):
        if key=='values':return tuple(self._logic_values)
        return super().__getitem__(key)

_OldNotebookAdd=ttk.Notebook.add
def _rtl_notebook_add(self,child,**kwargs):
    if 'text' in kwargs:kwargs['text']=visual_text(kwargs['text'])
    return _OldNotebookAdd(self,child,**kwargs)
ttk.Notebook.add=_rtl_notebook_add


def grams(value):
    return f"{unmicro(value):,.3f}"


def amount(value):
    return f'{unmicro(value or 0):,.2f}'


def decimal_plain(value, places=2):
    if value is None: return '—'
    return f'{dec(value).quantize(Decimal(10) ** -places, rounding=ROUND_HALF_UP):,.{places}f}'


def selected_id(combo_or_text):
    text = combo_or_text.get() if hasattr(combo_or_text, 'get') else str(combo_or_text)
    try: return int(text.partition(' | ')[0])
    except (ValueError, TypeError): raise ValueError('اختر عنصرًا من القائمة أولًا.')


def parse_date(text):
    try:
        value=date.fromisoformat(text.strip())
        if value.isoformat()!=text.strip(): raise ValueError()
        return text.strip()
    except (ValueError, TypeError): raise ValueError('صيغة التاريخ المطلوبة: YYYY-MM-DD')


def positive_num(value, label, allow_zero=False):
    try: value=dec(value.strip() if isinstance(value,str) else value)
    except (InvalidOperation, ValueError): raise ValueError(f'أدخل رقمًا صالحًا في «{label}».')
    if value < 0 or (not allow_zero and value==0): raise ValueError(f'يجب أن تكون قيمة «{label}» {"صفرًا أو أكثر" if allow_zero else "أكبر من صفر"}.')
    return value


def safe_cell(text):
    """Avoid spreadsheet formula injection when CSV is opened in Excel."""
    txt = str(text)
    return "'" + txt if txt.lstrip().startswith(('=', '+', '-', '@')) and not txt.replace('-', '',1).replace('.', '',1).isdigit() else txt


class TabiaApp:
    def __init__(self, root:tk.Tk, db_path=DBFILE):
        self.root=root
        self.db_path=Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            starter=BASE/'TABIA_TECH.db'
            if starter.is_file(): shutil.copy2(starter,self.db_path)
            else:
                from TABIA_TECH_engine import create_blank_db
                create_blank_db(self.db_path)
        self.svc=TabiaDB(self.db_path)
        self.root.title('تعبئة تك | TABIA TECH — إدارة التعبئة والإنتاج')
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.geometry('{}x{}'.format(min(1350, max(900, screen_w - 40)),
                                           min(850, max(570, screen_h - 75))))
        self.root.minsize(900,570)
        self.root.configure(bg=BG)
        self.root.protocol('WM_DELETE_WINDOW',self.on_close)
        self._configure_style()
        self.sidebar=tk.Frame(self.root,bg=NAVY,width=225)
        self.sidebar.pack(side='right',fill='y')
        self.sidebar.pack_propagate(False)
        self.main=tk.Frame(self.root,bg=BG)
        self.main.pack(side='left',fill='both',expand=True)
        self.title=tk.StringVar(value=visual_text('لوحة التحكم'))
        bar=tk.Frame(self.main,bg=WHITE,height=85)
        bar.pack(fill='x')
        bar.pack_propagate(False)
        tk.Label(bar,textvariable=self.title,bg=WHITE,fg=INK,font=('Segoe UI',19,'bold'),anchor='e').pack(side='right',padx=28,pady=20)
        tk.Label(bar,text='محلي  •  SQLite  •  YER',bg=WHITE,fg=MUTED,font=('Segoe UI',10)).pack(side='left',padx=30)
        self.content=tk.Frame(self.main,bg=BG)
        self.content.pack(fill='both',expand=True,padx=22,pady=18)
        tk.Label(self.sidebar,text='TABIA TECH',bg=NAVY,fg=WHITE,font=('Segoe UI',19,'bold')).pack(pady=(28,2))
        tk.Label(self.sidebar,text='تعبئة تك',bg=NAVY,fg='#AFD9EF',font=('Segoe UI',15,'bold')).pack(pady=(0,20))
        items=[('dashboard','لوحة التحكم','▣'),('materials','المواد الخام','▤'),
               ('purchases','المشتريات','▧'),('production','أوامر الإنتاج','▦'),
               ('workers','العمال والحسابات','▥'),('inventory','حركة المخزون وFIFO','◫'),
               ('reports','التقارير','▨'),('settings','العملات والأجور','⚙'),('audit','سجل التعديلات','◷')]
        self.nav_buttons={}
        for key,name,symbol in items:
            btn=tk.Button(self.sidebar,text=f'   {name}     {symbol}',font=('Segoe UI',11),fg='#D2E2F3',
                  bg=NAVY,activebackground='#244969',activeforeground=WHITE,relief='flat',bd=0,
                  anchor='e',padx=13,pady=11,cursor='hand2',command=lambda k=key:self.nav(k))
            btn.pack(fill='x',padx=10,pady=2)
            self.nav_buttons[key]=btn
        tk.Label(self.sidebar,text='الإصدار 1.0  •  يعمل دون إنترنت',bg=NAVY,fg='#91A8BB',font=('Segoe UI',9)).pack(side='bottom',pady=23)
        self.page=''
        self.nav('dashboard')

    def _configure_style(self):
        s=ttk.Style(self.root)
        if 'clam' in s.theme_names():s.theme_use('clam')
        s.configure('TLabel',background=BG,foreground=INK,font=('Segoe UI',10))
        s.configure('TEntry',padding=7,font=('Segoe UI',10))
        s.configure('TCombobox',padding=6,font=('Segoe UI',10))
        s.configure('TButton',padding=(12,9),font=('Segoe UI',10,'bold'))
        s.configure('Accent.TButton',background=BLUE,foreground=WHITE)
        s.map('Accent.TButton',background=[('active','#0C54A6')])
        s.configure('Good.TButton',background=GREEN,foreground=WHITE)
        s.configure('Treeview',font=('Segoe UI',10),rowheight=30,background=WHITE,fieldbackground=WHITE,foreground=INK)
        s.configure('Treeview.Heading',font=('Segoe UI',10,'bold'),background='#DFEAF6',foreground=NAVY)
        s.map('Treeview',background=[('selected',BLUE)],foreground=[('selected',WHITE)])
        s.configure('TNotebook',background=BG,borderwidth=0)
        s.configure('TNotebook.Tab',padding=(17,10),font=('Segoe UI',10,'bold'))

    def nav(self,page):
        self.page=page
        labels={'dashboard':'لوحة التحكم','materials':'المواد الخام','purchases':'المشتريات',
                'production':'أوامر التعبئة والإنتاج','workers':'العمال وكشوف الحساب',
                'inventory':'حركة المواد وتتبع FIFO','reports':'التقارير والتصدير',
                'settings':'الإعدادات والعملات والتعرفة','audit':'سجل التعديلات'}
        self.title.set(visual_text(labels[page]))
        for key,b in self.nav_buttons.items(): b.configure(bg=('#28517D' if key==page else NAVY),fg=WHITE if key==page else '#D2E2F3')
        for ch in self.content.winfo_children():ch.destroy()
        getattr(self,f'page_{page}')()

    def card(self,parent,**kw):
        f=tk.Frame(parent,bg=WHITE,highlightbackground='#DCE6F1',highlightthickness=1,**kw)
        return f

    def headline(self,parent,text,sub=''):
        tk.Label(parent,text=text,font=('Segoe UI',14,'bold'),fg=INK,bg=WHITE,anchor='e').pack(fill='x',padx=15,pady=(14,3))
        if sub:tk.Label(parent,text=sub,fg=MUTED,bg=WHITE,font=('Segoe UI',9),anchor='e',justify='right',wraplength=720).pack(fill='x',padx=15,pady=(0,12))

    def label(self,parent,text,grid=None):
        l=tk.Label(parent,text=text,bg=WHITE,fg=MUTED,font=('Segoe UI',10),anchor='e')
        if grid is not None:l.grid(row=grid[0],column=grid[1],sticky='e',padx=7,pady=(7,2))
        else:l.pack(anchor='e')
        return l

    def field(self,parent,title,row,col,default='',width=20):
        self.label(parent,title,(row*2,col))
        v=tk.StringVar(value=str(default))
        e=ttk.Entry(parent,textvariable=v,width=width,justify='right')
        e.grid(row=row*2+1,column=col,sticky='ew',padx=7,pady=(0,7))
        parent.columnconfigure(col,weight=1)
        return v

    def combo(self,parent,title,row,col,items=None,width=20):
        self.label(parent,title,(row*2,col))
        v=tk.StringVar()
        w=ArabicCombo(parent,textvariable=v,values=items or [],state='readonly',justify='right',width=width)
        w._value_var=v  # retain Tk variable after method returns
        w.grid(row=row*2+1,column=col,sticky='ew',padx=7,pady=(0,7))
        parent.columnconfigure(col,weight=1)
        if items:w.current(0)
        return w

    def button(self,parent,text,command,kind='regular',side='right'):
        style='Accent.TButton' if kind=='accent' else 'Good.TButton' if kind=='good' else 'TButton'
        b=ttk.Button(parent,text=visual_text(text),command=command,style=style)
        if side:b.pack(side=side,padx=5,pady=9)
        return b

    def table(self,parent,columns,heights=12):
        """columns: sequence of (column key, localized heading, width)."""
        outer=ttk.Frame(parent)
        outer.pack(fill='both',expand=True,padx=13,pady=12)
        keys=[c[0] for c in columns]
        tv=ttk.Treeview(outer,columns=keys,show='headings',height=heights,selectmode='browse')
        for key,title,width in columns:
            tv.heading(key,text=visual_text(title),anchor='e')
            tv.column(key,width=width,minwidth=70,anchor='e',stretch=True)
        sy=ttk.Scrollbar(outer,orient='vertical',command=tv.yview)
        sx=ttk.Scrollbar(outer,orient='horizontal',command=tv.xview)
        tv.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        tv.grid(row=0,column=0,sticky='nsew')
        sy.grid(row=0,column=1,sticky='ns')
        sx.grid(row=1,column=0,sticky='ew')
        outer.columnconfigure(0,weight=1);outer.rowconfigure(0,weight=1)
        tv.tag_configure('warn',background='#FFF2E7',foreground='#9B4025')
        tv.tag_configure('ok',background='#EAFBF4')
        return tv

    def populate(self,tv,items):
        tv.delete(*tv.get_children())
        for item in items:
            if len(item)==3:iid,values,tags=item
            else:iid,values=item;tags=()
            tv.insert('', 'end',iid=str(iid),values=tuple(visual_text(x) for x in values),tags=tags)

    def current_selection(self,tv):
        chosen=tv.selection()
        if not chosen:raise ValueError('حدد سجلًا من الجدول أولًا.')
        return int(chosen[0])

    def run(self,fn,success='تم حفظ العملية بنجاح.',refresh=True):
        try:
            result=fn()
            if success: messagebox.showinfo('تعبئة تك',success,parent=self.root)
            if refresh:self.nav(self.page)
            return result
        except (ValueError,InvalidOperation,sqlite3.Error,AssertionError,OverflowError,TypeError) as e:
            messagebox.showerror('تعذّر تنفيذ العملية',str(e),parent=self.root)
            return None

    def sql(self,query,args=()):
        return self.svc.db.execute(query,args).fetchall()

    def options(self,table,where='1=1',name='name'):
        return [f"{r['id']} | {r['label']}" for r in self.sql(f'SELECT id,{name} AS label FROM {table} WHERE {where} ORDER BY id DESC')]

    def materials_options(self):
        return [f"{r['id']} | {r['code']} - {r['name']}" for r in self.sql('SELECT id,code,name FROM raw_materials WHERE is_active=1 ORDER BY name')]

    def workers_options(self):
        return [f"{r['id']} | {r['code']} - {r['name']}" for r in self.sql('SELECT id,code,name FROM workers WHERE is_active=1 ORDER BY name')]

    def material_units(self,material_id):
        return [f"{r['slot']} | {r['name']} (×{r['factor_to_gram_decimal']} جرام)" for r in self.sql('SELECT slot,name,factor_to_gram_decimal FROM material_units WHERE material_id=? ORDER BY slot',(material_id,))]

    def page_dashboard(self):
        top=tk.Frame(self.content,bg=BG);top.pack(fill='x')
        n=self.sql('SELECT COUNT(*) n FROM raw_materials')[0]['n']
        p=self.sql('SELECT COUNT(*) n FROM purchase_invoices')[0]['n']
        o=self.sql("SELECT COUNT(*) n FROM production_orders WHERE status='POSTED'")[0]['n']
        w=self.sql('SELECT COUNT(*) n FROM workers')[0]['n']
        kpis=[('المواد الخام',n),('فواتير المشتريات',p),('أوامر معتمدة',o),('العمال',w)]
        for title,value in kpis:
            box=self.card(top);box.pack(side='right',fill='x',expand=True,padx=5,pady=5)
            tk.Label(box,text=title,bg=WHITE,fg=MUTED,font=('Segoe UI',10)).pack(anchor='e',padx=15,pady=(13,2))
            tk.Label(box,text=str(value),bg=WHITE,fg=BLUE,font=('Segoe UI',26,'bold')).pack(anchor='e',padx=15,pady=(0,15))
        warnings=self.card(self.content);warnings.pack(fill='x',pady=12)
        negatives=self.sql('SELECT name,balance_micrograms FROM v_material_stock WHERE balance_micrograms<0')
        shortages=self.sql('SELECT order_number,remaining_uncovered_micrograms FROM v_fifo_pending_shortages')
        tk.Label(warnings,text=f'تنبيهات المخزون: {len(negatives)} مادة سالبة  •  {len(shortages)} عجز FIFO مؤقت',
                 bg=WHITE,fg=WARN if negatives or shortages else GREEN,font=('Segoe UI',13,'bold'),anchor='e').pack(fill='x',padx=16,pady=(15,5))
        if negatives:
            tk.Label(warnings,text='، '.join(f"{r['name']}: {grams(r['balance_micrograms'])} جرام" for r in negatives[:6]),
                     fg=WARN,bg=WHITE,anchor='e',font=('Segoe UI',10)).pack(fill='x',padx=16,pady=(0,15))
        else:tk.Label(warnings,text='لا يوجد رصيد خام سالب حاليًا.',fg=MUTED,bg=WHITE,anchor='e').pack(fill='x',padx=16,pady=(0,15))
        rec=self.card(self.content);rec.pack(fill='both',expand=True,pady=5)
        self.headline(rec,'آخر أوامر الإنتاج','لا يتم تخزين المنتجات الجاهزة في المخزون؛ تفاصيلها داخل أوامر الإنتاج فقط.')
        tree=self.table(rec,[('no','الأمر',140),('day','التاريخ',120),('material','المادة',220),('state','الحالة',130),('cost','إجمالي التكلفة (ر.ي)',180)],8)
        rows=self.sql('''SELECT o.id,o.order_number,o.order_date,m.name material,o.status,v.total_cost_micro_local
           FROM production_orders o JOIN raw_materials m ON o.material_id=m.id
           JOIN production_versions v ON v.id=o.current_version_id ORDER BY o.id DESC LIMIT 15''')
        self.populate(tree,[(r['id'],(r['order_number'],r['order_date'],r['material'],self.status(r['status']), amount(r['total_cost_micro_local']) if r['status']=='POSTED' else '—'),('warn',) if r['status']=='CANCELED' else ()) for r in rows])

    def status(self,v):
        return {'DRAFT':'مسودة','POSTED':'معتمد','CANCELED':'ملغى'}.get(v,v)

    def page_materials(self):
        form=self.card(self.content);form.pack(fill='x',pady=(0,12))
        self.headline(form,'إضافة مادة خام','كل مادة لها ثلاث وحدات، ومعامل كل وحدة محسوب بالجرامات. الأولى هي وحدة الأساس (1 جرام).')
        f=tk.Frame(form,bg=WHITE);f.pack(fill='x',padx=15,pady=6)
        code=self.field(f,'رمز المادة',0,4);name=self.field(f,'اسم المادة',0,3);waste=self.field(f,'حد الفاقد %',0,2,'5')
        u2=self.field(f,'اسم الوحدة الثانية',1,4,'كيلوجرام');fact2=self.field(f,'جرامات الوحدة الثانية',1,3,'1000')
        u3=self.field(f,'اسم الوحدة الثالثة',1,2,'كيس');fact3=self.field(f,'جرامات الوحدة الثالثة',1,1,'25000')
        btnbar=tk.Frame(form,bg=WHITE);btnbar.pack(fill='x',padx=12)
        def save():
            if not code.get().strip() or not name.get().strip():raise ValueError('أدخل رمز المادة واسمها.')
            if not u2.get().strip() or not u3.get().strip():raise ValueError('أدخل اسم الوحدتين الثانية والثالثة.')
            return self.svc.add_material(code.get().strip(),name.get().strip(),
              [('جرام',1),(u2.get().strip(),positive_num(fact2.get(),'معامل الوحدة الثانية')),
               (u3.get().strip(),positive_num(fact3.get(),'معامل الوحدة الثالثة'))],
               positive_num(waste.get(),'حد الفاقد',True))
        self.button(btnbar,'حفظ المادة',lambda:self.run(save),'accent')
        self.button(btnbar,'تعديل بيانات المادة',lambda:self.run(lambda:self.open_edit_material(self.current_selection(tv)),success=None,refresh=False))
        self.button(btnbar,'تعديل وحدة المادة المحددة',lambda:self.run(lambda:self.open_edit_unit(self.current_selection(tv)),success=None,refresh=False))
        listing=self.card(self.content);listing.pack(fill='both',expand=True)
        self.headline(listing,'أرصدة المواد الخام وأسعار آخر شراء')
        tv=self.table(listing,[('code','الرمز',110),('material','المادة',190),('balance','الرصيد بالجرام',150),('price','آخر سعر/جرام',180),('value','قيمة المخزون (ر.ي)',200),('loss','حد الفاقد %',120)],11)
        rows=self.sql('''SELECT s.material_id,m.code,m.name,m.max_waste_ratio,s.balance_micrograms,p.price_local_per_gram_decimal
            FROM v_material_stock s JOIN raw_materials m ON m.id=s.material_id
            LEFT JOIN v_material_last_price p ON p.material_id=s.material_id ORDER BY m.name''')
        values=[]
        for r in rows:
            val=unmicro(r['balance_micrograms'])*dec(r['price_local_per_gram_decimal']) if r['price_local_per_gram_decimal'] is not None else None
            values.append((r['material_id'],(r['code'],r['name'],grams(r['balance_micrograms']),
                decimal_plain(r['price_local_per_gram_decimal'],4),decimal_plain(val),r['max_waste_ratio']),
                ('warn',) if r['balance_micrograms']<0 else ()))
        self.populate(tv,values)

    def open_edit_material(self,mid):
        row=self.svc.one('SELECT * FROM raw_materials WHERE id=?',(mid,))
        d=self.dialog('تعديل بيانات المادة الخام',570,355)
        fields=tk.Frame(d.body,bg=WHITE);fields.pack(fill='x')
        code=self.field(fields,'الرمز',0,0,row['code'])
        name=self.field(fields,'الاسم',1,0,row['name'])
        ratio=self.field(fields,'حد الفاقد %',2,0,row['max_waste_ratio'])
        def commit():
            self.svc.update_material(mid,code.get().strip(),name.get().strip(),positive_num(ratio.get(),'حد الفاقد',True))
            d.destroy();self.nav('materials')
        self.button(d.body,'حفظ البيانات',lambda:self.run(commit,refresh=False),'accent')

    def open_edit_unit(self,mid):
        records=self.sql('SELECT slot,name,factor_to_gram_decimal FROM material_units WHERE material_id=? ORDER BY slot',(mid,))
        dlg=self.dialog('تعديل وحدة مادة خام',540,330)
        self.label(dlg.body,'يبقى معامل التحويل في الفواتير القديمة محفوظًا كما كان.')
        fields=tk.Frame(dlg.body,bg=WHITE);fields.pack(fill='x')
        unit=self.combo(fields,'الوحدة',0,0,[f"{r['slot']} | {r['name']}" for r in records]);nm=self.field(fields,'اسم الوحدة الجديد',1,0)
        factor=self.field(fields,'جرامات الوحدة الجديدة',2,0)
        def changed(*_):
            row=next((r for r in records if r['slot']==selected_id(unit)),None)
            if row:nm.set(row['name']);factor.set(row['factor_to_gram_decimal'])
        unit.bind('<<ComboboxSelected>>',changed);changed()
        def commit():
            self.svc.update_material_unit(mid,selected_id(unit),nm.get().strip(),positive_num(factor.get(),'معامل التحويل'))
            dlg.destroy();self.nav('materials')
        self.button(dlg.body,'حفظ تعديل الوحدة',lambda:self.run(commit,refresh=False),'accent')

    def page_purchases(self):
        form=self.card(self.content);form.pack(fill='x',pady=(0,12))
        self.headline(form,'تسجيل فاتورة شراء','السعر المدخل نهائي وشامل مصاريف الشراء. يضاف الرصيد ويعاد توزيع FIFO تلقائيًا.')
        f=tk.Frame(form,bg=WHITE);f.pack(fill='x',padx=16)
        ino=self.field(f,'رقم الفاتورة',0,5);day=self.field(f,'تاريخ الفاتورة',0,4,TODAY)
        material=self.combo(f,'المادة الخام',0,3,self.materials_options())
        unit=self.combo(f,'وحدة الشراء',0,2)
        qty=self.field(f,'الكمية',1,5);total=self.field(f,'المبلغ النهائي',1,4)
        currencies=[r['code'] for r in self.sql('SELECT code FROM currencies WHERE is_active=1 ORDER BY is_local DESC,code')]
        currency=self.combo(f,'العملة',1,3,currencies)
        fx=self.field(f,'سعر الصرف (اختياري)',1,2)
        hint=tk.Label(form,text='اترك سعر الصرف فارغًا لاستخدام سعر العملة المسجل بتاريخ الفاتورة. العملة المحلية = 1.',bg=WHITE,fg=MUTED,anchor='e',font=('Segoe UI',9))
        hint.pack(fill='x',padx=17)
        def set_units(*_):
            try:unit.configure(values=self.material_units(selected_id(material)));unit.current(0)
            except ValueError:unit.configure(values=[]);unit.set('')
        material.bind('<<ComboboxSelected>>',set_units);set_units()
        buttons=tk.Frame(form,bg=WHITE);buttons.pack(fill='x',padx=15)
        def save():
            if not ino.get().strip():raise ValueError('أدخل رقم الفاتورة.')
            return self.svc.purchase(ino.get().strip(),parse_date(day.get()),selected_id(material),
                     positive_num(qty.get(),'كمية الشراء'),selected_id(unit),positive_num(total.get(),'المبلغ النهائي',True),
                     currency.get(),positive_num(fx.get(),'سعر الصرف') if fx.get().strip() else None)
        self.button(buttons,'حفظ فاتورة الشراء',lambda:self.run(save),'accent')
        listing=self.card(self.content);listing.pack(fill='both',expand=True)
        self.headline(listing,'سجل المشتريات','تعديل كمية فاتورة مستخدمة ممكن؛ تغيير سعر فاتورة سبق استهلاكها ممنوع.')
        controls=tk.Frame(listing,bg=WHITE);controls.pack(fill='x',padx=15)
        self.button(controls,'تعديل الفاتورة المحددة',lambda:self.open_edit_purchase(self.current_selection(tv)))
        tv=self.table(listing,[('id','المعرف',80),('no','الفاتورة',140),('date','التاريخ',115),('material','المادة',180),('qty','كمية جرام',160),('total','المبلغ المحلي',185),('fx','الصرف',90)],10)
        rows=self.sql('''SELECT p.id,p.invoice_number,p.purchase_date,m.name,p.quantity_micrograms,
                p.final_amount_micro_local,p.fx_rate_snapshot_decimal FROM purchase_invoices p
                JOIN raw_materials m ON m.id=p.material_id ORDER BY p.id DESC''')
        self.populate(tv,[(r['id'],(r['id'],r['invoice_number'],r['purchase_date'],r['name'],grams(r['quantity_micrograms']),amount(r['final_amount_micro_local']),r['fx_rate_snapshot_decimal'])) for r in rows])

    def dialog(self,title,width=620,height=440):
        d=tk.Toplevel(self.root)
        d.title(title);d.geometry(f'{width}x{height}');d.configure(bg=BG)
        d.transient(self.root);d.grab_set()
        frame=self.card(d);frame.pack(fill='both',expand=True,padx=15,pady=15)
        self.headline(frame,title)
        d.body=tk.Frame(frame,bg=WHITE)
        d.body.pack(fill='both',expand=True,padx=16,pady=8)
        return d

    def open_edit_purchase(self,pid):
        r=self.svc.one('''SELECT p.*,u.name unit_name FROM purchase_invoices p JOIN material_units u ON u.id=p.unit_id WHERE p.id=?''',(pid,))
        d=self.dialog(f"تعديل الفاتورة {r['invoice_number']}",590,340)
        self.label(d.body,'يُعاد احتساب سعر الوحدة تلقائيًا عند تعديل الكمية. يمنع تغيير مبلغ فاتورة مستهلكة.')
        fields=tk.Frame(d.body,bg=WHITE);fields.pack(fill='x')
        quantity=self.field(fields,f"الكمية ({r['unit_name']})",0,0,r['entered_quantity_decimal'])
        cost=self.field(fields,'المبلغ النهائي بعملة الشراء',1,0,str(unmicro(r['final_amount_micro_currency'])))
        def save():
            newqty=positive_num(quantity.get(),'كمية الفاتورة')
            newamount=positive_num(cost.get(),'مبلغ الفاتورة',True)
            self.svc.update_purchase(pid,quantity=newqty,total_amount=newamount)
            d.destroy();self.nav('purchases')
        self.button(d.body,'تطبيق التعديل',lambda:self.run(save,refresh=False),'accent')

    def package_editor(self,parent,initial=None):
        """Editable package counts & expense values; returns collector callable."""
        initial=initial or {}
        frame=tk.Frame(parent,bg=WHITE);frame.pack(fill='x',padx=15,pady=6)
        tk.Label(frame,text='أعداد العبوات حسب الوزن',bg=WHITE,fg=INK,font=('Segoe UI',11,'bold'),anchor='e').pack(fill='x',pady=(5,8))
        rows=tk.Frame(frame,bg=WHITE);rows.pack(fill='x')
        sizes=self.sql('SELECT id,label,weight_micrograms FROM packaging_sizes WHERE is_active=1 ORDER BY weight_micrograms DESC')
        counts={}
        for i,s in enumerate(sizes):
            row=tk.Frame(rows,bg=WHITE);row.pack(side='right',padx=8,pady=2)
            tk.Label(row,text=s['label'],bg=WHITE,fg=INK).pack(anchor='e')
            value=tk.StringVar(value=str(initial.get('packages',{}).get(s['id'],0)))
            ttk.Entry(row,textvariable=value,width=12,justify='right').pack()
            counts[s['id']]=value
        tk.Label(frame,text='المصاريف المشتركة (ريال يمني)',bg=WHITE,fg=INK,font=('Segoe UI',11,'bold'),anchor='e').pack(fill='x',pady=(14,6))
        exp_box=tk.Frame(frame,bg=WHITE);exp_box.pack(fill='x')
        expenses={}
        for c in self.sql('SELECT id,name FROM expense_categories WHERE is_active=1 ORDER BY id'):
            row=tk.Frame(exp_box,bg=WHITE);row.pack(side='right',padx=9)
            tk.Label(row,text=c['name'],bg=WHITE,fg=INK).pack(anchor='e')
            value=tk.StringVar(value=str(initial.get('expenses',{}).get(c['id'],0)))
            ttk.Entry(row,textvariable=value,width=14,justify='right').pack()
            expenses[c['id']]=value
        def collect():
            packages=[];costs=[]
            for sid,var in counts.items():
                val=positive_num(var.get() or '0','عدد العبوات',True)
                if val != val.to_integral_value():raise ValueError('عدد العبوات يجب أن يكون عددًا صحيحًا.')
                if val>0:packages.append((sid,int(val)))
            if not packages:raise ValueError('أدخل عددًا موجبًا لعبوة واحدة على الأقل.')
            for cid,var in expenses.items():
                val=positive_num(var.get() or '0','المصاريف',True)
                if val:costs.append((cid,val))
            return packages,costs
        return collect

    def page_production(self):
        book=ttk.Notebook(self.content);book.pack(fill='both',expand=True)
        new=tk.Frame(book,bg=BG);lst=tk.Frame(book,bg=BG);book.add(new,text='أمر إنتاج جديد');book.add(lst,text='أوامر الإنتاج والمتابعة')
        form=self.card(new);form.pack(fill='x',pady=5)
        self.headline(form,'إعداد أمر إنتاج','المسودة لا تخصم المخزون؛ عند الاعتماد تحفظ لقطة سعر الخام وأجور التعبئة.')
        f=tk.Frame(form,bg=WHITE);f.pack(fill='x',padx=16)
        number=self.field(f,'رقم الأمر',0,4);day=self.field(f,'التاريخ',0,3,TODAY)
        material=self.combo(f,'المادة الخام',0,2,self.materials_options())
        worker=self.combo(f,'العامل',0,1,self.workers_options())
        qty=self.field(f,'وزن الخام الداخل',1,4)
        unit=self.combo(f,'وحدة الوزن الداخل',1,3)
        def set_units(*_):
            try:unit.configure(values=self.material_units(selected_id(material)));unit.current(0)
            except ValueError:unit.configure(values=[]);unit.set('')
        material.bind('<<ComboboxSelected>>',set_units);set_units()
        collect=self.package_editor(form)
        buttons=tk.Frame(form,bg=WHITE);buttons.pack(fill='x',padx=15,pady=7)
        def create():
            lines,expenses=collect()
            if not number.get().strip():raise ValueError('أدخل رقم الأمر.')
            return self.svc.create_draft(number.get().strip(),parse_date(day.get()),
                 selected_id(material),selected_id(worker),positive_num(qty.get(),'وزن الخام'),
                 selected_id(unit),lines,expenses)
        self.button(buttons,'حفظ الأمر كمسودة',lambda:self.run(create,'تم تسجيل المسودة. افتح تبويب المتابعة لاعتمادها.'),'accent')
        hint=self.card(new);hint.pack(fill='x',pady=12)
        self.headline(hint,'تعليمات مهمة','قبل الاعتماد: عرّف المادة والعامل وسعر شراء المادة والتعرفة لكل وزن عبوة مستخدم. '
            'نقص المخزون أو تجاوز الفاقد يظهر كتحذير ولا يمنع الاعتماد؛ لا يتم إنشاء مخزون للعبوات الناتجة.')
        order_card=self.card(lst);order_card.pack(fill='both',expand=True,pady=(0,10))
        self.headline(order_card,'سجل أوامر الإنتاج','حدد أمرًا ثم اعتمده، أو عدّل أمرًا معتمدًا، أو ألغِه بحركات عكسية محفوظة.')
        bar=tk.Frame(order_card,bg=WHITE);bar.pack(fill='x',padx=13)
        self.button(bar,'اعتماد المسودة',lambda:self.approve_selected(self.current_selection(tv)),'good')
        self.button(bar,'تعديل أمر معتمد',lambda:self.open_edit_order(self.current_selection(tv)))
        self.button(bar,'إلغاء أمر معتمد',lambda:self.cancel_selected(self.current_selection(tv)))
        self.button(bar,'عرض تفاصيل التكاليف',lambda:self.show_cost_detail(self.current_selection(tv)))
        tv=self.table(order_card,[('no','الأمر',130),('date','التاريخ',105),('material','المادة',175),('worker','العامل',135),
                    ('status','الحالة',90),('input','مدخل (جرام)',140),('output','مخرج (جرام)',140),('total','التكلفة (ر.ي)',165)],12)
        rows=self.sql('''SELECT o.id,o.order_number,o.order_date,m.name material,w.name worker,o.status,
              v.input_quantity_micrograms,v.output_weight_micrograms,v.total_cost_micro_local
              FROM production_orders o JOIN production_versions v ON v.id=o.current_version_id
              JOIN raw_materials m ON m.id=o.material_id JOIN workers w ON w.id=o.worker_id ORDER BY o.id DESC''')
        self.populate(tv,[(r['id'],(r['order_number'],r['order_date'],r['material'],r['worker'],self.status(r['status']),
            grams(r['input_quantity_micrograms']),grams(r['output_weight_micrograms']),
            amount(r['total_cost_micro_local']) if r['status']=='POSTED' else '—'),('warn',) if r['status']=='CANCELED' else ()) for r in rows])
        tv.bind('<Double-1>',lambda e: self.run(lambda:self.show_cost_detail(self.current_selection(tv)),success=None,refresh=False))

    def approve_selected(self,order_id):
        if not messagebox.askyesno('اعتماد أمر','سيُخصم كامل الخام ويُثبت استحقاق العامل. هل تعتمد الأمر؟',parent=self.root):return
        def do():
            v=self.svc.approve(order_id)
            warnings=self.svc.one('SELECT warning_flags_json FROM production_versions WHERE id=?',(v,))['warning_flags_json']
            if warnings and warnings!='[]':messagebox.showwarning('تنبيهات الاعتماد',self.warning_text(warnings),parent=self.root)
            return v
        self.run(do,'تم اعتماد الأمر وترحيل المخزون وأجر العامل.')

    @staticmethod
    def warning_text(warnings):
        names={'NEGATIVE_INVENTORY':'المخزون أصبح سالبًا','WASTE_LIMIT_EXCEEDED':'الفاقد تجاوز الحد المسموح',
               'OUTPUT_EXCEEDS_INPUT':'أوزان المخرجات أكبر من المدخلات'}
        import json
        try:return '\n'.join('• '+names.get(x,x) for x in json.loads(warnings))
        except Exception:return str(warnings)

    def open_edit_order(self,order_id):
        o=self.svc.one('SELECT * FROM production_orders WHERE id=? AND status="POSTED"',(order_id,))
        ver=self.svc.one('SELECT * FROM production_versions WHERE id=?',(o['current_version_id'],))
        p={r['packaging_size_id']:r['package_count'] for r in self.sql('SELECT packaging_size_id,package_count FROM production_packaging_lines WHERE version_id=?',(ver['id'],))}
        costs={r['expense_category_id']:str(unmicro(r['amount_micro_local'])) for r in self.sql('SELECT expense_category_id,amount_micro_local FROM production_expense_lines WHERE version_id=?',(ver['id'],))}
        d=self.dialog('تعديل أمر معتمد — لقطات الأسعار ثابتة',850,600)
        self.label(d.body,'سعر الخام وتعرفة العبوات كما كانا عند الاعتماد الأصلي. تعديل الخام يؤدي لتسوية الأثر لا إلى تكرار الخصم.')
        top=tk.Frame(d.body,bg=WHITE);top.pack(fill='x')
        weight=self.field(top,'الخام الداخل (جرام)',0,3,str(unmicro(ver['input_quantity_micrograms'])))
        unit=self.combo(top,'الوحدة',0,2,self.material_units(o['material_id']))
        unit.current(0)
        worker=self.combo(top,'العامل',0,1,self.workers_options())
        for i,it in enumerate(worker['values']):
            if selected_id(it)==o['worker_id']:worker.current(i);break
        collect=self.package_editor(d.body,{'packages':p,'expenses':costs})
        def commit():
            packages,expenses=collect()
            v=self.svc.edit_order(order_id,positive_num(weight.get(),'وزن الخام'),selected_id(unit),
                                   packages,expenses,worker_id=selected_id(worker))
            warnings=self.svc.one('SELECT warning_flags_json FROM production_versions WHERE id=?',(v,))['warning_flags_json']
            d.destroy();self.nav('production')
            if warnings!='[]':messagebox.showwarning('تحذيرات بعد التعديل',self.warning_text(warnings),parent=self.root)
        self.button(d.body,'حفظ التعديل وترحيل الفروقات',lambda:self.run(commit,refresh=False),'accent')

    def cancel_selected(self,order_id):
        if not messagebox.askyesno('تأكيد الإلغاء','يُعكس خام الإنتاج واستحقاق العامل فقط. الدفعات النقدية للعامل لن تُلغى. هل تتابع؟',parent=self.root):return
        self.run(lambda:self.svc.cancel_order(order_id),'تم إلغاء الأمر وتسجيل الحركات العكسية.')

    def show_cost_detail(self,order_id):
        o=self.svc.one('SELECT o.order_number,o.status,o.current_version_id FROM production_orders o WHERE o.id=?',(order_id,))
        v=self.svc.one('SELECT * FROM production_versions WHERE id=?',(o['current_version_id'],))
        if o['status']!='POSTED':
            messagebox.showinfo('تفاصيل الأمر','التكاليف النهائية تظهر بعد الاعتماد. المسودة/الملغى ليست تكلفة إنتاج نشطة.',parent=self.root)
            return
        d=self.dialog(f"تكلفة الأمر {o['order_number']}",910,565)
        summary=(f"تكلفة خام: {amount(v['raw_cost_micro_local'])}  |  مصاريف: {amount(v['shared_expenses_micro_local'])}  |  "
                 f"أجور: {amount(v['wages_micro_local'])}  |  الإجمالي: {amount(v['total_cost_micro_local'])} ر.ي")
        tk.Label(d.body,text=summary,bg=WHITE,fg=BLUE,font=('Segoe UI',12,'bold'),anchor='e').pack(fill='x',pady=8)
        tk.Label(d.body,text=f"المدخل: {grams(v['input_quantity_micrograms'])} جرام   |   الناتج: {grams(v['output_weight_micrograms'])} جرام   |   الفاقد: {grams(v['waste_micrograms'])} جرام",bg=WHITE,fg=INK,anchor='e').pack(fill='x',pady=6)
        tv=self.table(d.body,[('size','وزن العبوة',150),('count','العدد',90),('fee','أجرة العبوة',130),('unit','تكلفة العبوة',160),('line','الإجمالي',170)],8)
        rows=self.sql('''SELECT s.label,p.package_count,p.fee_per_pack_micro_local_snapshot,p.unit_cost_precise_decimal,p.line_total_micro_local
           FROM production_packaging_lines p JOIN packaging_sizes s ON p.packaging_size_id=s.id WHERE p.version_id=?''',(v['id'],))
        self.populate(tv,[(i,(r['label'],r['package_count'],amount(r['fee_per_pack_micro_local_snapshot']),
                 decimal_plain(r['unit_cost_precise_decimal']),amount(r['line_total_micro_local']))) for i,r in enumerate(rows)])
        if v['warning_flags_json']!='[]':
            tk.Label(d.body,text=self.warning_text(v['warning_flags_json']),bg=WHITE,fg=WARN,anchor='e').pack(fill='x',pady=6)

    def page_workers(self):
        tabs=ttk.Notebook(self.content);tabs.pack(fill='both',expand=True)
        management=tk.Frame(tabs,bg=BG);ledger=tk.Frame(tabs,bg=BG)
        tabs.add(management,text='العمال وصرف الأجور');tabs.add(ledger,text='كشف حساب عامل')
        form=self.card(management);form.pack(fill='x',pady=(0,12))
        self.headline(form,'إضافة عامل')
        f=tk.Frame(form,bg=WHITE);f.pack(fill='x',padx=12)
        code=self.field(f,'رمز العامل',0,3);name=self.field(f,'اسم العامل',0,2);contact=self.field(f,'هاتف / تواصل (اختياري)',0,1)
        b=tk.Frame(form,bg=WHITE);b.pack(fill='x',padx=12)
        self.button(b,'حفظ العامل',lambda:self.run(lambda:self.svc.add_worker(code.get().strip(),name.get().strip(),contact.get().strip() or None)),'accent')
        pay=self.card(management);pay.pack(fill='x',pady=(0,12))
        self.headline(pay,'صرف أجرة أو سلفة','الصرف لا يدخل في تكلفة الإنتاج مرة أخرى. يمكن أن يصبح حساب العامل سالبًا.')
        f2=tk.Frame(pay,bg=WHITE);f2.pack(fill='x',padx=13)
        worker=self.combo(f2,'العامل',0,4,self.workers_options());dt=self.field(f2,'تاريخ الصرف',0,3,TODAY)
        val=self.field(f2,'المبلغ (ريال يمني)',0,2)
        kind=self.combo(f2,'نوع الصرف',0,1,['PAYMENT | دفعة أجرة','ADVANCE | سلفة'])
        ref=self.field(f2,'رقم المرجع',1,4)
        buttons=tk.Frame(pay,bg=WHITE);buttons.pack(fill='x',padx=13)
        def pay_save():
            return self.svc.worker_payment(selected_id(worker),parse_date(dt.get()),positive_num(val.get(),'المبلغ'),
                         kind.get().split(' | ')[0],ref.get().strip() or None)
        self.button(buttons,'تسجيل الصرف',lambda:self.run(pay_save),'accent')
        self.button(buttons,'إضافة رصيد افتتاحي/تسوية',self.open_worker_adjustment)
        lst=self.card(management);lst.pack(fill='both',expand=True)
        self.headline(lst,'العمال والأرصدة الحالية')
        tv=self.table(lst,[('id','المعرف',70),('code','رمز',120),('name','العامل',220),('contact','تواصل',180),('balance','الرصيد (ر.ي)',180)],7)
        rows=self.sql('''SELECT w.*,COALESCE((SELECT SUM(l.signed_amount_micro_local) FROM worker_ledger l WHERE l.worker_id=w.id),0) bal
                        FROM workers w ORDER BY w.id DESC''')
        self.populate(tv,[(r['id'],(r['id'],r['code'],r['name'],r['contact'] or '',amount(r['bal'])),('warn',) if r['bal']<0 else ()) for r in rows])
        editbar=tk.Frame(lst,bg=WHITE);editbar.pack(fill='x',padx=12)
        self.button(editbar,'تعديل بيانات العامل المحدد',lambda:self.run(lambda:self.open_edit_worker(self.current_selection(tv)),success=None,refresh=False))
        sheet=self.card(ledger);sheet.pack(fill='both',expand=True)
        self.headline(sheet,'كشف حساب العامل','مستحق (+) / صرف وسلفة (−) مع الرصيد المتتابع، ويمكن التصدير من التقارير.')
        controls=tk.Frame(sheet,bg=WHITE);controls.pack(fill='x',padx=12,pady=6)
        selection=self.combo(controls,'اختر العامل',0,2,self.workers_options())
        tv2=self.table(sheet,[('date','تاريخ التسجيل',185),('type','نوع الحركة',180),('ref','المرجع',145),
                  ('earned','مستحق (+)',140),('paid','صرف (−)',140),('running','الرصيد (ر.ي)',160)],12)
        summary=tk.StringVar(value='اختر العامل لعرض كشف الحساب.')
        tk.Label(sheet,textvariable=summary,bg=WHITE,fg=BLUE,font=('Segoe UI',12,'bold'),anchor='e').pack(fill='x',padx=16,pady=10)
        def refresh_statement(*_):
            tv2.delete(*tv2.get_children())
            try:wid=selected_id(selection)
            except ValueError:return
            ss=self.svc.worker_statement(wid)
            trs=self.sql('SELECT * FROM v_worker_statement WHERE worker_id=? ORDER BY ledger_id',(wid,))
            self.populate(tv2,[(r['ledger_id'],(r['created_at_utc'][:19],self.ledger_kind(r['ledger_kind']),r['reference'] or '',
                    amount(r['signed_amount_micro_local']) if r['signed_amount_micro_local']>0 else '',
                    amount(-r['signed_amount_micro_local']) if r['signed_amount_micro_local']<0 else '',
                    amount(r['running_balance_micro_local'])),('warn',) if r['running_balance_micro_local']<0 else ()) for r in trs])
            summary.set(visual_text(f"الرصيد الافتتاحي: {ss['opening']}  |  الرصيد الحالي: {ss['closing']} ر.ي"))
        selection.bind('<<ComboboxSelected>>',refresh_statement);refresh_statement()

    def open_edit_worker(self,wid):
        old=self.svc.one('SELECT * FROM workers WHERE id=?',(wid,))
        d=self.dialog('تعديل بيانات العامل',560,375)
        form=tk.Frame(d.body,bg=WHITE);form.pack(fill='x')
        code=self.field(form,'رمز العامل',0,0,old['code'])
        name=self.field(form,'اسم العامل',1,0,old['name'])
        phone=self.field(form,'الهاتف',2,0,old['contact'] or '')
        def commit():
            self.svc.update_worker(wid,code.get().strip(),name.get().strip(),phone.get().strip() or None)
            d.destroy();self.nav('workers')
        self.button(d.body,'حفظ بيانات العامل',lambda:self.run(commit,refresh=False),'accent')

    @staticmethod
    def ledger_kind(kind):
        return {'OPENING':'رصيد افتتاحي','EARNED':'مستحق إنتاج','REVERSE_EARNED':'عكس مستحق',
             'PAYMENT':'دفعة أجور','ADVANCE':'سلفة','ADJUSTMENT':'تسوية'}.get(kind,kind)

    def open_worker_adjustment(self):
        d=self.dialog('تسوية أو رصيد افتتاحي',570,380)
        fields=tk.Frame(d.body,bg=WHITE);fields.pack(fill='x')
        worker=self.combo(fields,'العامل',0,0,self.workers_options())
        kind=self.combo(fields,'نوع القيد',1,0,['OPENING | رصيد افتتاحي','ADJUSTMENT | تسوية'])
        value=self.field(fields,'المبلغ بإشارته (+ مستحق / − صرف)',2,0)
        reference=self.field(fields,'المرجع',3,0)
        def commit():
            v=dec(value.get());
            if v==0:raise ValueError('يجب ألا تكون التسوية صفرًا.')
            self.svc.worker_adjustment(selected_id(worker),v,kind.get().split(' | ')[0],reference.get().strip() or None)
            d.destroy();self.nav('workers')
        self.button(d.body,'تسجيل التسوية',lambda:self.run(commit,refresh=False),'accent')

    def page_inventory(self):
        tabs=ttk.Notebook(self.content);tabs.pack(fill='both',expand=True)
        inventory=tk.Frame(tabs,bg=BG);movements=tk.Frame(tabs,bg=BG);fifo=tk.Frame(tabs,bg=BG)
        tabs.add(inventory,text='أرصدة المواد');tabs.add(movements,text='حركات المخزون');tabs.add(fifo,text='تتبع FIFO والعجز')
        card=self.card(inventory);card.pack(fill='both',expand=True)
        self.headline(card,'الأرصدة الفعلية','FIFO مخصص لتتبع الكميات فقط؛ التقييم مبني على سعر آخر شراء.')
        tv=self.table(card,[('code','الرمز',115),('name','المادة',210),('weight','الرصيد جرام',170),('price','آخر سعر/جرام',180),('valuation','التقييم المحلي',195)],13)
        rows=self.sql('SELECT * FROM v_inventory_valuation ORDER BY name')
        values=[]
        for r in rows:
            val=unmicro(r['balance_micrograms'])*dec(r['price_local_per_gram_decimal']) if r['price_local_per_gram_decimal'] else None
            values.append((r['material_id'],(r['code'],r['name'],grams(r['balance_micrograms']),
                decimal_plain(r['price_local_per_gram_decimal'],5),decimal_plain(val)),('warn',) if r['balance_micrograms']<0 else ()))
        self.populate(tv,values)
        card2=self.card(movements);card2.pack(fill='both',expand=True)
        self.headline(card2,'دفتر حركات الخام','سجل حركات غير قابل للحذف أو التعديل المباشر؛ التصحيحات تكون بحركات عكسية.')
        tv2=self.table(card2,[('date','التاريخ UTC',180),('material','المادة',185),('kind','نوع الحركة',185),('delta','فرق الكمية جرام',185)],13)
        rows=self.sql('''SELECT i.id,i.created_at_utc,m.name,i.movement_type,i.quantity_delta_micrograms FROM raw_inventory_movements i
              JOIN raw_materials m ON m.id=i.material_id ORDER BY i.id DESC LIMIT 500''')
        self.populate(tv2,[(r['id'],(r['created_at_utc'][:19],r['name'],r['movement_type'],grams(r['quantity_delta_micrograms'])),
                      ('warn',) if r['quantity_delta_micrograms']<0 else ()) for r in rows])
        top=self.card(fifo);top.pack(fill='both',expand=True,pady=(0,10))
        self.headline(top,'دفعات المشتريات ونسب الاستهلاك','المتبقي في الدفعة لا يمثل قيمة الإنتاج؛ التقييم يعتمد آخر شراء.')
        tv3=self.table(top,[('invoice','الفاتورة',160),('material','المادة',180),('bought','الكمية جرام',170),('spent','المخصصة FIFO',160),('left','المتبقية',170)],7)
        rows=self.sql('''SELECT p.*,m.name FROM v_fifo_lot_usage p JOIN raw_materials m ON p.material_id=m.id ORDER BY p.purchase_id DESC''')
        self.populate(tv3,[(r['purchase_id'],(r['invoice_number'],r['name'],grams(r['quantity_micrograms']),grams(r['allocated_micrograms']),grams(r['remaining_micrograms']))) for r in rows])
        bottom=self.card(fifo);bottom.pack(fill='both',expand=True)
        self.headline(bottom,'العجز المؤقت غير المغطى')
        tv4=self.table(bottom,[('order','أمر الإنتاج',190),('initial','العجز الأولي (جرام)',190),('left','العجز المتبقي (جرام)',190)],6)
        rows=self.sql('SELECT * FROM v_fifo_pending_shortages ORDER BY order_id')
        self.populate(tv4,[(i,(r['order_number'],grams(r['initial_uncovered_micrograms']),grams(r['remaining_uncovered_micrograms'])),('warn',)) for i,r in enumerate(rows)])

    def page_settings(self):
        tabs=ttk.Notebook(self.content);tabs.pack(fill='both',expand=True)
        fees=tk.Frame(tabs,bg=BG);currencies=tk.Frame(tabs,bg=BG);maintenance=tk.Frame(tabs,bg=BG)
        tabs.add(fees,text='تعرفة تعبئة العبوات');tabs.add(currencies,text='العملات والصرف');tabs.add(maintenance,text='نسخ احتياطي وسلامة القاعدة')
        box=self.card(fees);box.pack(fill='x',pady=(0,10))
        self.headline(box,'إضافة وزن عبوة (اختياري)')
        f=tk.Frame(box,bg=WHITE);f.pack(fill='x',padx=15)
        name=self.field(f,'اسم وزن العبوة',0,2);g=self.field(f,'وزنها بالجرام',0,1)
        self.button(box,'إضافة وزن',lambda:self.run(lambda:self.svc.add_packaging_size(name.get().strip(),positive_num(g.get(),'وزن العبوة'))),'accent')
        fee_box=self.card(fees);fee_box.pack(fill='x',pady=(0,10))
        self.headline(fee_box,'تحديد أجرة التعبئة لكل وزن','التعرفة سارية من التاريخ المحدد، بينما تبقى الأجور التاريخية للأوامر كما هي.')
        ff=tk.Frame(fee_box,bg=WHITE);ff.pack(fill='x',padx=15)
        size=self.combo(ff,'العبوة',0,3,self.options('packaging_sizes',name='label'))
        datev=self.field(ff,'تاريخ سريان التعرفة',0,2,TODAY)
        am=self.field(ff,'أجرة العبوة (ر.ي)',0,1)
        self.button(fee_box,'حفظ تعرفة جديدة',lambda:self.run(lambda:self.svc.set_packaging_fee(selected_id(size),parse_date(datev.get()),positive_num(am.get(),'الأجرة',True))),'accent')
        fees_list=self.card(fees);fees_list.pack(fill='both',expand=True)
        self.headline(fees_list,'التعرفة الحالية المسجلة')
        t=self.table(fees_list,[('size','العبوة',150),('from','السريان من',145),('fee','أجرة العبوة',180)],7)
        rs=self.sql('''SELECT s.id,s.label,h.effective_from,h.fee_micro_local FROM packaging_sizes s LEFT JOIN packaging_fee_history h
           ON h.id=(SELECT id FROM packaging_fee_history WHERE packaging_size_id=s.id AND effective_from<=? ORDER BY effective_from DESC LIMIT 1)
           ORDER BY s.weight_micrograms DESC''',(TODAY,))
        self.populate(t,[(r['id'],(r['label'],r['effective_from'] or 'لم تُحدد',amount(r['fee_micro_local']) if r['fee_micro_local'] is not None else '—')) for r in rs])
        c1=self.card(currencies);c1.pack(fill='x',pady=(0,10))
        self.headline(c1,'إضافة عملة')
        c=tk.Frame(c1,bg=WHITE);c.pack(fill='x',padx=15)
        code=self.field(c,'رمز العملة (SAR)',0,3);name=self.field(c,'اسم العملة',0,2);symbol=self.field(c,'الرمز المختصر',0,1)
        self.button(c1,'حفظ العملة',lambda:self.run(lambda:self.svc.add_currency(code.get().strip().upper(),name.get().strip(),symbol.get().strip())),'accent')
        c2=self.card(currencies);c2.pack(fill='x',pady=(0,10))
        self.headline(c2,'إدخال سعر صرف','عدد الريالات اليمنية مقابل وحدة واحدة من العملة الأجنبية.')
        f=tk.Frame(c2,bg=WHITE);f.pack(fill='x',padx=14)
        codes=[r['code'] for r in self.sql('SELECT code FROM currencies WHERE is_active=1 ORDER BY code')]
        cur=self.combo(f,'العملة',0,3,codes);fxdate=self.field(f,'تاريخ السريان',0,2,TODAY)
        rate=self.field(f,'السعر بالعملة المحلية',0,1)
        self.button(c2,'حفظ سعر الصرف',lambda:self.run(lambda:self.svc.set_exchange_rate(cur.get(),parse_date(fxdate.get()),positive_num(rate.get(),'سعر الصرف'))),'accent')
        c3=self.card(currencies);c3.pack(fill='both',expand=True)
        self.headline(c3,'أسعار الصرف المحفوظة')
        t=self.table(c3,[('code','الرمز',110),('name','العملة',190),('date','السريان',160),('rate','سعر الصرف',190)],7)
        rs=self.sql('''SELECT h.id,c.code,c.name,h.valid_from,h.rate_local_per_unit FROM exchange_rate_history h
         JOIN currencies c ON c.id=h.currency_id ORDER BY h.id DESC LIMIT 100''')
        self.populate(t,[(r['id'],(r['code'],r['name'],r['valid_from'],r['rate_local_per_unit'])) for r in rs])
        b=self.card(maintenance);b.pack(fill='x')
        self.headline(b,'سلامة البيانات والنسخ الاحتياطي','عند الإغلاق الطبيعي، ينشئ البرنامج نسخة احتياطية آمنة ويحتفظ بآخر 10 نسخ على الجهاز نفسه.')
        tk.Label(b,text=f'ملف التشغيل: {self.db_path}',bg=WHITE,fg=MUTED,anchor='e').pack(fill='x',padx=15,pady=10)
        actions=tk.Frame(b,bg=WHITE);actions.pack(fill='x',padx=15,pady=10)
        self.button(actions,'فحص سلامة القاعدة',self.verify_database)
        self.button(actions,'نسخة احتياطية الآن',lambda:self.run(lambda:self.svc.backup(BACKUPS),'تم إنشاء نسخة احتياطية والتحقق من سلامتها.',refresh=False),'good')
        self.button(actions,'اختبار استعادة نسخة',self.verify_backup)
        self.button(actions,'استعادة النسخة إلى قاعدة التشغيل',self.restore_backup)
        tk.Label(b,text='تنبيه: نسخ الجهاز نفسه لا تحمي من تلفه أو فقدانه. انسخ ملفات النسخ الاحتياطية دوريًا إلى وسيط خارجي.',bg=WHITE,fg=WARN,anchor='e',wraplength=800,justify='right').pack(fill='x',padx=15,pady=12)

    def verify_database(self):
        integrity=self.svc.db.execute('PRAGMA integrity_check').fetchone()[0]
        fks=self.svc.db.execute('PRAGMA foreign_key_check').fetchall()
        messagebox.showinfo('نتيجة فحص البيانات',f"فحص SQLite: {integrity}\nأخطاء المفاتيح الخارجية: {len(fks)}",parent=self.root)

    def verify_backup(self):
        path=filedialog.askopenfilename(title='اختر نسخة احتياطية للاختبار',filetypes=[('SQLite databases','*.db')],initialdir=str(BACKUPS),parent=self.root)
        if not path:return
        self.run(lambda: self.svc.test_restore(path) or (_ for _ in ()).throw(ValueError('النسخة غير سليمة')),
                 'نجح اختبار الاستعادة في قاعدة منفصلة؛ لم يتغير ملف التشغيل.',refresh=False)

    def restore_backup(self):
        path=filedialog.askopenfilename(title='اختر نسخة لاستعادة قاعدة التشغيل',filetypes=[('SQLite databases','*.db')],initialdir=str(BACKUPS),parent=self.root)
        if not path:return
        if not messagebox.askyesno('تنبيه الاستعادة','ستُستبدل بيانات العمل الحالية بمحتويات النسخة المختارة. سيُحفظ الوضع الحالي أولًا كنسخة احتياطية. هل أنت متأكد؟',parent=self.root):return
        temp_path=None
        try:
            # Backup current first; never use a raw file copy while SQLite connection is open.
            self.svc.backup(BACKUPS)
            fd,tmp=tempfile.mkstemp(prefix='tabia_restore_',suffix='.db',dir=self.db_path.parent)
            import os
            os.close(fd);temp_path=Path(tmp)
            with closing(connect_sqlite(path)) as source:
                with closing(connect_sqlite(temp_path)) as target:
                    source.backup(target)
            with closing(connect_sqlite(temp_path)) as check:
                if check.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('النسخة تالفة')
                if check.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('أخطاء علاقات في النسخة')
                if check.execute('SELECT COUNT(*) FROM schema_migrations').fetchone()[0]==0:raise ValueError('ليست قاعدة تعبئة تك مهيأة')
            self.svc.close()
            # DB has been closed and WAL checkpointed; atomic swap on same drive.
            os.replace(str(temp_path),str(self.db_path));temp_path=None
            self.svc=TabiaDB(self.db_path)
            self.nav('settings')
            messagebox.showinfo('نجاح الاستعادة','تمت الاستعادة، وفُتحت قاعدة التشغيل من النسخة المختارة.',parent=self.root)
        except Exception as exc:
            if temp_path:temp_path.unlink(missing_ok=True)
            try:self.svc.db.execute('SELECT 1')
            except Exception:self.svc=TabiaDB(self.db_path)
            messagebox.showerror('خطأ الاستعادة',str(exc),parent=self.root)

    def page_audit(self):
        card=self.card(self.content);card.pack(fill='both',expand=True)
        self.headline(card,'سجل التعديلات والعمليات','يوثق الحدث ومرجع العملية والقيم قبل وبعد؛ القراءة فقط.')
        t=self.table(card,[('date','التوقيت UTC',170),('type','الجدول',165),('entity','معرف السجل',115),
            ('action','العملية',140),('old','القيم السابقة',260),('new','القيم الجديدة',300)],18)
        rows=self.sql('SELECT id,occurred_at_utc,entity_type,entity_id,action,previous_json,new_json FROM audit_events ORDER BY id DESC LIMIT 400')
        self.populate(t,[(r['id'],(r['occurred_at_utc'][:19],r['entity_type'],r['entity_id'],r['action'],
                  (r['previous_json'] or '')[:200],(r['new_json'] or '')[:200])) for r in rows])

    REPORT_NAMES=['تكاليف أوامر الإنتاج','تكلفة العبوات حسب الوزن','المخزون وتقييم آخر شراء','فواتير المشتريات',
       'الفاقد والتنبيهات','أرصدة العمال','كشف حساب عامل','العجز المؤقت FIFO','دفعات الشراء FIFO','تاريخ أسعار الخام']

    def page_reports(self):
        ctrl=self.card(self.content);ctrl.pack(fill='x',pady=(0,12))
        self.headline(ctrl,'مركز التقارير','ترشيح حسب المادة والعامل والتاريخ عند انطباقها. التصدير CSV قابل للفتح في Excel، والطباعة PDF من المتصفح.')
        f=tk.Frame(ctrl,bg=WHITE);f.pack(fill='x',padx=14,pady=5)
        kind=self.combo(f,'التقرير',0,4,self.REPORT_NAMES)
        material=self.combo(f,'المادة الخام (اختياري)',0,3,['الكل']+self.materials_options())
        worker=self.combo(f,'العامل (اختياري)',0,2,['الكل']+self.workers_options())
        start=self.field(f,'من تاريخ (اختياري)',1,4)
        end=self.field(f,'إلى تاريخ (اختياري)',1,3)
        buttons=tk.Frame(ctrl,bg=WHITE);buttons.pack(fill='x',padx=16,pady=4)
        body=self.card(self.content);body.pack(fill='both',expand=True)
        self.headline(body,'نتائج التقرير')
        outer=ttk.Frame(body);outer.pack(fill='both',expand=True,padx=13,pady=10)
        self.report_content=outer
        self.report_data=([],[])
        def run_report():
            if start.get().strip():parse_date(start.get())
            if end.get().strip():parse_date(end.get())
            if start.get().strip() and end.get().strip() and start.get()>end.get():raise ValueError('تاريخ البداية بعد تاريخ النهاية.')
            mid=selected_id(material) if material.get()!='الكل' else None
            wid=selected_id(worker) if worker.get()!='الكل' else None
            headers,rows=self.build_report(kind.get(),mid,wid,start.get().strip(),end.get().strip())
            self.report_data=(headers,rows)
            for x in outer.winfo_children():x.destroy()
            colspec=[(f'c{i}',h,min(280,max(100,len(h)*12))) for i,h in enumerate(headers)]
            tv=self.table(outer,colspec,16)
            self.populate(tv,[(i,tuple(row)) for i,row in enumerate(rows)])
            self.report_heading=kind.get()
            self.report_filter=f"المادة: {material.get()} | العامل: {worker.get()} | من: {start.get()} | إلى: {end.get()}"
        self.button(buttons,'عرض التقرير',lambda:self.run(run_report,success=None,refresh=False),'accent')
        self.button(buttons,'تصدير CSV (Excel)',lambda:self.run(self.export_csv,'تم تصدير التقرير بنجاح.',refresh=False))
        self.button(buttons,'طباعة / حفظ PDF',lambda:self.run(self.export_html,'فُتح التقرير في المتصفح؛ استخدم Ctrl+P للطباعة أو الحفظ PDF.',refresh=False))
        run_report()

    def build_report(self,typ,material=None,worker=None,start='',end=''):
        """Read-only, parameterized reporting. Financial values stay in Decimal arithmetic."""
        def filt(conditions,params,col,v,operator='='):
            if v is not None and v!='':conditions.append(f'{col} {operator} ?');params.append(v)
        wh=[];p=[]
        if typ=='تكاليف أوامر الإنتاج':
            filt(wh,p,'c.material_id',material);filt(wh,p,'c.worker_id',worker)
            filt(wh,p,'c.order_date',start,'>=');filt(wh,p,'c.order_date',end,'<=')
            sql='''SELECT c.order_number,c.order_date,m.name material,w.name worker,c.status,c.input_quantity_micrograms,c.output_weight_micrograms,
               c.raw_cost_micro_local,c.shared_expenses_micro_local,c.wages_micro_local,c.total_cost_micro_local FROM v_production_costs c
               JOIN raw_materials m ON m.id=c.material_id JOIN workers w ON w.id=c.worker_id'''
            rs=self.sql(sql+(' WHERE '+' AND '.join(wh) if wh else '')+' ORDER BY c.order_date DESC,c.order_id DESC',p)
            return ['الأمر','التاريخ','المادة','العامل','الحالة','المدخل جرام','الناتج جرام','تكلفة الخام','المصاريف','الأجور','الإجمالي'],[
                 [r['order_number'],r['order_date'],r['material'],r['worker'],self.status(r['status']),grams(r['input_quantity_micrograms']),
                  grams(r['output_weight_micrograms']),amount(r['raw_cost_micro_local']) if r['status']=='POSTED' else '—',
                  amount(r['shared_expenses_micro_local']) if r['status']=='POSTED' else '—',
                  amount(r['wages_micro_local']) if r['status']=='POSTED' else '—',
                  amount(r['total_cost_micro_local']) if r['status']=='POSTED' else '—'] for r in rs]
        if typ=='تكلفة العبوات حسب الوزن':
            filt(wh,p,'o.material_id',material);filt(wh,p,'o.worker_id',worker)
            filt(wh,p,'o.order_date',start,'>=');filt(wh,p,'o.order_date',end,'<=')
            rs=self.sql('''SELECT o.order_number,o.order_date,m.name material,s.label AS size_weight,p.package_count,p.unit_cost_precise_decimal,p.line_total_micro_local
                  FROM production_orders o JOIN production_packaging_lines p ON p.version_id=o.current_version_id
                  JOIN packaging_sizes s ON s.id=p.packaging_size_id JOIN raw_materials m ON m.id=o.material_id
                  WHERE o.status='POSTED' '''+(' AND '+' AND '.join(wh) if wh else '')+' ORDER BY o.order_date DESC,o.id DESC,s.weight_micrograms DESC',p)
            return ['الأمر','التاريخ','المادة','وزن العبوة','العدد','تكلفة العبوة','إجمالي السطر'],[
                [r['order_number'],r['order_date'],r['material'],r['size_weight'],r['package_count'],
                 decimal_plain(r['unit_cost_precise_decimal']),amount(r['line_total_micro_local'])] for r in rs]
        if typ=='المخزون وتقييم آخر شراء':
            filt(wh,p,'material_id',material)
            rs=self.sql('SELECT * FROM v_inventory_valuation'+(' WHERE '+' AND '.join(wh) if wh else '')+' ORDER BY name',p)
            return ['الرمز','المادة','رصيد جرام','سعر آخر شراء/جرام','قيمة المخزون (ر.ي)','الحالة'],[
                  [r['code'],r['name'],grams(r['balance_micrograms']),decimal_plain(r['price_local_per_gram_decimal'],6),
                    decimal_plain(unmicro(r['balance_micrograms'])*dec(r['price_local_per_gram_decimal'])) if r['price_local_per_gram_decimal'] else '—',
                    'رصيد سالب' if r['balance_micrograms']<0 else 'طبيعي'] for r in rs]
        if typ=='فواتير المشتريات':
            filt(wh,p,'p.material_id',material);filt(wh,p,'p.purchase_date',start,'>=');filt(wh,p,'p.purchase_date',end,'<=')
            rs=self.sql('''SELECT p.*,m.name material,c.code currency_code FROM purchase_invoices p JOIN raw_materials m ON m.id=p.material_id
                 JOIN currencies c ON c.id=p.currency_id'''+(' WHERE '+' AND '.join(wh) if wh else '')+' ORDER BY p.purchase_date DESC,p.id DESC',p)
            return ['الفاتورة','التاريخ','المادة','الوزن جرام','عملة','المبلغ بعملة الشراء','الصرف','المبلغ المحلي','تكلفة جرام'],[
                    [r['invoice_number'],r['purchase_date'],r['material'],grams(r['quantity_micrograms']),r['currency_code'],
                    amount(r['final_amount_micro_currency']),r['fx_rate_snapshot_decimal'],amount(r['final_amount_micro_local']),
                    decimal_plain(r['unit_price_local_per_gram_decimal'],6)] for r in rs]
        if typ=='الفاقد والتنبيهات':
            filt(wh,p,'c.material_id',material);filt(wh,p,'c.worker_id',worker)
            filt(wh,p,'c.order_date',start,'>=');filt(wh,p,'c.order_date',end,'<=')
            rs=self.sql('SELECT c.*,m.name material FROM v_waste_alerts c JOIN raw_materials m ON m.id=c.material_id'+
                   (' WHERE '+' AND '.join(wh) if wh else '')+' ORDER BY c.order_date DESC,c.order_id DESC',p)
            rows=[]
            for r in rs:
                ratio=unmicro(r['waste_micrograms'])*100/unmicro(r['input_quantity_micrograms'])
                rows.append([r['order_number'],r['order_date'],r['material'],grams(r['input_quantity_micrograms']),
                    grams(r['output_weight_micrograms']),grams(r['waste_micrograms']),decimal_plain(ratio),r['max_waste_ratio'],
                    self.warning_text(r['warning_flags_json']).replace('\n','، ')])
            return ['الأمر','التاريخ','المادة','المدخل','الناتج','الفاقد جرام','النسبة %','الحد %','تنبيهات'],rows
        if typ=='أرصدة العمال':
            filt(wh,p,'w.id',worker)
            rs=self.sql('''SELECT w.*,COALESCE(SUM(l.signed_amount_micro_local),0) bal FROM workers w
                          LEFT JOIN worker_ledger l ON l.worker_id=w.id'''+(' WHERE '+' AND '.join(wh) if wh else '')+
                        ' GROUP BY w.id ORDER BY w.name',p)
            return ['رمز العامل','الاسم','التواصل','الرصيد (ر.ي)'],[[r['code'],r['name'],r['contact'] or '',amount(r['bal'])] for r in rs]
        if typ=='كشف حساب عامل':
            if not worker: raise ValueError('اختر عاملًا لعرض كشف حسابه.')
            ss=self.svc.worker_statement(worker,f'{start}T00:00:00Z' if start else None,
                                               f'{end}T23:59:59.999Z' if end else None)
            begin=f'{start}T00:00:00Z' if start else '0000'
            finish=f'{end}T23:59:59.999Z' if end else '9999'
            rows=self.sql('''SELECT l.id,l.created_at_utc,l.ledger_kind,l.reference,l.signed_amount_micro_local,p.payment_date
                FROM worker_ledger l LEFT JOIN worker_payments p ON l.payment_id=p.id
                WHERE l.worker_id=? AND l.created_at_utc>=? AND l.created_at_utc<=? ORDER BY l.id''',(worker,begin,finish))
            bal=dec(ss['opening']);out=[['رصيد افتتاحي','','','', '',ss['opening']]]
            for r in rows:
                signed=unmicro(r['signed_amount_micro_local']);bal+=signed
                out.append([r['payment_date'] or r['created_at_utc'][:10],self.ledger_kind(r['ledger_kind']),r['reference'] or '',
                    amount(r['signed_amount_micro_local']) if signed>0 else '',amount(-r['signed_amount_micro_local']) if signed<0 else '',decimal_plain(bal)])
            out.append(['رصيد ختامي','','','', '',ss['closing']])
            return ['التاريخ','الحركة','المرجع','مستحق (+)','صرف (−)','الرصيد'],out
        if typ=='العجز المؤقت FIFO':
            filt(wh,p,'s.material_id',material)
            rs=self.sql('SELECT s.*,m.name material FROM v_fifo_pending_shortages s JOIN raw_materials m ON s.material_id=m.id'+
                        (' WHERE '+' AND '.join(wh) if wh else '')+' ORDER BY s.order_id',p)
            return ['أمر الإنتاج','المادة','العجز الأولي جرام','المتبقي غير مغطى جرام'],[
                    [r['order_number'],r['material'],grams(r['initial_uncovered_micrograms']),grams(r['remaining_uncovered_micrograms'])] for r in rs]
        if typ=='دفعات الشراء FIFO':
            filt(wh,p,'f.material_id',material)
            rs=self.sql('''SELECT f.*,m.name material FROM v_fifo_lot_usage f JOIN raw_materials m ON m.id=f.material_id'''+
                        (' WHERE '+' AND '.join(wh) if wh else '')+' ORDER BY f.purchase_id DESC',p)
            return ['الفاتورة','المادة','الكمية جرام','المخصص جرام','المتبقي جرام'],[
                    [r['invoice_number'],r['material'],grams(r['quantity_micrograms']),grams(r['allocated_micrograms']),grams(r['remaining_micrograms'])] for r in rs]
        if typ=='تاريخ أسعار الخام':
            filt(wh,p,'material_id',material);filt(wh,p,'event_time_utc',start+'T00:00:00Z' if start else '', '>=')
            filt(wh,p,'event_time_utc',end+'T23:59:59.999Z' if end else '', '<=')
            rs=self.sql('SELECT * FROM v_purchase_price_timeline'+(' WHERE '+' AND '.join(wh) if wh else '')+' ORDER BY event_id DESC',p)
            return ['وقت الحدث UTC','المادة','السبب','السعر السابق/جرام','الجديد/جرام'],[
                [r['event_time_utc'][:19],r['material_name'],r['reason'],decimal_plain(r['previous_price_decimal'],6),
                 decimal_plain(r['new_price_decimal'],6)] for r in rs]
        return [],[]

    def export_csv(self):
        headings,rows=self.report_data
        if not headings:raise ValueError('اعرض تقريرًا أولًا.')
        EXPORTS.mkdir(parents=True,exist_ok=True)
        path=filedialog.asksaveasfilename(title='تصدير التقرير إلى Excel/CSV',initialdir=str(EXPORTS),
                 defaultextension='.csv',filetypes=[('CSV Excel UTF-8','*.csv')],parent=self.root)
        if not path:return
        with open(path,'w',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f);w.writerow([safe_cell(x) for x in headings]);w.writerows([safe_cell(x) for x in row] for row in rows)

    def export_html(self):
        headings,rows=self.report_data
        if not headings:raise ValueError('اعرض تقريرًا أولًا.')
        EXPORTS.mkdir(parents=True,exist_ok=True)
        title=html.escape(getattr(self,'report_heading','تقرير'))
        filtertext=html.escape(getattr(self,'report_filter',''))
        td=''.join('<tr>'+''.join('<td>'+html.escape(str(c))+'</td>' for c in row)+'</tr>' for row in rows)
        headers=''.join('<th>'+html.escape(str(c))+'</th>' for c in headings)
        html_body=f'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>{title}</title>
        <style>body{{font:14px Tahoma,Arial,sans-serif;color:#19334b;padding:28px}}h1{{color:#145aa7}}
        p{{color:#58708a}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #cad9e8;padding:9px;text-align:right}}
        th{{background:#e7f0fa}}tr:nth-child(even){{background:#f8fbff}}@page{{size:A4 landscape;margin:13mm}}
        @media print{{button{{display:none}}body{{padding:0}}}}button{{padding:10px 18px;background:#176ac2;color:white;border:0;margin:8px}}</style>
        </head><body><button onclick="window.print()">طباعة / حفظ PDF</button><h1>تعبئة تك | {title}</h1>
        <p>{filtertext}</p><p>تاريخ الاستخراج: {date.today().isoformat()} | عدد السجلات: {len(rows)}</p>
        <table><thead><tr>{headers}</tr></thead><tbody>{td}</tbody></table></body></html>'''
        out=EXPORTS/f'tabia_report_{datetime.now().strftime("%Y%m%d_%H%M%S_%f")}.html'
        out.write_text(html_body,encoding='utf-8')
        webbrowser.open(out.as_uri())

    def on_close(self):
        try:
            backup=self.svc.backup(BACKUPS)
            self.svc.close()
        except Exception as exc:
            if not messagebox.askyesno('تعذر النسخ عند الإغلاق',f'تعذر إنشاء نسخة احتياطية:\n{exc}\n\nهل تغلق دون نسخة جديدة؟',parent=self.root):return
            try:self.svc.close()
            except Exception:pass
        self.root.destroy()


def main():
    try:
        root=tk.Tk()
        TabiaApp(root)
        root.mainloop()
    except Exception as exc:
        try:
            import traceback
            DATA.mkdir(parents=True, exist_ok=True)
            (DATA/'startup_error.log').write_text(traceback.format_exc(),encoding='utf-8')
        except Exception: pass
        try:messagebox.showerror('تعذر بدء تعبئة تك',str(exc))
        except Exception:print(exc,file=sys.stderr)
        raise

if __name__=='__main__': main()
