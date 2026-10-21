"""Lossless tokenizer / tree for SpecsIntact .SEC files.

.SEC files are XML (windows-1252). We do NOT use an XML library for the
primary representation because the whole point of Phase 0 is byte-identical
round-tripping: every token keeps its raw source text, and serialization is
just concatenation. A light element tree is built over the token stream for
structural queries (titles, tailoring extents, submittals, references).
"""

from __future__ import annotations

import codecs
import re
from dataclasses import dataclass, field
from pathlib import Path

# windows-1252 as Windows itself reads it: the five bytes the standard leaves
# undefined (0x81 0x8D 0x8F 0x90 0x9D) map to the C1 control characters of
# the same number instead of raising, so every byte round-trips. Python's
# "windows-1252" codec refuses them; SpecsIntact's own 02 83 00 has one.
UNDEFINED_BYTES = (0x81, 0x8D, 0x8F, 0x90, 0x9D)
ENCODING = "specgen-windows-1252"


def _codec():
    import encodings.cp1252 as base

    table = "".join(chr(i) if i in UNDEFINED_BYTES else c for i, c in enumerate(base.decoding_table))
    enc = codecs.charmap_build(table)

    def encode(s, errors="strict"):
        return codecs.charmap_encode(s, errors, enc)

    def decode(b, errors="strict"):
        return codecs.charmap_decode(b, errors, table)

    return codecs.CodecInfo(encode, decode, name=ENCODING)


codecs.register(lambda name: _codec() if name.replace("_", "-") == ENCODING else None)

# Tags that render as a line break when flattening to plain text.
_LINEBREAK_TAGS = {"BRK", "BRL"}

_NAME_RE = re.compile(r"[A-Za-z0-9._:-]+")

_ENTITIES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'"}


def unescape(text: str) -> str:
    for ent, ch in _ENTITIES.items():
        text = text.replace(ent, ch)
    return text


@dataclass
class Text:
    raw: str
    parent: "Element | None" = field(default=None, repr=False)

    def serialize(self) -> str:
        return self.raw


@dataclass
class Misc:
    """XML declaration, comment, or processing instruction — passed through."""

    raw: str
    parent: "Element | None" = field(default=None, repr=False)

    def serialize(self) -> str:
        return self.raw


@dataclass
class Element:
    name: str
    attrs: dict[str, str]
    open_raw: str  # exact source of the open (or self-closing) tag
    close_raw: str = ""  # exact source of the close tag ("" if self-closing)
    self_closing: bool = False
    children: list = field(default_factory=list)
    parent: "Element | None" = field(default=None, repr=False)
    src_start: int = -1  # offset of '<' of the open tag in the source
    src_end: int = -1  # offset just past the close tag (or self-closing tag)

    def serialize(self) -> str:
        if self.self_closing:
            return self.open_raw
        inner = "".join(c.serialize() for c in self.children)
        return f"{self.open_raw}{inner}{self.close_raw}"

    # -- queries ----------------------------------------------------------

    def iter(self, name: str | None = None):
        """Depth-first iteration over descendant Elements."""
        for child in self.children:
            if isinstance(child, Element):
                if name is None or child.name == name:
                    yield child
                yield from child.iter(name)

    def text(self) -> str:
        """Flattened plain text of this element (entities unescaped,
        BRK/BRL as newlines, other tags transparent)."""
        parts: list[str] = []
        _flatten(self, parts)
        return "".join(parts)

    def first(self, name: str) -> "Element | None":
        for child in self.children:
            if isinstance(child, Element) and child.name == name:
                return child
        return None

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent


def _flatten(el: Element, parts: list[str]) -> None:
    if el.name in _LINEBREAK_TAGS:
        parts.append("\n")
        return
    for child in el.children:
        if isinstance(child, Text):
            parts.append(unescape(child.raw))
        elif isinstance(child, Element):
            _flatten(child, parts)


class SecParseError(Exception):
    pass


