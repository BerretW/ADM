#!/usr/bin/env python3
import sys, pathlib, json
from container import verify,AdmError,HEADER
root=pathlib.Path(__file__).parent.parent
success=failures=0
for p in sorted((root/'fixtures/valid').iterdir()):
    if p.suffix not in ('.adm','.adm_anim'):continue
    try:
        res=verify(p)
        print('PASS valid',p.name,'chunks',res['chunks']);success+=1
    except Exception as e:
        print('FAIL valid',p.name,repr(e));failures+=1
for p in sorted((root/'fixtures/invalid').iterdir()):
    if p.suffix not in ('.adm','.adm_anim'):continue
    try:
        verify(p)
        print('FAIL invalid accepted',p.name);failures+=1
    except AdmError as e:
        print('PASS rejected',p.name,str(e));success+=1
# Explicit metadata-only parse with no payload reads
anim=root/'fixtures/valid/shader_parameter_tracks.adm_anim';b=anim.read_bytes()
magic,maj,minor,hs,flags,size,mo,ml,do,n,es,r=HEADER.unpack_from(b)
manifest=json.loads(b[mo:mo+ml])
assert manifest['library']['id']=='material@surface@dirty'
assert manifest['clips'][0]['description'].strip()
assert mo+ml<=do and do+n*es<=len(b)
print('PASS metadata-only catalog without reading payload chunks');success+=1
from container import RangeReader
p=root/'fixtures/valid/triangle_split.adm';r=RangeReader(p);initial=r.bytes_read
assert initial < p.stat().st_size
assert len(r.load(2))==6 and r.bytes_read==initial+6
print('PASS targeted chunk read (only 6 payload bytes)');success+=1
print(f'Total: {success} passed, {failures} failed')
sys.exit(bool(failures))
