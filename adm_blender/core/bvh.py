"""Bounded parser and structural analysis for Biovision Hierarchy (BVH) motion files."""

from dataclasses import dataclass
import math
import os
import re
from pathlib import Path

from . import constants as K
from .rolemap import suggest_role
from . import skeleton_profiles as SP

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_NODES = 2048
MAX_DEPTH = 256
MAX_FRAMES = 1_000_000
MAX_SAMPLES = 1_000_000

_TOKEN = re.compile(r"\s+|[{}]|[^\s{}]+")
_NUMBER = re.compile(r"[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?\Z")
_CHANNELS = {
    "Xposition", "Yposition", "Zposition",
    "Xrotation", "Yrotation", "Zrotation",
}
_ALIASES = {
    "hipjoint": "hips", "pelvis": "hips",
    "lowerback": "spine", "upperback": "chest", "thorax": "upperchest",
    "lclavicle": "leftshoulder", "rclavicle": "rightshoulder",
    "lhumerus": "leftupperarm", "rhumerus": "rightupperarm",
    "lradius": "leftlowerarm", "rradius": "rightlowerarm",
    "lulna": "leftlowerarm", "rulna": "rightlowerarm",
    "lfemur": "leftupperleg", "rfemur": "rightupperleg",
    "ltibia": "leftlowerleg", "rtibia": "rightlowerleg",
    "lankle": "leftfoot", "rankle": "rightfoot",
    "ltoe": "lefttoes", "rtoe": "righttoes",
}


class BvhError(ValueError):
    """Malformed or unsupported BVH data."""

    def __init__(self, message, offset=None):
        self.offset = offset
        suffix = f" at character {offset}" if offset is not None else ""
        super().__init__(message + suffix)


@dataclass(frozen=True)
class BvhNode:
    name: str
    parent: int | None
    offset: tuple[float, float, float]
    channels: tuple[str, ...]
    end_sites: tuple[tuple[float, float, float], ...] = ()


@dataclass(frozen=True)
class BvhMotion:
    nodes: tuple[BvhNode, ...]
    frames: tuple[tuple[float, ...], ...]
    frame_time: float

    @property
    def frame_count(self):
        return len(self.frames)

    @property
    def duration(self):
        return max(0, self.frame_count - 1) * self.frame_time

    @property
    def channel_count(self):
        return sum(len(node.channels) for node in self.nodes)

    @property
    def frame_rate(self):
        return 1.0 / self.frame_time


class _Tokens:
    def __init__(self, text):
        self._matches = iter(_TOKEN.finditer(text))
        self.current = None
        self.offset = 0
        self.advance()

    def advance(self):
        for match in self._matches:
            if not match.group().isspace():
                self.current = match.group()
                self.offset = match.start()
                return
        self.current = None
        self.offset = -1

    def take(self, expected=None):
        token = self.current
        if token is None:
            raise BvhError(f"expected {expected or 'a token'}, reached end of file")
        if expected is not None and token.lower() != expected.lower():
            raise BvhError(f"expected {expected!r}, found {token!r}", self.offset)
        self.advance()
        return token

    def number(self, *, integer=False):
        token = self.take()
        if not _NUMBER.fullmatch(token):
            raise BvhError(f"expected a finite number, found {token!r}", self.offset)
        try:
            value = float(token)
        except ValueError as exc:
            raise BvhError(f"invalid number {token!r}", self.offset) from exc
        if not math.isfinite(value):
            raise BvhError(f"number must be finite, found {token!r}", self.offset)
        if integer and (not value.is_integer() or value < 0):
            raise BvhError(f"expected a nonnegative integer, found {token!r}", self.offset)
        return int(value) if integer else value


