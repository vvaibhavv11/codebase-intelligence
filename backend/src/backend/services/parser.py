"""Tree-sitter code parsing service — extracts symbols, imports, calls, and inheritance.

Supports Python, JavaScript, TypeScript, Rust, Go, Java, C, C++, C#, Ruby, and PHP.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_c as tsc
import tree_sitter_c_sharp as tscsharp
import tree_sitter_cpp as tscpp
import tree_sitter_go as tsgo
import tree_sitter_java as tsjava
import tree_sitter_javascript as tsjavascript
import tree_sitter_php as tsphp
import tree_sitter_python as tspython
import tree_sitter_ruby as tsruby
import tree_sitter_rust as tsrust
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Node, Parser

logger = logging.getLogger(__name__)

PY_LANGUAGE = Language(tspython.language())
JS_LANGUAGE = Language(tsjavascript.language())
TS_LANGUAGE = Language(tstypescript.language_typescript())
TSX_LANGUAGE = Language(tstypescript.language_tsx())
RUST_LANGUAGE = Language(tsrust.language())
GO_LANGUAGE = Language(tsgo.language())
JAVA_LANGUAGE = Language(tsjava.language())
C_LANGUAGE = Language(tsc.language())
CPP_LANGUAGE = Language(tscpp.language())
CSHARP_LANGUAGE = Language(tscsharp.language())
RUBY_LANGUAGE = Language(tsruby.language())
PHP_LANGUAGE = Language(tsphp.language_php_only())

LANGUAGES: dict[str, Language] = {
    "python": PY_LANGUAGE,
    "javascript": JS_LANGUAGE,
    "typescript": TS_LANGUAGE,
    "rust": RUST_LANGUAGE,
    "go": GO_LANGUAGE,
    "java": JAVA_LANGUAGE,
    "c": C_LANGUAGE,
    "cpp": CPP_LANGUAGE,
    "csharp": CSHARP_LANGUAGE,
    "ruby": RUBY_LANGUAGE,
    "php": PHP_LANGUAGE,
}


@dataclass
class ExtractedSymbol:
    name: str
    kind: str  # "function", "class", "method"
    start_line: int  # 1-indexed
    end_line: int  # 1-indexed
    source_text: str
    signature: str | None = None
    docstring: str | None = None
    bases: list[str] = field(default_factory=list)  # class inheritance (classes only)
    children: list[ExtractedSymbol] = field(default_factory=list)


@dataclass
class ExtractedImport:
    """A module import statement (module-level)."""

    module: str  # module path being imported from ("" if unknown)
    imported_name: str  # what was imported (name or module)
    kind: str  # "import", "from_import", "require", "module_import"
    line: int  # 1-indexed


@dataclass
class ExtractedCall:
    """A call to an identifier, optionally inside a symbol."""

    caller_name: str  # enclosing symbol name ("" if module level)
    callee_name: str  # the function/method being called
    line: int


@dataclass
class ExtractedFile:
    """Everything extracted from a single source file."""

    symbols: list[ExtractedSymbol] = field(default_factory=list)
    imports: list[ExtractedImport] = field(default_factory=list)
    calls: list[ExtractedCall] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8")


def _child_by_type(node: Node, *types: str) -> Node | None:
    for child in node.children:
        if child.type in types:
            return child
    return None


def _walk(node: Node):
    """Depth-first yield of all descendants."""
    for child in node.children:
        yield child
        yield from _walk(child)


def _extract_docstring_python(block_node: Node, source: bytes) -> str | None:
    if block_node is None or block_node.type != "block":
        return None
    for child in block_node.children:
        if child.type == "expression_statement":
            expr = child.children[0] if child.children else None
            if expr and expr.type == "string":
                raw = _get_node_text(expr, source)
                # Strip triple-quote markers
                for q in ('"""', "'''", '"', "'"):
                    if raw.startswith(q) and raw.endswith(q):
                        return raw[len(q):-len(q)].strip()
                return raw
            break
        if child.type not in ("comment", "newline"):
            break
    return None


def _extract_jsdoc(node: Node, source: bytes) -> str | None:
    sib = node.prev_named_sibling
    if sib and sib.type == "comment":
        text = _get_node_text(sib, source)
        if text.startswith("/**"):
            return text.strip("/* \n\r\t")
    return None


def _has_async_keyword(node: Node) -> bool:
    return any(c.type == "async" for c in node.children)


def _python_signature(node: Node, source: bytes) -> str:
    """Build `def name(params) -> ret` or `class Name(bases)` from AST children."""
    if node.type in ("function_definition", "async_function_definition"):
        parts: list[str] = []
        if _has_async_keyword(node):
            parts.append("async ")
        parts.append("def ")
        name = _child_by_type(node, "identifier")
        if name:
            parts.append(_get_node_text(name, source))
        params = _child_by_type(node, "parameters")
        if params:
            parts.append(_get_node_text(params, source))
        ret = _child_by_type(node, "type")
        if ret:
            parts.append(" -> ")
            parts.append(_get_node_text(ret, source))
        return "".join(parts)

    if node.type == "class_definition":
        parts = ["class "]
        name = _child_by_type(node, "identifier")
        if name:
            parts.append(_get_node_text(name, source))
        bases = _child_by_type(node, "argument_list")
        if bases:
            parts.append(_get_node_text(bases, source))
        return "".join(parts)

    return _get_node_text(node, source).split("\n", 1)[0]


def _js_signature(node: Node, source: bytes) -> str:
    """Build a signature from the start of a JS/TS node up through the params."""
    if node.type in ("function_declaration", "generator_function_declaration"):
        text = _get_node_text(node, source)
        paren_end = text.find(")")
        if paren_end != -1:
            sig = text[:paren_end + 1]
            # Grab TS return type annotation if present
            rest = text[paren_end + 1:]
            colon = rest.lstrip()
            if colon.startswith(":"):
                type_text = colon[1:].split("{", 1)[0].strip()
                if type_text:
                    sig += ": " + type_text
            return sig.strip()
        return text.split("{", 1)[0].strip()

    if node.type == "arrow_function":
        params = _child_by_type(node, "formal_parameters")
        if params:
            sig = _get_node_text(params, source)
            ret = _child_by_type(node, "type_annotation")
            if ret:
                sig += _get_node_text(ret, source)
            return sig
        return ""

    if node.type == "method_definition":
        text = _get_node_text(node, source)
        paren_end = text.find(")")
        if paren_end != -1:
            sig = text[:paren_end + 1]
            rest = text[paren_end + 1:]
            colon = rest.lstrip()
            if colon.startswith(":"):
                type_text = colon[1:].split("{", 1)[0].strip()
                if type_text:
                    sig += ": " + type_text
            return sig.strip()
        return text.split("{", 1)[0].strip()

    if node.type == "class_declaration":
        text = _get_node_text(node, source)
        brace = text.find("{")
        if brace != -1:
            return text[:brace].strip()
        return text.split("\n", 1)[0].strip()

    return _get_node_text(node, source).split("\n", 1)[0]


