"""Verifier for Luau training examples (pure Python; no external binaries).

What it checks, and what it does NOT check. The verdict is only as strong as these checks:

  structure   tokenises Luau (strings, long strings, comments, numbers), then checks that
              block keywords balance (function/if/for/while/do/repeat...end/until), that brackets
              match, and that no string is left open. It understands Luau if-expressions.
  api         every Roblox class name in GetService/Instance.new must exist in the engine API dump,
              with the right kind (service / creatable). Method and property names used with ':' and
              '.' must exist somewhere in the API dump OR be defined in the same file.
  deprecated  calls to deprecated globals/members (wait, spawn, delay, BodyVelocity, ...) are reported.
  boundary    a client script (.client.luau / LocalScript-style name) must not touch server-only services.

What it does NOT do: static type checking. A file can pass every check above and still have type
errors. Records are labelled with the checks that actually ran, never as "type-checked".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# ----------------------------------------------------------------------------- lexer

KEYWORDS = {"and", "break", "do", "else", "elseif", "end", "false", "for", "function", "if", "in",
            "local", "nil", "not", "or", "repeat", "return", "then", "true", "until", "while", "continue", "export", "type"}


@dataclass
class Tok:
    kind: str  # kw | name | num | str | op | eof
    text: str
    line: int


_LONG_COMMENT = re.compile(r"--\[(=*)\[")
_LONG_STRING = re.compile(r"\[(=*)\[")
_NUMBER = re.compile(r"(0[xX][0-9a-fA-F_]+|0[bB][01_]+|(\d[\d_]*\.?[\d_]*|\.\d[\d_]*)([eE][+-]?\d+)?)")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def tokenize(src: str) -> tuple[list[Tok], list[str]]:
    toks: list[Tok] = []
    errors: list[str] = []
    i, n, line = 0, len(src), 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if c in " \t\r":
            i += 1
            continue
        if src.startswith("--", i):  # comment
            m = _LONG_COMMENT.match(src, i)
            if m:
                close = "]" + m.group(1) + "]"
                j = src.find(close, i + len(m.group(0)))
                if j < 0:
                    errors.append(f"line {line}: unterminated block comment")
                    return toks, errors
                line += src[i:j].count("\n")
                i = j + len(close)
            else:
                j = src.find("\n", i)
                i = n if j < 0 else j
            continue
        m = _LONG_STRING.match(src, i)
        if m:  # long string
            close = "]" + m.group(1) + "]"
            j = src.find(close, i + len(m.group(0)))
            if j < 0:
                errors.append(f"line {line}: unterminated long string")
                return toks, errors
            toks.append(Tok("str", src[i:j + len(close)], line))
            line += src[i:j].count("\n")
            i = j + len(close)
            continue
        if c == "`":  # Luau interpolated string
            j = src.find("`", i + 1)
            if j < 0:
                errors.append(f"line {line}: unterminated interpolated string")
                return toks, errors
            toks.append(Tok("str", src[i:j + 1], line))
            line += src[i:j].count("\n")
            i = j + 1
            continue
        if c in "\"'":
            j = i + 1
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                if j < n and src[j] == "\n":
                    errors.append(f"line {line}: newline inside string")
                    return toks, errors
                j += 1
            if j >= n:
                errors.append(f"line {line}: unterminated string")
                return toks, errors
            toks.append(Tok("str", src[i:j + 1], line))
            i = j + 1
            continue
        m = _NUMBER.match(src, i)
        if m and m.group(0):
            toks.append(Tok("num", m.group(0), line))
            i += len(m.group(0))
            continue
        m = _NAME.match(src, i)
        if m:
            w = m.group(0)
            toks.append(Tok("kw" if w in KEYWORDS else "name", w, line))
            i += len(w)
            continue
        three = src[i:i + 3]
        two = src[i:i + 2]
        if three in ("...",):
            toks.append(Tok("op", three, line))
            i += 3
        elif two in ("==", "~=", "<=", ">=", "..", "::", "->", "+=", "-=", "*=", "/=", "%=", "^=", "//"):
            toks.append(Tok("op", two, line))
            i += 2
        elif c in "+-*/%^#<>=(){}[];:,.&|?@":
            toks.append(Tok("op", c, line))
            i += 1
        else:
            errors.append(f"line {line}: unexpected character {c!r}")
            i += 1
    return toks, errors


# ----------------------------------------------------------------------------- structure

_EXPR_PREV = {"=", "(", ",", "return", "and", "or", "+", "-", "*", "/", "..", "==", "~=", "<", ">", "<=", ">=",
              "{", "[", "+=", "-=", "*=", "/=", ":", "%", "^", "#", "not"}


def check_structure(toks: list[Tok]) -> list[str]:
    errs: list[str] = []
    stack: list[tuple[str, int]] = []   # (opener, line)
    brackets: list[tuple[str, int]] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    prev: Tok | None = None
    for t in toks:
        if t.kind == "op" and t.text in "([{":
            brackets.append((t.text, t.line))
        elif t.kind == "op" and t.text in pairs:
            if not brackets or brackets[-1][0] != pairs[t.text]:
                errs.append(f"line {t.line}: unmatched {t.text!r}")
                return errs
            brackets.pop()
        if t.kind == "name" and t.text == "class" and prev is not None and prev.text == "declare":
            stack.append(("class", t.line))
        if t.kind == "kw":
            w = t.text
            if w == "function":
                # In type-definition files, 'declare function' and methods inside 'declare class' are
                # signatures with no body and no 'end'.
                in_decl = (prev is not None and prev.text == "declare") or (stack and stack[-1][0] == "class")
                if not in_decl:
                    stack.append(("function", t.line))
            elif w == "if":
                is_expr = prev is not None and (prev.text in _EXPR_PREV or prev.kind == "kw" and prev.text in ("return", "in"))
                if not is_expr:
                    stack.append(("if", t.line))
            elif w in ("for", "while"):
                stack.append((w, t.line))
            elif w == "do":
                # 'do' belongs to a preceding for/while (already on the stack) unless standalone
                if not stack or stack[-1][0] not in ("for", "while"):
                    stack.append(("do", t.line))
                else:
                    stack[-1] = ("loop", stack[-1][1])
            elif w == "repeat":
                stack.append(("repeat", t.line))
            elif w == "end":
                if not stack or stack[-1][0] in ("repeat",):
                    errs.append(f"line {t.line}: 'end' without matching opener")
                    return errs
                stack.pop()
            elif w == "until":
                if not stack or stack[-1][0] != "repeat":
                    errs.append(f"line {t.line}: 'until' without repeat")
                    return errs
                stack.pop()
        prev = t
    if brackets:
        errs.append(f"line {brackets[-1][1]}: unclosed {brackets[-1][0]!r}")
    if stack:
        errs.append(f"line {stack[-1][1]}: block opened with '{stack[-1][0]}' is never closed")
    return errs


# ----------------------------------------------------------------------------- api


@dataclass
class ApiIndex:
    services: set[str] = field(default_factory=set)
    creatable: set[str] = field(default_factory=set)
    classes: set[str] = field(default_factory=set)
    members: set[str] = field(default_factory=set)       # every property/method/event name, any class
    deprecated_members: set[str] = field(default_factory=set)
    deprecated_classes: set[str] = field(default_factory=set)
    server_only: set[str] = field(default_factory=set)   # services a client script must not use

    @staticmethod
    def from_dump(dump: dict) -> "ApiIndex":
        idx = ApiIndex()
        classes = dump.get("Classes", [])
        supers = {c["Name"]: c.get("Superclass") for c in classes}

        def is_sub(name: str, base: str) -> bool:
            seen = 0
            while name and seen < 50:
                if name == base:
                    return True
                name = supers.get(name)
                seen += 1
            return False

        for c in classes:
            name = c["Name"]
            idx.classes.add(name)
            tags = [t for t in (c.get("Tags") or []) if isinstance(t, str)]
            if "Service" in tags or is_sub(name, "Service"):
                idx.services.add(name)
            if "NotCreatable" not in tags and "Deprecated" not in tags:
                idx.creatable.add(name)
            if "Deprecated" in tags:
                idx.deprecated_classes.add(name)
            for m in c.get("Members", []):
                idx.members.add(m["Name"])
                mt = [t for t in (m.get("Tags") or []) if isinstance(t, str)]
                if "Deprecated" in mt:
                    idx.deprecated_members.add(m["Name"])
        # Server-only services: anything whose name marks it server-side in the engine.
        idx.server_only = {s for s in idx.services if s in {
            "ServerStorage", "ServerScriptService", "DataStoreService", "MessagingService", "MemoryStoreService",
            "BadgeService", "TeleportService", "ServerScriptService"}}
        return idx


_GETSERVICE = re.compile(r"""\bgame\s*[:.]\s*GetService\s*\(\s*["']([A-Za-z_]\w*)["']\s*\)""")
_INSTNEW = re.compile(r"""Instance\.new\s*\(\s*["']([A-Za-z_]\w*)["']""")
_METHOD = re.compile(r":\s*([A-Za-z_]\w*)\s*\(")
_DEFINED = re.compile(r"(?:function\s+[\w.:]*[:.]\s*([A-Za-z_]\w*)|local\s+function\s+([A-Za-z_]\w*)|\b([A-Za-z_]\w*)\s*=\s*function\b)")
_FIELD_DEF = re.compile(r"(?:^|[\s,{])([A-Za-z_]\w*)\s*=")
_KNOWN_LIB = {"task", "math", "string", "table", "coroutine", "os", "utf8", "bit32", "debug", "buffer"}
# Methods on Roblox value types and signals; these are not 'classes' in the Instance dump.
_DATATYPE_METHODS = {"Connect", "Once", "Wait", "Disconnect", "Lerp", "Cross", "Dot", "Angles", "ToEulerAngles",
                     "ToOrientation", "Inverse", "Orthonormalize", "PointToWorldSpace", "PointToObjectSpace",
                     "VectorToWorldSpace", "VectorToObjectSpace", "ToWorldSpace", "ToObjectSpace", "Lerp", "Min",
                     "Max", "FuzzyEq", "Abs", "Floor", "Ceil", "Sign", "IsClose", "ToHSV", "ToRGB", "ToHex",
                     "Destroy", "Clone", "IsA", "IsAncestorOf", "IsDescendantOf", "FindFirstChild",
                     "FindFirstChildOfClass", "FindFirstChildWhichIsA", "FindFirstAncestor", "GetChildren",
                     "GetDescendants", "GetAttribute", "SetAttribute", "GetAttributes", "GetPropertyChangedSignal",
                     "GetFullName", "GetPivot", "PivotTo", "WaitForChild", "GetService", "GetObjects",
                     "Raycast", "Blockcast", "Spherecast", "Shapecast", "Pause", "Play", "Stop", "Fire", "FireServer",
                     "FireClient", "FireAllClients", "InvokeServer", "InvokeClient", "Emit", "Lerp", "GetMouse",
                     "GetPlayers", "GetPlayerFromCharacter", "Kick", "LoadCharacter", "SetCore", "GetCore",
                     "Unit", "Magnitude", "Cross", "Dot", "IsFinite", "IsNaN", "ToAxisAngle", "Rotate"}
_LIB_METHODS = {"format", "sub", "gsub", "gmatch", "match", "find", "rep", "reverse", "byte", "char", "upper",
                "lower", "len", "split", "pack", "unpack", "insert", "remove", "concat", "sort", "clone",
                "clear", "freeze", "isfrozen", "create", "resume", "yield", "status", "wrap", "running", "close",
                "isyieldable", "getcurrent", "info", "trim", "trimStart", "trimEnd", "unpack", "tostring", "tonumber"}


def check_api(src: str, toks: list[Tok], api: ApiIndex) -> dict:
    """Hard errors: invented services, invented creatable classes. Soft warnings: member names that are
    not in the dump (often defined in another module, e.g. Promise or Knit methods), deprecated classes."""
    errs, warns = [], []
    for m in _GETSERVICE.finditer(src):
        name = m.group(1)
        if name not in api.services:
            errs.append(f"GetService(\"{name}\"): not a service in the engine API")
    for m in _INSTNEW.finditer(src):
        name = m.group(1)
        if name in api.deprecated_classes:
            warns.append(f"deprecated class Instance.new(\"{name}\")")
        elif name not in api.creatable:
            errs.append(f"Instance.new(\"{name}\"): not a creatable class in the engine API")
    defined = set()
    for m in _DEFINED.finditer(src):
        defined.update(g for g in m.groups() if g)
    for m in _FIELD_DEF.finditer(src):
        defined.add(m.group(1))
    unknown = []
    for m in _METHOD.finditer(src):
        name = m.group(1)
        if name in api.members or name in defined or name in _LIB_METHODS or name in _DATATYPE_METHODS:
            continue
        unknown.append(name)
    if unknown:
        warns.append("unknown member (not in engine API or this file): " + ", ".join(sorted(set(unknown))[:6]))
    dep_member = "|".join(sorted(api.deprecated_members)) or "(?!)"
    dep = sorted({m.group(0) for m in re.finditer(r"(?:[.:]\s*(?:" + dep_member + r")\b)", src)})
    dep += sorted({m.group(0) for m in re.finditer(r"(?<![.\w:])(wait|spawn|delay|tick)\s*\(", src)})
    dep += sorted({m.group(0) for m in re.finditer(r"\b(BodyVelocity|BodyPosition|BodyGyro|BodyForce|BodyAngularVelocity)\b", src)})
    if dep:
        warns.append("deprecated API used: " + ", ".join(dep[:8]))
    return {"errors": errs, "warnings": warns}


# ----------------------------------------------------------------------------- boundary

_CLIENT_NAME = re.compile(r"\.client\.(luau|lua)$|LocalScript", re.I)
_SERVER_NAME = re.compile(r"\.server\.(luau|lua)$|Script\.luau$", re.I)


_COMMENT = re.compile(r"--\[(=*)\[.*?\]\1\]|--[^\n]*", re.S)


def check_boundary(path: str, src: str, api: ApiIndex) -> list[str]:
    errs = []
    if _CLIENT_NAME.search(path):
        code = _COMMENT.sub("", src)
        for svc in api.server_only:
            if re.search(rf"\b{svc}\b", code):
                errs.append(f"client script references server-only service {svc}")
    return errs


# ----------------------------------------------------------------------------- verdict


@dataclass
class Verdict:
    ok: bool
    checks: list[str]           # the checks that ran
    errors: list[str]
    warnings: list[str]

    def to_dict(self) -> dict:
        return {"ok": self.ok, "checks": self.checks, "errors": self.errors, "warnings": self.warnings}


def verify(path: str, src: str, api: ApiIndex) -> Verdict:
    toks, lex_errs = tokenize(src)
    if lex_errs:
        return Verdict(False, ["lex"], lex_errs, [])
    errs = check_structure(toks)
    if errs:
        return Verdict(False, ["lex", "structure"], errs, [])
    a = check_api(src, toks, api)
    b = check_boundary(path, src, api)
    errors = a["errors"] + b
    return Verdict(not errors, ["lex", "structure", "api", "boundary", "deprecated"], errors, a["warnings"])


def load_api(path: str | Path) -> ApiIndex:
    return ApiIndex.from_dump(json.loads(Path(path).read_text()))