class _Parser:
    def __init__(self, text):
        self.tokens = _Tokens(text)
        self.nodes = []
        self.names = set()
        self.channel_count = 0

    def parse(self):
        t = self.tokens
        t.take("HIERARCHY")
        t.take("ROOT")
        self._node(None, 0)
        t.take("MOTION")
        t.take("Frames:")
        frame_count = t.number(integer=True)
        if frame_count < 1 or frame_count > MAX_FRAMES:
            raise BvhError(f"frame count must be between 1 and {MAX_FRAMES}")
        t.take("Frame")
        t.take("Time:")
        frame_time = t.number()
        if frame_time <= 0:
            raise BvhError("Frame Time must be finite and greater than zero")
        if frame_count * self.channel_count > MAX_SAMPLES:
            raise BvhError(f"motion exceeds the {MAX_SAMPLES} sample safety limit")
        frames = []
        for frame_index in range(frame_count):
            values = tuple(t.number() for _ in range(self.channel_count))
            frames.append(values)
            if frame_index + 1 < frame_count and t.current is None:
                raise BvhError(f"expected {frame_count} frames, found {frame_index + 1}")
        if t.current is not None:
            raise BvhError(f"unexpected trailing token {t.current!r}", t.offset)
        return BvhMotion(tuple(self.nodes), tuple(frames), frame_time)

    def _node(self, parent, depth):
        t = self.tokens
        if depth > MAX_DEPTH:
            raise BvhError(f"skeleton nesting exceeds {MAX_DEPTH}")
        name = t.take()
        if name in {"{", "}"}:
            raise BvhError(f"invalid joint name {name!r}", t.offset)
        if name in self.names:
            raise BvhError(f"duplicate joint name {name!r}", t.offset)
        if len(self.nodes) >= MAX_NODES:
            raise BvhError(f"skeleton exceeds {MAX_NODES} joints")
        self.names.add(name)
        index = len(self.nodes)
        self.nodes.append(None)
        t.take("{")
        t.take("OFFSET")
        offset = tuple(t.number() for _ in range(3))
        channels = ()
        end_sites = []
        has_channels = False
        while t.current is not None and t.current != "}":
            keyword = t.take()
            if keyword.upper() == "CHANNELS":
                if has_channels:
                    raise BvhError(f"joint {name!r} has duplicate CHANNELS declarations")
                has_channels = True
                count = t.number(integer=True)
                if count > 6:
                    raise BvhError(f"joint {name!r} declares more than six channels")
                channels = tuple(t.take() for _ in range(count))
                if any(channel not in _CHANNELS for channel in channels):
                    bad = next(channel for channel in channels if channel not in _CHANNELS)
                    raise BvhError(f"unsupported channel {bad!r} on joint {name!r}")
                if len(set(channels)) != len(channels):
                    raise BvhError(f"joint {name!r} contains duplicate channels")
                self.channel_count += count
            elif keyword.upper() == "JOINT":
                self._node(index, depth + 1)
            elif keyword.lower() == "end":
                t.take("Site")
                t.take("{")
                t.take("OFFSET")
                end_sites.append(tuple(t.number() for _ in range(3)))
                t.take("}")
            elif keyword.upper() == "MOTION":
                raise BvhError("expected '}' before MOTION", t.offset)
            else:
                raise BvhError(f"unsupported hierarchy token {keyword!r}", t.offset)
        if not has_channels:
            raise BvhError(f"joint {name!r} is missing CHANNELS")
        t.take("}")
        self.nodes[index] = BvhNode(name, parent, offset, channels, tuple(end_sites))


def parse_bvh_text(text):
    """Parse BVH text into an immutable hierarchy and frame table with bounded allocation."""
    if not isinstance(text, str):
        raise TypeError("BVH input must be text")
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise BvhError(f"file exceeds the {MAX_FILE_BYTES}-byte limit")
    prefix = text.lstrip("\ufeff \t\r\n").lower()
    if prefix.startswith(("<!doctype html", "<html", "<head", "<body")):
        raise BvhError("input appears to be HTML, not BVH; download the raw .bvh file instead")
    return _Parser(text).parse()


def parse_bvh_file(filepath):
    """Read and parse one local BVH file, rejecting oversized or invalid UTF-8 input."""
    path = Path(os.fspath(filepath))
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise BvhError(f"file exceeds the {MAX_FILE_BYTES}-byte limit")
        data = path.read_bytes()
    except OSError:
        raise
    if len(data) > MAX_FILE_BYTES:
        raise BvhError(f"file exceeds the {MAX_FILE_BYTES}-byte limit")
    try:
        text = data.decode("utf-8-sig", "strict")
    except UnicodeDecodeError as exc:
        raise BvhError("file is not valid UTF-8", exc.start) from exc
    return parse_bvh_text(text)


def _bvh_name_key(name):
    compact = re.sub(r"[^a-z0-9]", "", name.lower())
    return _ALIASES.get(compact, compact)


def analyze_skeleton(motion):
    """Return cautious humanoid mapping suggestions and diagnostics; never asserts conformance."""
    mapped = {}
    used = set()
    for node in motion.nodes:
        role = suggest_role(node.name)
        if role is None:
            role = suggest_role(_bvh_name_key(node.name))
        if role is not None and role not in used:
            mapped[node.name] = role
            used.add(role)
    required = set(SP.required_roles(SP.HUMANOID))
    missing = sorted(required - used)
    diagnostics = []
    if not motion.nodes:
        diagnostics.append("skeleton has no joints")
    if missing:
        diagnostics.append("missing required humanoid roles: " + ", ".join(missing))
    if "hips" in mapped.values():
        hips = next(node for node in motion.nodes if mapped.get(node.name) == "hips")
        children = [node for node in motion.nodes if node.parent == motion.nodes.index(hips)]
        if not children:
            diagnostics.append("mapped hips joint has no child joints")
    confidence = "high" if not missing else "low" if len(mapped) < 4 else "medium"
    return {
        "profile": "humanoid.vrm1" if not missing else None,
        "confidence": confidence,
        "mapping": mapped,
        "missingRoles": missing,
        "unmappedJoints": [node.name for node in motion.nodes if node.name not in mapped],
        "diagnostics": diagnostics,
        "semanticCompatible": False,
        "semanticNote": "Name and hierarchy suggestions are not ADM reference-pose or retarget validation.",
    }