# ---------------------------------------------------------------------------
# Python extraction
# ---------------------------------------------------------------------------

def _python_class_bases(node: Node, source: bytes) -> list[str]:
    """Extract base class names from a class_definition argument_list."""
    bases: list[str] = []
    arg_list = _child_by_type(node, "argument_list")
    if not arg_list:
        return bases
    for child in arg_list.children:
        if child.type == "keyword_argument":
            break  # only positional bases matter
        if child.type in ("identifier", "attribute"):
            bases.append(_get_node_text(child, source))
    return bases


def _extract_python_function(node: Node, source: bytes, kind: str = "function") -> ExtractedSymbol:
    name_node = _child_by_type(node, "identifier")
    name = _get_node_text(name_node, source) if name_node else "<anonymous>"
    block = _child_by_type(node, "block")
    return ExtractedSymbol(
        name=name,
        kind=kind,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        source_text=_get_node_text(node, source),
        signature=_python_signature(node, source),
        docstring=_extract_docstring_python(block, source),
    )


def _extract_python_class(node: Node, source: bytes) -> ExtractedSymbol:
    name_node = _child_by_type(node, "identifier")
    name = _get_node_text(name_node, source) if name_node else "<anonymous>"
    block = _child_by_type(node, "block")

    methods: list[ExtractedSymbol] = []
    if block:
        for child in block.children:
            inner = child
            if child.type == "decorated_definition":
                inner = _child_by_type(child, "function_definition", "async_function_definition")
                if inner is None:
                    continue
            if inner.type in ("function_definition", "async_function_definition"):
                methods.append(_extract_python_function(inner, source, kind="method"))

    return ExtractedSymbol(
        name=name,
        kind="class",
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        source_text=_get_node_text(node, source),
        signature=_python_signature(node, source),
        docstring=_extract_docstring_python(block, source),
        bases=_python_class_bases(node, source),
        children=methods,
    )


def _extract_python_symbols(root: Node, source: bytes) -> list[ExtractedSymbol]:
    symbols: list[ExtractedSymbol] = []
    for child in root.children:
        node = child
        # Unwrap decorated definitions
        if child.type == "decorated_definition":
            node = (
                _child_by_type(child, "function_definition", "async_function_definition", "class_definition")
            )
            if node is None:
                continue

        if node.type in ("function_definition", "async_function_definition"):
            symbols.append(_extract_python_function(node, source))
        elif node.type == "class_definition":
            symbols.append(_extract_python_class(node, source))
    return symbols


def _extract_python_imports(root: Node, source: bytes) -> list[ExtractedImport]:
    imports: list[ExtractedImport] = []
    for node in _walk(root):
        if node.type == "import_statement":
            dotted = _child_by_type(node, "dotted_name")
            if dotted:
                module = _get_node_text(dotted, source)
                imports.append(ExtractedImport(
                    module=module,
                    imported_name=module.split(".")[-1],
                    kind="import",
                    line=node.start_point[0] + 1,
                ))
        elif node.type == "import_from_statement":
            module_node = _child_by_type(node, "dotted_name")
            module = _get_node_text(module_node, source) if module_node else ""
            import_list = _child_by_type(node, "import_list")
            if import_list:
                for item in import_list.children:
                    if item.type in ("dotted_name", "aliased_import"):
                        name_node = _child_by_type(item, "dotted_name") or item
                        if name_node.type == "dotted_name":
                            name = _get_node_text(name_node, source).split(".")[-1]
                            imports.append(ExtractedImport(
                                module=module,
                                imported_name=name,
                                kind="from_import",
                                line=node.start_point[0] + 1,
                            ))
            else:
                dotted = _child_by_type(node, "dotted_name")
                # `from x import y` with a single name: second dotted_name is the name
                names = [c for c in node.children if c.type == "dotted_name"]
                if len(names) >= 2:
                    name = _get_node_text(names[-1], source).split(".")[-1]
                    imports.append(ExtractedImport(
                        module=module,
                        imported_name=name,
                        kind="from_import",
                        line=node.start_point[0] + 1,
                    ))
    return imports


def _call_function_node(node: Node) -> Node | None:
    """Return the callee node of a call: the child before the argument list."""
    for child in node.children:
        if child.type != "argument_list" and child.type != "arguments":
            return child
    return None


def _extract_python_calls(
    root: Node, source: bytes, symbols: list[ExtractedSymbol]
) -> list[ExtractedCall]:
    """Extract calls to plain identifiers, plus self/cls method calls."""
    ranges = _symbol_ranges(symbols)
    calls: list[ExtractedCall] = []
    for node in _walk(root):
        if node.type != "call":
            continue
        fn = _call_function_node(node)
        if fn is None:
            continue
        callee: str | None = None
        if fn.type == "identifier":
            callee = _get_node_text(fn, source)
        elif fn.type == "attribute":
            kids = [c for c in fn.children if c.type == "identifier"]
            if len(kids) >= 2 and _get_node_text(kids[0], source) in ("self", "cls"):
                callee = _get_node_text(kids[-1], source)
        if not callee:
            continue
        line = node.start_point[0] + 1
        caller = _find_enclosing_symbol_name(line, ranges) or ""
        calls.append(ExtractedCall(caller_name=caller, callee_name=callee, line=line))
    return calls


# ---------------------------------------------------------------------------
# JS / TS extraction
# ---------------------------------------------------------------------------

def _js_class_bases(node: Node, source: bytes) -> list[str]:
    """Extract base class names from a class_heritage node."""
    heritage = _child_by_type(node, "class_heritage")
    if not heritage:
        return []
    bases: list[str] = []
    for child in heritage.children:
        if child.type in ("identifier", "type_identifier", "member_expression"):
            bases.append(_get_node_text(child, source))
    return bases


