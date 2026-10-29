"""Confirm that PyInstaller generated an actual x86 Windows PE and includes key runtime files."""
from pathlib import Path
import sys,struct
exe=Path(sys.argv[1] if len(sys.argv)>1 else 'dist/TABIA_TECH/TABIA_TECH.exe')
assert exe.is_file(), 'Missing EXE: '+str(exe)
blob=exe.read_bytes()
assert blob[:2] == b'MZ', 'Not a Windows executable'
pe_offset=struct.unpack_from('<I',blob,0x3c)[0]
assert blob[pe_offset:pe_offset+4]==b'PE\x00\x00','Invalid Windows PE'
machine=struct.unpack_from('<H',blob,pe_offset+4)[0]
assert machine == 0x14c, 'Expected Win32 x86, got PE machine %#x'%machine
magic=struct.unpack_from('<H',blob,pe_offset+24)[0]
assert magic==0x10b, 'Expected 32-bit PE32, got %#x'%magic
folder=exe.parent
names={p.name.lower() for p in folder.rglob('*') if p.is_file()}
assert any(n=='_tkinter.pyd' for n in names),'Tkinter binary missing'
assert any(n=='_sqlite3.pyd' for n in names),'SQLite binary missing'
assert any(n.startswith('tcl86') and n.endswith('.dll') for n in names),'Tcl runtime missing'
assert any(n.startswith('tk86') and n.endswith('.dll') for n in names),'Tk runtime missing'
assert 'tabia_tech.db' in names, 'Database seed missing'
assert 'tabia_tech_schema.sql' in names, 'Schema missing'
print('Verified: Windows PE32, x86, bundled Tcl/Tk, SQLite, DB seed and schema.')
