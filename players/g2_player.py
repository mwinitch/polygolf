import numpy as np
import functools
import sympy
import logging
import heapq
from scipy import stats as scipy_stats

from typing import Tuple, Iterator, List
from sympy.geometry import Polygon, Point2D
from matplotlib.path import Path
from shapely.geometry import Polygon as ShapelyPolygon, Point as ShapelyPoint


# Cached distribution
DIST = scipy_stats.norm(0, 1)


@functools.lru_cache()
def standard_ppf(conf: float) -> float:
    return DIST.ppf(conf)


def result_point(distance: float, angle: float, current_point: Tuple[float, float]) -> Tuple[float, float]:
    cx, cy = current_point
    nx = cx + distance * np.cos(angle)
    ny = cy + distance * np.sin(angle)
    return nx, ny


def splash_zone(distance: float, angle: float, conf: float, skill: int, current_point: Tuple[float, float]) -> List[Tuple[float, float]]:
    curr_x, curr_y = current_point
    conf_points = np.linspace(1 - conf, conf, 100)
    distances = np.vectorize(standard_ppf)(conf_points) * (distance / skill) + distance
    angles = np.vectorize(standard_ppf)(conf_points) * (1/(2*skill)) + angle
    xs = []
    ys = []
    scale = 1.1
    if distance <= 20:
        scale = 1.0
    max_distance = distances[-1]*scale
    for a in angles:
        x = curr_x + max_distance * np.cos(a)
        y = curr_y + max_distance * np.sin(a)

        xs.append(x)
        ys.append(y)

    min_distance = distances[0]
    for a in reversed(angles):
        x = curr_x + min_distance * np.cos(a)
        y = curr_y + min_distance * np.sin(a)

        xs.append(x)
        ys.append(y)

    # return Polygon(*zip(xs,ys), evaluate=False)
    return list(zip(xs, ys))


def poly_to_points(poly: Polygon) -> Iterator[Tuple[float, float]]:
    x_min, y_min = float('inf'), float('inf')
    x_max, y_max = float('-inf'), float('-inf')
    for point in poly.vertices:
        x = float(point.x)
        y = float(point.y)
        x_min = min(x, x_min)
        x_max = max(x, x_max)
        y_min = min(y, y_min)
        y_max = max(y, y_max)
    x_step = 1.0  # meter
    y_step = 1.0  # meter

    x_current = x_min + x_step
    y_current = y_min + y_step
    while x_current < x_max:
        while y_current < y_max:
            yield float(x_current), float(y_current)
            y_current += y_step
        y_current = y_min
        x_current += x_step


def sympy_poly_to_mpl(sympy_poly: Polygon) -> Path:
    """Helper function to convert sympy Polygon to matplotlib Path object"""
    v = sympy_poly.vertices
    v.append(v[0])
    return Path(v, closed=True)


def sympy_poly_to_shapely(sympy_poly: Polygon) -> ShapelyPolygon:
    """Helper function to convert sympy Polygon to shapely Polygon object"""
    v = sympy_poly.vertices
    v.append(v[0])
    return ShapelyPolygon(v)


class ScoredPoint:
    """Scored point class for use in A* search algorithm"""
    def __init__(self, point: Tuple[float, float], goal: Tuple[float, float], actual_cost=float('inf'), previous=None):
        if type(point) == Point2D:
            self.point = tuple(point)
            self.point = float(self.point[0]), float(self.point[1])
        else:
            self.point = point

        if type(goal) == Point2D:
            self.goal = tuple(goal)
            self.goal = float(self.goal[0]), float(self.goal[1])
        else:
            self.goal = goal

        a = np.array(self.point).astype(float)
        b = np.array(self.goal).astype(float)
        self.h_cost = np.linalg.norm(a - b)

        self.actual_cost = actual_cost
        self.previous = previous
    
    def f_cost(self):
        return self.h_cost + self.actual_cost

    def __lt__(self, other):
        return self.f_cost() < other.f_cost()

    def __eq__(self, other):
        return self.point == other.point
    
    def __hash__(self):
        return hash(self.point)
    
    def __repr__(self):
        return f"ScoredPoint(point = {self.point}, h_cost = {self.h_cost})"