def _extract_js_function(node: Node, source: bytes, jsdoc: str | None = None) -> ExtractedSymbol:
    name_node = _child_by_type(node, "identifier")
    name = _get_node_text(name_node, source) if name_node else "<anonymous>"
    return ExtractedSymbol(
        name=name,
        kind="function",
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        source_text=_get_node_text(node, source),
        signature=_js_signature(node, source),
        docstring=jsdoc,
    )


def _extract_js_arrow(var_node: Node, arrow_node: Node, source: bytes, jsdoc: str | None = None) -> ExtractedSymbol:
    name_node = _child_by_type(var_node, "identifier")
    name = _get_node_text(name_node, source) if name_node else "<anonymous>"
    return ExtractedSymbol(
        name=name,
        kind="function",
        start_line=var_node.start_point[0] + 1,
        end_line=arrow_node.end_point[0] + 1,
        source_text=_get_node_text(var_node, source),
        signature=f"const {name} = {_js_signature(arrow_node, source)}",
        docstring=jsdoc,
    )


def _extract_js_method(node: Node, source: bytes) -> ExtractedSymbol:
    name_node = _child_by_type(node, "property_identifier", "computed_property_name")
    name = _get_node_text(name_node, source) if name_node else "<anonymous>"
    return ExtractedSymbol(
        name=name,
        kind="method",
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        source_text=_get_node_text(node, source),
        signature=_js_signature(node, source),
        docstring=_extract_jsdoc(node, source),
    )


def _extract_js_class(node: Node, source: bytes, jsdoc: str | None = None) -> ExtractedSymbol:
    name_node = _child_by_type(node, "type_identifier", "identifier")
    name = _get_node_text(name_node, source) if name_node else "<anonymous>"

    methods: list[ExtractedSymbol] = []
    body = _child_by_type(node, "class_body")
    if body:
        for child in body.children:
            if child.type == "method_definition":
                methods.append(_extract_js_method(child, source))

    return ExtractedSymbol(
        name=name,
        kind="class",
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        source_text=_get_node_text(node, source),
        signature=_js_signature(node, source),
        docstring=jsdoc,
        bases=_js_class_bases(node, source),
        children=methods,
    )


def _process_js_node(node: Node, source: bytes, jsdoc_source: Node | None = None) -> ExtractedSymbol | None:
    """Try to extract a symbol from a single AST node. Returns None if not a relevant node."""
    doc_src = jsdoc_source or node
    jsdoc = _extract_jsdoc(doc_src, source)

    if node.type in ("function_declaration", "generator_function_declaration"):
        return _extract_js_function(node, source, jsdoc)

    if node.type == "class_declaration":
        return _extract_js_class(node, source, jsdoc)

    # `const foo = (...) => { ... }` or `const foo = function(...) { ... }`
    if node.type in ("lexical_declaration", "variable_declaration"):
        for declarator in node.children:
            if declarator.type == "variable_declarator":
                value = _child_by_type(declarator, "arrow_function")
                if value:
                    return _extract_js_arrow(declarator, value, source, jsdoc)
                value = _child_by_type(declarator, "function_expression", "generator_function")
                if value:
                    name_node = _child_by_type(declarator, "identifier")
                    if name_node:
                        sym = _extract_js_function(value, source, jsdoc)
                        sym.name = _get_node_text(name_node, source)
                        sym.signature = f"const {sym.name} = {sym.signature}"
                        return sym

    return None


def _extract_js_ts_symbols(root: Node, source: bytes) -> list[ExtractedSymbol]:
    symbols: list[ExtractedSymbol] = []
    for child in root.children:
        node = child
        export_node = None

        # Unwrap export_statement
        if child.type == "export_statement":
            export_node = child
            inner = None
            for sub in child.children:
                if sub.type not in ("export", "default", "comment", "{", "}", ";"):
                    inner = sub
                    break
            if inner is None:
                continue
            node = inner

        sym = _process_js_node(node, source, jsdoc_source=export_node or node)
        if sym:
            symbols.append(sym)

    return symbols


def _extract_js_imports(root: Node, source: bytes) -> list[ExtractedImport]:
    imports: list[ExtractedImport] = []
    for node in _walk(root):
        if node.type == "import_statement":
            src = None
            for child in node.children:
                if child.type == "string":
                    src = _get_node_text(child, source).strip("'\"")
                    break
            if src is None:
                continue
            clause = _child_by_type(node, "import_clause")
            if clause is None:
                # side-effect import: `import "module"`
                imports.append(ExtractedImport(
                    module=src, imported_name="", kind="module_import",
                    line=node.start_point[0] + 1,
                ))
                continue
            for sub in _walk(clause):
                if sub.type == "identifier":
                    name = _get_node_text(sub, source)
                    if name in ("as", "*"):
                        continue
                    kind = "from_import" if sub.parent and sub.parent.type in ("import_specifier", "named_imports") else "import"
                    imports.append(ExtractedImport(
                        module=src, imported_name=name, kind=kind,
                        line=node.start_point[0] + 1,
                    ))
        elif node.type == "call_expression":
            fn = _call_function_node(node)
            if fn and fn.type == "identifier" and _get_node_text(fn, source) == "require":
                args = _child_by_type(node, "arguments")
                if args:
                    for a in args.children:
                        if a.type == "string":
                            src = _get_node_text(a, source).strip("'\"")
                            imports.append(ExtractedImport(
                                module=src, imported_name="", kind="require",
                                line=node.start_point[0] + 1,
                            ))
                            break
    return imports


def _extract_js_calls(
    root: Node, source: bytes, symbols: list[ExtractedSymbol]
) -> list[ExtractedCall]:
    ranges = _symbol_ranges(symbols)
    calls: list[ExtractedCall] = []
    for node in _walk(root):
        if node.type != "call_expression":
            continue
        fn = _call_function_node(node)
        if fn is None:
            continue
        callee: str | None = None
        if fn.type == "identifier":
            name = _get_node_text(fn, source)
            if name != "require":
                callee = name
        elif fn.type == "member_expression":
            obj = _child_by_type(fn, "this", "identifier")
            if obj and _get_node_text(obj, source) in ("this", "self"):
                prop = _child_by_type(fn, "property_identifier")
                if prop:
                    callee = _get_node_text(prop, source)
        if not callee:
            continue
        line = node.start_point[0] + 1
        caller = _find_enclosing_symbol_name(line, ranges) or ""
        calls.append(ExtractedCall(caller_name=caller, callee_name=callee, line=line))
    return calls


