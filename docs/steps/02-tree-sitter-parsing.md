# Step 2: Tree-sitter Code Parsing Service

## Goal

Create `backend/src/backend/services/parser.py` — a service that uses tree-sitter to parse Python, JavaScript, and TypeScript source files and extract structured symbols (functions, classes, methods) with their signatures, docstrings, and line ranges.

---

## Prerequisites

- Step 1 complete (dependencies `tree-sitter`, `tree-sitter-python`, `tree-sitter-javascript`, `tree-sitter-typescript` already installed)

---

## What to Build

### File: `backend/src/backend/services/parser.py`

### 2.1 Language Setup

Initialize tree-sitter with the three language grammars. The `tree-sitter` v0.26 Python bindings use `Language` objects from each grammar package.

```python
import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())
JS_LANGUAGE = Language(tsjavascript.language())
TS_LANGUAGE = Language(tstypescript.language_typescript())
TSX_LANGUAGE = Language(tstypescript.language_tsx())

LANGUAGES = {
    "python": PY_LANGUAGE,
    "javascript": JS_LANGUAGE,
    "typescript": TS_LANGUAGE,
}
```

Create a parser instance per parse call (or reuse one, resetting the language each time).

### 2.2 Core Parse Function

```python
def parse_file(content: str, language: str) -> list[ExtractedSymbol]
```

**Input**: file content as a string, language identifier (`"python"`, `"javascript"`, `"typescript"`)

**Output**: list of `ExtractedSymbol` dataclass/TypedDict:

```python
@dataclass
class ExtractedSymbol:
    name: str
    kind: str              # "function", "class", "method"
    start_line: int        # 1-indexed
    end_line: int          # 1-indexed
    source_text: str       # full source code of the symbol
    signature: str | None  # e.g. "def foo(a: int, b: str) -> bool"
    docstring: str | None  # extracted docstring/JSDoc
    children: list[ExtractedSymbol]  # methods inside a class
```

### 2.3 Python Extraction

Walk the AST from tree-sitter. The relevant node types for Python are:

| Node type | Maps to |
|---|---|
| `function_definition` | `kind="function"` (top-level) or `kind="method"` (inside class) |
| `class_definition` | `kind="class"` |

**For each `function_definition`:**
1. **Name**: child node of type `identifier` (the first one)
2. **Signature**: extract the text from the start of the node through the end of the `parameters` node (or through the return type annotation if present `:` → `type`). Simplest: take text from `def` through `)` or through `-> type:`
3. **Docstring**: check if the first statement in the `block` child is an `expression_statement` containing a `string` node. If so, that's the docstring.
4. **Source text**: `content[node.start_byte:node.end_byte]`
5. **Lines**: `node.start_point[0] + 1` through `node.end_point[0] + 1`

**For each `class_definition`:**
1. **Name**: child `identifier`
2. **Signature**: `class ClassName(bases):` — extract text through the `:`
3. **Docstring**: first statement in body, same as function
4. **Children**: recursively extract `function_definition` nodes inside the class body — mark them as `kind="method"`

**Tree-sitter query approach (preferred):**

```python
PYTHON_QUERY = """
(function_definition
  name: (identifier) @func.name) @func.def

(class_definition
  name: (identifier) @class.name
  body: (block) @class.body) @class.def
"""
```

Use `language.query(PYTHON_QUERY)` and iterate over captures. For each class, do a sub-query on the class body to find methods.

### 2.4 JavaScript/TypeScript Extraction

Relevant node types:

| Node type | Maps to |
|---|---|
| `function_declaration` | `kind="function"` |
| `arrow_function` (when assigned to a `variable_declarator`) | `kind="function"` |
| `method_definition` | `kind="method"` |
| `class_declaration` | `kind="class"` |
| `export_statement` containing any of the above | unwrap and extract inner |

**For functions:**
- Name from `identifier` child
- Signature: text from start through closing `)` of formal_parameters (include type annotations for TS)
- Docstring: look for a preceding sibling that is a `comment` node starting with `/**` (JSDoc)

