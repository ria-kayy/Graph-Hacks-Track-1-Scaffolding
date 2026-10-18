from backend.graph.client import Graph
from backend.ingestion.claims import extract_claims


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="Use configured structured-output provider; may incur API costs")
    args = parser.parse_args()
    extractor = None
    if args.llm:
        from backend.agent.llm import extract
        extractor = extract
    print(extract_claims(Graph(), extractor))