# ---------------------------------------------------------------------------
# Rust
# ---------------------------------------------------------------------------

RUST_ITEM_TYPES = {"function_item", "struct_item", "enum_item", "union_item", "trait_item"}


def _rust_doc_comments(node: Node, source: bytes) -> str | None:
    """Collect contiguous `///` or `/** */` doc comments directly above a node."""
    lines: list[str] = []
    sib = node.prev_named_sibling
    while sib is not None and sib.type in ("line_comment", "block_comment"):
        text = _get_node_text(sib, source).strip()
        if text.startswith("///"):
            lines.append(text[3:].strip())
        elif text.startswith("/**") and text.endswith("*/"):
            inner = text[3:-2].strip()
            lines.append(inner.strip("*").strip())
        else:
            break
        sib = sib.prev_named_sibling
    return "\n".join(reversed(lines)) or None


def _rust_function_signature(node: Node, source: bytes) -> str:
    parts = ["fn "]
    name = _child_by_type(node, "identifier")
    if name:
        parts.append(_get_node_text(name, source))
    params = _child_by_type(node, "parameters")
    if params:
        parts.append(_get_node_text(params, source))
    ret = _child_by_type(node, "return_type")
    if ret:
        parts.append(" ")
        parts.append(_get_node_text(ret, source))
    return "".join(parts)


def _rust_item_signature(node: Node, source: bytes) -> str:
    prefix = {
        "struct_item": "struct",
        "enum_item": "enum",
        "union_item": "union",
        "trait_item": "trait",
    }.get(node.type, node.type)
    name = _child_by_type(node, "type_identifier", "identifier")
    sig = f"{prefix} {_get_node_text(name, source) if name else '<anonymous>'}"
    generics = _child_by_type(node, "type_parameters")
    if generics:
        sig += _get_node_text(generics, source)
    return sig


def _impl_target_and_traits(impl: Node, source: bytes) -> tuple[str, list[str]]:
    """Parse `impl Trait1 for Type` (or `impl Type`) into (Type, [Trait1, ...])."""
    body = _get_node_text(impl, source).split("{", 1)[0]
    after = re.sub(r"^(unsafe\s+|default\s+)?impl\s+", "", body).strip()
    after = re.sub(r"^<[^>]*>\s*", "", after).split("where", 1)[0].strip()

    def last_segment(name: str) -> str:
        return name.split("::")[-1].split("<")[0].strip()

    if " for " in after:
        trait_part, target_part = after.split(" for ", 1)
        return last_segment(target_part), [last_segment(trait_part)]
    return last_segment(after), []


def _extract_rust_symbols(root: Node, source: bytes) -> list[ExtractedSymbol]:
    """Extract functions, structs/enums/traits, and impl methods (merged into
    their type with trait bases)."""
    symbols: list[ExtractedSymbol] = []
    impls: list[Node] = []

    for child in root.children:
        if child.type in RUST_ITEM_TYPES:
            name = _child_by_type(child, "type_identifier", "identifier")
            name_text = _get_node_text(name, source) if name else "<anonymous>"
            is_type = child.type in ("struct_item", "enum_item", "union_item", "trait_item")
            symbols.append(ExtractedSymbol(
                name=name_text,
                kind="class" if is_type else "function",
                start_line=child.start_point[0] + 1,
                end_line=child.end_point[0] + 1,
                source_text=_get_node_text(child, source),
                signature=(
                    _rust_item_signature(child, source)
                    if is_type
                    else _rust_function_signature(child, source)
                ),
                docstring=_rust_doc_comments(child, source),
            ))
        elif child.type == "impl_item":
            impls.append(child)

    for impl in impls:
        methods = [
            _extract_rust_function(inner, source, kind="method")
            for inner in impl.children
            if inner.type == "function_item"
        ]
        target_name, trait_names = _impl_target_and_traits(impl, source)
        if not target_name:
            continue

        # Merge into the matching struct/enum symbol if present, else synthesize one
        owner = next((s for s in symbols if s.name == target_name), None)
        if owner is None:
            owner = ExtractedSymbol(
                name=target_name,
                kind="class",
                start_line=impl.start_point[0] + 1,
                end_line=impl.end_point[0] + 1,
                source_text=_get_node_text(impl, source),
                signature=f"impl {target_name}",
            )
            symbols.append(owner)
        owner.children.extend(methods)
        owner.bases.extend(trait_names)

    return symbols


def _extract_rust_function(node: Node, source: bytes, kind: str = "function") -> ExtractedSymbol:
    name = _child_by_type(node, "identifier")
    return ExtractedSymbol(
        name=_get_node_text(name, source) if name else "<anonymous>",
        kind=kind,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        source_text=_get_node_text(node, source),
        signature=_rust_function_signature(node, source),
        docstring=_rust_doc_comments(node, source),
    )


def _rust_path_segments(node: Node, source: bytes) -> list[str]:
    """Flatten scoped_identifier/identifier chains into path segments."""
    if node.type != "scoped_identifier":
        return [_get_node_text(node, source)]
    out: list[str] = []
    for c in node.children:
        if c.type in ("identifier", "type_identifier", "scoped_identifier"):
            out.extend(_rust_path_segments(c, source))
        elif c.type == "crate":
            out.append("crate")
        elif c.type == "super":
            out.append("super")
    return out


def _rust_collect_path(node: Node, source: bytes) -> list[str]:
    """Collect path segments from a clause node (use_as_clause, etc.)."""
    segs: list[str] = []
    for c in node.children:
        if c.type in ("identifier", "type_identifier", "scoped_identifier"):
            segs.extend(_rust_path_segments(c, source))
        elif c.type == "crate":
            segs.append("crate")
        elif c.type == "super":
            segs.append("super")
    return segs


