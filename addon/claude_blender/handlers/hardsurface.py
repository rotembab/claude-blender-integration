"""hardsurface toolset: armor plates traced off a reference and laid onto a body, domed shells and
rounded segments, the way a hard-surface artist builds a suit over a base mesh.

A plate is drawn like on an ortho reference plane: its outline in one view's coordinates (metres)
as four sides (bottom, right, top, left; each a polyline from corner to corner). The outline is
filled with a Coons-patch quad grid (even quads whose loops follow the outline), every grid point
is projected onto the body's armor envelope (the body pushed out by `inset`), relaxed so quads stay
even, then Solidify inward, an angle Bevel and Weighted Normal make it a real plate.
On a limb, give `limb_axis` (the limb's centreline): the outline is wrapped round the limb, so
front, back and side plates meet cleanly instead of grazing off the silhouette.
"""

import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from . import CommandError, command
from .util import get_mesh, link_to_scene, mesh_counts

# View coordinates (a, b) -> ray origin, and the ray direction.
VIEWS = {
    "front": (lambda a, b: Vector((a, -50.0, b)), Vector((0, 1, 0))),   # a = x, b = z
    "back": (lambda a, b: Vector((a, 50.0, b)), Vector((0, -1, 0))),    # a = x (world), b = z
    "right": (lambda a, b: Vector((50.0, a, b)), Vector((-1, 0, 0))),   # a = y (front negative), b = z
    "left": (lambda a, b: Vector((-50.0, a, b)), Vector((1, 0, 0))),    # a = y, b = z
    "top": (lambda a, b: Vector((a, b, 50.0)), Vector((0, 0, -1))),     # a = x, b = y
}


class _Envelope:
    """The body's evaluated surface pushed out along its normals by `inset`, as a BVH."""

    def __init__(self, obj, inset):
        dg = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(dg)
        me = ev.to_mesh()
        bm = bmesh.new()
        bm.from_mesh(me)
        ev.to_mesh_clear()
        bm.transform(obj.matrix_world)
        bm.normal_update()
        for v in bm.verts:
            v.co += v.normal * inset
        bm.normal_update()
        bm.faces.ensure_lookup_table()
        self.bvh = BVHTree.FromBMesh(bm)
        self.bm = bm

    def normal(self, idx):
        f = self.bm.faces[idx]
        return sum((v.normal for v in f.verts), Vector()).normalized()

    def project(self, view, a, b):
        org_fn, d = VIEWS[view]
        hit, nrm, idx, dist = self.bvh.ray_cast(org_fn(a, b), d, 200.0)
        if hit is None:  # off the outline: nearest surface point instead
            hit, nrm, idx, dist = self.bvh.find_nearest(org_fn(a, b) + d * 50.0)
        return hit


class _Axis:
    """A limb centreline. Coordinates (theta degrees, t 0..1): theta 0 = `forward`, +90 = towards
    `lateral`."""

    def __init__(self, points, forward=(0, -1, 0), lateral=(1, 0, 0)):
        self.P = [Vector(p) for p in points]
        if len(self.P) < 2:
            raise CommandError("limb_axis needs at least 2 points")
        L = [0.0]
        for a, b in zip(self.P, self.P[1:]):
            L.append(L[-1] + (b - a).length)
        self.L = np.array(L) / L[-1]
        self.fwd0, self.lat0 = Vector(forward), Vector(lateral)

    def at(self, t):
        t = min(max(t, 0.0), 1.0)
        i = min(int(np.searchsorted(self.L, t, side="right") - 1), len(self.P) - 2)
        u = (t - self.L[i]) / max(self.L[i + 1] - self.L[i], 1e-9)
        c = self.P[i].lerp(self.P[i + 1], u)
        ax = (self.P[i + 1] - self.P[i]).normalized()
        f = (self.fwd0 - ax * self.fwd0.dot(ax)).normalized()
        lat = ax.cross(f)
        if lat.dot(self.lat0) < 0:
            lat = -lat
        return c, f, lat

    def coords(self, p):
        best = None
        for i in range(len(self.P) - 1):
            a, b = self.P[i], self.P[i + 1]
            d = b - a
            u = min(max((p - a).dot(d) / d.length_squared, 0.0), 1.0)
            dist = (a + d * u - p).length
            if best is None or dist < best[0]:
                best = (dist, self.L[i] + (self.L[i + 1] - self.L[i]) * u)
        c, f, lat = self.at(best[1])
        r = p - c
        return math.degrees(math.atan2(r.dot(lat), r.dot(f))), best[1]

    def project(self, env, theta, t, reach=0.16):
        # Cast from the limb's own centreline outwards, so a ray never lands on a neighbouring limb.
        c, f, lat = self.at(t)
        d = f * math.cos(math.radians(theta)) + lat * math.sin(math.radians(theta))
        hit, nrm, idx, dist = env.bvh.ray_cast(c, d, reach)
        if hit is None:
            hit, nrm, idx, dist = env.bvh.find_nearest(c + d * 0.08)
        return hit


