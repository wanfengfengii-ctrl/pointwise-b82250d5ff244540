"""Check replayable observations, not the correctness of an unimplemented design."""
import argparse
import json
from pathlib import Path
import re
from observe import observe


def verify(path):
    doc = Path(path).read_text()
    matches = re.findall(r"```observations\s*\n(.*?)\n```", doc, re.S)
    if len(matches) != 1:
        raise ValueError("expected one observations block")
    actual = observe("all")
    if json.loads(matches[0]) != actual:
        raise ValueError("document observations differ from replay")
    citations = re.findall(r"\b(source|mosaic_ref|regrid_ref|pipeline)\.py:L([1-9][0-9]*)", doc)
    if not citations:
        raise ValueError("no source locations")
    for name, line in citations:
        if int(line) > len(Path(name + ".py").read_text().splitlines()):
            raise ValueError("source location outside file")
    return actual


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("document")
    args = p.parse_args()
    print(json.dumps({"observations": verify(args.document)}, ensure_ascii=False, indent=2))
