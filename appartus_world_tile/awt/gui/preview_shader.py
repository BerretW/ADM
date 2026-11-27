"""VTK material-preview shader extensions."""

from __future__ import annotations

import hashlib
import io
import os

import numpy as np
from PIL import Image

from ..material import MAX_TEXTURE_BYTES, MAX_TEXTURE_PIXELS, MapSlot, normal_preview_array, prepare_texture
from ..bake import _srgb_to_linear


_PARALLAX_GLSL = """
vec2 admUv = tcoordVCVSOutput;
vec2 admDx = dFdx(admUv);
vec2 admDy = dFdy(admUv);
vec3 admPosDx = dFdx(admPositionVC);
vec3 admPosDy = dFdy(admPositionVC);
float admDet = admDx.x * admDy.y - admDx.y * admDy.x;
vec3 admCross = cross(admPosDx, admPosDy);
if (gl_FrontFacing && abs(admDet) > 1e-12 && length(admCross) > 1e-12) {
    vec3 n = normalize(admCross);
    vec3 t0 = (admPosDx * admDy.y - admPosDy * admDx.y) / admDet;
    vec3 b0 = (admPosDy * admDx.x - admPosDx * admDy.x) / admDet;
    vec3 tangent = t0 - n * dot(n, t0);
    if (length(tangent) > 1e-12 && length(b0) > 1e-12) {
        vec3 t = normalize(tangent);
        vec3 b = normalize(cross(n, t)) * (dot(cross(n, t), b0) < 0.0 ? -1.0 : 1.0);
        vec3 v = cameraParallel == 1 ? vec3(0.0, 0.0, 1.0) : normalize(-admPositionVC);
        vec3 view = normalize(vec3(dot(v, t), dot(v, b), dot(v, n)));
        if (view.z > 0.0) {
            vec2 ray = -view.xy / max(view.z, 0.1) * admParallaxScale;
            if (admParallaxMode == 1) {
                float height = clamp(textureGrad(admHeight, admUv, admDx, admDy).r
                                     * admHeightScale + admHeightBias, 0.0, 1.0);
                vec2 offset = ray * (height - 0.5);
                offset *= min(1.0, admParallaxScale / max(length(offset), 1e-12));
                admUv += offset;
            } else {
                ray *= min(1.0, admParallaxScale / max(length(ray), 1e-12));
                int count = int(round(float(admMinSteps) + float(admMaxSteps - admMinSteps)
                                      * (1.0 - clamp(view.z, 0.0, 1.0))));
                float previousDepth = 0.0;
                float height = clamp(textureGrad(admHeight, admUv, admDx, admDy).r
                                     * admHeightScale + admHeightBias, 0.0, 1.0);
                float previousDelta = -(1.0 - height);
                for (int i = 1; i <= 256 && previousDelta < 0.0; ++i) {
                    if (i > count) break;
                    float depth = float(i) / float(count);
                    height = clamp(textureGrad(admHeight, admUv + ray * depth, admDx, admDy).r
                                   * admHeightScale + admHeightBias, 0.0, 1.0);
                    float delta = depth - (1.0 - height);
                    if (delta >= 0.0) {
                        float fraction = clamp(-previousDelta / (delta - previousDelta), 0.0, 1.0);
                        admUv += ray * mix(previousDepth, depth, fraction);
                        break;
                    }
                    previousDepth = depth;
                    previousDelta = delta;
                }
            }
        }
    }
}
//VTK::UniformFlow::Impl
"""