class Player:
    def __init__(self, skill: int, rng: np.random.Generator, logger: logging.Logger) -> None:
        """Initialise the player with given skill.

        Args:
            skill (int): skill of your player
            rng (np.random.Generator): numpy random number generator, use this for same player behvior across run
            logger (logging.Logger): logger use this like logger.info("message")
        """
        self.skill = skill
        self.rng = rng
        self.logger = logger
        self.map_points = None
        self.mpl_paly = None
        self.shapely_poly = None
        self.goal = None
        self.prev_rv = None

        # Cached data
        max_dist = 200 + self.skill
        self.max_ddist = scipy_stats.norm(max_dist, max_dist / self.skill)

    @functools.lru_cache()
    def _max_ddist_ppf(self, conf: float):
        return self.max_ddist.ppf(1.0 - conf)

    def reachable_point(self, current_point: Tuple[float, float], target_point: Tuple[float, float], conf: float) -> bool:
        """Determine whether the point is reachable with confidence [conf] based on our player's skill"""
        if type(current_point) == Point2D:
            current_point = tuple(current_point)
        if type(target_point) == Point2D:
            target_point = tuple(target_point)

        current_point = np.array(current_point).astype(float)
        target_point = np.array(target_point).astype(float)

        return np.linalg.norm(current_point - target_point) <= self._max_ddist_ppf(conf)
    
    def splash_zone_within_polygon(self, current_point: Tuple[float, float], target_point: Tuple[float, float], conf: float) -> bool:
        if type(current_point) == Point2D:
            current_point = tuple(Point2D)

        if type(target_point) == Point2D:
            target_point = tuple(Point2D)

        distance = np.linalg.norm(np.array(current_point).astype(float) - np.array(target_point).astype(float))
        cx, cy = current_point
        tx, ty = target_point
        angle = np.arctan2(float(ty) - float(cy), float(tx) - float(cx))
        splash_zone_poly_points = splash_zone(float(distance), float(angle), float(conf), self.skill, current_point)
        splash_zone_poly_points.append(splash_zone_poly_points[0])
        return self.shapely_poly.contains(ShapelyPolygon(splash_zone_poly_points))

    def adjacent_points(self, point: Tuple[float, float], conf: float) -> Iterator[Tuple[float, float]]:
        # check goal point
        if self.reachable_point(point, self.goal, conf):
            yield self.goal

        for candidate_point in self.map_points:
            if self.reachable_point(point, candidate_point, conf):
                yield tuple(candidate_point)

    def scored_adjacent_points(self, point: Tuple[float, float], goal: Tuple[float, float], conf: float) -> Iterator[Tuple[float, float]]:
        for candidate_point in self.adjacent_points(point, conf):
            # Tuple of heuristic score and candidate point
            yield ScoredPoint(candidate_point, goal)

    def next_target(self, curr_loc: Point2D, goal: Point2D, conf: float) -> Tuple[float, float]:
        heap = [ScoredPoint(curr_loc, goal, 0.0)]
        start_point = heap[0].point
        # Used to cache the best cost and avoid adding useless points to the heap
        best_cost = {tuple(curr_loc): 0.0}
        visited = set()
        while len(heap) > 0:
            next_sp = heapq.heappop(heap)
            next_p = next_sp.point
            del best_cost[next_p]

            if next_p in visited:
                continue
            if next_sp.actual_cost > 0 and not self.splash_zone_within_polygon(next_sp.previous.point, next_p, conf):
                continue
            visited.add(next_p)

            if np.linalg.norm(np.array(self.goal) - np.array(next_p)) <= 5.4 / 100.0:
                # All we care about is the next point
                while next_sp.previous.point != start_point:
                    next_sp = next_sp.previous
                return next_sp.point
            
            # Add adjacent points to heap
            sap = list(self.adjacent_points(next_p, conf))
            for candidate_point in sap:
                new_point = ScoredPoint(candidate_point, goal, next_sp.actual_cost + 1, next_sp)
                if candidate_point not in best_cost or best_cost[candidate_point] > new_point.f_cost():
                    best_cost[candidate_point] = new_point.f_cost()
                    heapq.heappush(heap, new_point)

        # No path available
        return None

    def _initialize_map_points(self, golf_map: Polygon):
        map_points = []
        self.mpl_poly = sympy_poly_to_mpl(golf_map)
        self.shapely_poly = sympy_poly_to_shapely(golf_map)
        pp = list(poly_to_points(golf_map))
        for point in pp:
            # Use matplotlib here because it's faster than shapely for this calculation...
            if self.mpl_poly.contains_point(point):
                map_points.append(tuple(point))
        self.map_points = np.array(map_points)

    def play(self, score: int, golf_map: sympy.Polygon, target: sympy.geometry.Point2D, curr_loc: sympy.geometry.Point2D, prev_loc: sympy.geometry.Point2D, prev_landing_point: sympy.geometry.Point2D, prev_admissible: bool) -> Tuple[float, float]:
        """Function which based n current game state returns the distance and angle, the shot must be played 

        Args:
            score (int): Your total score including current turn
            golf_map (sympy.Polygon): Golf Map polygon
            target (sympy.geometry.Point2D): Target location
            curr_loc (sympy.geometry.Point2D): Your current location
            prev_loc (sympy.geometry.Point2D): Your previous location. If you haven't played previously then None
            prev_landing_point (sympy.geometry.Point2D): Your previous shot landing location. If you haven't played previously then None
            prev_admissible (bool): Boolean stating if your previous shot was within the polygon limits. If you haven't played previously then None

        Returns:
            Tuple[float, float]: Return a tuple of distance and angle in radians to play the shot
        """
        if self.map_points is None:
            self._initialize_map_points(golf_map)
            self.goal = float(target.x), float(target.y)

        # Optimization to retry missed shots
        if self.prev_rv is not None and curr_loc == prev_loc:
            return self.prev_rv

        target_point = None
        confidence = 0.95
        cl = float(curr_loc.x), float(curr_loc.y)
        while target_point is None:
            target_point = self.next_target(cl, target, confidence)
            confidence -= 0.05

        # fixup target
        current_point = np.array(tuple(curr_loc)).astype(float)
        if tuple(target_point) == self.goal:
            dist = np.linalg.norm(np.array(target_point) - current_point)
            v = np.array(target_point) - current_point
            u = v / dist
            if dist * 1.10 > 20.0:
                pass
                # target_point = current_point + u * dist * (1 / 1.10)
            else:
                target_point = current_point + u * dist * 1.10

        cx, cy = current_point
        tx, ty = target_point
        angle = np.arctan2(ty - cy, tx - cx)

        rv = curr_loc.distance(Point2D(target_point, evaluate=False)), angle
        self.prev_rv = rv
        return rv


# === Unit Tests ===

def test_reachable():
    current_point = Point2D(0, 0, evaluate=False)
    target_point = Point2D(0, 250, evaluate=False)
    player = Player(50, 0xdeadbeef, None)
    
    assert not player.reachable_point(current_point, target_point, 0.80)


def test_splash_zone_within_polygon():
    poly = Polygon((0,0), (0, 300), (300, 300), (300, 0), evaluate=False)

    current_point = Point2D(0, 0, evaluate=False)

    # Just checking polygons inside and outside
    inside_target_point = Point2D(150, 150, evaluate=False)
    outside_target_point = Point2D(299, 100, evaluate=False)

    player = Player(50, 0xdeadbeef, None)
    assert player.splash_zone_within_polygon(current_point, inside_target_point, poly, 0.8)
    assert not player.splash_zone_within_polygon(current_point, outside_target_point, poly, 0.8)


def test_poly_to_points():
    poly = Polygon((0,0), (0, 10), (10, 10), (10, 0))
    points = set(poly_to_points(poly))
    for x in range(1, 10):
        for y in range(1, 10):
            assert (x,y) in points
    assert len(points) == 81
