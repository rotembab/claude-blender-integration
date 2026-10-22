"""MCP tools for the hardsurface toolset: plates, shells and rounded blocks over a base body."""

from typing import Literal

Vec3 = list[float]
Polyline = list[list[float]]
PlateView = Literal["front", "back", "right", "left", "top", "limb"]


def register(tool, call, dump):
    @tool("hardsurface")
    def armor_plate(name: str, body: str, view: PlateView, bottom: Polyline, right: Polyline, top: Polyline,
                    left: Polyline, inset: float = 0.012, thickness: float = 0.012, gap: float = 0.0014,
                    density: float = 0.007, lift: float = 0.0, dome: float = 0.0, fold: list | None = None,
                    bevel: float = 0.003, mirror: bool = True, limb_axis: list[Vec3] | None = None,
                    limb_forward: Vec3 = (0, -1, 0), limb_lateral: Vec3 = (1, 0, 0), relax: int = 8,
                    fair: int = 0, seam_range: list[float] | None = None, seam_sides: list[str] | None = None,
                    material: str | None = None, collection: str | None = None) -> str:
        """Trace an armor plate off a reference view and lay it onto the body (the under-suit) as
        an even quad grid with Solidify, Bevel and Weighted Normal. Outline = four polylines of
        [a, b] metres in that view, corner to corner: bottom and top left-to-right, left and right
        bottom-to-top. front/back: a = world x, b = z; right/left: a = world y (front negative);
        top: a = x, b = y. Read the coordinates off a reference_overlay zoom with a grid. The
        plate's outer face sits `inset` outside the body: build the suit that far inside the
        reference outline. On an arm or leg pass limb_axis (centreline points, shoulder to wrist)
        so the plate wraps the limb (theta 0 = limb_forward, +90 = limb_lateral); for a front/back
        pair add seam_range (front [-90, 90], back [-270, -90]) and seam_sides ["left", "right"] so
        they meet on one side seam with no overlap. view "limb" takes the outline straight in
        (theta, t) round limb_axis, for parts no single view draws (a strap over a foot, a counter
        round a heel). fair (10-30) irons out creases from the body under the plate. fold = [[a0, b0], [a1, b1],
        slope] sinks the part right of the line (a facet). mirror: model +X, Mirror makes the other side."""
        return dump(call("armor_plate", timeout=300, name=name, body=body, view=view, bottom=bottom, right=right,
                         top=top, left=left, inset=inset, thickness=thickness, gap=gap, density=density, lift=lift,
                         dome=dome, fold=fold, bevel=bevel, mirror=mirror, limb_axis=limb_axis,
                         limb_forward=limb_forward, limb_lateral=limb_lateral, relax=relax, fair=fair,
                         seam_range=seam_range, seam_sides=seam_sides, material=material,
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

    @tool("hardsurface")
    def build_hand(name: str, wrist: Vec3, down: Vec3, across: Vec3, palm_side: Vec3, width: float = 0.074,
                   depth: float = 0.027, palm_length: float = 0.088, fingers: list[list[float]] | None = None,
                   thumb: list[float] | None = None, thumb_directions: list[Vec3] | None = None,
                   curl: list[float] | None = None, gap: float = 0.0016, mirror: bool = True,
                   material: str | None = None, joint_material: str | None = None,
                   collection: str | None = None) -> str:
        """A hand as ONE connected all-quad mesh, box-modeled: palm box, four fingers and a thumb
        extruded bone by bone with pinched knuckle loops, Subdivision. Never build a hand from
        separate finger pieces. wrist = palm start; down = towards the fingertips; across = index
        -> pinky; palm_side = the way the palm faces. fingers = bone lengths per finger (index
        first); curl = degrees per bone; thumb_directions = one direction per thumb bone, read off
        the reference's front and side views. Compare with reference_overlay zoomed on the hand."""
        return dump(call("build_hand", name=name, wrist=wrist, down=down, across=across, palm_side=palm_side,
                         width=width, depth=depth, palm_length=palm_length, fingers=fingers, thumb=thumb,
                         thumb_directions=thumb_directions, curl=curl, gap=gap, mirror=mirror, material=material,
                         joint_material=joint_material, collection=collection))
