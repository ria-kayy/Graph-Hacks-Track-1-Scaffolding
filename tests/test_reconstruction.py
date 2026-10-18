from backend.ingestion.code_parser import parse_sources
from backend.ingestion.diff_mapper import map_symbols
from backend.ingestion.github import closing_issues


def test_parser_async_methods_imports_and_calls():
    parsed = parse_sources("owner/repo", {"src/pkg/a.py": "from .b import helper\nclass Engine:\n    async def run(self):\n        helper()\n        self.stop()\n    def stop(self):\n        pass\n", "src/pkg/b.py": "def helper():\n    pass\n"})
    assert {(s["qualified_name"], s["kind"]) for s in parsed.symbols} == {("pkg.a.Engine", "class"), ("pkg.a.Engine.run", "method"), ("pkg.a.Engine.stop", "method"), ("pkg.b.helper", "function")}
    assert len(parsed.calls) == 2
    assert parsed.imports


def test_unresolved_calls_are_skipped():
    parsed = parse_sources("o/r", {"a.py": "def run(obj):\n    obj.unknown()\n"})
    assert not parsed.calls


def test_nested_calls_not_attributed_to_parent():
    parsed = parse_sources("o/r", {"a.py": "def target(): pass\ndef outer():\n    def inner():\n        target()\n"})
    assert len(parsed.calls) == 1
    assert parsed.calls[0]["a"].endswith("a.outer.inner")


def test_shadowed_parameters_and_assigned_names_are_not_resolved():
    parsed = parse_sources("o/r", {"a.py": "def helper(): pass\ndef run(helper):\n    helper()\ndef other():\n    helper = unknown\n    helper()\n"})
    assert not parsed.calls


def test_unqualified_class_members_are_not_globals():
    parsed = parse_sources("o/r", {"a.py": "class C:\n    def helper(self): pass\n    def run(self):\n        helper()\n        self.helper()\n"})
    assert len(parsed.calls) == 1


def test_outer_resolves_its_nested_function():
    parsed = parse_sources("o/r", {"a.py": "def outer():\n    def inner(): pass\n    inner()\n"})
    assert parsed.calls[0]["a"].endswith("a.outer")
    assert parsed.calls[0]["b"].endswith("a.outer.inner")


def test_diff_maps_old_and_new_lines():
    before = parse_sources("o/r", {"a.py": "def first():\n    return 1\n\ndef second():\n    return 2\n"}).symbols
    after = parse_sources("o/r", {"a.py": "def first():\n    return 1\n\ndef second():\n    return 3\n"}).symbols
    mapped = map_symbols("@@ -5 +5 @@\n-    return 2\n+    return 3", before, after)
    assert [m["symbol"]["name"] for m in mapped] == ["second"]
    assert mapped[0]["lines_added"] == mapped[0]["lines_deleted"] == 1


def test_deleted_symbol_is_mapped():
    before = parse_sources("o/r", {"a.py": "def gone():\n    return 1\n"}).symbols
    mapped = map_symbols("@@ -1,2 +0,0 @@", before, [])
    assert mapped[0]["symbol"]["name"] == "gone"


def test_closing_variants_and_cross_repo():
    for verb in ("fix", "fixes", "fixed", "close", "closes", "closed", "resolve", "resolves", "resolved"):
        assert closing_issues(f"{verb} #12", "o/r") == [12]
    assert closing_issues("Fixes https://github.com/o/r/issues/12", "o/r") == [12]
    assert closing_issues("Fixes https://github.com/x/y/issues/12", "o/r") == []
    assert closing_issues("mentions #12") == []