def _poly(pts, t):
    P = [Vector((p[0], p[1])) for p in pts]
    L = [0.0]
    for p, q in zip(P, P[1:]):
        L.append(L[-1] + (q - p).length)
    s = t * L[-1]
    for i in range(len(P) - 1):
        if s <= L[i + 1] or i == len(P) - 2:
            u = (s - L[i]) / max(L[i + 1] - L[i], 1e-9)
            return P[i].lerp(P[i + 1], min(max(u, 0), 1))


def _length(pts):
    return sum((Vector(q) - Vector(p)).length for p, q in zip(pts, pts[1:]))


def _densify(pts, n=6):
    out = [tuple(pts[0])]
    for p, q in zip(pts, pts[1:]):
        for k in range(1, n + 1):
            out.append((p[0] + (q[0] - p[0]) * k / n, p[1] + (q[1] - p[1]) * k / n))
    return out


def _coons(bottom, right, top, left, u, v):
    c0, c1 = _poly(bottom, u), _poly(top, u)
    d0, d1 = _poly(left, v), _poly(right, v)
    P00, P10, P01, P11 = Vector(bottom[0]), Vector(bottom[-1]), Vector(top[0]), Vector(top[-1])
    return ((1 - v) * c0 + v * c1 + (1 - u) * d0 + u * d1
            - ((1 - u) * (1 - v) * P00 + u * (1 - v) * P10 + (1 - u) * v * P01 + u * v * P11))


def _wrap_outline(env, axis, view, sides):
    """View outline -> (theta, t) round the limb, unwrapped and smoothed."""
    conv = [[axis.coords(env.project(view, a, b)) for a, b in _densify(sd)] for sd in sides]
    bottom, right, top, left = conv
    loop = bottom + right[1:] + top[::-1][1:] + left[::-1][1:-1]
    th = np.degrees(np.unwrap(np.radians([p[0] for p in loop])))
    nb, nr, nt, nl = len(bottom), len(right), len(top), len(left)
    n = len(loop)
    ids = (list(range(nb)), [nb - 1 + k for k in range(nr)], [nb + nr - 2 + (nt - 1 - k) for k in range(nt)],
           [(nb + nr + nt - 3 + (nl - 1 - k)) % n for k in range(nl)])
    out = []
    for idx, sd in zip(ids, conv):
        a = np.array([(th[i], p[1]) for i, p in zip(idx, sd)], dtype=float)
        for _ in range(12):  # silhouette points come out noisy: smooth, ends fixed
            a[1:-1] = a[1:-1] * 0.5 + (a[:-2] + a[2:]) * 0.25
        out.append([tuple(p) for p in a])
    bottom, right, top, left = out
    right[0], top[-1], left[-1], left[0] = bottom[-1], right[-1], top[0], bottom[0]
    return bottom, right, top, left