def _rust_use_pairs(use_node: Node, source: bytes) -> list[tuple[str, str]]:
    """Return (module, imported_name) pairs for a use_declaration."""
    pairs: list[tuple[str, str]] = []
    prefix: list[str] = []
    seen_clause = False

    def emit_as_clause(clause: Node) -> None:
        segs = _rust_collect_path(clause, source)
        alias = next(
            (
                _get_node_text(c, source)
                for c in clause.children
                if c.type == "identifier"
            ),
            segs[-1] if segs else "",
        )
        if segs:
            pairs.append(("::".join(segs[:-1]), alias))

    def handle_use_list(lst: Node, prefix_segs: list[str]) -> None:
        for child in lst.named_children:
            if child.type == "use_wildcard":
                continue
            if child.type == "use_list":
                handle_use_list(child, prefix_segs)
            elif child.type == "use_as_clause":
                segs = _rust_collect_path(child, source)
                alias = next(
                    (
                        _get_node_text(c, source)
                        for c in child.children
                        if c.type == "identifier"
                    ),
                    segs[-1] if segs else "",
                )
                if segs:
                    pairs.append(("::".join(prefix_segs + segs[:-1]), alias))
            else:
                pairs.append(("::".join(prefix_segs), _get_node_text(child, source)))

    for child in use_node.named_children:
        if child.type == "scoped_use_list":
            path_node = next(
                (c for c in child.named_children if c.type != "use_list"), None
            )
            use_list_node = _child_by_type(child, "use_list")
            if path_node:
                prefix.extend(_rust_path_segments(path_node, source))
            if use_list_node:
                handle_use_list(use_list_node, prefix)
                seen_clause = True
        elif child.type == "use_list":
            handle_use_list(child, prefix)
            seen_clause = True
        elif child.type == "use_as_clause":
            emit_as_clause(child)
            seen_clause = True
        elif child.type in ("scoped_identifier", "identifier", "type_identifier"):
            prefix.extend(_rust_path_segments(child, source))
        elif child.type in ("crate", "super", "self"):
            prefix.append(_get_node_text(child, source))

    if not seen_clause and prefix:
        pairs.append(("::".join(prefix[:-1]), prefix[-1]))
    return pairs


def _extract_rust_imports(root: Node, source: bytes) -> list[ExtractedImport]:
    imports: list[ExtractedImport] = []
    for node in _walk(root):
        if node.type != "use_declaration":
            continue
        for module, name in _rust_use_pairs(node, source):
            if not name or name in ("self", "*"):
                continue
            imports.append(ExtractedImport(
                module=module,
                imported_name=name,
                kind="use",
                line=node.start_point[0] + 1,
            ))
    return imports


def _extract_rust_calls(
    root: Node, source: bytes, symbols: list[ExtractedSymbol]
) -> list[ExtractedCall]:
    ranges = _symbol_ranges(symbols)
    calls: list[ExtractedCall] = []
    for node in _walk(root):
        if node.type != "call_expression":
            continue
        fn = _child_by_type(
            node, "identifier", "scoped_identifier", "field_expression", "generic_function"
        )
        if fn is None:
            continue
        callee: str | None = None
        if fn.type in ("identifier", "scoped_identifier"):
            callee = _get_node_text(fn, source).split("::")[-1]
        elif fn.type == "generic_function":
            inner = _child_by_type(fn, "identifier")
            if inner:
                callee = _get_node_text(inner, source)
        elif fn.type == "field_expression":
            field = _child_by_type(fn, "field_identifier")
            if field:
                callee = _get_node_text(field, source)
        if not callee:
            continue
        line = node.start_point[0] + 1
        caller = _find_enclosing_symbol_name(line, ranges) or ""
        calls.append(ExtractedCall(caller_name=caller, callee_name=callee, line=line))
    return calls


# ---------------------------------------------------------------------------
# Generic helpers for C-family / JVM / scripting languages
# ---------------------------------------------------------------------------

def _first_line(node: Node, source: bytes) -> str:
    return _get_node_text(node, source).split("\n", 1)[0].strip()


def _simple_symbol(
    node: Node,
    source: bytes,
    name_node: Node | None,
    kind: str,
    bases: list[str] | None = None,
    children: list[ExtractedSymbol] | None = None,
) -> ExtractedSymbol:
    return ExtractedSymbol(
        name=_get_node_text(name_node, source) if name_node else "<anonymous>",
        kind=kind,
        start_line=node.start_point[0] + 1,
        end_line=node.end_point[0] + 1,
        source_text=_get_node_text(node, source),
        signature=_first_line(node, source),
        bases=bases or [],
        children=children or [],
    )


def _extract_calls(
    root: Node,
    source: bytes,
    symbols: list[ExtractedSymbol],
    call_types: set[str],
    get_callee,
) -> list[ExtractedCall]:
    """Generic call extraction: walk for call node types, resolve the callee name."""
    ranges = _symbol_ranges(symbols)
    calls: list[ExtractedCall] = []
    for node in _walk(root):
        if node.type not in call_types:
            continue
        callee = get_callee(node, source)
        if not callee:
            continue
        line = node.start_point[0] + 1
        caller = _find_enclosing_symbol_name(line, ranges) or ""
        calls.append(ExtractedCall(caller_name=caller, callee_name=callee, line=line))
    return calls


def _last_segment(name: str) -> str:
    for sep in ("::", ".", "/", "\\"):
        if sep in name:
            name = name.split(sep)[-1]
    return name


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------

def _extract_go_symbols(root: Node, source: bytes) -> list[ExtractedSymbol]:
    symbols: list[ExtractedSymbol] = []
    for child in root.children:
        if child.type == "function_declaration":
            name = _child_by_type(child, "identifier")
            symbols.append(_simple_symbol(child, source, name, "function"))
        elif child.type == "type_declaration":
            spec = _child_by_type(child, "type_spec")
            if spec is None:
                continue
            name = _child_by_type(spec, "type_identifier")
            type_node = _child_by_type(spec, "struct_type", "interface_type")
            if type_node is None:
                continue
            bases: list[str] = []
            if type_node.type == "struct_type":
                body = _child_by_type(type_node, "field_declaration_list")
                if body:
                    for emb in body.named_children:
                        if emb.type != "field_declaration":
                            continue
                        # Embedded: direct type_identifier child, no field_identifier
                        has_type = any(c.type == "type_identifier" for c in emb.children)
                        has_field = any(c.type == "field_identifier" for c in emb.children)
                        if has_type and not has_field:
                            t = _child_by_type(emb, "type_identifier")
                            if t:
                                bases.append(_get_node_text(t, source))
            children: list[ExtractedSymbol] = []
            if type_node.type == "interface_type":
                body = _child_by_type(type_node, "method_spec_list")
                if body:
                    for spec_node in body.named_children:
                        if spec_node.type == "method_spec":
                            n = _child_by_type(spec_node, "field_identifier")
                            if n:
                                children.append(_simple_symbol(spec_node, source, n, "method"))
            symbols.append(
                _simple_symbol(child, source, name, "class", bases=bases, children=children)
            )
    # Attach method_declaration receivers to their type symbol
    for child in root.children:
        if child.type != "method_declaration":
            continue
        name = _child_by_type(child, "field_identifier")
        owner_name = _receiver_type_name(child, source)
        if owner_name:
            owner = next((s for s in symbols if s.name == owner_name), None)
            if owner is not None:
                owner.children.append(_simple_symbol(child, source, name, "method"))
                continue
        symbols.append(_simple_symbol(child, source, name, "method"))
    return symbols


