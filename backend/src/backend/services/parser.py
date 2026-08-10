"""Tree-sitter code parsing service — extracts symbols, imports, calls, and inheritance.

Supports Python, JavaScript, and TypeScript.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import tree_sitter_javascript as tsjavascript
import tree_sitter_python as tspython
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Node, Parser

logger = logging.getLogger(__name__)

PY_LANGUAGE = Language(tspython.language())
JS_LANGUAGE = Language(tsjavascript.language())
TS_LANGUAGE = Language(tstypescript.language_typescript())
TSX_LANGUAGE = Language(tstypescript.language_tsx())

LANGUAGES: dict[str, Language] = {
    "python": PY_LANGUAGE,
    "javascript": JS_LANGUAGE,
    "typescript": TS_LANGUAGE,
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
    else:
        symbols = _extract_js_ts_symbols(tree.root_node, source)
        imports = _extract_js_imports(tree.root_node, source)
        calls = _extract_js_calls(tree.root_node, source, symbols)

    return ExtractedFile(symbols=symbols, imports=imports, calls=calls)
