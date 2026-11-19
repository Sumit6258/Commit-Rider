"""Bicycle and rider artwork, drawn procedurally (no external assets).

Each frame the rider is split into a *back* layer (far arm and leg, which pass behind the
wheels and frame), the *bike*, and a *front* layer (torso, head, near arm and leg). Each
group is drawn at 4x resolution into a tight RGBA layer and box-filtered down, which gives
clean anti-aliased edges and stable sub-pixel motion.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter

from commit_rider.animation.bicycle import BikePoints, BikeSpec, Point, bike_points, chain_lines
from commit_rider.animation.cyclist import (
    Arm,
    Leg,
    RiderPose,
    RiderSpec,
    shoe_polygon,
    solve_pose,
)
from commit_rider.animation.engine import FrameState
from commit_rider.animation import camera as cam
from commit_rider.config.settings import Settings
from commit_rider.rendering.colors import Color, darken, lighten, rgb
from commit_rider.rendering.drawing import Painter, downsample, regular_arc
from commit_rider.rendering.themes import Theme

SUPERSAMPLE = 4
EDGE = 0.95


@dataclass(frozen=True)
class SpritePalette:
    ink: Color
    jersey: Color
    helmet: Color
    helmet_dark: Color
    skin: Color
    shorts: Color
    shoes: Color
    glove: Color
    frame: Color
    fork: Color
    fork_dark: Color
    rim: Color
    tire: Color
    tire_hi: Color
    spoke: Color
    saddle: Color
    chain: Color
    far: float = 0.30  # how much darker the far-side limbs are

    @classmethod
    def from_theme(cls, t: Theme) -> SpritePalette:
        return cls(
            ink=rgb(t.ink), jersey=rgb(t.jersey), helmet=rgb(t.helmet),
            helmet_dark=darken(t.helmet, 0.22), skin=rgb(t.skin), shorts=rgb(t.shorts),
            shoes=rgb(t.shoes), glove=rgb(t.glove), frame=rgb(t.frame), fork=rgb(t.fork),
            fork_dark=darken(t.fork, 0.45), rim=rgb(t.rim), tire=rgb(t.tire),
            tire_hi=lighten(t.tire, 0.22), spoke=rgb(t.spoke), saddle=rgb(t.saddle),
            chain=rgb(t.chain),
        )


def _lerp(a: Point, b: Point, t: float) -> Point:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


class SpriteRenderer:
    def __init__(self, theme: Theme, settings: Settings, bike: BikeSpec, rider: RiderSpec) -> None:
        self.theme = theme
        self.settings = settings
        self.bike = bike
        self.rider = rider
        self.pal = SpritePalette.from_theme(theme)
        self.unit = settings.unit
        self.anchor_px = cam.ANCHOR_Y * settings.height

    # ------------------------------------------------------------------ public ------
    def _geometry(self, frame: FrameState):
        """Pose, bike points, the local->canvas mapping and the sprite's pixel bounding box."""
        pose = solve_pose(self.bike, self.rider, frame.controls)
        pts = bike_points(self.bike, pose.fork_compress)
        unit = self.unit
        c, s = math.cos(frame.pitch), math.sin(frame.pitch)
        rx, ry = frame.rear

        def to_canvas(lx: float, ly: float) -> Point:
            wx = rx + lx * c - ly * s
            wy = ry + lx * s + ly * c
            return ((wx - frame.cam_x) * unit, self.anchor_px - (wy - frame.cam_y) * unit)

        key: list[Point] = [pts.rear_axle, pts.front_axle, pts.grip, pts.saddle_rear, pts.saddle_nose, pose.head,
                            pose.hip, pose.shoulder]
        for leg in (pose.near_leg, pose.far_leg):
            key += [leg.knee, leg.ankle, leg.toe, leg.heel]
        extents: list[Point] = []
        radius = self.bike.wheel_radius + 3
        for lx, ly in key:
            r = self.rider.head_radius + 6 if (lx, ly) == pose.head else (radius if (lx, ly) in (pts.rear_axle, pts.front_axle) else 8)
            for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r)):
                extents.append(to_canvas(lx + dx, ly + dy))
        margin = 4
        box = (
            math.floor(min(p[0] for p in extents)) - margin,
            math.floor(min(p[1] for p in extents)) - margin,
            math.ceil(max(p[0] for p in extents)) + margin,
            math.ceil(max(p[1] for p in extents)) + margin,
        )
        return pose, pts, to_canvas, box

    def bounds(self, frame: FrameState) -> tuple[int, int, int, int]:
        """Pixel bounding box ``(x0, y0, x1, y1)`` of the bicycle and rider in this frame."""
        return self._geometry(frame)[3]

    def draw(self, canvas: Image.Image, frame: FrameState) -> None:
        pose, pts, to_canvas, (bx0, by0, bx1, by1) = self._geometry(frame)
        unit = self.unit
        w, h = bx1 - bx0, by1 - by0
        sc = SUPERSAMPLE

        def mapper(lx: float, ly: float) -> Point:
            x, y = to_canvas(lx, ly)
            return ((x - bx0) * sc, (y - by0) * sc)

        layers = [Image.new("RGBA", (w * sc, h * sc), (0, 0, 0, 0)) for _ in range(3)]
        back, mid, front = (Painter(layer, unit * sc, mapper) for layer in layers)
        self._rider_back(back, pose)
        self._bike(mid, pts, pose, frame)
        self._rider_front(front, pose, pts)
        for index, layer in enumerate(layers):
            small = downsample(layer, sc)
            if index == 1 and self.theme.glow:
                glow = small.filter(ImageFilter.GaussianBlur(radius=3.2 * unit))
                glow.putalpha(glow.getchannel("A").point(lambda a: int(a * 0.55)))
                canvas.paste(glow, (bx0, by0), glow)
            canvas.paste(small, (bx0, by0), small)

    # ------------------------------------------------------------------- rider ------
    def _far(self, color: Color) -> Color:
        return darken(color, self.pal.far)

    def _leg(self, p: Painter, leg: Leg, far: bool) -> None:
        pal = self.pal
        f = self._far if far else (lambda col: col)
        skin, shorts, sock = f(pal.skin), f(pal.shorts), f(pal.shoes)
        split = _lerp(leg.hip, leg.knee, 0.74)
        sock_start = _lerp(leg.ankle, leg.knee, 0.30)
        p.limb(
            [
                (leg.knee, leg.ankle, 9.4, skin),
                (split, leg.knee, 12.4, skin),
                (leg.hip, split, 14.0, shorts),
                (sock_start, leg.ankle, 10.0, sock),
            ],
            f(pal.ink), EDGE,
        )
        p.poly(shoe_polygon(leg.ball, leg.angle), f(pal.shoes), f(pal.ink), EDGE)
        sole = [(x, y - 0.1) for x, y in shoe_polygon(leg.ball, leg.angle)[7:10]]
        p.polyline(sole, 1.5, f(darken(pal.shoes, 0.45)))

    def _arm(self, p: Painter, arm: Arm, far: bool) -> None:
        pal = self.pal
        f = self._far if far else (lambda col: col)
        p.limb(
            [(arm.elbow, arm.hand, 7.4, f(pal.skin)), (arm.shoulder, arm.elbow, 9.8, f(pal.jersey))],
            f(pal.ink), EDGE,
        )
        p.disc(arm.hand, 4.9, f(pal.ink))
        p.disc(arm.hand, 4.0, f(pal.glove))

    def _pedal(self, p: Painter, ball: Point, far: bool) -> None:
        pal = self.pal
        color = self._far(pal.shorts) if far else pal.shorts
        a, b = (ball[0] - 7.0, ball[1] - 3.6), (ball[0] + 7.0, ball[1] - 3.6)
        p.line(a, b, 2.8, self._far(pal.ink) if far else pal.ink)
        p.line(a, b, 1.6, color)

    def _rider_back(self, p: Painter, pose: RiderPose) -> None:
        pal = self.pal
        bb = self.bike.bb
        p.line(bb, pose.far_leg.ball, 4.4, pal.ink)
        p.line(bb, pose.far_leg.ball, 3.1, self._far(pal.rim))
        self._pedal(p, pose.far_leg.ball, far=True)
        self._leg(p, pose.far_leg, far=True)
        self._arm(p, pose.far_arm, far=True)

    def _rider_front(self, p: Painter, pose: RiderPose, pts: BikePoints) -> None:
        pal = self.pal
        hip, shoulder, head = pose.hip, pose.shoulder, pose.head
        dx, dy = shoulder[0] - hip[0], shoulder[1] - hip[1]
        length = math.hypot(dx, dy)
        d = (dx / length, dy / length)
        n = (d[1], -d[0])  # forward-facing normal

        def at(t: float, off: float, along: float = 0.0) -> Point:
            return (hip[0] + dx * t + n[0] * off + d[0] * along, hip[1] + dy * t + n[1] * off + d[1] * along)

        torso = [at(0, -9.6, -2.0), at(0.45, -10.0), at(1, -7.8, 1.0), at(1, 7.2, 1.6), at(0.55, 8.4), at(0, 9.0, -2.0)]
        p.poly(torso, pal.jersey, pal.ink, EDGE)
        stripe = [at(0.62, -8.0), at(0.62, 7.0)]
        p.line(stripe[0], stripe[1], 2.0, lighten(pal.jersey, 0.35), caps=False)
        p.disc(at(0, 0, -1.0), 8.8, pal.ink)
        p.disc(at(0, 0, -1.0), 7.9, pal.shorts)

        # near leg + crank (the crank arm sits outside the frame, under the foot)
        p.line(self.bike.bb, pose.near_leg.ball, 4.8, pal.ink)
        p.line(self.bike.bb, pose.near_leg.ball, 3.4, pal.rim)
        self._pedal(p, pose.near_leg.ball, far=False)
        self._leg(p, pose.near_leg, far=False)

        # neck + head
        p.limb([(shoulder, head, 7.0, pal.skin)], pal.ink, EDGE)
        self._head(p, head, pose.head_angle)
        self._arm(p, pose.near_arm, far=False)

    def _head(self, p: Painter, c: Point, tilt: float) -> None:
        pal, r = self.pal, self.rider.head_radius
        p.disc(c, r + EDGE, pal.ink)
        p.disc(c, r, pal.skin)
        nose = (c[0] + r * 0.98, c[1] - 0.6)
        p.disc(nose, 2.6, pal.ink)
        p.disc(nose, 1.8, pal.skin)
        p.disc((c[0] - 1.6, c[1] - 0.8), 2.1, darken(pal.skin, 0.12))
        # helmet: a dome over the top/back with a peak at the front
        centre = (c[0] - 0.8, c[1] + 1.6)
        arc = regular_arc(centre, r + 2.0, math.radians(-14), math.radians(196), 14)
        dome = arc + [(c[0] - 9.5, c[1] - 1.2), (c[0] + 6.0, c[1] + 1.6)]
        p.poly(dome, pal.helmet, pal.ink, EDGE)
        peak = [(c[0] + 9.0, c[1] + 4.6), (c[0] + 17.0, c[1] + 2.2), (c[0] + 9.5, c[1] + 1.6)]
        p.poly(peak, pal.helmet_dark, pal.ink, 0.8)
        vent = regular_arc(centre, r - 1.4, math.radians(35), math.radians(165), 8)
        p.polyline(vent, 1.3, lighten(pal.helmet, 0.45))
        # sunglasses
        p.line((c[0] + 3.4, c[1] + 2.3), (c[0] + 8.0, c[1] + 1.9), 3.3, pal.ink)

    # -------------------------------------------------------------------- bike -------
    def _bike(self, p: Painter, pts: BikePoints, pose: RiderPose, frame: FrameState) -> None:
        spec, pal = self.bike, self.pal
        for centre in (pts.rear_axle, pts.front_axle):
            self._wheel(p, centre, frame)
        upper, lower = chain_lines(spec)
        p.line(upper[0], upper[1], 1.5, pal.chain, caps=False)
        p.line(lower[0], lower[1], 1.5, pal.chain, caps=False)
        p.ring(spec.bb, spec.chainring_radius, 1.7, lighten(pal.chain, 0.25))
        p.disc(pts.rear_axle, spec.cog_radius, pal.chain)

        def tube(a: Point, b: Point, w: float, color: Color | None = None) -> None:
            p.limb([(a, b, w, color or pal.frame)], pal.ink, EDGE)

        tube(spec.bb, pts.rear_axle, 3.8)
        tube(pts.seat_stay_top, pts.rear_axle, 2.8)
        tube(spec.bb, pts.seat_tube_top, 4.0)
        tube(pts.down_tube_front, spec.bb, 4.8)
        tube(pts.top_tube_rear, pts.top_tube_front, 4.2)
        tube(pts.head_bottom, pts.head_top, 5.8)
        # suspension fork: dark lowers on the axle, silver stanchions sliding into them
        tube(pts.front_axle, pts.lowers_top, 4.8, pal.fork_dark)
        tube(pts.lowers_top, pts.crown, 3.0, pal.fork)
        p.disc(pts.crown, 3.3, pal.ink)
        p.disc(pts.crown, 2.4, pal.fork)
        tube(pts.seat_tube_top, pts.seat_clamp, 3.0, pal.fork)
        # saddle
        s_top = pts.saddle_top
        saddle = [
            (s_top[0] - 11.5, s_top[1] - 0.2), (s_top[0] + 1.0, s_top[1] + 0.5),
            (s_top[0] + 12.5, s_top[1] - 1.4), (s_top[0] + 12.0, s_top[1] - 3.9),
            (s_top[0] + 2.0, s_top[1] - 3.3), (s_top[0] - 10.5, s_top[1] - 5.4),
        ]
        p.poly(saddle, pal.saddle, pal.ink, 0.8)
        # stem, riser bar, grip, brake lever
        tube(pts.head_top, pts.stem_top, 3.6, pal.fork)
        tube(pts.stem_top, pts.grip, 3.2, pal.fork_dark)
        p.line(pts.grip, pts.lever_tip, 1.5, pal.ink)
        p.line(pts.grip, pts.lever_tip, 0.8, pal.fork)
        p.disc(pts.grip, 3.9, pal.ink)
        p.disc(pts.grip, 3.0, pal.saddle)

    def _wheel(self, p: Painter, centre: Point, frame: FrameState) -> None:
        spec, pal = self.bike, self.pal
        r_tire, r_rim = spec.wheel_radius, spec.rim_radius
        p.ring(centre, r_tire + 0.5, 6.6, pal.ink)
        p.ring(centre, r_tire - 0.4, 5.6, pal.tire)
        p.ring(centre, r_tire - 1.6, 0.9, pal.tire_hi)
        p.ring(centre, r_rim, 1.9, pal.rim)
        self._spokes(p, centre, frame)
        p.disc(centre, 4.4, pal.ink)
        p.disc(centre, 3.4, pal.rim)
        p.disc(centre, 1.5, pal.ink)

    def _spokes(self, p: Painter, centre: Point, frame: FrameState) -> None:
        """Crisp spokes at low spin, a translucent motion-blurred fan at high spin.

        At 18 fps a wheel turns tens of degrees per frame, so crisp spokes would strobe
        (the "wagon wheel" effect). Blending to sweep-sectors removes it.
        """
        spec = self.bike
        n = spec.spokes
        spacing = math.tau / n
        step = abs(frame.wheel_step)
        blur = min(1.0, max(0.0, (step / spacing - 0.22) / 0.5))
        x, y = p.pt(centre)
        r_out = (spec.rim_radius - 0.8) * p.scale
        r_in = 3.6 * p.scale
        size = int(2 * r_out + 8)
        mask = Image.new("L", (size, size), 0)
        md = ImageDraw.Draw(mask)
        c = size / 2.0
        spin = frame.wheel_angle
        # Sweep sectors first (the blur), then spokes on top so they are never overwritten.
        if blur > 0.0:
            box = (c - r_out, c - r_out, c + r_out, c + r_out)
            for i in range(n):
                a1 = spin + i * spacing
                md.pieslice(box, math.degrees(a1 - step), math.degrees(a1), fill=round(40 * blur))
        crisp = round(255 * (1.0 - blur) + 130 * blur)
        for i in range(n):
            a = spin + i * spacing
            md.line(
                [(c + r_in * math.cos(a), c + r_in * math.sin(a)), (c + r_out * math.cos(a), c + r_out * math.sin(a))],
                fill=max(crisp, 40), width=max(1, round(0.7 * p.scale)),
            )
        md.ellipse((c - r_in, c - r_in, c + r_in, c + r_in), fill=0)
        patch = Image.new("RGBA", mask.size, rgb_tuple(self.pal.spoke) + (0,))
        patch.putalpha(mask)
        p.image.alpha_composite(patch, (int(round(x - c)), int(round(y - c))))


def rgb_tuple(color: Color) -> tuple[int, int, int]:
    return (color[0], color[1], color[2])