def _receiver_type_name(node: Node, source: bytes) -> str | None:
    """Go method receiver: first parameter_list → parameter_declaration → type."""
    params = _child_by_type(node, "parameter_list")
    if params is None:
        return None
    for p in params.named_children:
        if p.type == "parameter_declaration":
            for t in _walk(p):
                if t.type == "type_identifier":
                    return _get_node_text(t, source)
    return None


def _extract_go_imports(root: Node, source: bytes) -> list[ExtractedImport]:
    imports: list[ExtractedImport] = []
    for node in _walk(root):
        if node.type != "import_spec":
            continue
        path = _child_by_type(node, "interpreted_string_literal", "string_literal")
        if path is None:
            continue
        module = _get_node_text(path, source).strip('"`')
        alias = _child_by_type(node, "identifier")
        imported = _get_node_text(alias, source) if alias else _last_segment(module)
        imports.append(ExtractedImport(
            module=module, imported_name=imported, kind="import",
            line=node.start_point[0] + 1,
        ))
    return imports


def _go_callee(node: Node, source: bytes) -> str | None:
    fn = _child_by_type(node, "identifier", "selector_expression")
    if fn is None:
        return None
    if fn.type == "selector_expression":
        field = _child_by_type(fn, "field_identifier")
        return _get_node_text(field, source) if field else None
    return _get_node_text(fn, source)


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------

JAVA_TYPE_DECLS = {
    "class_declaration", "interface_declaration", "enum_declaration", "record_declaration"
}


def _extract_java_symbols(root: Node, source: bytes) -> list[ExtractedSymbol]:
    symbols: list[ExtractedSymbol] = []
    for child in root.children:
        if child.type not in JAVA_TYPE_DECLS:
            continue
        name = _child_by_type(child, "identifier")
        body = _child_by_type(child, "class_body")
        methods: list[ExtractedSymbol] = []
        if body:
            for m in body.named_children:
                if m.type == "method_declaration":
                    n = _child_by_type(m, "identifier")
                    methods.append(_simple_symbol(m, source, n, "method"))
                elif m.type == "constructor_declaration":
                    n = _child_by_type(m, "identifier")
                    methods.append(_simple_symbol(m, source, n, "method"))
        bases: list[str] = []
        sup = _child_by_type(child, "superclass")
        if sup:
            t = _child_by_type(sup, "type_identifier", "scoped_type_identifier")
            if t:
                bases.append(_last_segment(_get_node_text(t, source)))
        ifaces = _child_by_type(child, "super_interfaces")
        if ifaces:
            for t in _walk(ifaces):
                if t.type == "type_identifier":
                    bases.append(_last_segment(_get_node_text(t, source)))
        symbols.append(_simple_symbol(child, source, name, "class", bases=bases, children=methods))
    return symbols


def _extract_java_imports(root: Node, source: bytes) -> list[ExtractedImport]:
    imports: list[ExtractedImport] = []
    for node in _walk(root):
        if node.type != "import_declaration":
            continue
        path = _child_by_type(node, "scoped_identifier")
        if path is None:
            continue
        full = _get_node_text(path, source)
        imports.append(ExtractedImport(
            module=".".join(full.split(".")[:-1]),
            imported_name=full.split(".")[-1],
            kind="import",
            line=node.start_point[0] + 1,
        ))
    return imports


def _java_callee(node: Node, source: bytes) -> str | None:
    if node.type == "object_creation_expression":
        t = _child_by_type(node, "type_identifier", "scoped_type_identifier")
        return _last_segment(_get_node_text(t, source)) if t else None
    # method_invocation: last direct-child identifier is the method name
    name = None
    for c in node.children:
        if c.type == "identifier":
            name = _get_node_text(c, source)
    return name


# ---------------------------------------------------------------------------
# C / C++
# ---------------------------------------------------------------------------

def _c_function_name(node: Node) -> Node | None:
    decl = _child_by_type(node, "function_declarator")
    if decl is None:
        return None
    for c in _walk(decl):
        if c.type == "identifier":
            return c
    return None


def _extract_c_symbols(root: Node, source: bytes, is_cpp: bool) -> list[ExtractedSymbol]:
    symbols: list[ExtractedSymbol] = []
    for child in root.children:
        if child.type == "function_definition":
            name = _c_function_name(child)
            symbols.append(_simple_symbol(child, source, name, "function"))
        elif child.type == "class_specifier" and is_cpp:
            name = _child_by_type(child, "type_identifier")
            class_name = _get_node_text(name, source) if name else None
            bases: list[str] = []
            body = _child_by_type(child, "field_declaration_list")
            methods: list[ExtractedSymbol] = []
            if body:
                for m in body.named_children:
                    if m.type == "function_definition":
                        n = _c_function_name(m) or name
                        methods.append(_simple_symbol(m, source, n, "method"))
                for b in _walk(body):
                    if b.type == "base_class_clause":
                        for t in b.named_children:
                            tid = _child_by_type(t, "type_identifier")
                            if tid:
                                bases.append(_get_node_text(tid, source))
            symbols.append(
                _simple_symbol(child, source, name, "class", bases=bases, children=methods)
            )
        elif child.type in ("struct_specifier", "union_specifier", "enum_specifier"):
            name = _child_by_type(child, "type_identifier")
            bases: list[str] = []
            body = _child_by_type(child, "field_declaration_list")
            methods: list[ExtractedSymbol] = []
            if body and child.type in ("struct_specifier", "union_specifier"):
                for m in body.named_children:
                    if m.type == "function_definition" and is_cpp:
                        n = _c_function_name(m) or name
                        methods.append(_simple_symbol(m, source, n, "method"))
            symbols.append(
                _simple_symbol(child, source, name, "class", bases=bases, children=methods)
            )
    return symbols