def _seam(sides, seam_range, seam_sides, snap=15.0):
    """Keep a wrapped outline inside its share of the limb, seam_range = [lo, hi] degrees (e.g.
    front -90..90, back -270..-90), so a front/back pair never overlaps. Sides in seam_sides
    ("left"/"right") run exactly along the nearer seam, top and bottom stretched out to them."""
    lo, hi = map(float, seam_range)
    allth = np.array([p[0] for sd in sides for p in sd])
    shift = 360.0 * np.round(((lo + hi) / 2 - np.median(allth)) / 360.0)

    def ease(th):
        th = min(max(th + shift, lo), hi)
        if hi - th < snap:  # sides that stop just short of a seam ease onto it (C1 blend)
            th = hi - (hi - th) ** 2 / snap
        elif th - lo < snap:
            th = lo + (th - lo) ** 2 / snap
        return th
    bottom, right, top, left = ([(ease(a), b) for a, b in sd] for sd in sides)
    for key in seam_sides:
        sd = right if key == "right" else left
        med = float(np.median([p[0] for p in sd]))
        lim = lo if abs(med - lo) < abs(med - hi) else hi
        sd[:] = [(lim, b) for a, b in sd]
    for sd, a, b in ((bottom, left[0], right[0]), (top, left[-1], right[-1])):
        o0, o1 = sd[0][0], sd[-1][0]
        span = (o1 - o0) or 1e-9
        sd[:] = [(a[0] + (p[0] - o0) * (b[0] - a[0]) / span, p[1]) for p in sd]
        sd[0], sd[-1] = a, b
    return bottom, right, top, left


def _untangle(S, rounds=30):
    """Quads folded against their neighbours (an outline corner doubling back where it grazes the
    limb): move their verts to the average of their grid neighbours until none fold."""
    S = S.copy()
    nv, nu = S.shape[0] - 1, S.shape[1] - 1
    for _ in range(rounds):
        N = np.cross(S[1:, 1:] - S[:-1, :-1], S[:-1, 1:] - S[1:, :-1])
        N /= np.maximum(np.linalg.norm(N, axis=2, keepdims=True), 1e-12)
        pad = np.pad(N, ((2, 2), (2, 2), (0, 0)), mode="edge")
        blur = sum(pad[a:a + nv, b:b + nu] for a in range(5) for b in range(5))
        blur /= np.maximum(np.linalg.norm(blur, axis=2, keepdims=True), 1e-12)
        bad = (N * blur).sum(2) < 0.5
        if not bad.any():
            break
        move = np.zeros(S.shape[:2], bool)
        for i, j in zip(*np.nonzero(bad)):
            move[i:i + 2, j:j + 2] = True
        T = S.copy()
        for i, j in zip(*np.nonzero(move)):
            nb = [S[a, b] for a, b in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)) if 0 <= a <= nv and 0 <= b <= nu]
            T[i, j] = np.mean(nb, axis=0)
        S = T
    return S


def _fair(S, iterations, lam=0.5, mu=-0.53):
    """Taubin smoothing of the projected grid: irons out creases the body had under the plate (a
    knee fold, a kink in the limb axis) without shrinking it. The border slides along itself."""
    S = S.copy()

    def step(S, k):
        A = S.copy()
        A[1:-1, 1:-1] = (S[:-2, 1:-1] + S[2:, 1:-1] + S[1:-1, :-2] + S[1:-1, 2:]) / 4
        A[0, 1:-1] = (S[0, :-2] + S[0, 2:]) / 2
        A[-1, 1:-1] = (S[-1, :-2] + S[-1, 2:]) / 2
        A[1:-1, 0] = (S[:-2, 0] + S[2:, 0]) / 2
        A[1:-1, -1] = (S[:-2, -1] + S[2:, -1]) / 2
        return S + k * (A - S)
    for _ in range(int(iterations)):
        S = step(step(S, lam), mu)
    return S


def _material(name, color=None):
    if not name:
        return None
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        if color:
            bsdf = m.node_tree.nodes.get("Principled BSDF")
            bsdf.inputs["Base Color"].default_value = (*color[:3], 1)
            m.diffuse_color = (*color[:3], 1)
    return m


def _finish(obj, thickness, bevel, mirror, subdivide=0):
    """The plate stack: Mirror, Subdivision, Solidify inward, angle Bevel, Weighted Normal."""
    for p in obj.data.polygons:
        p.use_smooth = True
    if mirror:
        m = obj.modifiers.new("Mirror", "MIRROR")
        m.use_clip = True
        m.use_mirror_merge = True
        m.merge_threshold = 0.0005
    if subdivide:
        s = obj.modifiers.new("Subdivision", "SUBSURF")
        s.levels = s.render_levels = int(subdivide)
    sol = obj.modifiers.new("Solidify", "SOLIDIFY")
    sol.thickness = thickness
    sol.offset = -1.0
    sol.use_even_offset = False  # even offset spikes where a thin plate turns sharply
    sol.use_quality_normals = True
    if bevel:
        bv = obj.modifiers.new("Bevel", "BEVEL")
        bv.width = bevel
        bv.segments = 3
        bv.limit_method = "ANGLE"
        bv.angle_limit = math.radians(35)
        bv.harden_normals = True
    wn = obj.modifiers.new("WeightedNormal", "WEIGHTED_NORMAL")
    wn.keep_sharp = True


