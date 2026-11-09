"""Small pictures the review pages draw themselves, so no image is fetched from anywhere.

The pages' security policy allows only our own style sheet and no outside pictures, so
every picture is inline SVG made here from the data. Nothing in this file is a score or a
judgement. It only decides how a fact is drawn.
"""

import hashlib
from typing import TypedDict

CELL = 40  # a tile is two cells by two, in an 80 by 80 box
PALETTES = 6  # the tile colourings the style sheet defines, as `pal-0` to `pal-5`
SHAPES = 5


class Cell(TypedDict):
    d: str
    turn: str  # the SVG `transform` that turns the shape about its cell's centre
    tone: int  # 1 to 3, which of the palette's three colours it takes


class Tile(TypedDict):
    palette: int
    cells: list[Cell]


def tile(company_key: str) -> Tile:
    """A little Bauhaus-style tile for a company: four cells of quarter discs, half discs,
    circles, squares and triangles, turned and coloured from a hash of its key. The same key
    always draws the same tile, and different keys almost always draw different ones, so a
    company can be told apart at a glance before its name is read."""
    seed = hashlib.sha256(company_key.encode()).digest()
    cells: list[Cell] = []
    for i in range(4):
        x, y = (i % 2) * CELL, (i // 2) * CELL
        turn = (seed[i + 4] % 4) * 90
        cells.append(
            {
                "d": _shape(seed[i] % SHAPES, x, y),
                "turn": f"rotate({turn} {x + CELL // 2} {y + CELL // 2})",
                "tone": 1 + seed[i + 8] % 3,
            }
        )
    return {"palette": seed[12] % PALETTES, "cells": cells}


def _shape(kind: int, x: int, y: int) -> str:
    c, h = CELL, CELL // 2
    if kind == 0:  # a quarter disc, its corner in the cell's corner
        return f"M{x} {y}h{c}a{c} {c} 0 0 1 {-c} {c}z"
    if kind == 1:  # a half disc standing on the cell's floor
        return f"M{x} {y + c}a{h} {h} 0 0 1 {c} 0z"
    if kind == 2:  # a circle
        return f"M{x + 2} {y + h}a{h - 2} {h - 2} 0 1 0 {c - 4} 0a{h - 2} {h - 2} 0 1 0 {4 - c} 0z"
    if kind == 3:  # a small square
        return f"M{x + 7} {y + 7}h{c - 14}v{c - 14}h{14 - c}z"
    return f"M{x} {y}h{c}L{x} {y + c}z"  # a triangle


class Slice(TypedDict):
    name: str
    usd: str
    x: float
    w: float
    tone: int


def slices(parts: list[tuple[str, float]]) -> list[Slice]:
    """One slice of a bar, 100 wide, for each thing the month's money went on, biggest first.
    `parts` is (name, dollars). Nothing is drawn when there is no money."""
    total = sum(usd for _, usd in parts)
    if total <= 0:
        return []
    out: list[Slice] = []
    at = 0.0
    for tone, (name, usd) in enumerate(sorted(parts, key=lambda p: -p[1])):
        width = 100 * usd / total
        out.append(
            {
                "name": name,
                "usd": f"{usd:.2f}",
                "x": round(at, 2),
                "w": round(width, 2),
                "tone": tone % 4,
            }
        )
        at += width
    return out
