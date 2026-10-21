"""MCP tools for the hardsurface toolset: plates, shells and rounded blocks over a base body."""

from typing import Literal

Vec3 = list[float]
Polyline = list[list[float]]
PlateView = Literal["front", "back", "right", "left", "top"]


def register(tool, call, dump):
    @tool("hardsurface")
    def armor_plate(name: str, body: str, view: PlateView, bottom: Polyline, right: Polyline, top: Polyline,
                    left: Polyline, inset: float = 0.012, thickness: float = 0.012, gap: float = 0.0014,
                    density: float = 0.007, lift: float = 0.0, dome: float = 0.0, fold: list | None = None,
                    bevel: float = 0.003, mirror: bool = True, limb_axis: list[Vec3] | None = None,
                    limb_forward: Vec3 = (0, -1, 0), limb_lateral: Vec3 = (1, 0, 0), relax: int = 8,
                    material: str | None = None, collection: str | None = None) -> str:
        """Trace an armor plate off a reference view and lay it onto the body (the under-suit) as
        an even quad grid with Solidify, Bevel and Weighted Normal. Outline = four polylines of
        [a, b] metres in that view, corner to corner: bottom and top left-to-right, left and right
        bottom-to-top. front/back: a = world x, b = z; right/left: a = world y (front negative);
        top: a = x, b = y. Read the coordinates off a reference_overlay zoom with a grid. The
        plate's outer face sits `inset` outside the body: build the suit that far inside the
        reference outline. On an arm or leg pass limb_axis (centreline points, shoulder to wrist)
        so the plate wraps the limb and front/back plates meet cleanly. fold = [[a0, b0], [a1, b1],
        slope] sinks the part right of the line (a facet). mirror: model +X, Mirror makes the other side."""
        return dump(call("armor_plate", timeout=300, name=name, body=body, view=view, bottom=bottom, right=right,
                         top=top, left=left, inset=inset, thickness=thickness, gap=gap, density=density, lift=lift,
                         dome=dome, fold=fold, bevel=bevel, mirror=mirror, limb_axis=limb_axis,
                         limb_forward=limb_forward, limb_lateral=limb_lateral, relax=relax, material=material,
                         collection=collection))

    @tool("hardsurface")
    def shell_cap(name: str, centre: Vec3, radii: Vec3, up: Vec3 = (0, 0, 1), across: Vec3 = (1, 0, 0),
                  coverage: float = 95.0, resolution: int = 14, thickness: float = 0.008, bevel: float = 0.002,
                  mirror: bool = True, material: str | None = None, collection: str | None = None) -> str:
        """A domed shell (shoulder pad, kneecap, joint cap, helmet) as a pole-free quad grid:
        part of an ellipsoid with radii [across, depth, up], apex along `up`, reaching `coverage`
        degrees from the apex (90 = half dome). Fit centre and radii to the outline in two views.
        A flat dome (small up radius, coverage ~88) makes a joint disc."""
        return dump(call("shell_cap", name=name, centre=centre, radii=radii, up=up, across=across, coverage=coverage,
                         resolution=resolution, thickness=thickness, bevel=bevel, mirror=mirror, material=material,
                         collection=collection))

    @tool("hardsurface")
    def rounded_segment(name: str, start: Vec3, end: Vec3, width: float, depth: float, across: Vec3 = (0, 1, 0),
                        taper: float = 1.0, stations: int = 3, mirror: bool = True, subdivide: int = 2,
                        material: str | None = None, collection: str | None = None) -> str:
        """A box-modeled rounded block from start to end, all quads with Subdivision: finger and
        thumb bones, knuckles, palms, wrist cuffs, struts. width runs along `across`."""
        return dump(call("rounded_segment", name=name, start=start, end=end, width=width, depth=depth, across=across,
                         taper=taper, stations=stations, mirror=mirror, subdivide=subdivide, material=material,
                         collection=collection))