def _extract_c_imports(root: Node, source: bytes) -> list[ExtractedImport]:
    imports: list[ExtractedImport] = []
    for node in _walk(root):
        if node.type != "preproc_include":
            continue
        path = _child_by_type(node, "system_lib_string", "string_literal")
        if path is None:
            continue
        module = _get_node_text(path, source).strip("<>\"'")
        imports.append(ExtractedImport(
            module=module, imported_name=Path(module).stem, kind="include",
            line=node.start_point[0] + 1,
        ))
    return imports


def _c_callee(node: Node, source: bytes) -> str | None:
    fn = _child_by_type(node, "identifier", "field_expression", "qualified_identifier")
    if fn is None:
        return None
    if fn.type == "field_expression":
        f = _child_by_type(fn, "field_identifier")
        return _get_node_text(f, source) if f else None
    if fn.type == "qualified_identifier":
        f = _child_by_type(fn, "identifier")
        return _get_node_text(f, source) if f else None
    return _get_node_text(fn, source)


# ---------------------------------------------------------------------------
# C#
# ---------------------------------------------------------------------------

CSHARP_TYPE_DECLS = {
    "class_declaration", "interface_declaration", "struct_declaration",
    "enum_declaration", "record_declaration",
}


def _extract_csharp_symbols(root: Node, source: bytes) -> list[ExtractedSymbol]:
    symbols: list[ExtractedSymbol] = []
    for child in root.children:
        if child.type not in CSHARP_TYPE_DECLS:
            continue
        name = _child_by_type(child, "identifier")
        bases: list[str] = []
        base_list = _child_by_type(child, "base_list")
        if base_list:
            for t in _walk(base_list):
                if t.type in ("identifier", "generic_name"):
                    bases.append(_last_segment(_get_node_text(t, source)))
        methods: list[ExtractedSymbol] = []
        body = _child_by_type(child, "declaration_list")
        if body:
            for m in body.named_children:
                if m.type == "method_declaration":
                    n = _child_by_type(m, "identifier")
                    methods.append(_simple_symbol(m, source, n, "method"))
                elif m.type == "constructor_declaration":
                    n = _child_by_type(m, "identifier")
                    methods.append(_simple_symbol(m, source, n, "method"))
        symbols.append(_simple_symbol(child, source, name, "class", bases=bases, children=methods))
    return symbols


def _extract_csharp_imports(root: Node, source: bytes) -> list[ExtractedImport]:
    imports: list[ExtractedImport] = []
    for node in _walk(root):
        if node.type != "using_directive":
            continue
        path = _child_by_type(node, "qualified_name", "identifier")
        if path is None:
            continue
        full = _get_node_text(path, source)
        imports.append(ExtractedImport(
            module=".".join(full.split(".")[:-1]),
            imported_name=full.split(".")[-1],
            kind="using",
            line=node.start_point[0] + 1,
        ))
    return imports


def _csharp_callee(node: Node, source: bytes) -> str | None:
    if node.type == "object_creation_expression":
        t = _child_by_type(node, "identifier", "generic_name", "qualified_name")
        if t:
            return _last_segment(_get_node_text(t, source))
        return None
    fn = _child_by_type(node, "identifier", "member_access_expression")
    if fn is None:
        return None
    # last identifier inside the callee expression is the method name
    name = None
    for c in _walk(fn):
        if c.type == "identifier":
            name = _get_node_text(c, source)
    return name


# ---------------------------------------------------------------------------
# Ruby
# ---------------------------------------------------------------------------

def _extract_ruby_symbols(root: Node, source: bytes) -> list[ExtractedSymbol]:
    symbols: list[ExtractedSymbol] = []
    for child in root.children:
        if child.type == "method":
            name = _child_by_type(child, "identifier")
            symbols.append(_simple_symbol(child, source, name, "function"))
        elif child.type == "singleton_method":
            name = _child_by_type(child, "identifier")
            symbols.append(_simple_symbol(child, source, name, "method"))
        elif child.type in ("class", "module"):
            name = _child_by_type(child, "constant")
            if name is None:
                continue
            bases: list[str] = []
            methods: list[ExtractedSymbol] = []
            body = _child_by_type(child, "body_statement")
            for c in _walk(child):
                if c.type == "superclass":
                    sup = _child_by_type(c, "constant")
                    if sup:
                        bases.append(_get_node_text(sup, source))
                elif c.type == "call" and c.parent in (child, body):
                    m = _child_by_type(c, "identifier")
                    if m and _get_node_text(m, source) in ("include", "extend", "prepend"):
                        for a in _walk(c):
                            if a.type == "constant":
                                bases.append(_get_node_text(a, source))
                elif c.type in ("method", "singleton_method") and c.parent in (child, body):
                    n = _child_by_type(c, "identifier")
                    if n:
                        methods.append(_simple_symbol(c, source, n, "method"))
            symbols.append(
                _simple_symbol(child, source, name, "class", bases=bases, children=methods)
            )
    return symbols


def _extract_ruby_imports(root: Node, source: bytes) -> list[ExtractedImport]:
    imports: list[ExtractedImport] = []
    for node in _walk(root):
        if node.type != "call":
            continue
        m = _child_by_type(node, "identifier")
        if m is None or _get_node_text(m, source) not in ("require", "require_relative", "load"):
            continue
        for a in _walk(node):
            if a.type == "string":
                imports.append(ExtractedImport(
                    module=_get_node_text(a, source).strip("'\""),
                    imported_name="",
                    kind="require",
                    line=node.start_point[0] + 1,
                ))
    return imports


def _ruby_callee(node: Node, source: bytes) -> str | None:
    ident = None
    for c in node.children:
        if c.type == "identifier":
            ident = _get_node_text(c, source)
    return ident


# ---------------------------------------------------------------------------
# PHP
# ---------------------------------------------------------------------------

PHP_TYPE_DECLS = {
    "class_declaration", "interface_declaration", "trait_declaration", "enum_declaration"
}