def _mip_chain_bytes(shape, itemsize: int) -> int:
    height, width = shape[:2]
    components = int(np.prod(shape[2:])) if len(shape) > 2 else 1
    total = 0
    while True:
        total += width * height * components * itemsize
        if width == 1 and height == 1:
            return total
        width = max(1, width // 2)
        height = max(1, height // 2)


def _height_samples(slot: MapSlot) -> np.ndarray:
    with open(slot.path, "rb") as stream:
        magic = stream.read(12)
        if magic[:4] in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
            from ..adm_export import _core, _multichannel_tiff16
            _core()
            prepared = _multichannel_tiff16(slot.path, os.path.splitext(os.path.basename(slot.path))[0])
        else:
            prepared = None
        if magic.startswith((b"DDS ", b"\xabKTX 20\xbb\r\n\x1a\n")):
            stream.seek(0)
            data = stream.read(MAX_TEXTURE_BYTES + 1)
            if len(data) > MAX_TEXTURE_BYTES:
                raise ValueError("GPU height texture exceeds the file size limit")
            from ..adm_export import _core
            _core()
            from adm_blender.core import gputex
            try:
                info = gputex.parse(data, gputex.mime_of(data), strict=True)
            except gputex.GpuTextureError:
                info = None
            if info is not None and info["kind"] == "R16":
                if info["width"] * info["height"] > MAX_TEXTURE_PIXELS:
                    raise ValueError(f"Texture dimensions exceed the {MAX_TEXTURE_PIXELS:,}-pixel limit")
                scalar = gputex.decode_scalar_level(data, info).astype(np.float32) / 65535.0
                samples = scalar if slot.channel == 0 else np.full_like(scalar, 1.0 if slot.channel == 3 else 0.0)
                return 1.0 - samples if slot.invert else samples
    if prepared is None:
        prepared = prepare_texture(slot.path)
    png16 = prepared.data.startswith(b"\x89PNG\r\n\x1a\n") and prepared.data[24] == 16
    if png16:
        from vtkmodules.util.numpy_support import vtk_to_numpy
        from vtkmodules.vtkIOImage import vtkPNGReader

        reader = vtkPNGReader()
        try:
            from vtkmodules.vtkIOCore import vtkMemoryResourceStream
        except ImportError:
            vtkMemoryResourceStream = None
        if vtkMemoryResourceStream is not None and hasattr(reader, "SetStream"):
            stream = vtkMemoryResourceStream()
            stream.SetBuffer(prepared.data, len(prepared.data))
            reader.SetStream(stream)
        else:
            reader.SetMemoryBuffer(prepared.data)
            reader.SetMemoryBufferLength(len(prepared.data))
        reader.Update()
        image = reader.GetOutput()
        scalars = image.GetPointData().GetScalars()
        width, height, depth = image.GetDimensions()
        if reader.GetErrorCode() or scalars is None or depth != 1 or (width, height) != (prepared.width, prepared.height):
            raise ValueError(f"Could not decode 16-bit PNG height texture: {slot.path}")
        values = vtk_to_numpy(scalars)
        if values.dtype != np.uint16:
            raise ValueError(f"16-bit PNG height texture lost precision: {slot.path}")
        channels = scalars.GetNumberOfComponents()
        values = values.reshape(height, width, channels)[::-1]
        if slot.channel == 3 and channels in (1, 3):
            samples = np.ones((height, width), dtype=np.float32)
        else:
            channel = (0 if slot.channel < 3 else 1) if channels == 2 else (
                0 if channels == 1 else slot.channel)
            samples = values[..., channel].astype(np.float32) / 65535.0
        return 1.0 - samples if slot.invert else samples
    with Image.open(io.BytesIO(prepared.data)) as image:
        if image.mode in ("I", "I;16", "I;16B", "I;16L"):
            values = np.asarray(image, dtype=np.float32)
            peak = 65535.0 if image.mode.startswith("I;16") or values.max() > 255 else 255.0
            samples = np.ones_like(values) if slot.channel == 3 else values / peak
        else:
            samples = np.asarray(image.convert("RGBA"), dtype=np.float32)[..., slot.channel] / 255.0
    return 1.0 - samples if slot.invert else samples


def _install_view_position(shader, asset_position=False):
    shader.AddVertexShaderReplacement(
        "//VTK::Camera::Dec", True, "//VTK::Camera::Dec\nuniform mat4 MCVCMatrix;", False)
    shader.AddVertexShaderReplacement(
        "uniform mat4 MCVCMatrix;", False,
        "#ifndef ADM_MCVC_MATRIX_DECLARED\n#define ADM_MCVC_MATRIX_DECLARED\n"
        "uniform mat4 MCVCMatrix;\n#endif", True)
    declarations = "//VTK::PositionVC::Dec\nout vec3 admPositionVC;"
    if asset_position:
        declarations += "\nout vec3 admAssetPosition;"
    shader.AddVertexShaderReplacement("//VTK::PositionVC::Dec", True, declarations, False)
    implementation = "//VTK::PositionVC::Impl\nadmPositionVC = (MCVCMatrix * vertexMC).xyz;"
    if asset_position:
        implementation += "\nadmAssetPosition = vertexMC.xyz;"
    shader.AddVertexShaderReplacement(
        "//VTK::PositionVC::Impl", True, implementation, False)


def install_parallax(actor, pv, surface, material):
    """Apply a per-fragment, view-dependent parallax effect to a single PBR surface."""
    if material.parallax_mode == "NONE" or not surface.height_map.path or surface.parallax_scale == 0:
        return False
    if material.parallax_mode not in ("PARALLAX", "PARALLAX_OCCLUSION"):
        raise ValueError(f"Unknown parallax mode: {material.parallax_mode}")
    if not 1 <= material.parallax_min_steps <= material.parallax_max_steps <= 256:
        raise ValueError("POM steps must satisfy 1 <= minimum <= maximum <= 256")
    height = pv.Texture(_height_samples(surface.height_map))
    height.repeat = True
    height.interpolate = True
    actor.prop.SetTexture("admHeight", height)
    shader = actor.GetShaderProperty()
    uniforms = shader.GetFragmentCustomUniforms()
    uniforms.SetUniformf("admParallaxScale", float(surface.parallax_scale))
    uniforms.SetUniformf("admHeightScale", float(surface.height_scale))
    uniforms.SetUniformf("admHeightBias", float(surface.height_bias))
    uniforms.SetUniformi("admParallaxMode", 1 if material.parallax_mode == "PARALLAX" else 2)
    uniforms.SetUniformi("admMinSteps", int(material.parallax_min_steps))
    uniforms.SetUniformi("admMaxSteps", int(material.parallax_max_steps))
    _install_view_position(shader)
    shader.AddFragmentShaderReplacement(
        "//VTK::PositionVC::Dec", True, "//VTK::PositionVC::Dec\nin vec3 admPositionVC;", False)
    shader.AddFragmentShaderReplacement("//VTK::UniformFlow::Impl", True, _PARALLAX_GLSL, False)
    for name in ("albedoTex", "materialTex", "normalTex", "emissiveTex"):
        shader.AddFragmentShaderReplacement(
            f"texture({name}, tcoordVCVSOutput)", False,
            f"textureGrad({name}, admUv, admDx, admDy)", True,
        )
    return True


_LAYER_FUNCTIONS = """
vec2 admLayerOffset(sampler2D heightTex, vec2 uv, vec2 dx, vec2 dy,
                    vec3 view, float scale, float heightScale, float heightBias,
                    int mode, int minSteps, int maxSteps) {
    if (mode == 0 || !gl_FrontFacing || view.z <= 0.0 || scale <= 0.0) return vec2(0.0);
    vec2 ray = -view.xy / max(view.z, 0.1) * scale;
    float h = clamp(textureGrad(heightTex, uv, dx, dy).r * heightScale + heightBias, 0.0, 1.0);
    if (mode == 1) {
        vec2 offset = ray * (h - 0.5);
        return offset * min(1.0, scale / max(length(offset), 1e-12));
    }
    ray *= min(1.0, scale / max(length(ray), 1e-12));
    int count = int(round(float(minSteps) + float(maxSteps - minSteps) * (1.0 - clamp(view.z, 0.0, 1.0))));
    float previousDepth = 0.0;
    float previousDelta = -(1.0 - h);
    for (int i = 1; i <= 256 && previousDelta < 0.0; ++i) {
        if (i > count) break;
        float depth = float(i) / float(count);
        h = clamp(textureGrad(heightTex, uv + ray * depth, dx, dy).r * heightScale + heightBias, 0.0, 1.0);
        float delta = depth - (1.0 - h);
        if (delta >= 0.0) {
            return ray * mix(previousDepth, depth, clamp(-previousDelta / (delta - previousDelta), 0.0, 1.0));
        }
        previousDepth = depth;
        previousDelta = delta;
    }
    return vec2(0.0);
}
"""

_LAYER_FRAME = """
vec2 admBaseUv = tcoordVCVSOutput;
vec2 admBaseDx = dFdx(admBaseUv);
vec2 admBaseDy = dFdy(admBaseUv);
vec3 admPosDx = dFdx(admPositionVC);
vec3 admPosDy = dFdy(admPositionVC);
float admDet = admBaseDx.x * admBaseDy.y - admBaseDx.y * admBaseDy.x;
vec3 admCross = cross(admPosDx, admPosDy);
vec3 admView = vec3(0.0);
if (abs(admDet) > 1e-12 && length(admCross) > 1e-12) {
    vec3 n = normalize(admCross);
    vec3 t0 = (admPosDx * admBaseDy.y - admPosDy * admBaseDx.y) / admDet;
    vec3 b0 = (admPosDy * admBaseDx.x - admPosDx * admBaseDy.x) / admDet;
    vec3 tangent = t0 - n * dot(n, t0);
    if (length(tangent) > 1e-12 && length(b0) > 1e-12) {
        vec3 t = normalize(tangent);
        vec3 b = normalize(cross(n, t)) * (dot(cross(n, t), b0) < 0.0 ? -1.0 : 1.0);
        vec3 v = cameraParallel == 1 ? vec3(0.0, 0.0, 1.0) : normalize(-admPositionVC);
        admView = normalize(vec3(dot(v, t), dot(v, b), dot(v, n)));
    }
}
"""


def install_layered_preview(actor, pv, surfaces, weights, material, *, height_blend, transition, strength,
                            texture_units, vertex_weights=None, uv_scales=None, diagnostic=None,
                            texture_cache=None, texture_budget_bytes=None, control_map_pixels=None):
    """Bind independent layer textures and evaluate the material at each fragment."""
    if material.parallax_mode not in ("NONE", "PARALLAX", "PARALLAX_OCCLUSION"):
        raise ValueError(f"Unsupported layered parallax mode: {material.parallax_mode}")
    if not 1 <= material.parallax_min_steps <= material.parallax_max_steps <= 256:
        raise ValueError("POM steps must satisfy 1 <= minimum <= maximum <= 256")
    if len(surfaces) != len(weights) or not 1 <= len(surfaces) <= 4 or sum(weights) <= 0:
        raise ValueError("Layer preview requires one to four surfaces with positive total weight")
    if not np.isfinite(weights).all() or any(weight < 0 for weight in weights):
        raise ValueError("Layer weights must be finite and non-negative")
    if not np.isfinite(transition) or transition <= 0 or not np.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError("Height transition must be positive and strength must be in 0..1")
    if uv_scales is not None and (len(uv_scales) != len(surfaces)
                                  or not np.isfinite(uv_scales).all()
                                  or any(scale <= 0 for scale in uv_scales)):
        raise ValueError("Layer UV scales must be finite and positive")
    if diagnostic is not None:
        kind, layer = diagnostic
        if kind not in ("base", "final", "offset", "control") or not 0 <= layer < (
                4 if kind == "control" else len(surfaces)):
            raise ValueError("Unknown layer diagnostic")
    if vertex_weights is not None:
        if not hasattr(actor.mapper, "MapDataArrayToVertexAttribute"):
            raise ValueError("Vertex-weight preview requires a VTK polydata mapper")
        if actor.mapper.GetScalarVisibility():
            raise ValueError("Vertex-weight preview requires scalar coloring to be disabled")
        dataset = pv.wrap(actor.mapper.GetInput())
        if vertex_weights not in dataset.point_data:
            raise ValueError(f"Missing point-weight array: {vertex_weights}")
        values = np.asarray(dataset.point_data[vertex_weights])
        if values.shape != (dataset.n_points, 4) or not np.isfinite(values).all() or np.any(values < 0):
            raise ValueError("Point weights must have four finite non-negative components")
    if control_map_pixels is not None:
        control_map_pixels = np.asarray(control_map_pixels)
        if (control_map_pixels.ndim != 3 or control_map_pixels.shape[2] != 4
                or not 2 <= control_map_pixels.shape[0] <= 4096
                or not 2 <= control_map_pixels.shape[1] <= 4096
                or control_map_pixels.dtype != np.uint8):
            raise ValueError("Control Map preview needs a four-channel 8-bit image from 2 to 4096 pixels per side")
    if diagnostic is not None and diagnostic[0] == "control" and control_map_pixels is None:
        raise ValueError("Control Map channel diagnostics require a Control Map image")
    macro = material.macro_color
    macro_enabled = bool(macro.path)
    if macro_enabled:
        macro.validate()

    textures = {}
    lines = [_LAYER_FRAME]
    if control_map_pixels is None and vertex_weights is not None:
        components = "rgba"[:len(surfaces)]
        lines.append("float admBaseWeightSum = " + " + ".join(f"admWeightsVC.{c}" for c in components) + ";")

    def number(value):
        value = float(value)
        if not np.isfinite(value):
            raise ValueError("Layer preview settings must be finite")
        text = format(value, ".9g")
        return text if "." in text or "e" in text else text + ".0"

    def check_budget(size):
        if texture_cache is not None and texture_budget_bytes is not None:
            used = sum(size for _, size in texture_cache.values())
            if used + size > texture_budget_bytes:
                raise ValueError(f"Detailed material exceeds the {texture_budget_bytes // (1024 * 1024):,} MiB "
                                 "decoded texture budget; select fewer tiles or smaller textures")

    def bind(name, pixels, srgb=False, repeat=True):
        allocation_bytes = _mip_chain_bytes(pixels.shape, pixels.dtype.itemsize)
        check_budget(allocation_bytes)
        texture = pv.Texture(pixels)
        texture.repeat = repeat
        texture.interpolate = True
        texture.mipmap = True
        texture.SetUseSRGBColorSpace(srgb)
        textures[name] = texture

    def color_map(name, path, normal=False):
        key = ("color", path, normal)
        if texture_cache is not None and key in texture_cache:
            textures[name] = texture_cache[key][0]
            return
        if normal:
            pixels = normal_preview_array(path)
        else:
            prepared = prepare_texture(path)
            with Image.open(io.BytesIO(prepared.data)) as image:
                pixels = np.asarray(image.convert("RGBA"))
        bind(name, pixels, not normal)
        if texture_cache is not None:
            texture_cache[key] = (textures[name], _mip_chain_bytes(pixels.shape, pixels.dtype.itemsize))

    def scalar_map(name, slot):
        key = ("scalar", slot.path, slot.channel, slot.invert)
        if texture_cache is not None and key in texture_cache:
            textures[name] = texture_cache[key][0]
            return
        pixels = _height_samples(slot)
        bind(name, pixels)
        if texture_cache is not None:
            texture_cache[key] = (textures[name], _mip_chain_bytes(pixels.shape, pixels.dtype.itemsize))

    def scalar_maps(surface, index):
        groups = {}
        for label, slot in (("Height", surface.height_map), ("Ao", surface.ao_map),
                            ("Roughness", surface.roughness_map), ("Metallic", surface.metallic_map)):
            if slot.path:
                prepared = prepare_texture(slot.path)
                groups.setdefault((prepared.width, prepared.height), []).append((label, slot))
        bindings = {}
        for (width, height), group in groups.items():
            name = f"admLayer{group[0][0]}{index}"
            if len(group) == 1:
                scalar_map(name, group[0][1])
            else:
                key = ("scalar_group", tuple((slot.path, slot.channel, slot.invert) for _, slot in group))
                if texture_cache is not None and key in texture_cache:
                    textures[name] = texture_cache[key][0]
                else:
                    check_budget(_mip_chain_bytes((height, width, 4), np.dtype(np.float32).itemsize))
                    pixels = np.ones((height, width, 4), dtype=np.float32)
                    for component, (_, slot) in enumerate(group):
                        pixels[..., component] = _height_samples(slot)
                    bind(name, pixels)
                    if texture_cache is not None:
                        texture_cache[key] = (textures[name], _mip_chain_bytes(pixels.shape, pixels.dtype.itemsize))
            for component, (label, _) in enumerate(group):
                bindings[label] = (name, "rgba"[component])
        return bindings

    if control_map_pixels is not None:
        control_hash = hashlib.blake2b(control_map_pixels, digest_size=16).hexdigest()
        control_key = ("control_map", control_map_pixels.shape, control_hash)
        if texture_cache is not None and control_key in texture_cache:
            textures["admControlMap"] = texture_cache[control_key][0]
        else:
            bind("admControlMap", control_map_pixels, repeat=False)
            if texture_cache is not None:
                texture_cache[control_key] = (
                    textures["admControlMap"],
                    _mip_chain_bytes(control_map_pixels.shape, control_map_pixels.dtype.itemsize))
        lines += [
            "vec4 admControlWeights = textureGrad(admControlMap, admBaseUv, admBaseDx, admBaseDy);",
            "float admBaseWeightSum = dot(admControlWeights, vec4(1.0));",
        ]
    if macro_enabled:
        color_map("admMacroColor", macro.path)
        if macro.projection == "LOCAL_UV":
            macro_source = "admBaseUv"
        elif macro.projection == "SHARED_WORLD_XZ":
            macro_source = f"(admAssetPosition.xz - vec2({number(macro.origin[0])}, {number(macro.origin[1])}))"
        else:
            raise ValueError(f"Unknown Macro Color projection: {macro.projection}")
        lines += [
            f"vec2 admMacroUv = {macro_source} * vec2({number(macro.scale[0])}, "
            f"{number(macro.scale[1])}) + vec2({number(macro.offset[0])}, {number(macro.offset[1])});",
            "vec2 admMacroDx = dFdx(admMacroUv);",
            "vec2 admMacroDy = dFdy(admMacroUv);",
            "vec4 admMacroSample = textureGrad(admMacroColor, admMacroUv, admMacroDx, admMacroDy);",
        ]

    total = sum(weights)
    mode = {"NONE": 0, "PARALLAX": 1, "PARALLAX_OCCLUSION": 2}[material.parallax_mode]
    for i, (surface, weight) in enumerate(zip(surfaces, weights)):
        if surface.repeat_m <= 0:
            raise ValueError(f"Surface '{surface.name}' repeat must be positive")
        repeat = number(uv_scales[i] if uv_scales is not None else 15.0 / surface.repeat_m)
        if control_map_pixels is not None:
            weight_expr = (f"(admBaseWeightSum > 0.0 ? admControlWeights.{'rgba'[i]} / admBaseWeightSum"
                           f" : {1 if i == 0 else 0}.0)")
        elif vertex_weights is not None:
            weight_expr = (f"(admBaseWeightSum > 0.0 ? admWeightsVC.{'rgba'[i]} / admBaseWeightSum"
                           f" : {1 if i == 0 else 0}.0)")
        else:
            weight_expr = number(weight / total)
        lines += [f"vec2 admUV{i} = admBaseUv * {repeat};",
                  f"vec2 admDX{i} = admBaseDx * {repeat};",
                  f"vec2 admDY{i} = admBaseDy * {repeat};",
                  f"float admWeight{i} = {weight_expr};",
                  f"float admBaseWeight{i} = admWeight{i};",
                  f"vec2 admOffset{i} = vec2(0.0);"]
        scalar_bindings = scalar_maps(surface, i)
        if surface.height_map.path:
            name, _ = scalar_bindings["Height"]
            lines.append(f"admOffset{i} = admLayerOffset({name}, admUV{i}, admDX{i}, admDY{i}, admView, "
                         f"{number(surface.parallax_scale)}, {number(surface.height_scale)}, "
                         f"{number(surface.height_bias)}, {mode}, {material.parallax_min_steps}, "
                         f"{material.parallax_max_steps});")
            lines.append(f"admUV{i} += admOffset{i};")
            lines.append(f"float admHeight{i} = clamp(textureGrad({name}, admUV{i}, admDX{i}, admDY{i}).r "
                         f"* {number(surface.height_scale)} + {number(surface.height_bias)}, 0.0, 1.0);")
        else:
            lines.append(f"float admHeight{i} = 0.5;")

        for label, slot in (("Ao", surface.ao_map), ("Roughness", surface.roughness_map),
                            ("Metallic", surface.metallic_map)):
            if slot.path:
                name, component = scalar_bindings[label]
                lines.append(f"float adm{label}{i} = textureGrad({name}, admUV{i}, admDX{i}, admDY{i}).{component};")
            else:
                lines.append(f"float adm{label}{i} = 1.0;")
        for label, path, normal in (("Albedo", surface.albedo, False), ("Normal", surface.normal, True),
                                    ("Emission", surface.emission, False)):
            if path:
                name = f"admLayer{label}{i}"
                color_map(name, path, normal)
                expr = f"textureGrad({name}, admUV{i}, admDX{i}, admDY{i}).rgb"
                if normal:
                    lines.append(f"vec3 admNormalRaw{i} = {expr} * 2.0 - 1.0;")
                    expr = (f"(length(admNormalRaw{i}) > 1e-12 ? normalize(admNormalRaw{i}) "
                            ": vec3(0.0, 0.0, 1.0))")
            else:
                expr = "vec3(0.0, 0.0, 1.0)" if normal else (
                    "vec3(1.0)" if label == "Albedo" else "vec3(0.0)")
            lines.append(f"vec3 adm{label}{i} = {expr};")
        tint = _srgb_to_linear(np.asarray(surface.color, dtype=np.float64) / 255.0)
        lines += [f"admAlbedo{i} *= vec3({', '.join(number(v) for v in tint)});",
                  f"admAo{i} = mix(1.0, admAo{i}, {number(surface.ao_strength)});",
                  f"admRoughness{i} *= {number(surface.roughness)};",
                  f"admMetallic{i} *= {number(surface.metallic)};"]

    if len(textures) + 4 > texture_units:
        raise ValueError(f"Layered preview needs {len(textures) + 4} texture units; renderer has {texture_units}")
    count = len(surfaces)
    if height_blend and strength > 0 and any(surface.height_map.path for surface in surfaces):
        lines.append("float admHighest = -1.0;")
        for i in range(count):
            lines.append(f"if (admWeight{i} > 0.0) admHighest = max(admHighest, admHeight{i});")
        for i in range(count):
            lines.append(f"float admQ{i} = admWeight{i} * exp(clamp((admHeight{i} - admHighest) "
                         f"/ {number(transition)}, -80.0, 0.0));")
        lines.append("float admQSum = " + " + ".join(f"admQ{i}" for i in range(count)) + ";")
        for i in range(count):
            lines.append(f"admWeight{i} = mix(admWeight{i}, admQ{i} / admQSum, {number(strength)});")
    lines.append("float admWeightSum = " + " + ".join(f"admWeight{i}" for i in range(count)) + ";")
    for i in range(count):
        lines.append(f"admWeight{i} /= admWeightSum;")
    if macro_enabled:
        if macro.blend_mode not in ("MULTIPLY", "TINT", "LERP"):
            raise ValueError(f"Unknown Macro Color blend mode: {macro.blend_mode}")
        for i in range(count):
            factor = number(float(macro.strength) * float(macro.layer_influence[i]))
            if macro.blend_mode == "MULTIPLY":
                lines.append(f"admAlbedo{i} *= mix(vec3(1.0), admMacroSample.rgb, {factor});")
            elif macro.blend_mode == "TINT":
                lines.append(f"admAlbedo{i} *= mix(vec3(1.0), admMacroSample.rgb, "
                             f"{factor} * admMacroSample.a);")
            else:
                lines.append(f"admAlbedo{i} = mix(admAlbedo{i}, admMacroSample.rgb, "
                             f"{factor} * admMacroSample.a);")
    lines += ["vec3 admMixedAlbedo = vec3(0.0);", "vec3 admMixedNormal = vec3(0.0);",
              "vec3 admMixedEmission = vec3(0.0);", "vec3 admMixedOrm = vec3(0.0);"]
    for i in range(count):
        lines += [f"admMixedAlbedo += admWeight{i} * admAlbedo{i};",
                  f"admMixedNormal += admWeight{i} * admNormal{i};",
                  f"admMixedEmission += admWeight{i} * admEmission{i};",
                  f"admMixedOrm += admWeight{i} * vec3(admAo{i}, admRoughness{i}, admMetallic{i});"]
    lines.append("admMixedNormal = length(admMixedNormal) > 1e-12 ? normalize(admMixedNormal) : vec3(0.0, 0.0, 1.0);")
    lines.append("//VTK::UniformFlow::Impl")
    for name, texture in textures.items():
        actor.prop.SetTexture(name, texture)
    shader = actor.GetShaderProperty()
    _install_view_position(shader, asset_position=macro_enabled and macro.projection == "SHARED_WORLD_XZ")
    if vertex_weights is not None:
        from vtkmodules.vtkCommonDataModel import vtkDataObject

        actor.mapper.MapDataArrayToVertexAttribute(
            "admWeightsMC", vertex_weights, vtkDataObject.FIELD_ASSOCIATION_POINTS, -1)
        shader.AddVertexShaderReplacement(
            "//VTK::Color::Dec", True,
            "//VTK::Color::Dec\nin vec4 admWeightsMC;\nout vec4 admWeightsVC;", False)
        shader.AddVertexShaderReplacement(
            "//VTK::Color::Impl", True, "//VTK::Color::Impl\nadmWeightsVC = admWeightsMC;", False)
        shader.AddFragmentShaderReplacement(
            "//VTK::Color::Dec", True, "//VTK::Color::Dec\nin vec4 admWeightsVC;", False)
    position_inputs = "in vec3 admPositionVC;"
    if macro_enabled and macro.projection == "SHARED_WORLD_XZ":
        position_inputs += "\nin vec3 admAssetPosition;"
    shader.AddFragmentShaderReplacement(
        "//VTK::PositionVC::Dec", True,
        "//VTK::PositionVC::Dec\n" + position_inputs + "\n" + _LAYER_FUNCTIONS, False)
    shader.AddFragmentShaderReplacement("//VTK::UniformFlow::Impl", True, "\n".join(lines), False)
    expressions = {"albedoTex": "vec4(admMixedAlbedo, 1.0)",
                   "materialTex": "vec4(admMixedOrm, 1.0)",
                   "normalTex": "vec4(admMixedNormal * 0.5 + 0.5, 1.0)",
                   "emissiveTex": "vec4(admMixedEmission, 1.0)"}
    if diagnostic is not None:
        kind, layer = diagnostic
        if kind == "control":
            color = f"vec3(admControlWeights.{'rgba'[layer]})"
        elif kind == "offset":
            scale = number(max(float(surfaces[layer].parallax_scale), 1e-12))
            color = f"vec3(clamp(vec2(0.5) + admOffset{layer} / (2.0 * {scale}), 0.0, 1.0), 0.5)"
        else:
            weight = f"admBaseWeight{layer}" if kind == "base" else f"admWeight{layer}"
            color = f"vec3({weight})"
        expressions["albedoTex"] = "vec4(0.0, 0.0, 0.0, 1.0)"
        expressions["emissiveTex"] = f"vec4({color}, 1.0)"
    for name, expr in expressions.items():
        shader.AddFragmentShaderReplacement(f"texture({name}, tcoordVCVSOutput)", False, expr, True)