def _parse_tag(src: str, pos: int) -> tuple[str, int]:
    """Return (raw_tag, end_pos) for the tag starting at src[pos] == '<',
    respecting quoted attribute values."""
    i = pos + 1
    n = len(src)
    quote: str | None = None
    while i < n:
        ch = src[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == ">":
            return src[pos : i + 1], i + 1
        i += 1
    raise SecParseError(f"Unterminated tag at offset {pos}")


_ATTR_RE = re.compile(r"""([A-Za-z0-9._:-]+)\s*=\s*("([^"]*)"|'([^']*)')""")


def _tag_parts(raw: str) -> tuple[str, dict[str, str], bool, bool]:
    """Return (name, attrs, is_end, is_self_closing) for a raw tag."""
    body = raw[1:-1]
    is_end = body.startswith("/")
    if is_end:
        body = body[1:]
    is_self = body.rstrip().endswith("/")
    if is_self:
        body = body.rstrip()[:-1]
    m = _NAME_RE.match(body.strip())
    if not m:
        raise SecParseError(f"Cannot parse tag: {raw!r}")
    name = m.group(0)
    attrs = {
        am.group(1): unescape(am.group(3) if am.group(3) is not None else am.group(4))
        for am in _ATTR_RE.finditer(body[m.end() :])
    }
    return name, attrs, is_end, is_self


@dataclass
class SecFile:
    path: Path
    source: str  # decoded source text
    prolog: list  # Misc/Text nodes before the root element
    root: Element
    epilog: list  # nodes after the root element
    # tolerant-mode source defects (stray close tags kept as Misc nodes)
    defects: list = field(default_factory=list)

    # -- round trip --------------------------------------------------------

    def serialize(self) -> str:
        parts = [n.serialize() for n in self.prolog]
        parts.append(self.root.serialize())
        parts.extend(n.serialize() for n in self.epilog)
        return "".join(parts)

    def roundtrips(self) -> bool:
        return self.serialize() == self.source

    def save(self, path: Path | str) -> None:
        Path(path).write_bytes(self.serialize().encode(ENCODING))


def parse(path: Path | str, tolerant: bool = False) -> SecFile:
    path = Path(path)
    return parse_source(path.read_bytes().decode(ENCODING), path, tolerant=tolerant)


def parse_source(
    source: str, path: Path | str = Path("<memory>"), tolerant: bool = False
) -> SecFile:
    """Strict by default. tolerant=True accepts a close tag that matches no
    open element (keeps it as a Misc node, records it in SecFile.defects)."""
    path = Path(path)
    prolog: list = []
    epilog: list = []
    defects: list[dict] = []
    root: Element | None = None
    stack: list[Element] = []

    def emit(node) -> None:
        if stack:
            node.parent = stack[-1]
            stack[-1].children.append(node)
        elif root is None:
            prolog.append(node)
        else:
            epilog.append(node)

    i, n = 0, len(source)
    while i < n:
        if source[i] == "<":
            if source.startswith("<!--", i):
                end = source.find("-->", i)
                if end < 0:
                    raise SecParseError(f"Unterminated comment at {i}")
                emit(Misc(source[i : end + 3]))
                i = end + 3
                continue
            if source.startswith("<?", i):
                end = source.find("?>", i)
                if end < 0:
                    raise SecParseError(f"Unterminated PI at {i}")
                emit(Misc(source[i : end + 2]))
                i = end + 2
                continue
            if source.startswith("<!", i):  # DOCTYPE etc.
                raw, i = _parse_tag(source, i)
                emit(Misc(raw))
                continue
            tag_start = i
            raw, i = _parse_tag(source, i)
            name, attrs, is_end, is_self = _tag_parts(raw)
            if is_end:
                if not stack or stack[-1].name != name:
                    got = stack[-1].name if stack else None
                    # Tolerant: a close tag that matches NOTHING open is a
                    # stray (UFGS 01 42 00 NORSOK entry). Keep its raw text
                    # so round-trip stays byte-identical, and record it. A
                    # tag matching a deeper element is a real nesting error
                    # and still raises.
                    if tolerant and all(e.name != name for e in stack):
                        emit(Misc(raw))
                        defects.append(
                            {"type": "stray-close-tag", "tag": name, "raw": raw,
                             "offset": tag_start, "open": got}
                        )
                        continue
                    raise SecParseError(f"Mismatched </{name}> (open: {got})")
                el = stack.pop()
                el.close_raw = raw
                el.src_end = i
                if not stack and root is None:
                    root = el
            else:
                el = Element(
                    name=name,
                    attrs=attrs,
                    open_raw=raw,
                    self_closing=is_self,
                    src_start=tag_start,
                    src_end=i if is_self else -1,
                )
                if is_self:
                    emit(el)
                else:
                    emit(el)
                    stack.append(el)
        else:
            end = source.find("<", i)
            if end < 0:
                end = n
            emit(Text(source[i:end]))
            i = end
    if stack:
        raise SecParseError(f"Unclosed tags at EOF: {[e.name for e in stack]}")
    if root is None:
        raise SecParseError("No root element found")
    # The root was appended into prolog by emit() when its open tag was seen
    # (stack was empty and root was None) — pull it out.
    prolog = [node for node in prolog if node is not root]
    # a byte windows-1252 leaves undefined is kept as-is and reported (it is
    # a corrupt character, e.g. "off\x81-site" in 02 83 00)
    for m in _UNDEFINED_RE.finditer(source):
        defects.append({"type": "undefined-byte", "raw": m.group(), "offset": m.start()})
    defects.sort(key=lambda d: d["offset"])
    return SecFile(
        path=path, source=source, prolog=prolog, root=root, epilog=epilog,
        defects=defects,
    )


_UNDEFINED_RE = re.compile("[" + "".join(chr(b) for b in UNDEFINED_BYTES) + "]")
