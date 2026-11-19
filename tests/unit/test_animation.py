import math
import unittest

from commit_rider.animation import camera, movement
from commit_rider.animation.bicycle import BIKES, BikeSpec, bike_points, chain_lines, get_bike, pedal_position
from commit_rider.animation.cyclist import (
    RiderControls,
    RiderSpec,
    shoe_polygon,
    solve_pose,
    two_bone_ik,
)
from commit_rider.animation.engine import Timeline
from commit_rider.animation.particles import Puff, landing_burst, takeoff_puffs, trail_puff
from commit_rider.animation.physics import GroundContact
from commit_rider.animation.stunts import MAX_CHANGE_PER_FRAME, Flight, StuntPlan, Wheelie, plan_stunts, rider_controls
from commit_rider.terrain.generator import TerrainParams, generate_terrain, params_from_settings
from commit_rider.terrain.geometry import Terrain
from commit_rider.data.demo import generate_demo_series
from tests.support import demo, small_settings, series_from_counts


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def flat_terrain(height=50.0, n=2000, dx=1.0):
    return Terrain([height] * n, dx, n * dx, 14.0, 100, 42, (1,) * 100, (1,) * 100)


class BicycleTests(unittest.TestCase):
    def setUp(self):
        self.spec = BikeSpec()

    def test_wheelbase_and_recognisable_parts(self):
        pts = bike_points(self.spec)
        self.assertAlmostEqual(dist(pts.rear_axle, pts.front_axle), self.spec.wheelbase)
        self.assertGreater(pts.saddle_top[1], pts.bb[1])  # saddle above the crank
        self.assertGreater(pts.grip[1], pts.head_top[1])  # riser bar above the head tube
        self.assertGreater(pts.crown[1], 0)
        self.assertEqual(get_bike("bmx"), self.spec)
        with self.assertRaises(KeyError):
            get_bike("unicycle")
        self.assertIn("bmx", BIKES)

    def test_fork_compresses_toward_the_axle(self):
        extended, compressed = bike_points(self.spec, 0.0), bike_points(self.spec, 1.0)
        self.assertAlmostEqual(
            dist(extended.crown, extended.front_axle) - dist(compressed.crown, compressed.front_axle),
            self.spec.fork_travel,
        )
        self.assertLess(compressed.grip[1], extended.grip[1])
        self.assertEqual(bike_points(self.spec, 5.0), bike_points(self.spec, 1.0))  # clamped

    def test_pedals_orbit_the_bottom_bracket(self):
        for angle in (0.0, 1.0, 2.5, 4.0):
            near, far = pedal_position(self.spec, angle), pedal_position(self.spec, angle, far_side=True)
            self.assertAlmostEqual(dist(near, self.spec.bb), self.spec.crank_length)
            self.assertAlmostEqual(near[0] - self.spec.bb[0], -(far[0] - self.spec.bb[0]))
        top = pedal_position(self.spec, 0.0)
        self.assertGreater(top[1], self.spec.bb[1])
        self.assertGreater(pedal_position(self.spec, 0.2)[0], top[0])  # moves forward over the top

    def test_chain_runs_are_tangent_to_both_sprockets(self):
        for a, b in chain_lines(self.spec):
            self.assertAlmostEqual(dist(a, self.spec.bb), self.spec.chainring_radius)
            self.assertAlmostEqual(dist(b, (0.0, 0.0)), self.spec.cog_radius)
            # tangent: the run is perpendicular to the radius at the ring end
            run = (b[0] - a[0], b[1] - a[1])
            radius = (a[0] - self.spec.bb[0], a[1] - self.spec.bb[1])
            self.assertAlmostEqual(run[0] * radius[0] + run[1] * radius[1], 0.0, places=6)


