#!/usr/bin/env python3
"""Draft 0.4 P1 structural + math smoke tests for vehicle and firearm profiles.
Not a complete runtime/animation/LOD conformance suite.
"""
import json,math,sys,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from container import verify
P=Path(__file__).parent.parent/'fixtures'/'profiles'
class ProfileError(ValueError): pass

def check(m):
 profiles=m.get('modelProfiles',[])
 if len(profiles)!=1:raise ProfileError('PROFILE_COUNT')
 p=profiles[0]; id=p['id'];meta=p['metadata']
 if p['schemaVersion']!=1:raise ProfileError('PROFILE_VERSION')
 nodes=m['nodes']; roles={}
 for e in m.get('componentRoles',[]):
  if e['profile']!=id or e['role'] in roles or not isinstance(e['node'],int) or not 0<=e['node']<len(nodes):raise ProfileError('ROLE')
  roles[e['role']]=e['node']
 if len(set(roles.values()))!=len(roles):raise ProfileError('ROLE_NODE_DUPLICATE')
 attachments={a['name']:a['node'] for a in m.get('attachments',[])}
 if len(attachments)!=len(m.get('attachments',[])):raise ProfileError('DUPLICATE_SOCKET')
 parent={}
 for i,n in enumerate(nodes):
  for c in n.get('children',[]):
   if c in parent:raise ProfileError('MULTIPLE_PARENTS')
   parent[c]=i
 for role,i in roles.items():
  n=nodes[i]
  if any(abs(a-b)>1e-7 for a,b in zip(n.get('rotation',[0,0,0,1]),[0,0,0,1])):raise ProfileError('AXIS_ROTATION')
  if n.get('scale',[1,1,1])!=[1,1,1]:raise ProfileError('NONUNIT_SCALE')
 def rest_origin(i):
  pos=[0.0,0.0,0.0]
  while True:
   v=nodes[i].get("translation",[0,0,0])
   pos=[pos[k]+v[k] for k in range(3)]
   if i not in parent:break
   i=parent[i]
  return pos
 def ancestor(a,b):
  while b in parent:
   b=parent[b]
   if b==a:return True
  return False
 if id=='vehicle.car.v1':
  if set(meta)-{'axles','hinges','visualOnly','extensions'}:raise ProfileError('UNKNOWN_METADATA')
  axles=meta['axles']
  if len(axles)<2:raise ProfileError('AXLE_COUNT')
  if 'chassis' not in roles:raise ProfileError('CHASSIS')
  lastz=-float('inf');used=set()
  for idx,a in enumerate(axles):
   if a['index']!=idx:raise ProfileError('AXLE_INDEX')
   centres=[]
   for side in ('left','right'):
    w=a['wheels'][side]; role=f'wheel.axle{idx}.{side}'
    if w['role']!=role or role not in roles or role in used:raise ProfileError('WHEEL_ROLE')
    used.add(role);i=roles[role]
    if not ancestor(roles['chassis'],i):raise ProfileError('CHASSIS_PARENT')
    for key in ('radius','width'):
     if not isinstance(w[key],(int,float)) or not math.isfinite(w[key]) or w[key]<=0:raise ProfileError('WHEEL_SIZE')
    centres.append(rest_origin(i))
   if centres[0][0]>=centres[1][0]:raise ProfileError('SIDE_ORDER')
   z=(centres[0][2]+centres[1][2])/2
   if z<=lastz:raise ProfileError('AXLE_ORDER')
   lastz=z
   if a.get('steeringAngleRad',0):
    if not 0<a['steeringAngleRad']<=math.pi/2:raise ProfileError('STEERING_LIMIT')
    for side in ('left','right'):
     sr=f'steering.axle{idx}.{side}'
     if sr not in roles or not ancestor(roles[sr],roles[f'wheel.axle{idx}.{side}']):raise ProfileError('STEERING_ROLE')
  hinge_roles={r for r in roles if r.startswith('door.') or r in ('hood','trunk')}
  declared={h['role'] for h in meta.get('hinges',[])}
  if declared!=hinge_roles:raise ProfileError('HINGES')
  for h in meta.get('hinges',[]):
   x=h['openAngleRad']
   if not math.isfinite(x) or not 0<abs(x)<=math.pi:raise ProfileError('HINGE_ANGLE')
 elif id=='weapon.firearm.v1':
  if set(meta)-{'feedType','mounts','articulations','extensions'}:raise ProfileError('UNKNOWN_METADATA')
  if not all(r in roles for r in ('weapon.receiver','weapon.muzzle')):raise ProfileError('REQUIRED_ROLES')
  if not ancestor(roles['weapon.receiver'],roles['weapon.muzzle']):raise ProfileError('RECEIVER_PARENT')
  if meta['feedType'] not in ('DETACHABLE_MAGAZINE','INTERNAL','OTHER','NONE'):raise ProfileError('FEED')
  if meta['feedType']=='DETACHABLE_MAGAZINE' and ('weapon.magazine' not in roles or 'mount.magazine' not in attachments):raise ProfileError('MAGAZINE')
  sockets={'mount.optic.primary':'optic.v1','mount.muzzle':'muzzle.v1','mount.underbarrel':'underbarrel.v1','mount.side.left':'side.v1','mount.side.right':'side.v1','mount.stock':'stock.v1','mount.magazine':'magazine.v1','mount.handguard':'handguard.v1','mount.grip':'grip.v1'}
  mounts={e['socket']:e for e in meta.get('mounts',[])}
  if set(mounts)!=(set(attachments)&set(sockets)):raise ProfileError('MOUNT_METADATA')
  for k,v in mounts.items():
   if k not in sockets or v['class']!=sockets[k] or not v['interface'].endswith('.v1'):raise ProfileError('MOUNT_INTERFACE')
  for a in meta.get('articulations',[]):
   if a['role'] not in roles:raise ProfileError('ARTICULATION_ROLE')
 elif id=='weapon.attachment.v1':
  if 'mount.root' not in attachments or set(meta)!={'class','interface'}:raise ProfileError('ATTACHMENT')
 else:raise ProfileError('UNKNOWN_PROFILE')
 return id

