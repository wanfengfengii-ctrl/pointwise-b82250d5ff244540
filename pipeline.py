"""Public whole-materialization baseline, not a streaming implementation."""
from source import open_job
from mosaic_ref import compose
from regrid_ref import reduce_grid


def run(job):
    target, readers, trace = open_job(job)
    loaded = []
    for reader in readers:
        rows = []
        while True:
            item = reader.read()
            if item is None:
                break
            index, values = item
            assert index == len(rows)
            rows.append(values)
        loaded.append((reader.tile, rows))
    patches = compose(loaded)
    output = reduce_grid(target, patches)
    return {"output": output, "trace": trace,
            "materialized_source_cells": sum(len(r) for _, rs in loaded for r in rs),
            "materialized_patches": len(patches)}
