"""Whole-image oracle. Its Cartesian arrangement is deliberately unbounded."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Patch:
    rect: tuple
    owner: str
    value: object


def compose(loaded):
    xs, ys = set(), set()
    for tile, rows in loaded:
        g = tile.grid
        xs.update(g.x + i * g.dx for i in range(g.width + 1))
        ys.update(g.y + i * g.dy for i in range(g.height + 1))
    xs, ys = sorted(xs), sorted(ys)
    patches = []
    for y0, y1 in zip(ys, ys[1:]):
        for x0, x1 in zip(xs, xs[1:]):
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            winner = None
            for tile, rows in loaded:
                g = tile.grid
                if (g.x <= mx < g.x + g.width * g.dx
                        and g.y <= my < g.y + g.height * g.dy):
                    col = int((mx - g.x) // g.dx)
                    row = int((my - g.y) // g.dy)
                    if winner is None or tile.priority > winner[0]:
                        winner = tile.priority, tile.name, rows[row][col]
            if winner is not None:
                patches.append(Patch((x0, y0, x1, y1), winner[1], winner[2]))
    return patches