class RiderRigTests(unittest.TestCase):
    def setUp(self):
        self.bike, self.rider = BikeSpec(), RiderSpec()

    def test_two_bone_ik_preserves_segment_lengths(self):
        root = (0.0, 0.0)
        for target in ((30, -50), (-20, -60), (60, 10), (0, -75)):
            joint, stretch = two_bone_ik(root, target, 40, 40, 1.0)
            self.assertAlmostEqual(dist(root, joint), 40, places=6)
            self.assertAlmostEqual(dist(joint, target), 40, places=6)
            self.assertLess(stretch, 1.0)

    def test_two_bone_ik_out_of_reach_and_degenerate(self):
        joint, stretch = two_bone_ik((0, 0), (500, 0), 40, 40, 1.0)
        self.assertGreater(stretch, 1.0)
        self.assertLess(dist((0, 0), joint), 40 + 1e-6)
        joint, stretch = two_bone_ik((0, 0), (0, 0), 40, 40, 1.0)
        self.assertEqual(stretch, 0.0)

    def test_rider_stays_attached_in_every_posture(self):
        """Hands on the grips, feet on the pedals, no limb ever fully straight or detached."""
        worst = 0.0
        for stand in (0.0, 0.5, 1.0):
            for climb, desc in ((0, 0), (1, 0), (0, 1)):
                for compress in (-0.35, 0.0, 0.5, 1.0):
                    for air, wheelie in ((0, 0), (1, 0), (0, 1)):
                        for deg in range(0, 360, 20):
                            ctrl = RiderControls(math.radians(deg), stand, climb, desc, compress, air, wheelie)
                            pose = solve_pose(self.bike, self.rider, ctrl)
                            worst = max(worst, pose.max_stretch)
                            self.assertEqual(pose.near_arm.hand, bike_points(self.bike, pose.fork_compress).grip)
                            self.assertLess(dist(pose.near_leg.ankle, pose.near_leg.ball), 15)
                            # segment lengths are preserved (the skeleton does not stretch)
                            self.assertAlmostEqual(dist(pose.near_leg.hip, pose.near_leg.knee), self.rider.thigh, places=5)
                            self.assertAlmostEqual(dist(pose.near_leg.knee, pose.near_leg.ankle), self.rider.shin, places=5)
                            self.assertAlmostEqual(dist(pose.near_arm.shoulder, pose.near_arm.elbow), self.rider.upper_arm, places=5)
                            self.assertAlmostEqual(dist(pose.hip, pose.shoulder), self.rider.torso, places=5)
        self.assertLess(worst, 0.9995)

    def test_feet_follow_the_pedals(self):
        for deg in range(0, 360, 45):
            ctrl = RiderControls(crank=math.radians(deg))
            pose = solve_pose(self.bike, self.rider, ctrl)
            self.assertEqual(pose.near_leg.ball, pedal_position(self.bike, ctrl.crank))
            self.assertEqual(pose.far_leg.ball, pedal_position(self.bike, ctrl.crank, far_side=True))

    def test_posture_responds_to_the_terrain(self):
        flat = solve_pose(self.bike, self.rider, RiderControls())
        stand = solve_pose(self.bike, self.rider, RiderControls(stand=1.0))
        landing = solve_pose(self.bike, self.rider, RiderControls(compress=1.0))
        wheelie = solve_pose(self.bike, self.rider, RiderControls(wheelie=1.0, stand=0.5))
        climbing = solve_pose(self.bike, self.rider, RiderControls(climb=1.0))
        self.assertGreater(stand.hip[1], flat.hip[1] + 5)  # standing: hips higher
        self.assertLess(landing.hip[1], flat.hip[1] - 3)  # landing: hips drop
        self.assertGreater(landing.fork_compress, 0.5)  # suspension compresses
        self.assertLess(wheelie.hip[0], flat.hip[0])  # wheelie: hips back
        self.assertGreater(climbing.torso_angle, flat.torso_angle)  # climbing: torso leans forward

    def test_shoe_outline_is_placed_on_the_ball_of_the_foot(self):
        shoe = shoe_polygon((10.0, 20.0), 0.0)
        xs = [p[0] for p in shoe]
        self.assertLess(min(xs), 10.0)
        self.assertGreater(max(xs), 10.0)
        rotated = shoe_polygon((10.0, 20.0), 0.3)
        self.assertNotEqual(shoe, rotated)