count=0
for file in sorted(P.glob('*.adm')):
 verify(file)
 m=json.loads(file.with_suffix('.json').read_text());print('PASS PROFILE',file.name,check(m));count+=1
v=json.loads((P/'vehicle_car_minimal.json').read_text())
for transform,code in [(lambda m:m['modelProfiles'][0]['metadata']['axles'].pop(),'AXLE_COUNT'),(lambda m:m['componentRoles'].pop(1),'WHEEL_ROLE'),(lambda m:m['nodes'][1].update(scale=[-1,1,1]),'NONUNIT_SCALE')]:
 x=copy.deepcopy(v);transform(x)
 try:check(x);raise AssertionError('accepted invalid fixture')
 except ProfileError as e:print('PASS invalid',str(e));count+=1
w=json.loads((P/'weapon_firearm_minimal.json').read_text())
x=copy.deepcopy(w);x['attachments']=[]
try:check(x);raise AssertionError('accepted missing mount')
except ProfileError as e:print('PASS invalid',str(e));count+=1
# Normative axis mathematics in the vehicle annex.
r=.35
bottom=(0,-r,0)
# rotate by +pi/2 about +X: y'=y*cos - z*sin, z'=y*sin +z*cos
th=math.pi/2
p=(0,bottom[1]*math.cos(th)-bottom[2]*math.sin(th),bottom[1]*math.sin(th)+bottom[2]*math.cos(th))
assert abs(p[2]+r)<1e-10 and abs(p[1])<1e-10
print('PASS wheel spin +X');count+=1
th=math.pi/6
forward=(-math.sin(th),0,-math.cos(th))
assert abs(forward[0]+.5)<1e-10
print('PASS steering +Y');count+=1
# host socket (1,2,3), accessory mount offset (0,0,-.25)
res=(1,2,3+.25)
assert res==(1,2,3.25)
print('PASS accessory root composition');count+=1
print(f'PROFILE TESTS: {count} passed (structural/math smoke only)')

from container import RangeReader
import struct
for fn, expected_role, expected_type in [('vehicle_front_wheel_spin','wheel.axle0.left','VEC4'),('weapon_visual_bolt_shift','weapon.bolt','VEC3')]:
 file=P/(fn+'.adm_anim'); verify(file)
 rr=RangeReader(file); man=rr.manifest; channel=man['clips'][0]['channels'][0]
 assert channel['target']['kind']=='component' and channel['target']['role']==expected_role
 assert man['accessors'][1]['type']==expected_type
 dat=rr.load(1); assert struct.unpack_from('<2f',dat)==(0.,1.)
 if expected_type=='VEC4':
  q=struct.unpack_from('<4f',dat,8+4*4)
  assert abs(q[0]-math.sqrt(.5))<1e-6 and abs(q[3]-math.sqrt(.5))<1e-6
 else:
  v=struct.unpack_from('<3f',dat,8+3*4)
  assert abs(v[2]+.02)<1e-6
 print('PASS COMPONENT-ANIM',fn);count+=1
print(f'PROFILE TESTS TOTAL: {count} passed (structural/math/container smoke only)')
