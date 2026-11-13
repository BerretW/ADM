#!/usr/bin/env python3
from pathlib import Path
import zipfile,struct,json,sys,copy
sys.path.insert(0,str(Path(__file__).parent));from container import create,verify,HEADER,ENTRY
src=Path('/mnt/data/ADM-1.0-shadery-a-animace.zip')
root=Path(__file__).parent.parent/'fixtures';valid=root/'valid';invalid=root/'invalid'
valid.mkdir(parents=True,exist_ok=True);invalid.mkdir(parents=True,exist_ok=True)
fixtures=[('triangle','adm',b'ADM0',b'GEOM'),('shader_layered','adm',b'ADM0',b'GEOM'),('catalog-only','adm_anim',b'AMA0',b'ANIM'),('shader_parameter_tracks','adm_anim',b'AMA0',b'ANIM')]
with zipfile.ZipFile(src) as z:
 for name,ext,magic,typ in fixtures:
  raw=z.read('adm-standard/fixtures/'+name+'.'+ext)
  m=json.loads(z.read('adm-standard/fixtures/'+name+'.json'))
  # old header 32: magic 4, major u16 minor u16, jsonLen u64, binLen u64, flags u32, res u32
  _,ver,mi,jsz,bsz,flags,res=struct.unpack_from('<4sHHQQII',raw,0)
  assert len(raw)==32+jsz+bsz,(name,len(raw),jsz,bsz)
  payload=raw[32+jsz:]
  if payload:
   for view in m.get('bufferViews',[]):view['chunkId']=1
   chunks=[(1,typ,payload,True)]
  else:chunks=[]
  create(valid/(name+'.'+ext),magic,m,chunks)
  (valid/(name+'.json')).write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
  print(verify(valid/(name+'.'+ext)))
# negative files made from base without altering expected fixture
base=bytearray((valid/'triangle.adm').read_bytes())
b=base.copy(); b[8]=0; (invalid/'bad_header_size.adm').write_bytes(b)
b=base.copy(); b[-17]^=0x01;(invalid/'bad_hash.adm').write_bytes(b)
b=base.copy(); b[16:24]=struct.pack('<Q', len(b)+1);(invalid/'bad_file_size.adm').write_bytes(b)
b=base.copy(); d=struct.unpack_from('<Q',b,40)[0]; b[d+24:d+32]=struct.pack('<Q',4);(invalid/'bad_chunk_offset.adm').write_bytes(b)
# malicious dependency cycle via two zero-length? use two raw chunks and metadata
cyc={'asset':{},'scene':0,'scenes':[{'nodes':[]}],'nodes':[],'meshes':[],'accessors':[],'bufferViews':[], 'chunkDependencies':[{'chunkId':1,'requires':[2]},{'chunkId':2,'requires':[1]}]}
create(invalid/'bad_dependency_cycle.adm',b'ADM0',cyc,[(1,b'DATA',b'A',True),(2,b'DATA',b'B',True)])