class GroundContactTests(unittest.TestCase):
    def test_flat_ground_gives_level_bike_resting_on_both_wheels(self):
        gc = GroundContact(flat_terrain(50.0), 27.0, 104.0)
        for x in (300.0, 777.7, 1500.0):
            mid_y, pitch = gc.solve(x)
            self.assertAlmostEqual(pitch, 0.0, places=6)
            self.assertAlmostEqual(mid_y, 50.0 + 27.0, places=3)  # wheel centre = ground + radius

    def test_constant_slope_gives_matching_pitch(self):
        n, slope = 3000, 0.4
        heights = [20 + slope * i for i in range(n)]
        # not periodic, so look away from the seam
        t = Terrain(heights, 1.0, float(n), 14.0, 100, 42, (1,) * 100, (1,) * 100)
        gc = GroundContact(t, 27.0, 104.0)
        mid_y, pitch = gc.solve(1500.0)
        self.assertAlmostEqual(pitch, math.atan(slope), places=2)

    def test_wheels_never_penetrate_and_both_touch_in_real_terrain(self):
        terrain = generate_terrain(demo().counts)
        gc = GroundContact(terrain, 27.0, 104.0)
        for i in range(0, terrain.n, 25):
            x = i * terrain.dx
            mid_y, pitch = gc.solve(x)
            sep = 104.0 * math.cos(pitch)
            rear = (x - 0.5 * sep, mid_y - 52.0 * math.sin(pitch))
            front = (x + 0.5 * sep, mid_y + 52.0 * math.sin(pitch))
            self.assertAlmostEqual(dist(rear, front), 104.0, places=2)  # rigid frame
            self.assertLess(abs(gc.penetration(*rear)), 0.05)  # rear wheel rests on the ground
            self.assertLess(abs(gc.penetration(*front)), 0.05)  # front wheel rests on the ground
            # the wheel circle never goes below the terrain surface under it
            for cx, cy in (rear, front):
                for dxp in (-27, -14, 0, 14, 27):
                    under = terrain.height(cx + dxp)
                    circle_bottom = cy - math.sqrt(max(27.0**2 - dxp**2, 0.0))
                    self.assertGreaterEqual(circle_bottom, under - 0.2)

    def test_a_step_is_climbed_not_penetrated(self):
        n = 1200
        heights = [10.0 if i < 600 else 60.0 for i in range(n)]
        t = Terrain(heights, 1.0, float(n), 14.0, 50, 10, (1,) * 50, (1,) * 50)
        gc = GroundContact(t, 27.0, 104.0)
        self.assertGreaterEqual(gc.center_y(600.0), 60.0 + 27.0 - 27.0 + 0.0)  # centre above the step edge
        self.assertGreater(gc.center_y(610.0), gc.center_y(560.0))


class StuntAndMovementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = small_settings()
        terrain = generate_terrain(demo().counts, params_from_settings(cls.settings))
        cls.timeline = Timeline(terrain, cls.settings)

    def test_no_stunts_at_zero_intensity(self):
        tl = self.timeline
        plan = plan_stunts(tl.ground_mid_y, tl.ground_pitch, tl.dx, [False] * tl.n, 0.0)
        self.assertEqual((plan.flights, plan.wheelies), ([], []))

    def test_flights_are_physical_parabolas_that_land_on_the_ground(self):
        tl = self.timeline
        self.assertGreaterEqual(len(tl.plan.flights), 2)
        previous_end = -1
        for f in tl.plan.flights:
            self.assertGreater(f.start, previous_end)
            self.assertGreater(f.end, f.start)
            previous_end = f.end
            self.assertGreaterEqual(f.apex, 7.0)
            # above the ground path all the way, and meeting it at the end
            for i in range(f.start + 2, f.end, 7):
                self.assertGreaterEqual(f.mid_y(i, tl.dx) + 0.01, tl.ground_mid_y[i])
            self.assertLess(abs(f.mid_y(f.end, tl.dx) - tl.ground_mid_y[f.end]), 3.0)
            # constant gravity: the second derivative of the path equals -gravity
            h = 10
            mid = f.start + (f.end - f.start) // 2
            second = f.mid_y(mid + h, tl.dx) - 2 * f.mid_y(mid, tl.dx) + f.mid_y(mid - h, tl.dx)
            self.assertAlmostEqual(second / (h * tl.dx) ** 2, -f.gravity, places=7)
            # pitch eases from the launch slope to the landing slope
            self.assertAlmostEqual(f.pitch(f.start), f.pitch0, places=6)
            self.assertAlmostEqual(f.pitch(f.end), f.pitch1 + math.tau * f.flips, places=6)

    def test_no_jumps_inside_the_loop_seam(self):
        tl = self.timeline
        for f in tl.plan.flights:
            self.assertGreater(f.start * tl.dx, 150.0 - 1)  # clear of the lap start
            self.assertLess(f.end, tl.n - 20)  # lands before the lap ends

    def test_stunt_mode_adds_air_and_flips_calm_mode_is_quieter(self):
        counts = demo().counts
        results = {}
        for mode in ("relaxed", "normal", "stunt"):
            s = small_settings(ride_mode=mode)
            results[mode] = Timeline(generate_terrain(counts, params_from_settings(s)), s)
        self.assertLessEqual(len(results["relaxed"].plan.flights), len(results["normal"].plan.flights))
        self.assertLessEqual(len(results["normal"].plan.flights), len(results["stunt"].plan.flights))
        self.assertEqual(sum(f.flips for f in results["normal"].plan.flights), 0)
        self.assertGreaterEqual(sum(f.flips for f in results["stunt"].plan.flights), 1)

    def test_wheelie_weight_shape(self):
        w = Wheelie(100, 300, 0.4)
        self.assertEqual(w.weight(50, 1.0), 0.0)
        self.assertEqual(w.weight(301, 1.0), 0.0)
        self.assertAlmostEqual(w.weight(200, 1.0), 1.0)
        self.assertLess(w.weight(110, 1.0), 0.2)

    def test_rider_controls_never_change_faster_than_the_rate_limit(self):
        tl = self.timeline
        per_unit = MAX_CHANGE_PER_FRAME * tl.dx / (tl.period / tl.frames)
        for name, values in tl.controls.items():
            if name == "level":  # crank levelling is deliberately not rate-limited
                self.assertTrue(all(0.0 <= v <= 1.0 for v in values))
                continue
            worst = max(abs(values[(i + 1) % tl.n] - values[i]) for i in range(tl.n))
            self.assertLessEqual(worst, per_unit + 1e-9, name)
            self.assertTrue(all(-0.36 <= v <= 1.0 + 1e-9 for v in values), name)
        # ...which bounds the change between consecutive *frames* as well
        for k in range(tl.frames):
            a, b = tl.frame(k).controls, tl.frame(k + 1).controls
            for field in ("stand", "climb", "desc", "air", "compress"):
                self.assertLessEqual(abs(getattr(b, field) - getattr(a, field)), MAX_CHANGE_PER_FRAME * 1.15, field)

    def test_rider_controls_react_to_the_plan(self):
        n = 600
        flight = Flight(200, 400, 80.0, 0.5, 0.003, 0.3, -0.3, 0, 0.8, 30.0)
        plan = StuntPlan([flight], [])
        c = rider_controls([0.0] * n, plan, [0.0] * n, 1.0)
        self.assertGreater(c["air"][300], 0.95)
        self.assertLess(c["air"][50], 0.01)
        self.assertGreater(c["stand"][300], 0.9)
        self.assertGreater(max(c["compress"][400:520]), 0.4)  # absorbs the landing

    def test_time_is_monotonic_and_sums_to_the_duration(self):
        tl = self.timeline
        self.assertEqual(len(tl.times), tl.n + 1)
        self.assertEqual(tl.times[0], 0.0)
        self.assertAlmostEqual(tl.times[-1], tl.duration)
        self.assertTrue(all(b > a for a, b in zip(tl.times, tl.times[1:])))

    def test_speed_profile_is_slower_uphill(self):
        pitch = [0.5] * 100 + [-0.5] * 100
        speed = movement.speed_profile(pitch, 1.0)
        self.assertLess(speed[50], speed[150])
        self.assertTrue(all(0.7 <= v <= 1.3 for v in speed))

    def test_wheel_and_crank_totals_close_the_loop(self):
        tl = self.timeline
        spacing = math.tau / tl.bike.spokes
        self.assertAlmostEqual(tl.wheel_total / spacing, round(tl.wheel_total / spacing), places=9)
        self.assertAlmostEqual(tl.crank_total / math.tau, round(tl.crank_total / math.tau), places=9)
        self.assertGreaterEqual(tl.crank_total, 2 * math.tau)  # the rider keeps pedalling
        self.assertTrue(all(b >= a for a, b in zip(tl.wheel, tl.wheel[1:])))  # wheels never roll backwards
        self.assertTrue(all(b >= a for a, b in zip(tl.crank, tl.crank[1:])))

    def test_pedals_settle_near_level_in_the_air(self):
        # the small 3 s fixture rides so fast that flights last only ~0.1 s; use a realistic lap
        realistic = small_settings(fps=18, duration=8.0)
        tl = Timeline(generate_terrain(demo().counts, params_from_settings(realistic)), realistic)
        checked = 0
        for f in tl.plan.flights:
            seconds = tl.times[f.end] - tl.times[f.start]
            if seconds < 0.3:
                continue
            for i in range(f.start + int(0.55 * (f.end - f.start)), f.end - int(0.1 * (f.end - f.start))):
                # deviation of the crank from horizontal, in degrees
                deviation = math.degrees(math.asin(min(1.0, abs(math.cos(tl.crank[i])))))
                self.assertLess(deviation, 20.0, f"flight at {f.start}, index {i}")
                checked += 1
        self.assertGreater(checked, 0)

    def test_flips_keep_the_riders_head_off_the_ground(self):
        """A backflip hangs the head ~130 units below the bike: it must still clear the terrain."""
        for seed, days in ((7, 365), (11, 300)):
            settings = small_settings(ride_mode="stunt", fps=24, duration=8.0)
            series = generate_demo_series(days=days, seed=seed)
            terrain = generate_terrain(series.counts, params_from_settings(settings))
            tl = Timeline(terrain, settings)
            self.assertGreaterEqual(sum(f.flips for f in tl.plan.flights), 1, "stunt mode should find a flip")
            rider = RiderSpec()
            for k in range(tl.frames):
                fr = tl.frame(k)
                pose = solve_pose(tl.bike, rider, fr.controls)
                c, sn = math.cos(fr.pitch), math.sin(fr.pitch)
                wx = fr.rear[0] + pose.head[0] * c - pose.head[1] * sn
                wy = fr.rear[1] + pose.head[0] * sn + pose.head[1] * c
                self.assertGreater(wy - rider.head_radius - terrain.height(wx), 4.0, f"seed {seed} frame {k}")

    def test_flips_are_planned_only_where_there_is_room(self):
        tl = self.timeline
        for f in tl.plan.flights:
            if f.flips:
                self.assertGreaterEqual((f.end - f.start) * tl.dx, 280.0)
                self.assertGreaterEqual(f.apex, 50.0)
        # without terrain information the planner refuses flips rather than guessing
        plan = plan_stunts(tl.ground_mid_y, tl.ground_pitch, tl.dx, [False] * tl.n, 0.95, surface=None)
        self.assertEqual(sum(f.flips for f in plan.flights), 0)

    def test_camera_rises_only_for_big_air(self):
        terrain = generate_terrain(demo().counts)
        n, dx = terrain.n, terrain.dx
        base = camera.camera_heights(terrain, 0.0, n, dx)
        low_hop = camera.camera_heights(terrain, 0.0, n, dx, [40.0] * n)
        self.assertEqual(base, low_hop)  # jumps below AIR_FREE never move the camera
        big = camera.camera_heights(terrain, 0.0, n, dx, [160.0] * n)
        self.assertAlmostEqual(big[0] - base[0], camera.AIR_FOLLOW * (160.0 - camera.AIR_FREE), places=3)

    def test_camera_helpers(self):
        self.assertAlmostEqual(camera.camera_x(1000.0, 1200.0), 1000.0 - camera.ANCHOR_X * 1200.0)
        terrain = generate_terrain(demo().counts)
        heights = camera.camera_heights(terrain, 0.0, terrain.n, terrain.dx)
        self.assertEqual(len(heights), terrain.n)
        self.assertLess(max(heights) - min(heights), terrain.max_height - terrain.min_height)  # damped


class TimelineInvariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = small_settings()
        cls.terrain = generate_terrain(demo().counts, params_from_settings(cls.settings))
        cls.tl = Timeline(cls.terrain, cls.settings)

    def test_frame_count_and_timing(self):
        tl = self.tl
        self.assertEqual(tl.frames, 30)
        self.assertAlmostEqual(tl.frame(10).t, 1.0)
        self.assertAlmostEqual(tl.duration, 3.0)

    def test_bicycle_never_penetrates_the_ground_and_only_floats_while_jumping(self):
        tl, spec = self.tl, self.tl.bike
        for k in range(tl.frames + 1):
            fr = tl.frame(k)
            rx, ry = fr.rear
            fx, fy = rx + spec.wheelbase * math.cos(fr.pitch), ry + spec.wheelbase * math.sin(fr.pitch)
            for cx, cy in ((rx, ry), (fx, fy)):
                self.assertLess(tl.ground.penetration(cx, cy), 0.1, f"frame {k}")
            if not fr.airborne and fr.controls.wheelie == 0.0:
                self.assertLess(abs(tl.ground.penetration(rx, ry)), 0.2, f"rear wheel off the ground, frame {k}")

    def test_loop_closure_is_exact(self):
        tl = self.tl
        first, last = tl.frame(0), tl.frame(tl.frames)
        self.assertAlmostEqual(last.rear[0] - first.rear[0], tl.period, places=6)
        self.assertAlmostEqual(last.rear[1], first.rear[1], places=6)
        self.assertAlmostEqual(last.pitch, first.pitch, places=6)
        self.assertAlmostEqual(last.cam_y, first.cam_y, places=6)
        self.assertAlmostEqual(last.cam_x - first.cam_x, tl.period, places=6)
        spacing = math.tau / tl.bike.spokes
        self.assertAlmostEqual(((last.wheel_angle - first.wheel_angle) / spacing) % 1.0, 0.0, places=6)
        self.assertAlmostEqual(((last.crank - first.crank) / math.tau) % 1.0, 0.0, places=6)
        self.assertAlmostEqual(last.controls.stand, first.controls.stand, places=9)
        self.assertEqual(first.airborne, False)

    def test_frames_continue_into_later_laps(self):
        tl = self.tl
        a, b = tl.frame(5), tl.frame(5 + tl.frames)
        self.assertAlmostEqual(b.rear[0] - a.rear[0], tl.period, places=5)
        self.assertAlmostEqual(b.rear[1], a.rear[1], places=6)

    def test_wheel_rotation_equals_distance_travelled(self):
        """Rolling without slipping: wheel angle * radius == path length (not decorative).

        Uses a finer time resolution so that the straight chord between two frames is a good
        estimate of the (curved) path length."""
        settings = small_settings(fps=30, duration=8.0)
        tl = Timeline(generate_terrain(demo().counts, params_from_settings(settings)), settings)
        radius = tl.bike.wheel_radius
        spacing = math.tau / tl.bike.spokes
        total_path = 0.0
        for k in range(tl.frames):
            a, b = tl.frame(k), tl.frame(k + 1)
            chord = math.hypot(b.rear[0] - a.rear[0], b.rear[1] - a.rear[1])
            arc = (b.wheel_angle - a.wheel_angle) * radius
            self.assertGreater(arc, 0)
            # the arc is the true path; the chord only cuts corners (e.g. the bottom of a
            # steep valley), so it can only be shorter, and only by a bounded amount
            self.assertGreaterEqual(arc / chord, 0.999, f"frame {k}")
            self.assertLess(arc / chord, 1.3, f"frame {k}")
            total_path += chord
        total_arc = (tl.frame(tl.frames).wheel_angle - tl.frame(0).wheel_angle) * radius
        self.assertAlmostEqual(total_arc / total_path, 1.0, delta=0.02)
        self.assertGreater(spacing, 0)

    def test_pose_is_smooth_between_frames(self):
        tl, rider = self.tl, RiderSpec()
        prev = None
        for k in range(tl.frames + 1):
            pose = solve_pose(tl.bike, rider, tl.frame(k).controls)
            head = pose.head
            if prev is not None:
                self.assertLess(dist(head, prev), 14.0, f"head popped at frame {k}")
            prev = head

    def test_rider_stays_in_the_frame(self):
        tl, s = self.tl, self.settings
        for k in range(tl.frames):
            fr = tl.frame(k)
            x_screen = (fr.rear[0] + 52 - fr.cam_x) * s.unit
            self.assertGreater(x_screen, 0.2 * s.width)
            self.assertLess(x_screen, 0.6 * s.width)
            y_screen = camera.ANCHOR_Y * s.height - (fr.rear[1] - fr.cam_y) * s.unit
            self.assertGreater(y_screen, 0.2 * s.height)
            self.assertLess(y_screen, s.height)

    def test_every_frame_reports_a_day_and_progress(self):
        tl = self.tl
        days = {tl.frame(k).day_index for k in range(tl.frames)}
        self.assertTrue(any(d is not None and d > 300 for d in days))
        self.assertTrue(all(0.0 <= tl.frame(k).progress <= 1.0 for k in range(tl.frames)))

    def test_summary(self):
        summary = self.tl.summary()
        self.assertEqual(summary["frames"], 30)
        self.assertGreaterEqual(summary["jumps"], 1)

    def test_degenerate_data_still_produces_a_ride(self):
        for counts in ([0] * 60, [4] * 60, [0] * 29 + [30] + [0] * 30):
            t = generate_terrain(counts, TerrainParams())
            tl = Timeline(t, small_settings())
            first, last = tl.frame(0), tl.frame(tl.frames)
            self.assertAlmostEqual(last.rear[0] - first.rear[0], tl.period, places=5)

    def test_short_range_works(self):
        series = series_from_counts([1, 5, 2, 0, 9, 3, 4])
        tl = Timeline(generate_terrain(series.counts, params_from_settings(small_settings())), small_settings())
        self.assertEqual(tl.frame(0).rear[0] > 0, True)


