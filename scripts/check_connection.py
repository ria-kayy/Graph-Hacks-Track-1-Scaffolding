"""Milestone 1: exercise CREATE, MATCH, DELETE against real FalkorDB."""
from uuid import uuid4
from backend.graph.client import Graph


def main():
    graph = Graph()
    identity = "acceptance:" + str(uuid4())
    graph.query("CREATE (s:Symbol {id: $id, qualified_name: 'acceptance.sample'})", {"id": identity})
    assert graph.query("MATCH (s:Symbol {id: $id}) RETURN s.qualified_name", {"id": identity}) == [["acceptance.sample"]]
    graph.query("MATCH (s:Symbol {id: $id}) DELETE s", {"id": identity})
    assert graph.query("MATCH (s:Symbol {id: $id}) RETURN s", {"id": identity}) == []
    print("FalkorDB CREATE/MATCH/DELETE acceptance passed")


if __name__ == "__main__":
    main()
