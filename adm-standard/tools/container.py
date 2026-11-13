#!/usr/bin/env python3
"""ADM Draft 0.4 byte-accurate container writer/validator (not full semantic compliance)."""
import hashlib, json, struct, sys, pathlib
HEADER=struct.Struct('<4sHHIIQQQQIIQ')
ENTRY=struct.Struct('<Q4sII I QQQ32s')
assert HEADER.size == 64 and ENTRY.size == 80
LIMIT_MANIFEST=16*1024*1024
LIMIT_CHUNK=256*1024*1024
MAX_CHUNKS=65535
class AdmError(ValueError): pass

def align(n):return (n+15)&~15

def serial(o):return json.dumps(o,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')

def create(path, magic, manifest, chunks):
    if magic not in (b'ADM0',b'AMA0'):raise AdmError('magic')
    mb=serial(manifest); n=len(chunks); d=align(64+len(mb)); cursor=align(d+80*n)
    directory=[];payload=[]
    for cid,typ,raw,required in sorted(chunks,key=lambda x:x[0]):
        assert len(typ)==4 and 0 < cid < 2**32 and raw and len(raw)<=LIMIT_CHUNK
        directory.append(ENTRY.pack(cid,typ,1 if required else 0,0,0,cursor,len(raw),len(raw),hashlib.sha256(raw).digest()))
        payload.append((cursor,raw));cursor=align(cursor+len(raw))
    out=bytearray(cursor)
    out[:64]=HEADER.pack(magic,1,0,64,0,len(out),64,len(mb),d,n,80,0)
    out[64:64+len(mb)]=mb
    out[d:d+80*n]=b''.join(directory)
    for offset,data in payload:out[offset:offset+len(data)]=data
    pathlib.Path(path).write_bytes(out)

def no_duplicate(pairs):
    d={}
    for k,v in pairs:
        if k in d:raise AdmError('ADM_ERR_DUPLICATE_JSON_KEY')
        d[k]=v
    return d

def verify(path, verify_payload=True):
    b=pathlib.Path(path).read_bytes()
    if len(b)<64:raise AdmError('ADM_ERR_TRUNCATED_HEADER')
    magic,maj,minr,hsize,flags,fsize,moff,mlen,doff,n,esize,res=HEADER.unpack_from(b)
    if magic not in (b'ADM0',b'AMA0') or (maj,minr,hsize,flags,res,moff,esize)!=(1,0,64,0,0,64,80):raise AdmError('ADM_ERR_HEADER')
    if fsize!=len(b) or not 2<=mlen<=LIMIT_MANIFEST or n>MAX_CHUNKS or doff!=align(64+mlen) or doff+n*80>fsize:raise AdmError('ADM_ERR_BOUNDS')
    if any(b[64+mlen:doff]):raise AdmError('ADM_ERR_PADDING')
    try:m=json.loads(b[64:64+mlen].decode('utf8'),object_pairs_hook=no_duplicate,parse_constant=lambda v: (_ for _ in ()).throw(AdmError('ADM_ERR_NONFINITE')))
    except (UnicodeError,json.JSONDecodeError) as e:raise AdmError('ADM_ERR_JSON') from e
    if not isinstance(m,dict):raise AdmError('ADM_ERR_MANIFEST')
    if magic==b'ADM0':
        for k in ('asset','nodes','scenes','scene','meshes','accessors','bufferViews'):
            if k not in m:raise AdmError('ADM_ERR_MANIFEST_REQUIRED:'+k)
    else:
        for k in ('asset','library','clips','accessors','bufferViews'):
            if k not in m:raise AdmError('ADM_ERR_MANIFEST_REQUIRED:'+k)
        for clip in m['clips']:
            if not str(clip.get('description','')).strip():raise AdmError('ADM_ERR_MISSING_DESCRIPTION')
    chunks={};last_id=0;prev_end=align(doff+n*80)
    if any(b[doff+n*80:prev_end]):raise AdmError('ADM_ERR_PADDING')
    for i in range(n):
        cid,typ,flags,codec,res,off,stored,raw,sha=ENTRY.unpack_from(b,doff+i*80)
        if not 0<cid<=4294967295 or cid<=last_id:raise AdmError('ADM_ERR_CHUNK_ID')
        if flags&~1 or res or not stored or not raw or raw>LIMIT_CHUNK:raise AdmError('ADM_ERR_CHUNK_ENTRY')
        if off%16 or off<prev_end or off+stored>len(b):raise AdmError('ADM_ERR_CHUNK_BOUNDS')
        if any(b[prev_end:off]):raise AdmError('ADM_ERR_PADDING')
        if typ not in (b'GEOM',b'ANIM',b'IMAG',b'DATA') and flags&1:raise AdmError('ADM_ERR_UNSUPPORTED_CHUNK')
        if codec not in (0,1) and flags&1:raise AdmError('ADM_ERR_UNSUPPORTED_CODEC')
        if codec==0 and stored!=raw:raise AdmError('ADM_ERR_CHUNK_SIZE')
        if verify_payload:
            if codec != 0:raise AdmError('ADM_ERR_UNSUPPORTED_CODEC')
            if hashlib.sha256(b[off:off+stored]).digest()!=sha:raise AdmError('ADM_ERR_HASH_MISMATCH')
        chunks[cid]=(typ,raw)
        last_id=cid;prev_end=align(off+stored)
    if prev_end!=len(b) or any(b[len(b)-(prev_end-(off+stored)):] if n and prev_end>off+stored else b''):raise AdmError('ADM_ERR_TRAILING_BYTES')
    for v in m.get('bufferViews',[]):
        if not isinstance(v,dict) or not all(k in v for k in ('chunkId','byteOffset','byteLength')):raise AdmError('ADM_ERR_BUFFER_VIEW')
        c=v['chunkId'];start=v['byteOffset'];size=v['byteLength']
        if c not in chunks or not isinstance(start,int) or not isinstance(size,int) or start<0 or size<0 or start+size>chunks[c][1]:raise AdmError('ADM_ERR_BUFFER_VIEW')
    for material in m.get('materials',[]):
        shader=material.get('shader')
        if shader is not None and (shader.get('id'),shader.get('version'))!=('adm.pbr.metallic_roughness','1.0.0'):
            if any(key not in material for key in ('baseColorFactor','metallicFactor','roughnessFactor','emissiveFactor','alphaMode')):
                raise AdmError('ADM_ERR_MISSING_PBR_FALLBACK')
    for a in m.get('accessors',[]):
        try:
            bv=m['bufferViews'][a['bufferView']];unit={'F32':4,'U32':4,'U16':2,'U8':1}[a['componentType']];elems={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4,'MAT4':16}[a['type']];offset=a.get('byteOffset',0); count=a['count']
            if not all(isinstance(t,int) and t>=0 for t in (offset,count)) or offset%unit or offset+count*unit*elems>bv['byteLength']:raise ValueError('bounds')
        except (KeyError,IndexError,ValueError,TypeError):raise AdmError('ADM_ERR_ACCESSOR')
    graph={}
    for dep in m.get('chunkDependencies',[]):
        node=dep['chunkId']; req=dep['requires']
        if node not in chunks or node in graph or not isinstance(req,list) or len(set(req))!=len(req) or node in req or any(x not in chunks for x in req):raise AdmError('ADM_ERR_DEPENDENCY')
        graph[node]=req
    color={}
    def walk(node):
        if color.get(node)==1:raise AdmError('ADM_ERR_DEPENDENCY_CYCLE')
        if color.get(node)==2:return
        color[node]=1
        for adj in graph.get(node,[]):walk(adj)
        color[node]=2
    for node in graph:walk(node)
    return {'file':str(path),'kind':magic.decode(),'chunks':n,'manifestBytes':mlen,'bufferViews':len(m.get('bufferViews',[])),'verifiedPayloads':verify_payload}

if __name__=='__main__':
    status=0
    for arg in sys.argv[1:]:
        try:print('OK',verify(arg))
        except Exception as e: print('FAIL',arg,repr(e));status=1
    sys.exit(status)

class RangeReader:
    """Minimal demonstrator: header/manifest/directory via seek; demand-load RAW chunks."""
    def __init__(self,path):
        self.path=path;self.bytes_read=0
        with open(path,'rb') as f:
            def read(n):
                b=f.read(n);self.bytes_read+=len(b);return b
            h=read(64)
            if len(h)!=64:raise AdmError('ADM_ERR_TRUNCATED_HEADER')
            magic,major,minor,hs,flags,fs,mo,ml,do,n,esz,res=HEADER.unpack(h)
            if magic not in (b'ADM0',b'AMA0') or (major,minor,hs,flags,mo,esz,res)!=(1,0,64,0,64,80,0) or n>MAX_CHUNKS or ml>LIMIT_MANIFEST or do!=align(64+ml):raise AdmError('ADM_ERR_HEADER')
            f.seek(mo);self.manifest=json.loads(read(ml))
            f.seek(do);d=read(n*80)
            self.chunks={}
            for i in range(n):
                cid,typ,ef,codec,rsv,off,stored,raw,sha=ENTRY.unpack_from(d,i*80)
                self.chunks[cid]=(typ,codec,off,stored,raw,sha)
    def load(self,cid):
        typ,codec,off,stored,raw,sha=self.chunks[cid]
        if codec!=0:raise AdmError('ADM_ERR_UNSUPPORTED_CODEC')
        with open(self.path,'rb') as f:
            f.seek(off);data=f.read(stored);self.bytes_read+=len(data)
        if hashlib.sha256(data).digest()!=sha:raise AdmError('ADM_ERR_HASH_MISMATCH')
        return data
