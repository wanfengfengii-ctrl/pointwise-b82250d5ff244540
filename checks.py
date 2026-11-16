"""Business regression; no target streaming algorithm is hidden here."""
import json
import unittest
from pipeline import run
from observe import samples
from source import open_job
from regrid_ref import overlap
from fractions import Fraction as F


def independent_cell(job, row, col):
    """Small-case Cartesian partition independent of production mosaic/reducer."""
    target, readers, _ = open_job(job)
    rect = target.rect(row, col)
    xs, ys = {rect[0], rect[2]}, {rect[1], rect[3]}
    for r in readers:
        g = r.tile.grid
        xs.update(x for i in range(g.width + 1)
                  if rect[0] < (x := g.x + i * g.dx) < rect[2])
        ys.update(y for i in range(g.height + 1)
                  if rect[1] < (y := g.y + i * g.dy) < rect[3])
    area = weighted = F(0)
    for x0, x1 in zip(sorted(xs), sorted(xs)[1:]):
        for y0, y1 in zip(sorted(ys), sorted(ys)[1:]):
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            candidates = []
            for t in job["tiles"]:
                g = t["grid"]
                x, y, dx, dy = (F(g[k]) for k in ("x", "y", "dx", "dy"))
                if x <= mx < x + g["width"] * dx and y <= my < y + g["height"] * dy:
                    value = t["rows"][int((my-y)//dy)][int((mx-x)//dx)]
                    candidates.append((t["priority"], value))
            if candidates:
                value = max(candidates)[1]
                if value is not None:
                    a = (x1-x0)*(y1-y0)
                    area += a
                    weighted += a * F(value)
    return {"area": str(area), "coverage": str(area/(target.dx*target.dy)),
            "mean": str(weighted/area) if area else None}


class Baseline(unittest.TestCase):
    def test_mask_anchor(self):
        result = run(samples()[0])
        self.assertEqual(result["output"], [[
            {"area": "2", "coverage": "2/3", "mean": "11/2"}]])
        self.assertEqual(result["trace"], [
            ["read", "old", 0], ["eof", "old"],
            ["read", "new", 0], ["eof", "new"]])

    def test_all_cells(self):
        for j in samples():
            actual = run(j)["output"]
            for row, cells in enumerate(actual):
                for col, cell in enumerate(cells):
                    self.assertEqual(cell, independent_cell(j, row, col),
                                     (j["name"], row, col))

    def test_coarse_rows(self):
        out = run(samples()[1])["output"]
        self.assertEqual(out, [
            [{"area": "1", "coverage": "1", "mean": "4"},
             {"area": "1", "coverage": "1", "mean": "4"}],
            [{"area": "3/4", "coverage": "3/4", "mean": "10/3"},
             {"area": "1/2", "coverage": "1/2", "mean": "2"}],
            [{"area": "1", "coverage": "1", "mean": "7/2"},
             {"area": "3/4", "coverage": "3/4", "mean": "2"}]])

    def test_fraction(self):
        self.assertEqual(run(samples()[3])["output"], [[
            {"area": "2/9", "coverage": "2/9", "mean": "3/2"}]])

    def test_bad_and_one_pass(self):
        j = samples()[0]
        _, readers, _ = open_job(j)
        self.assertEqual(readers[0].read()[0], 0)
        self.assertIsNone(readers[0].read())
        with self.assertRaises(RuntimeError):
            readers[0].seek(0)
        j["tiles"][1]["priority"] = 1
        with self.assertRaises(ValueError):
            run(j)
        j = samples()[0]
        j["tiles"][0]["rows"][0].pop()
        with self.assertRaises(ValueError):
            run(j)


if __name__ == "__main__":
    unittest.main()