def _make_object(name, bm, material, collection):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    link_to_scene(obj, collection)
    if material:
        me.materials.append(material)
    return obj


def _orient_out(obj, centre_fn):
    me = obj.data
    f = me.polygons[len(me.polygons) // 2]
    if f.normal.dot(f.center - centre_fn(f.center)) < 0:
        me.flip_normals()


@command("armor_plate", "hardsurface")
def armor_plate(name, body, view, bottom, right, top, left, inset=0.012, thickness=0.012, gap=0.0014,
                density=0.007, lift=0.0, dome=0.0, fold=None, bevel=0.003, mirror=True, limb_axis=None,
                limb_forward=(0, -1, 0), limb_lateral=(1, 0, 0), relax=8, fair=0, seam_range=None, seam_sides=None,
                material=None, collection=None):
    """Lay an armor plate onto `body`, traced in a reference view. bottom/right/top/left are
    polylines of [a, b] points in that view's metres, corner to corner (bottom and top run left
    to right, left and right run bottom to top). Views: front/back (a = world x, b = z),
    right/left (a = world y, front negative), top (a = x, b = y). The body is the under-suit; the
    plate's outer face lands `inset` outside it (so model the suit that far inside the
    reference). gap trims a panel line off each side; lift raises the plate; dome bulges its
    middle; fold = [[a0, b0], [a1, b1], slope] sinks the part right of that line (a facet).
    limb_axis = centreline points wraps the plate round an arm or leg (theta 0 = limb_forward, +90 =
    limb_lateral). On a limb, seam_range = [lo, hi] degrees keeps the plate in its share of the limb
    (front -90..90, back -270..-90) and seam_sides = ["left", "right"] runs those sides exactly
    along the seams, so a front/back pair meets on one clean side seam with no overlap. view
    "limb" takes the outline straight in (theta, t) round limb_axis (t 0..1 along it): for parts a
    single view can't draw, like a strap over a foot or a counter round a heel. fair = Taubin
    smoothing passes that iron out creases from the body under the plate. mirror adds a clipped
    Mirror (model the +X side)."""
    sides = [[tuple(map(float, p)) for p in s] for s in (bottom, right, top, left)]
    if any(len(s) < 2 for s in sides):
        raise CommandError("Each side needs at least 2 points")
    if view not in VIEWS and view != "limb":
        raise CommandError(f"view must be one of {sorted(VIEWS) + ['limb']}")
    if view == "limb" and not limb_axis:
        raise CommandError('view "limb" needs limb_axis')
    if seam_range is not None and not limb_axis:
        raise CommandError("seam_range needs limb_axis")
    if any(sd not in ("left", "right") for sd in seam_sides or ()):
        raise CommandError('seam_sides takes "left" and/or "right"')
    env = _Envelope(get_mesh(body), float(inset))
    axis = _Axis(limb_axis, limb_forward, limb_lateral) if limb_axis else None
    view_sides = sides
    if view == "limb":  # measure the sides in metres on the surface, for the grid density and gap
        def m_len(sd):
            pts = [axis.project(env, a, b) for a, b in _densify(sd, 3)]
            return sum((q - p).length for p, q in zip(pts, pts[1:]))
        view_sides = [[(0.0, 0.0), (m_len(sd), 0.0)] for sd in sides]
    elif axis is not None:
        sides = _wrap_outline(env, axis, view, sides)
        if seam_range is not None:
            sides = _seam(sides, seam_range, seam_sides or ())
    b_, r_, t_, l_ = sides
    nu = max(3, int(round(max(_length(view_sides[0]), _length(view_sides[2])) / density)))
    nv = max(3, int(round(max(_length(view_sides[3]), _length(view_sides[1])) / density)))
    eu = gap / max(_length(view_sides[0]), 1e-6)
    on_seam = mirror and axis is None and view in ("front", "back", "top") and abs(b_[0][0]) < 1e-6 and abs(t_[0][0]) < 1e-6
    eu0 = 0.0 if on_seam else eu  # a plate on the mirror plane gets no gap there: the Mirror welds it
    ev = gap / max(_length(view_sides[3]), 1e-6)
    S = np.zeros((nv + 1, nu + 1, 3))
    UV = {}
    for i in range(nv + 1):
        v = ev + (1 - 2 * ev) * i / nv
        for j in range(nu + 1):
            u = eu0 + (1 - eu0 - eu) * j / nu
            ab = _coons(b_, r_, t_, l_, u, v)
            UV[i, j] = (u, v, ab)
            S[i, j] = axis.project(env, ab.x, ab.y) if axis else env.project(view, ab.x, ab.y)
    for _ in range(int(relax)):  # like the Relax brush: even quads, outline fixed
        avg = S.copy()
        avg[1:-1, 1:-1] = (S[:-2, 1:-1] + S[2:, 1:-1] + S[1:-1, :-2] + S[1:-1, 2:]) / 4
        for i in range(1, nv):
            for j in range(1, nu):
                S[i, j] = env.bvh.find_nearest(Vector(S[i, j] * 0.5 + avg[i, j] * 0.5))[0]
    if fair:
        S = _untangle(_fair(_untangle(S), fair))
    bm = bmesh.new()
    grid = []
    for i in range(nv + 1):
        row = []
        for j in range(nu + 1):
            u, v, ab = UV[i, j]
            p, _, idx, _ = env.bvh.find_nearest(Vector(S[i, j]))
            off = float(lift) + float(dome) * math.sin(math.pi * u) * math.sin(math.pi * v)
            if fold and axis is None:
                (a0, b0), (a1, b1), slope = fold
                dx, dy = a1 - a0, b1 - b0
                side = (dx * (ab.y - b0) - dy * (ab.x - a0)) / math.hypot(dx, dy)
                if side < 0:
                    off -= slope * (-side)
            row.append(bm.verts.new((Vector(S[i, j]) if fair else p) + env.normal(idx) * off))
        grid.append(row)
    for i in range(nv):
        for j in range(nu):
            bm.faces.new((grid[i][j], grid[i][j + 1], grid[i + 1][j + 1], grid[i + 1][j]))
    obj = _make_object(name, bm, _material(material), collection)
    if axis is not None:
        _orient_out(obj, lambda p: axis.at(axis.coords(p)[1])[0])
    else:
        me = obj.data
        if me.polygons[len(me.polygons) // 2].normal.dot(VIEWS[view][1]) > 0:
            me.flip_normals()
    _finish(obj, float(thickness), float(bevel), mirror)
    return {"name": obj.name, "grid": [nu, nv], **mesh_counts(obj)}


@command("shell_cap", "hardsurface")
def shell_cap(name, centre, radii, up=(0, 0, 1), across=(1, 0, 0), coverage=95.0, resolution=14,
              thickness=0.008, bevel=0.002, mirror=True, material=None, collection=None):
    """A domed shell: shoulder pad, kneecap, helmet, joint cap. Part of an ellipsoid round
    `centre` with radii [across, depth, up], its apex along `up`, open on the far side.
    coverage = polar angle in degrees from the apex (90 = a half dome, 180 = closed). A pole-free
    quad grid (square mapped to a disc, then onto the ellipsoid), Subdivision 1, Solidify
    inward, Bevel, Weighted Normal."""
    O = Vector(centre)
    n = Vector(up).normalized()
    u = (Vector(across) - n * Vector(across).dot(n)).normalized()
    if u.length < 0.5:
        raise CommandError("across must not be parallel to up")
    v = n.cross(u)
    a, b, h = (float(r) for r in radii)
    res = int(resolution)
    bm = bmesh.new()
    grid = []
    for i in range(res + 1):
        row = []
        for j in range(res + 1):
            x, y = -1 + 2 * i / res, -1 + 2 * j / res
            dx, dy = x * math.sqrt(1 - y * y / 2), y * math.sqrt(1 - x * x / 2)
            r, psi = math.hypot(dx, dy), math.atan2(dy, dx)
            phi = math.radians(float(coverage)) * r
            row.append(bm.verts.new(O + u * (a * math.sin(phi) * math.cos(psi))
                                    + v * (b * math.sin(phi) * math.sin(psi)) + n * (h * math.cos(phi))))
        grid.append(row)
    for i in range(res):
        for j in range(res):
            bm.faces.new((grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]))
    obj = _make_object(name, bm, _material(material), collection)
    _orient_out(obj, lambda p: O)
    _finish(obj, float(thickness), float(bevel), mirror, subdivide=1)
    return {"name": obj.name, **mesh_counts(obj)}


@command("rounded_segment", "hardsurface")
def rounded_segment(name, start, end, width, depth, across=(0, 1, 0), taper=1.0, stations=3, mirror=True,
                    subdivide=2, material=None, collection=None):
    """A box-modeled rounded block from start to end: finger bones, palms, wrist cuffs, boots,
    struts. Rings of 8 edges (a rounded rectangle, `width` along `across`, `depth` across that),
    quad end caps, Subdivision. taper scales the end ring. All quads."""
    a, b = Vector(start), Vector(end)
    if (b - a).length < 1e-6:
        raise CommandError("start and end are the same point")
    ax = (b - a).normalized()
    w = Vector(across) - ax * Vector(across).dot(ax)
    if w.length < 1e-6:
        raise CommandError("across must not be parallel to the segment")
    w.normalize()
    t = ax.cross(w)
    bm = bmesh.new()
    rings = []
    stations = max(2, int(stations))
    for k in range(stations):
        f = k / (stations - 1)
        c = a.lerp(b, f)
        s = 1.0 + (float(taper) - 1.0) * f
        hw, hd = float(width) / 2 * s, float(depth) / 2 * s
        pts = [(-hw, -hd), (0, -hd * 1.07), (hw, -hd), (hw * 1.07, 0), (hw, hd), (0, hd * 1.07), (-hw, hd),
               (-hw * 1.07, 0)]
        rings.append([bm.verts.new(c + w * x + t * y) for x, y in pts])
    for r0, r1 in zip(rings, rings[1:]):
        for k in range(8):
            bm.faces.new((r0[k], r0[(k + 1) % 8], r1[(k + 1) % 8], r1[k]))
    for ring in (rings[0], rings[-1]):
        for q in ((0, 1, 6, 7), (1, 2, 5, 6), (2, 3, 4, 5)):
            bm.faces.new([ring[k] for k in q])
    obj = _make_object(name, bm, _material(material), collection)
    for p in obj.data.polygons:
        p.use_smooth = True
    if mirror:
        obj.modifiers.new("Mirror", "MIRROR")
    if subdivide:
        s = obj.modifiers.new("Subdivision", "SUBSURF")
        s.levels = s.render_levels = int(subdivide)
    return {"name": obj.name, **mesh_counts(obj)}



@command("build_hand", "hardsurface")
def build_hand(name, wrist, down, across, palm_side, width=0.074, depth=0.027, palm_length=0.088,
               fingers=None, thumb=None, thumb_directions=None, curl=None, gap=0.0016, mirror=True,
               material=None, joint_material=None, collection=None):
    """One connected, all-quad hand, box-modeled: a palm box whose knuckle end splits into four
    finger bases and whose index-side face grows the thumb; each finger is extruded bone by bone
    with a pinched knuckle loop between bones; Subdivision rounds it. wrist = where the palm
    starts; down = along the hand towards the fingertips; across = index -> pinky; palm_side =
    the way the palm faces. fingers = bone lengths per finger, index first; curl = degrees per
    bone towards the palm; thumb_directions = one direction per thumb bone (default: out past
    the index side, then down). Defaults fit an adult human-sized hand. material colours the back and the bones, joint_material the palm
    and knuckle loops."""
    fingers = fingers or ((0.038, 0.027, 0.022), (0.042, 0.03, 0.024), (0.039, 0.028, 0.022), (0.031, 0.022, 0.019))
    thumb = thumb or (0.046, 0.04)
    curl = curl or (6, 14, 20)
    W = Vector(wrist)
    d = Vector(down).normalized()
    wv = Vector(across) - d * Vector(across).dot(d)
    palm = Vector(palm_side) - d * Vector(palm_side).dot(d)
    if wv.length < 1e-6 or palm.length < 1e-6:
        raise CommandError("across and palm_side must not be parallel to down")
    wv.normalize()
    palm = (palm - wv * palm.dot(wv)).normalized()
    if len(fingers) != 4:
        raise CommandError("fingers needs 4 entries (index, middle, ring, pinky)")
    t = -palm
    bm = bmesh.new()
    hw, hd = width / 2, depth / 2
    rings = []
    for f, sc in ((0.0, 0.92), (0.5, 1.0), (1.0, 1.0)):
        c = W + d * (palm_length * f)
        back = [bm.verts.new(c + wv * (hw * sc * (i / 2 - 1)) + t * hd) for i in range(5)]
        front = [bm.verts.new(c + wv * (hw * sc * (i / 2 - 1)) - t * hd) for i in range(5)]
        rings.append((back, front))
    dark = set()
    thumb_face = None
    for k in range(2):
        (b0, f0), (b1, f1) = rings[k], rings[k + 1]
        for i in range(4):
            bm.faces.new((b0[i], b0[i + 1], b1[i + 1], b1[i]))
            dark.add(bm.faces.new((f0[i + 1], f0[i], f1[i], f1[i + 1])))
        side0 = bm.faces.new((f0[0], b0[0], b1[0], f1[0]))
        side4 = bm.faces.new((b0[4], f0[4], f1[4], b1[4]))
        if k == 0:
            thumb_face = side0
            dark |= {side0, side4}
    b0, f0 = rings[0]
    for i in range(4):  # wrist end, closed (a cuff usually covers it)
        bm.faces.new((b0[i + 1], b0[i], f0[i], f0[i + 1]))
    b2, f2 = rings[2]
    tips = [bm.faces.new((b2[i], b2[i + 1], f2[i + 1], f2[i])) for i in range(4)]

    def grow(face, directions, lengths):
        dark.update(bmesh.ops.inset_individual(bm, faces=[face], thickness=gap, use_even_offset=True)["faces"])
        cur = face
        size_w = (cur.verts[0].co - cur.verts[1].co).length
        size_d = (cur.verts[1].co - cur.verts[2].co).length
        p = cur.calc_center_median()
        for direction, L in zip(directions, lengths):
            for adv, sc, knuckle in ((0.004, 0.8, True), (0.008, 0.98, False), (L - 0.012, 0.92, False)):
                newf = bmesh.ops.extrude_discrete_faces(bm, faces=[cur])["faces"][0]
                if knuckle:
                    dark.update(f for e in newf.edges for f in e.link_faces if f is not newf)
                p = p + direction * max(adv, 0.001)
                a = (wv - direction * wv.dot(direction)).normalized()
                b = direction.cross(a)
                c0 = newf.calc_center_median()
                for v in newf.verts:
                    off = v.co - c0
                    v.co = (p + a * (size_w / 2 * sc * (1 if off.dot(a) >= 0 else -1))
                            + b * (size_d / 2 * sc * (1 if off.dot(b) >= 0 else -1)))
                cur = newf

    for face, lengths in zip(tips, fingers):
        dirs, dr = [], d
        for k in range(len(lengths)):
            dr = (Matrix.Rotation(math.radians(curl[min(k, len(curl) - 1)]), 3, wv) @ dr).normalized()
            dirs.append(dr)
        grow(face, dirs, lengths)
    if thumb_directions:
        tdirs = [Vector(x).normalized() for x in thumb_directions]
    else:
        tdirs = [(d * 0.8 - wv * 0.6).normalized(), (d - wv * 0.12).normalized()]
    grow(thumb_face, tdirs, thumb)
    mat, jmat = _material(material), _material(joint_material)
    for f in bm.faces:
        f.smooth = True
        f.material_index = 1 if (f in dark and jmat) else 0
    obj = _make_object(name, bm, mat, collection)
    if jmat:
        if not mat:
            obj.data.materials.append(_material("Hand", (0.8, 0.8, 0.8)))
        obj.data.materials.append(jmat)
    if mirror:
        obj.modifiers.new("Mirror", "MIRROR")
    s = obj.modifiers.new("Subdivision", "SUBSURF")
    s.levels = s.render_levels = 2
    return {"name": obj.name, **mesh_counts(obj)}