**For arrow functions:**
- These appear as: `const foo = (params) => { ... }` or `const foo = (params): ReturnType => { ... }`
- The `variable_declarator` has `name` (identifier) and `value` (arrow_function)
- Extract name from the variable_declarator, signature from the arrow function params

**For classes:**
- Name from `identifier` child
- Methods: recurse into `class_body` and find `method_definition` nodes

**TypeScript additions:**
- `interface_declaration` — optionally extract as `kind="interface"`
- `type_alias_declaration` — optionally extract as `kind="type"`
- Type annotations are part of the parameter nodes, so signatures naturally include types

### 2.5 Helper Functions

```python
def _get_node_text(node, source_bytes: bytes) -> str:
    """Extract source text for a tree-sitter node."""
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8")

def _extract_docstring_python(block_node, source_bytes: bytes) -> str | None:
    """Extract Python docstring from the first statement of a block."""
    ...

def _extract_jsdoc(node, source_bytes: bytes) -> str | None:
    """Look for a JSDoc comment immediately before a node."""
    # Check previous named sibling — if it's a comment starting with /**, extract it
    ...

def _extract_signature(node, source_bytes: bytes, language: str) -> str:
    """Extract the function/class signature (first line up to the body)."""
    ...
```

### 2.6 Module-Level Entry Point

```python
def parse_file(content: str, language: str) -> list[ExtractedSymbol]:
    """Parse a source file and extract all symbols."""
    if language not in LANGUAGES:
        return []

    lang = LANGUAGES[language]
    # Handle TSX files
    if language == "typescript" and content_looks_like_tsx(content):
        lang = TSX_LANGUAGE

    parser = Parser(lang)
    tree = parser.parse(content.encode("utf-8"))

    if language == "python":
        return _extract_python_symbols(tree.root_node, content.encode("utf-8"))
    else:
        return _extract_js_ts_symbols(tree.root_node, content.encode("utf-8"))
```

---

## Testing

After implementing, test manually:

```python
# Quick test script — run with: uv run python -c "..."
from backend.services.parser import parse_file

# Test Python
code = '''
def hello(name: str) -> str:
    """Greet someone."""
    return f"Hello, {name}"

class Calculator:
    """A simple calculator."""

    def add(self, a: int, b: int) -> int:
        return a + b
'''
symbols = parse_file(code, "python")
for s in symbols:
    print(f"{s.kind}: {s.name} (lines {s.start_line}-{s.end_line})")
    print(f"  signature: {s.signature}")
    print(f"  docstring: {s.docstring}")
    for child in s.children:
        print(f"  - {child.kind}: {child.name}")
```

Expected output:
```
function: hello (lines 2-4)
  signature: def hello(name: str) -> str
  docstring: Greet someone.
class: Calculator (lines 6-10)
  signature: class Calculator
  docstring: A simple calculator.
  - method: add
```

Also test with JS/TS code containing arrow functions, classes, JSDoc comments, and exported functions.

---

## Edge Cases to Handle

1. **Decorated functions** (`@decorator` above `def`) — tree-sitter wraps these in a `decorated_definition` node. Unwrap to get the inner `function_definition`.
2. **Async functions** — `async_function_definition` in Python, `function_declaration` with `async` keyword in JS/TS.
3. **Nested functions** — decide whether to extract them. Recommendation: only extract top-level and class-level symbols to avoid noise.
4. **Anonymous arrow functions** — skip these (no name to reference).
5. **Re-exported functions** (`export { foo } from './bar'`) — skip, not a definition.
6. **Very large files** — the `walk_source_files()` in `github.py` already caps at 500KB.
7. **Empty files / syntax errors** — tree-sitter is error-tolerant and will still produce a partial AST. Handle gracefully.

---

## Definition of Done

- [ ] `backend/src/backend/services/parser.py` exists with `parse_file()` and `ExtractedSymbol`
- [ ] Correctly extracts functions, classes, and methods from Python
- [ ] Correctly extracts functions (including arrow), classes, and methods from JS/TS
- [ ] Extracts signatures and docstrings
- [ ] Handles decorated and async functions
- [ ] Manual test with the snippet above passes