class ParticleTests(unittest.TestCase):
    def test_puff_lifetime_and_loop_wrap(self):
        puff = Puff(t0=2.8, x=100.0, y=20.0, vx=-10, vy=30, size0=2, size1=8, life=0.5, alpha=0.5)
        self.assertIsNone(puff.at(1.0, 3.0, 500.0))
        alive = puff.at(2.9, 3.0, 500.0)
        self.assertIsNotNone(alive)
        # spawned near the end of the lap and still alive at the start of the next one
        wrapped = puff.at(0.1, 3.0, 500.0)
        self.assertIsNotNone(wrapped)
        self.assertAlmostEqual(wrapped[0], puff.at(3.1, 3.0, 500.0)[0] - 500.0 + 0.0, delta=3.0) if puff.at(3.1, 3.0, 500.0) else None
        self.assertIsNone(puff.at(0.5, 3.0, 500.0))
        x, y, r, a = alive
        self.assertTrue(r > 0 and 0 <= a <= 0.5)

    def test_generators_are_deterministic(self):
        self.assertEqual(landing_burst(1, 0.5, 10, 5, 600, 0.8), landing_burst(1, 0.5, 10, 5, 600, 0.8))
        self.assertGreater(len(landing_burst(1, 0.5, 10, 5, 600, 1.0)), len(landing_burst(1, 0.5, 10, 5, 600, 0.0)))
        self.assertEqual(trail_puff(3, 0.1, 5, 5, 500), trail_puff(3, 0.1, 5, 5, 500))
        self.assertEqual(len(takeoff_puffs(2, 0.2, 5, 5, 500)), 4)


if __name__ == "__main__":
    unittest.main()
