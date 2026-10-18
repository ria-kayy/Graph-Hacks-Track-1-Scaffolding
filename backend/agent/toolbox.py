"""Validated read-only tools bound to one repository and historical cutoff."""
from pydantic import BaseModel, ConfigDict, Field


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Search(Arguments):
    query: str = Field(min_length=1, max_length=10000)
    limit: int = Field(default=6, ge=1, le=10)


class Symbol(Arguments):
    symbol: str = Field(min_length=1, max_length=1000)


class Source(Arguments):
    file_path: str = Field(min_length=1, max_length=1000)
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)


TOOLS = {
    "search_code": (Search, "Search actual source symbols and return verified code citations."),
    "search_commits": (Search, "Search time-valid commit messages as historical background."),
    "similar_issues": (Search, "Search past issues; similarity alone does not establish causation."),
    "localize": (Search, "Rank source and relevant historical candidates for a bug description."),
    "read_source": (Source, "Read at most 200 lines of an indexed file at the active revision."),
    "get_symbol_context": (Symbol, "Read the snapshot symbol metadata and static call relationships."),
    "trace_callers": (Symbol, "List static callers of an indexed symbol; structural evidence only."),
    "trace_callees": (Symbol, "List static callees of an indexed symbol; structural evidence only."),
    "history": (Symbol, "Retrieve verified changes and directly attributed rationale for a symbol."),
    "impact": (Symbol, "Trace bounded transitive callers of a symbol."),
    "experts": (Symbol, "Retrieve contributors with source-backed changes and reviews."),
}


def dispatch(repo_id, as_of, name, arguments):
    from backend.agent import investigation as service
    from backend.repositories import context
    from backend.graph.client import Graph
    if name not in TOOLS:
        raise ValueError("Unknown investigation tool")
    args = TOOLS[name][0].model_validate(arguments).model_dump()
    if name in ("search_code", "search_commits"):
        return getattr(service, name)(repo_id, args.pop("query"), as_of=as_of, **args)
    if name == "read_source":
        return service.read_source(repo_id, as_of=as_of, **args)
    if name in ("get_symbol_context", "trace_callers", "trace_callees"):
        result = service.get_symbol_context(repo_id, args["symbol"], as_of)
        return result if name == "get_symbol_context" else {"snapshot_ref": result["snapshot_ref"], name: result["callers" if name == "trace_callers" else "callees"]}
    graph = Graph(context(repo_id).graph_name)
    if name == "similar_issues":
        from backend.tools.similar import similar_issues
        return similar_issues(graph, args["query"], as_of, k=args["limit"])
    if name == "localize":
        from backend.tools.localize import localize
        return localize(graph, {"title": args["query"]}, as_of, limit=args["limit"])
    if name == "history":
        from backend.tools.history import history
        return history(graph, args["symbol"], as_of)
    if name == "impact":
        from backend.tools.impact import impact
        return impact(graph, args["symbol"], as_of)
    if name == "experts":
        from backend.tools.experts import experts
        return experts(graph, args["symbol"], as_of)
    raise ValueError("Unsupported investigation tool")
