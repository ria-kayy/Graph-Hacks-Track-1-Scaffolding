from backend.graph.client import Graph
from backend.graph.vectors import index_embeddings


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--issues-only", action="store_true")
    args = parser.parse_args()
    print("Embeddings stored in FalkorDB:", index_embeddings(Graph(), ("Issue",) if args.issues_only else ("Issue", "Symbol")))
