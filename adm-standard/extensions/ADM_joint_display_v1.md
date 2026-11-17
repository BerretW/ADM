# `ADM_joint_display_v1`

This normative ADM 1.0 extension carries the exact display frame and tail point for a joint
represented as an editable bone. Its schema version is `1.0.0`; its capability is
`ADM-JOINT-DISPLAY-1`. It does not change node transforms, skinning, inverse bind matrices or
animation semantics.

## Declaration and node data

The extension is attached to each node whose bone display geometry is specified:

```json
{
  "extensionsUsed": ["ADM_joint_display_v1"],
  "extensionsRequired": ["ADM_joint_display_v1"],
  "nodes": [{
    "extensions": {
      "ADM_joint_display_v1": {
        "version": "1.0.0",
        "displayFrame": [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1],
        "tail": [0,0.1,0]
      }
    }
  }]
}
```

The fragment shows the identity display frame only. Each extension object has exactly the required
members `version`, `displayFrame` and `tail`. `version` MUST equal `"1.0.0"`. `displayFrame` is a
finite, invertible, affine column-major MAT4. `tail` is a finite, nonzero VEC3. The extension object
MUST be present in the node's `extensions`; its name MUST appear in `extensionsUsed`. A producer
whose consumer must preserve this display geometry MUST also list it in `extensionsRequired`.

When `ADM_joint_display_v1` is required, every node referenced by every `skins[*].joints` array MUST
contain valid data for this extension. A producer MAY also attach it to non-skin nodes that it
represents as editable bones. An extension occurrence on any other node is still well-formed and
defines display geometry for that node.

## Coordinate and endpoint semantics

All matrices and vectors use ADM's coordinate system and model units. Let `W_node` be the node's
accumulated world matrix in its scene, and let `F` be `displayFrame`. `F` maps points from the
display-bone local frame into the node's frame. The display frame in model coordinates is:

```
W_display = W_node × F
head_model = W_display × [0,0,0,1]
tail_model = W_display × [tail.x,tail.y,tail.z,1]
```

The origin of `displayFrame` is the displayed bone head. Its basis specifies the complete local
orientation, including roll; `tail` is the exact endpoint in that local frame. Implementations MUST
use these values as authored and MUST NOT replace them with a child-joint position, a profile
heuristic, or a guessed terminal-bone length. Matrices and points are evaluated using the ordinary
node hierarchy, so model-root and ancestor transforms apply exactly once.

This extension specifies display/edit geometry only. It MUST NOT be applied to vertex skinning or
used to modify node transforms, inverse bind matrices, animation samples, role mappings or socket
frames. Those remain governed by ADM core and their respective extensions.

## Missing and unsupported data

An unknown required extension MUST be rejected under ADM §4. An unknown optional extension MAY be
ignored because it does not change core skinning or animation results. If the extension is absent,
the file specifies no exact display tail or roll. A reader MUST NOT claim to have reconstructed the
source bone shape from the joint hierarchy. An authoring tool that requires editable bones MUST
either report that the exact display geometry is unavailable or use an explicitly named,
non-interoperable repair mode; it MUST NOT silently substitute guessed geometry.

## Conformance

An implementation claiming `ADM-JOINT-DISPLAY-1` MUST validate and apply the frame and tail
semantics above. It MUST preserve the node extension through import/export without changing its
values except for the specified floating-point encoding. A Blender exporter with an editable
armature MUST write this extension for every exported bone node and mark it required; its importer
MUST reject incomplete or malformed required data instead of inferring endpoints.

- `JOINT-001`: compute head and tail from a translated, rotated, scaled node hierarchy.
- `JOINT-002`: preserve roll using the complete `displayFrame` basis.
- `JOINT-003`: reject missing data on any skin joint when the extension is required.
- `JOINT-004`: reject non-finite, non-affine, singular frames and zero-length tails.
- `JOINT-005`: reject an unsupported required extension and report when exact display data is absent.