def _extract_php_symbols(root: Node, source: bytes) -> list[ExtractedSymbol]:
    symbols: list[ExtractedSymbol] = []
    for child in root.children:
        if child.type == "function_definition":
            name = _child_by_type(child, "name")
            symbols.append(_simple_symbol(child, source, name, "function"))
        elif child.type in PHP_TYPE_DECLS:
            name = _child_by_type(child, "name")
            if name is None:
                continue
            bases: list[str] = []
            base = _child_by_type(child, "base_clause")
            if base:
                t = _child_by_type(base, "name")
                if t:
                    bases.append(_get_node_text(t, source))
            ifaces = _child_by_type(child, "class_interface_clause", "interface_list")
            if ifaces:
                for t in _walk(ifaces):
                    if t.type == "name":
                        bases.append(_get_node_text(t, source))
            methods: list[ExtractedSymbol] = []
            body = _child_by_type(child, "declaration_list")
            if body:
                for m in body.named_children:
                    if m.type == "method_declaration":
                        n = _child_by_type(m, "name")
                        methods.append(_simple_symbol(m, source, n, "method"))
            symbols.append(_simple_symbol(child, source, name, "class", bases=bases, children=methods))
    return symbols


def _extract_php_imports(root: Node, source: bytes) -> list[ExtractedImport]:
    imports: list[ExtractedImport] = []
    for node in _walk(root):
        if node.type == "namespace_use_declaration":
            for clause in _walk(node):
                if clause.type == "namespace_use_clause":
                    name = _child_by_type(clause, "name", "qualified_name")
                    if name is None:
                        continue
                    full = _get_node_text(name, source).lstrip("\\")
                    # Alias: `use Foo\Bar as Baz;` — the last direct name child
                    alias = None
                    for c in clause.children:
                        if c.type in ("name", "identifier"):
                            alias = _get_node_text(c, source)
                    imported = alias if alias else _last_segment(full)
                    imports.append(ExtractedImport(
                        module=full, imported_name=imported, kind="use",
                        line=node.start_point[0] + 1,
                    ))
        elif node.type == "require_expression":
            p = _child_by_type(node, "string")
            if p:
                imports.append(ExtractedImport(
                    module=_get_node_text(p, source).strip("'\""),
                    imported_name="", kind="require",
                    line=node.start_point[0] + 1,
                ))
    return imports


def _php_callee(node: Node, source: bytes) -> str | None:
    if node.type == "object_creation_expression":
        t = _child_by_type(node, "name", "qualified_name")
        return _last_segment(_get_node_text(t, source)) if t else None
    fn = _child_by_type(node, "name", "qualified_name")
    if fn is None:
        return None
    return _last_segment(_get_node_text(fn, source))


# ---------------------------------------------------------------------------
# Shared call helpers
# ---------------------------------------------------------------------------

def _symbol_ranges(symbols: list[ExtractedSymbol]) -> list[tuple[int, int, str]]:
    """Flatten symbols (and children) into (start, end, name) ranges."""
    ranges: list[tuple[int, int, str]] = []
    for sym in symbols:
        ranges.append((sym.start_line, sym.end_line, sym.name))
        for child in sym.children:
            ranges.append((child.start_line, child.end_line, child.name))
    return ranges


def _find_enclosing_symbol_name(line: int, ranges: list[tuple[int, int, str]]) -> str | None:
    """Find the innermost symbol containing the given line."""
    best: tuple[int, int, str] | None = None
    for start, end, name in ranges:
        if start <= line <= end:
            if best is None or (end - start) < (best[1] - best[0]):
                best = (start, end, name)
    return best[2] if best else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _looks_like_tsx(content: str) -> bool:
    # Quick heuristic: contains JSX-like syntax
    return "</" in content or "< />" in content or "/>" in content


def parse_file(content: str, language: str) -> ExtractedFile:
    """Parse a source file and return all extracted symbols, imports, and calls."""
    if language not in LANGUAGES:
        return ExtractedFile()

    lang = LANGUAGES[language]
    if language == "typescript" and _looks_like_tsx(content):
        lang = TSX_LANGUAGE

    parser = Parser(lang)
    source = content.encode("utf-8")
    tree = parser.parse(source)

    if language == "python":
        symbols = _extract_python_symbols(tree.root_node, source)
        imports = _extract_python_imports(tree.root_node, source)
        calls = _extract_python_calls(tree.root_node, source, symbols)
    elif language == "rust":
        symbols = _extract_rust_symbols(tree.root_node, source)
        imports = _extract_rust_imports(tree.root_node, source)
        calls = _extract_rust_calls(tree.root_node, source, symbols)
    elif language == "go":
        symbols = _extract_go_symbols(tree.root_node, source)
        imports = _extract_go_imports(tree.root_node, source)
        calls = _extract_calls(tree.root_node, source, symbols, {"call_expression"}, _go_callee)
    elif language == "java":
        symbols = _extract_java_symbols(tree.root_node, source)
        imports = _extract_java_imports(tree.root_node, source)
        calls = _extract_calls(
            tree.root_node,
            source,
            symbols,
            {"method_invocation", "object_creation_expression"},
            _java_callee,
        )
    elif language in ("c", "cpp"):
        symbols = _extract_c_symbols(tree.root_node, source, is_cpp=(language == "cpp"))
        imports = _extract_c_imports(tree.root_node, source)
        calls = _extract_calls(tree.root_node, source, symbols, {"call_expression"}, _c_callee)
    elif language == "csharp":
        symbols = _extract_csharp_symbols(tree.root_node, source)
        imports = _extract_csharp_imports(tree.root_node, source)
        calls = _extract_calls(
            tree.root_node,
            source,
            symbols,
            {"invocation_expression", "object_creation_expression"},
            _csharp_callee,
        )
    elif language == "ruby":
        symbols = _extract_ruby_symbols(tree.root_node, source)
        imports = _extract_ruby_imports(tree.root_node, source)
        calls = _extract_calls(
            tree.root_node, source, symbols, {"call", "method_call"}, _ruby_callee
        )
    elif language == "php":
        symbols = _extract_php_symbols(tree.root_node, source)
        imports = _extract_php_imports(tree.root_node, source)
        calls = _extract_calls(
            tree.root_node,
            source,
            symbols,
            {"function_call_expression", "member_call_expression", "object_creation_expression"},
            _php_callee,
        )
    else:
        symbols = _extract_js_ts_symbols(tree.root_node, source)
        imports = _extract_js_imports(tree.root_node, source)
        calls = _extract_js_calls(tree.root_node, source, symbols)

    return ExtractedFile(symbols=symbols, imports=imports, calls=calls)
