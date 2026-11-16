"""Replay baseline results and row-access traces as JSON."""
import argparse
import json
from pathlib import Path
from pipeline import run


def samples():
    return json.loads(Path(__file__).with_name("samples.json").read_text())


def observe(name="all"):
    jobs = samples()
    chosen = jobs if name == "all" else [j for j in jobs if j["name"] == name]
    if not chosen:
        raise ValueError("unknown case")
    return [{"name": j["name"], **run(j)} for j in chosen]


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("name", nargs="?", default="all")
    args = p.parse_args()
    print(json.dumps(observe(args.name), ensure_ascii=False, indent=2))
