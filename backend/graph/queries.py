from backend.config import ROOT


def query(name):
    return (ROOT / "cypher" / f"{name}.cypher").read_text()
