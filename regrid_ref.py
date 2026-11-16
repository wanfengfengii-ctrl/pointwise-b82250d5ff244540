"""Exact area reduction of an already resolved mosaic."""
from fractions import Fraction as F


def overlap(a, b):
    return (max(F(0), min(a[2], b[2]) - max(a[0], b[0]))
            * max(F(0), min(a[3], b[3]) - max(a[1], b[1])))


def text(value):
    return None if value is None else str(value)


def reduce_grid(target, patches):
    result = []
    for row in range(target.height):
        cells = []
        for col in range(target.width):
            rect, area, weighted = target.rect(row, col), F(0), F(0)
            for patch in patches:
                if patch.value is not None:
                    part = overlap(rect, patch.rect)
                    area += part
                    weighted += part * patch.value
            cells.append({"area": text(area),
                          "coverage": text(area / (target.dx * target.dy)),
                          "mean": text(weighted / area if area else None)})
        result.append(cells)
    return result
