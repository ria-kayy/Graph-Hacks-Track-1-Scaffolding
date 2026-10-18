"""Python AST extraction: skip ambiguous calls rather than inventing targets."""
import ast
import hashlib
import json
import warnings
from dataclasses import dataclass, field
from pathlib import PurePosixPath

PARSER_VERSION = "2"


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def module_name(path):
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[0] == "src":
        parts.pop(0)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


@dataclass
class Parsed:
    files: list = field(default_factory=list)
    symbols: list = field(default_factory=list)
    contains: list = field(default_factory=list)
    calls: list = field(default_factory=list)
    imports: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def parse_sources(repo, sources, snapshot="current"):
    from backend.graph.client import edge
    result = Parsed()
    modules = {module_name(p): p for p in sources}
    by_name, pending, trees = {}, [], {}
    for path, source in sorted(sources.items()):
        file_id = f"{repo}:{path}"
        result.files.append({"id": file_id, "path": path, "language": "python", "content_hash": digest(source), "source_text": source})
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(source)
        except SyntaxError as exc:
            result.warnings.append({"path": path, "error": str(exc)})
            continue
        trees[path] = tree
        module = module_name(path)
        aliases = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    aliases[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    package = module.split(".") if path.endswith("__init__.py") else module.split(".")[:-1]
                    prefix = package[:len(package)-node.level+1]
                    base = ".".join(prefix + ([base] if base else []))
                for alias in node.names:
                    aliases[alias.asname or alias.name] = f"{base}.{alias.name}".strip(".")
                if base in modules:
                    result.imports.append(edge(file_id, f"{repo}:{modules[base]}", snapshot, snapshot_ref=snapshot, confidence=1.0))
        for target in aliases.values():
            imported = target if target in modules else target.rsplit(".", 1)[0]
            if imported in modules and modules[imported] != path:
                result.imports.append(edge(file_id, f"{repo}:{modules[imported]}", snapshot, snapshot_ref=snapshot, confidence=1.0))

        def visit(node, scope=(), parent_kind=None, lexical_scopes=(), class_scope=None):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = scope + (node.name,)
                qualified = ".".join((module, *name)).strip(".")
                identity = f"{repo}:{path}:{qualified}"
                kind = "class" if isinstance(node, ast.ClassDef) else "method" if parent_kind == "class" else "function"
                text = ast.get_source_segment(source, node) or ""
                start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                symbol = {"id": identity, "qualified_name": qualified, "name": node.name, "kind": kind, "file_path": path, "start_line": start, "end_line": node.end_lineno, "docstring": ast.get_docstring(node) or "", "content_hash": digest(text), "body_summary": text[:1200], "snapshot_ref": snapshot}
                result.symbols.append(symbol)
                by_name[qualified] = identity
                compact = {key: symbol[key] for key in ("id", "qualified_name", "name", "kind", "file_path", "start_line", "end_line", "snapshot_ref")}
                result.contains.append(edge(
                    file_id, identity, snapshot, snapshot_ref=snapshot,
                    parser_version=PARSER_VERSION, metadata_json=json.dumps(symbol),
                    search_text=(qualified + "\n" + path + "\n" + text).lower(),
                    search_names=(qualified + " " + path).lower(), search_kind=kind,
                    search_metadata_json=json.dumps(compact), confidence=1.0,
                ))
                if kind != "class":
                    blocked = {arg.arg for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]}
                    blocked.update(arg.arg for arg in (node.args.vararg, node.args.kwarg) if arg)
                    def local_bindings(item):
                        if item is not node and isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                            return
                        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store):
                            blocked.add(item.id)
                        for child in ast.iter_child_nodes(item):
                            local_bindings(child)
                    local_bindings(node)
                    bound_class = None if any(isinstance(d, ast.Name) and d.id == "staticmethod" for d in node.decorator_list) else class_scope
                    # Nested definitions belong to their own caller, not the enclosing function.
                    def own_calls(item):
                        if item is not node and isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            return
                        if isinstance(item, ast.Call):
                            pending.append((identity, module, (qualified, *lexical_scopes), bound_class, aliases, blocked, item.func))
                        for child in ast.iter_child_nodes(item):
                            own_calls(child)
                    own_calls(node)
                for child in node.body:
                    visit(child, name, kind, lexical_scopes if kind == "class" else (qualified, *lexical_scopes), qualified if kind == "class" else class_scope)
            else:
                for child in ast.iter_child_nodes(node):
                    visit(child, scope, parent_kind, lexical_scopes, class_scope)
        visit(tree)

    def dotted(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = dotted(node.value)
            return f"{prefix}.{node.attr}" if prefix else None
        return None

    for caller, module, lexical_scopes, class_scope, aliases, blocked, func in pending:
        name = dotted(func)
        if not name:
            continue
        candidates = []
        first, *rest = name.split(".")
        if first in blocked and not (first in ("self", "cls") and class_scope and rest):
            continue
        if "." not in name:
            candidates.extend(prefix + "." + name for prefix in lexical_scopes)
            candidates.append(module + "." + name)
        elif name.startswith(("self.", "cls.")) and class_scope:
            candidates.append(class_scope + "." + name.split(".", 1)[1])
        else:
            candidates.append(f"{module}.{name}")
        if first in aliases:
            candidates.append(".".join((aliases[first], *rest)))
        for qualified in candidates:
            if qualified in by_name:
                result.calls.append(edge(caller, by_name[qualified], snapshot, snapshot_ref=snapshot, confidence=0.85, resolution="static"))
                break
    return result


def persist(graph, parsed, repo, snapshot):
    clear_snapshot(graph, snapshot)
    graph.nodes("File", parsed.files)
    graph.nodes("Symbol", parsed.symbols)
    graph.edges("Repository", "HAS_FILE", "File", [{"a": repo, "b": f["id"], "key": snapshot, "props": {"snapshot_ref": snapshot}} for f in parsed.files])
    graph.edges("File", "CONTAINS", "Symbol", parsed.contains)
    graph.edges("Symbol", "CALLS", "Symbol", parsed.calls)
    graph.edges("File", "IMPORTS", "File", parsed.imports)


def clear_snapshot(graph, ref):
    for relationship in ("CALLS", "CONTAINS", "IMPORTS"):
        graph.query(f"MATCH ()-[e:{relationship}]->() WHERE e.snapshot_ref=$ref DELETE e", {"ref": ref})


def ensure_search_fields(graph, context, ref):
    """Upgrade older snapshots once, without changing source or structural facts."""
    if not graph.query("MATCH ()-[e:CONTAINS]->(:Symbol) WHERE e.snapshot_ref=$ref AND (e.search_text IS NULL OR e.search_metadata_json IS NULL) RETURN e.key LIMIT 1", {"ref": ref}):
        return
    from backend.ingestion.git_history import sources_at
    parsed = parse_sources(context.identity, sources_at(context.checkout, ref), ref)
    # Only properties on existing snapshot edges are updated. In particular, an
    # old snapshot upgrade must not overwrite mutable current symbol/file nodes.
    values = [{"id": item["b"], **{key: item["props"][key] for key in ("search_text", "search_names", "search_kind", "search_metadata_json")}} for item in parsed.contains]
    for offset in range(0, len(values), 100):
        graph.query("UNWIND $rows AS row MATCH ()-[e:CONTAINS]->(s:Symbol {id:row.id}) WHERE e.snapshot_ref=$ref SET e.search_text=row.search_text,e.search_names=row.search_names,e.search_kind=row.search_kind,e.search_metadata_json=row.search_metadata_json", {"rows": values[offset:offset+100], "ref": ref})
