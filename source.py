"""Finite rational rasters and one-pass row readers."""
from dataclasses import dataclass
from fractions import Fraction as F


def q(value):
    return F(str(value))


@dataclass(frozen=True)
class Grid:
    x: F
    y: F
    dx: F
    dy: F
    width: int
    height: int

    @classmethod
    def parse(cls, obj):
        g = cls(*(q(obj[k]) for k in ("x", "y", "dx", "dy")),
                obj["width"], obj["height"])
        if (type(g.width) is not int or type(g.height) is not int
                or min(g.width, g.height) <= 0 or min(g.dx, g.dy) <= 0):
            raise ValueError("invalid grid")
        return g

    def rect(self, row, col):
        x, y = self.x + col * self.dx, self.y + row * self.dy
        return (x, y, x + self.dx, y + self.dy)


@dataclass(frozen=True)
class Tile:
    name: str
    priority: int
    grid: Grid


class RowReader:
    """The fixture backs a reader; its backing is not pipeline work memory."""
    def __init__(self, tile, rows, trace):
        self.tile, self._rows, self._trace = tile, rows, trace
        self._next = 0

    def read(self):
        g = self.tile.grid
        if self._next == g.height:
            self._trace.append(["eof", self.tile.name])
            return None
        i = self._next
        raw = self._rows[i]
        if len(raw) != g.width:
            raise ValueError("row width: " + self.tile.name)
        values = tuple(None if v is None else q(v) for v in raw)
        self._next += 1
        self._trace.append(["read", self.tile.name, i])
        return i, values

    def seek(self, row):
        raise RuntimeError("source cannot rewind")


def open_job(job):
    trace, readers, seen_names, seen_priorities = [], [], set(), set()
    target = Grid.parse(job["target"])
    for spec in job["tiles"]:
        name, priority = spec["name"], spec["priority"]
        if (not isinstance(name, str) or not name or name in seen_names
                or type(priority) is not int or priority in seen_priorities):
            raise ValueError("nonunique tile name or priority")
        grid = Grid.parse(spec["grid"])
        if len(spec["rows"]) != grid.height:
            raise ValueError("row count: " + name)
        tile = Tile(name, priority, grid)
        seen_names.add(name)
        seen_priorities.add(priority)
        readers.append(RowReader(tile, spec["rows"], trace))
    return target, readers, trace
