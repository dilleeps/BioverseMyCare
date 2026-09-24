"""In-hospital wayfinding: indoor maps, step-by-step routes, and corridor or elevator closures.

The building is a graph (wf_nodes, wf_edges) drawn over floor plans (wf_areas). Routes are Dijkstra over
travel time, with a step-free option and closed edges removed. Text directions come from the geometry:
turns from the angle between walking vectors, landmarks from rooms whose doors open onto the path, and
floor changes from elevator, stairs and escalator edges.

Anyone signed in can read maps and routes (QR signs open /find-your-way?from=<code>). Patients can route
to their own next appointment. Staff and administrators close and reopen segments; every change is audited.

Plan coordinates are meters with y growing downward (south), as drawn. A positive signed turn angle is
therefore a right turn.
"""

from __future__ import annotations

import heapq
import math
import re
from dataclasses import dataclass, field, replace
from typing import Annotated, Iterable

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg import Connection
from pydantic import BaseModel, Field, field_validator, model_validator

from bioverse import audit
from bioverse.auth import CurrentUser, Patient, User, Workforce
from bioverse.db import DbConn
from bioverse.routers.visits import clinic_tz

router = APIRouter(prefix="/api/wayfinding", tags=["wayfinding"])

# --- Travel model ------------------------------------------------------------------------------------

PACE_M_PER_S = {"normal": 1.2, "slow": 0.7}
ELEVATOR_WAIT_S = 30          # added when stepping into an elevator
ELEVATOR_PER_LEVEL_S = 8
ESCALATOR_RIDE_S = {"normal": 30, "slow": 35}
STAIRS_EFFORT = 2.5           # climbing a flight takes this many times as long as walking its length
FLOOR_CHANGE_S = 15           # orientation cost of every level changed, whatever the means

VERTICAL = ("elevator", "stairs", "escalator")
STRAIGHT_DEG, BEAR_DEG, AROUND_DEG = 25, 60, 150
SHORT_LEG_M = 8               # a last leg this short reads as "X is on your left", not a walk

LANDMARK_KINDS = ("cafe", "pharmacy", "desk", "restroom", "escalator", "lab", "imaging", "clinic", "waiting",
                  "entrance")
LANDMARK_RANK = {k: i for i, k in enumerate(LANDMARK_KINDS)}


@dataclass(frozen=True)
class Node:
    id: str
    floor_id: str
    level: int
    floor_name: str
    kind: str
    name: str | None
    code: str | None
    x: float
    y: float
    facing: float | None = None


@dataclass(frozen=True)
class Edge:
    id: str
    a: str
    b: str
    meters: float
    step_free: bool
    kind: str
    segment: str | None
    closed: bool = False
    closed_reason: str | None = None

    def other(self, node_id: str) -> str:
        return self.b if node_id == self.a else self.a


@dataclass(frozen=True)
class Area:
    id: str
    floor_id: str
    level: int
    name: str
    label: str | None
    kind: str
    polygon: list
    node_id: str | None
    slug: str | None
    keywords: list
    searchable: bool
    label_x: float | None = None
    label_y: float | None = None

    @property
    def centroid(self) -> tuple[float, float]:
        return polygon_centroid(self.polygon)


@dataclass
class Graph:
    nodes: dict[str, Node]
    edges: dict[str, Edge]
    areas: list[Area]
    floors: dict[int, dict]
    adj: dict[str, list[Edge]] = field(default_factory=dict)
    areas_by_node: dict[str, list[Area]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.adj = {n: [] for n in self.nodes}
        for e in sorted(self.edges.values(), key=lambda e: e.id):
            self.adj[e.a].append(e)
            self.adj[e.b].append(e)
        self.areas_by_node = {}
        for a in self.areas:
            if a.node_id:
                self.areas_by_node.setdefault(a.node_id, []).append(a)

    def with_closed(self, edge_ids: Iterable[str], reason: str) -> "Graph":
        """A copy with these edges closed (used by tests and what-if checks)."""
        ids = set(edge_ids)
        edges = {i: replace(e, closed=True, closed_reason=reason) if i in ids else e for i, e in self.edges.items()}
        return Graph(self.nodes, edges, self.areas, self.floors)

    def segment_edges(self, segment: str) -> list[str]:
        return [e.id for e in self.edges.values() if e.segment == segment]

    def node_by_code(self, code: str) -> Node | None:
        code = code.strip().upper()
        return next((n for n in self.nodes.values() if n.code == code), None)

    def area_for_node(self, node_id: str) -> Area | None:
        """The main (searchable) area whose door this node is."""
        found = self.areas_by_node.get(node_id, [])
        found = sorted(found, key=lambda a: (not a.searchable, a.kind == "desk" and len(found) > 1))
        return found[0] if found else None


def polygon_centroid(points: list) -> tuple[float, float]:
    area2 = cx = cy = 0.0
    n = len(points)
    for i in range(n):
        x0, y0 = points[i]
        x1, y1 = points[(i + 1) % n]
        cross = x0 * y1 - x1 * y0
        area2 += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(area2) < 1e-9:
        return (sum(p[0] for p in points) / n, sum(p[1] for p in points) / n)
    return (cx / (3 * area2), cy / (3 * area2))


# --- Geometry ----------------------------------------------------------------------------------------


def vector(p: Node, q: Node) -> tuple[float, float]:
    return (q.x - p.x, q.y - p.y)


def facing_vector(deg: float) -> tuple[float, float]:
    r = math.radians(deg)
    return (math.cos(r), math.sin(r))


def turn_angle(v1: tuple[float, float], v2: tuple[float, float]) -> float:
    """Signed angle from heading v1 to heading v2, in degrees. Positive is a right turn (y grows downward)."""
    cross = v1[0] * v2[1] - v1[1] * v2[0]
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    return math.degrees(math.atan2(cross, dot))


def turn_word(angle: float) -> str:
    a = abs(angle)
    if a < STRAIGHT_DEG:
        return "straight"
    side = "right" if angle > 0 else "left"
    if a < BEAR_DEG:
        return f"slight {side}"
    if a < AROUND_DEG:
        return side
    return "around"


def side_of(heading: tuple[float, float], origin: tuple[float, float], point: tuple[float, float]) -> str:
    """Where `point` lies for someone at `origin` walking along `heading`: left, right or ahead."""
    angle = turn_angle(heading, (point[0] - origin[0], point[1] - origin[1]))
    if abs(angle) < STRAIGHT_DEG:
        return "ahead"
    if abs(angle) > 180 - STRAIGHT_DEG:
        return "behind"
    return "right" if angle > 0 else "left"


# --- Shortest path -----------------------------------------------------------------------------------


@dataclass
class Path:
    nodes: list[Node]
    edges: list[Edge]
    cost_s: float

    @property
    def distance_m(self) -> float:
        return sum(e.meters for e in self.edges if e.kind in ("walk", "stairs"))

    @property
    def step_free(self) -> bool:
        return all(e.step_free and e.kind in ("walk", "elevator") for e in self.edges)


def closure_key(edge: Edge) -> str:
    return edge.segment or edge.id


def usable(edge: Edge, step_free: bool, ignore_closed: bool, only_closed: set[str] | None = None) -> bool:
    if edge.closed and not ignore_closed and (only_closed is None or closure_key(edge) in only_closed):
        return False
    if step_free and (not edge.step_free or edge.kind in ("stairs", "escalator")):
        return False
    return True


def edge_cost(edge: Edge, riding: bool, pace: str) -> float:
    speed = PACE_M_PER_S[pace]
    if edge.kind == "walk":
        return edge.meters / speed
    if edge.kind == "elevator":
        return ELEVATOR_PER_LEVEL_S + FLOOR_CHANGE_S + (0 if riding else ELEVATOR_WAIT_S)
    if edge.kind == "stairs":
        return edge.meters / speed * STAIRS_EFFORT + FLOOR_CHANGE_S
    return ESCALATOR_RIDE_S[pace] + FLOOR_CHANGE_S


def shortest(graph: Graph, source: str, targets: set[str], *, step_free: bool = False, slow: bool = False,
             ignore_closed: bool = False, only_closed: set[str] | None = None) -> Path | None:
    """Dijkstra over travel time. State is (node, riding an elevator), so the wait counts once per ride.

    `only_closed` honours just those closures (segment names or edge ids) and treats the rest as open."""
    pace = "slow" if slow else "normal"
    start = (source, False)
    best: dict[tuple[str, bool], float] = {start: 0.0}
    prev: dict[tuple[str, bool], tuple[tuple[str, bool], Edge]] = {}
    heap: list = [(0.0, 0, start)]
    seq = 0
    while heap:
        cost, _, state = heapq.heappop(heap)
        if cost > best.get(state, math.inf):
            continue
        node_id, riding = state
        if node_id in targets:
            edges, nodes, s = [], [graph.nodes[node_id]], state
            while s in prev:
                s, e = prev[s]
                edges.append(e)
                nodes.append(graph.nodes[s[0]])
            return Path(nodes[::-1], edges[::-1], cost)
        for e in graph.adj.get(node_id, []):
            if not usable(e, step_free, ignore_closed, only_closed):
                continue
            nxt = (e.other(node_id), e.kind == "elevator")
            c = cost + edge_cost(e, riding, pace)
            if c < best.get(nxt, math.inf) - 1e-9:
                best[nxt] = c
                prev[nxt] = (state, e)
                seq += 1
                heapq.heappush(heap, (c, seq, nxt))
    return None


# --- Directions --------------------------------------------------------------------------------------


def the(area: Area) -> str:
    if area.kind == "restroom":
        return "the restrooms"
    if area.kind == "escalator":
        return "the escalator"
    return f"the {area.name}"


def place_name(graph: Graph, node: Node, area: Area | None = None) -> str:
    area = area or graph.area_for_node(node.id)
    if area:
        return the(area)
    return f"the {node.name}" if node.name else "your starting point"


def meters_text(m: float) -> str:
    m = max(1, round(m / 5) * 5 if m >= 30 else round(m))
    return f"{m} m"


def segment_label(edges: list[Edge]) -> str | None:
    """The corridor most of this leg follows, e.g. 'Level 1 corridor' (from 'Level 1 corridor, west')."""
    weight: dict[str, float] = {}
    for e in edges:
        if e.segment and e.kind == "walk":
            name = e.segment.split(",")[0].strip()
            weight[name] = weight.get(name, 0) + e.meters
    return max(weight, key=weight.get) if weight else None


def along(label: str | None, turned: bool) -> str:
    if not label:
        return ""
    if "lobby" in label.lower():
        return f" through the {label}"
    return f" into the {label}" if turned else f" along the {label}"


def vertical_phrase(node: Node) -> str:
    if node.kind == "escalator":
        return "the escalator"
    if node.kind == "stairs":
        return f"the {node.name or 'stairs'}"
    return node.name or "the elevator"


def is_are(subject: str) -> str:
    return "are" if subject.lower().endswith(("restrooms", "stairs")) else "is"


def position(word: str | None) -> str:
    if word in (None, "straight"):
        return "straight ahead"
    if word == "around":
        return "behind you"
    return f"on your {word.split()[-1]}"


@dataclass
class Leg:
    nodes: list[Node]
    edges: list[Edge]

    @property
    def length(self) -> float:
        return sum(e.meters for e in self.edges)

    @property
    def heading_in(self) -> tuple[float, float]:
        return vector(self.nodes[0], self.nodes[1])

    @property
    def heading_out(self) -> tuple[float, float]:
        return vector(self.nodes[-2], self.nodes[-1])


def split_legs(nodes: list[Node], edges: list[Edge]) -> list[Leg]:
    """Break a same-floor walk wherever the direction changes by more than a slight bend."""
    legs: list[Leg] = []
    cur_nodes, cur_edges = [nodes[0]], []
    for i, e in enumerate(edges):
        a, b = nodes[i], nodes[i + 1]
        if cur_edges:
            angle = turn_angle(vector(cur_nodes[-2], cur_nodes[-1]), vector(a, b))
            if abs(angle) >= STRAIGHT_DEG:
                legs.append(Leg(cur_nodes, cur_edges))
                cur_nodes, cur_edges = [a], []
        cur_nodes.append(b)
        cur_edges.append(e)
    if cur_edges:
        legs.append(Leg(cur_nodes, cur_edges))
    return legs


def landmarks(graph: Graph, leg: Leg, on_path: set[str], skip: set[str]) -> list[tuple[Area, str]]:
    """Rooms whose doors open onto this leg, with the side they are on."""
    found: list[tuple[int, Area, str]] = []
    for i in range(1, len(leg.nodes)):
        here = leg.nodes[i]
        heading = vector(leg.nodes[i - 1], here)
        for e in graph.adj.get(here.id, []):
            other = e.other(here.id)
            if e.kind != "walk" or other in on_path:
                continue
            for area in graph.areas_by_node.get(other, []):
                if area.id in skip or area.kind not in LANDMARK_KINDS:
                    continue
                if not area.searchable and area.kind != "escalator":
                    continue
                side = side_of(heading, (here.x, here.y), area.centroid)
                if side in ("left", "right"):
                    found.append((i, area, side))
    found.sort(key=lambda t: (LANDMARK_RANK[t[1].kind], t[0]))
    picked: list[tuple[Area, str]] = []
    for _, area, side in found:
        if area.id not in {a.id for a, _ in picked}:
            picked.append((area, side))
        if len(picked) == 2:
            break
    return picked


def landmark_text(items: list[tuple[Area, str]]) -> str:
    if not items:
        return ""
    parts = [f"{the(a)} on your {side}" for a, side in items]
    return " You'll pass " + " and ".join(parts) + "."


def floor_change_text(edges: list[Edge], start: Node, end: Node, graph: Graph) -> str:
    kind, seg = edges[0].kind, edges[0].segment or edges[0].kind.title()
    direction = "up" if end.level > start.level else "down"
    to = end.floor_name
    if kind == "elevator":
        return f"Take {seg} {direction} to {to}."
    if kind == "escalator":
        return f"Take the escalator {direction} to {to}."
    levels = abs(end.level - start.level)
    flights = "one floor" if levels == 1 else f"{levels} floors"
    return f"Take the {seg} {direction} {flights} to {to}."


def directions(graph: Graph, path: Path, dest_area: Area | None, start_area: Area | None = None) -> dict:
    """Numbered text steps, per-floor polylines and floor-change markers for a path."""
    nodes, edges = path.nodes, path.edges
    start, end = nodes[0], nodes[-1]
    dest_name = place_name(graph, end, dest_area)
    steps: list[dict] = []

    def add(text: str, kind: str, node: Node, meters: float | None = None) -> None:
        steps.append({"n": len(steps) + 1, "text": text[0].upper() + text[1:], "kind": kind,
                      "floor_level": node.level, "node_id": node.id, "meters": meters})

    if not edges:
        add(f"You're already at {dest_name}.", "arrive", end)
        return {"steps": steps, "segments": [], "markers": []}

    on_path = {n.id for n in nodes}
    mentioned = {a.id for a in (dest_area, start_area, graph.area_for_node(start.id)) if a}
    start_name = f"the {start.name}" if start.code and start.name else place_name(graph, start, start_area)
    add(f"Start at {start_name} on {start.floor_name}.", "start", start)

    # Runs: same-floor walking, or consecutive vertical edges of one elevator, stair or escalator.
    runs: list[tuple[str, int, int]] = []   # (kind, first edge index, last edge index)
    for i, e in enumerate(edges):
        kind = "vertical" if e.kind in VERTICAL else "walk"
        if runs and runs[-1][0] == kind and (kind == "walk" or edges[runs[-1][2]].segment == e.segment):
            runs[-1] = (kind, runs[-1][1], i)
        else:
            runs.append((kind, i, i))

    segments: list[dict] = []
    markers: list[dict] = []
    heading = facing_vector(start.facing) if start.facing is not None else None
    leaving: str | None = None
    for r, (kind, i0, i1) in enumerate(runs):
        run_nodes, run_edges = nodes[i0:i1 + 2], edges[i0:i1 + 1]
        if kind == "vertical":
            a, b = run_nodes[0], run_nodes[-1]
            add(floor_change_text(run_edges, a, b, graph), "floor_change", a)
            label = run_edges[0].segment or "Stairs"
            markers.append({"floor_level": a.level, "x": a.x, "y": a.y, "kind": run_edges[0].kind,
                            "text": f"{label} to {b.floor_name}"})
            markers.append({"floor_level": b.level, "x": b.x, "y": b.y, "kind": run_edges[0].kind,
                            "text": f"Arrive by {label}"})
            leaving = vertical_phrase(b)
            heading = None
            continue

        segments.append({"floor_level": run_nodes[0].level,
                         "points": [[n.x, n.y] for n in run_nodes],
                         "starts_route": r == 0, "ends_route": r == len(runs) - 1})
        legs = split_legs(run_nodes, run_edges)
        last_run = r == len(runs) - 1
        next_vertical = None if last_run else nodes[runs[r + 1][1]]
        for j, leg in enumerate(legs):
            last_leg = j == len(legs) - 1
            out_of_room = r == 0 and j == 0 and start.kind in ("door", "desk")
            if j == 0 and len(legs) > 1 and leg.length <= SHORT_LEG_M and (leaving or out_of_room):
                # The few steps out of an elevator or a room set the heading for the first real turn.
                leaving = leaving or place_name(graph, start, start_area)
                heading = leg.heading_out
                continue
            angle = turn_angle(heading, leg.heading_in) if heading else None
            word = turn_word(angle) if angle is not None else None
            prefix = f"leave {leaving}, " if leaving else ""
            leaving = None

            if last_leg and (last_run or next_vertical) and leg.length <= SHORT_LEG_M and len(steps) > 1:
                subject = dest_name if last_run else vertical_phrase(next_vertical)
                lead = f"{prefix[:-2]}. " if prefix else ""
                subject_cap = subject[0].upper() + subject[1:] if lead else subject
                add(f"{lead}{subject_cap} {is_are(subject)} {position(word)}.", "arrive" if last_run else "walk",
                    leg.nodes[-1], None if last_run else leg.length)
                heading = leg.heading_out
                continue

            label = segment_label(leg.edges)
            dist = meters_text(leg.length)
            if word is None:
                text = f"{prefix}walk {dist}{along(label, False)}"
            elif word == "straight":
                verb = "walk straight ahead" if j == 0 else "continue straight"
                text = f"{prefix}{verb}{along(label, False)} for {dist}"
            elif word == "around":
                text = f"{prefix}turn around and walk {dist}{along(label, False)}"
            else:
                text = f"{prefix}turn {word}{along(label, True)} and walk {dist}"
            if last_leg and next_vertical is not None:
                text += f" to {vertical_phrase(next_vertical)}"
            text += "."
            items = landmarks(graph, leg, on_path, mentioned)
            mentioned.update(a.id for a, _ in items)
            text += landmark_text(items)
            add(text, "walk", leg.nodes[-1], leg.length)
            heading = leg.heading_out

            if last_leg and last_run:
                target = dest_area.centroid if dest_area else (end.x, end.y)
                side = side_of(heading, (end.x, end.y), target)
                where = {"ahead": "straight ahead", "behind": "behind you"}.get(side, f"on your {side}")
                add(f"{dest_name} {is_are(dest_name)} {where}.", "arrive", end)
    return {"steps": steps, "segments": segments, "markers": markers}


# --- Loading -----------------------------------------------------------------------------------------


def building_for(conn: Connection, user: User, building_id: str | None = None) -> dict:
    row = conn.execute(
        """
        SELECT id::text, name, campus, address, parking_note, help_note FROM wf_buildings
        WHERE organization_id = %s AND (%s::text IS NULL OR id::text = %s)
        ORDER BY created_at, name LIMIT 1
        """,
        (user.organization_id, building_id, building_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No indoor map for this organization yet")
    return row


def load_graph(conn: Connection, building_id: str) -> Graph:
    floors = {
        r["level"]: r for r in conn.execute(
            """
            SELECT id::text, level, name, short_name, width_m::float AS width_m, height_m::float AS height_m
            FROM wf_floors WHERE building_id = %s ORDER BY level
            """,
            (building_id,),
        ).fetchall()
    }
    nodes = {
        r["id"]: Node(**r) for r in conn.execute(
            """
            SELECT n.id::text, n.floor_id::text, f.level, f.name AS floor_name, n.kind, n.name, n.code,
                   n.x::float AS x, n.y::float AS y, n.facing_deg::float AS facing
            FROM wf_nodes n JOIN wf_floors f ON f.id = n.floor_id WHERE f.building_id = %s
            """,
            (building_id,),
        ).fetchall()
    }
    edges = {
        r["id"]: Edge(**r) for r in conn.execute(
            """
            SELECT id::text, from_node::text AS a, to_node::text AS b, meters::float AS meters, step_free, kind,
                   segment, closed, closed_reason
            FROM wf_edges WHERE building_id = %s
            """,
            (building_id,),
        ).fetchall()
    }
    areas = [
        Area(**r) for r in conn.execute(
            """
            SELECT a.id::text, a.floor_id::text, f.level, a.name, a.label, a.kind, a.polygon, a.node_id::text,
                   a.slug, a.keywords, a.searchable, a.label_x::float AS label_x, a.label_y::float AS label_y
            FROM wf_areas a JOIN wf_floors f ON f.id = a.floor_id WHERE a.building_id = %s ORDER BY a.id
            """,
            (building_id,),
        ).fetchall()
    ]
    return Graph(nodes, edges, areas, floors)


_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclass
class Point:
    node_ids: set[str]
    area: Area | None
    node: Node | None
    label: str


def resolve(graph: Graph, value: str, allow_nearest: bool = False) -> Point:
    """A sign code, a node or area id, an area slug, or (destinations only) nearest:<kind>."""
    value = (value or "").strip()
    if not value or len(value) > 64:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown place")
    if allow_nearest and value.lower().startswith("nearest:"):
        kind = value.split(":", 1)[1].lower()
        areas = [a for a in graph.areas if a.kind == kind and a.node_id and a.searchable]
        if not areas:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown place")
        return Point({a.node_id for a in areas}, None, None, f"nearest {kind}")
    node = graph.node_by_code(value)
    if node:
        return Point({node.id}, None, node, node.name or node.code)
    low = value.lower()
    for a in graph.areas:
        if a.node_id and (a.slug == low or a.id == low):
            return Point({a.node_id}, a, graph.nodes[a.node_id], a.name)
    if _UUID.match(low) and low in graph.nodes:
        node = graph.nodes[low]
        return Point({node.id}, graph.area_for_node(node.id), node, node.name or "this point")
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown place")


def node_view(node: Node) -> dict:
    return {"id": node.id, "name": node.name, "code": node.code, "kind": node.kind, "floor_level": node.level,
            "floor_name": node.floor_name, "x": node.x, "y": node.y}


def area_view(area: Area | None) -> dict | None:
    if area is None:
        return None
    return {"id": area.id, "name": area.name, "slug": area.slug, "kind": area.kind, "floor_level": area.level}


def closed_on(path: Path | None) -> list[Edge]:
    return [e for e in path.edges if e.closed] if path else []


def closure_notices(edges: list[Edge]) -> list[dict]:
    seen: dict[str, dict] = {}
    for e in edges:
        key = closure_key(e)
        if key not in seen:
            name = e.segment or "A corridor on this route"
            seen[key] = {"segment": e.segment, "reason": e.closed_reason,
                         "text": f"{name} is closed ({e.closed_reason})."}
    return list(seen.values())


def blocking_closures(graph: Graph, source: str, targets: set[str], step_free: bool, slow: bool) -> list[Edge]:
    """The closures that together cut every route: add the closures on the best remaining route until none is left."""
    honoured: set[str] = set()
    blockers: list[Edge] = []
    for _ in range(12):
        p = shortest(graph, source, targets, step_free=step_free, slow=slow, only_closed=honoured)
        if p is None:
            return blockers
        closed = [e for e in p.edges if e.closed]
        if not closed:
            return []
        for e in closed:
            if closure_key(e) not in honoured:
                honoured.add(closure_key(e))
                blockers.append(e)
    return blockers


def plan_route(graph: Graph, src: Point, dst: Point, *, step_free: bool, slow: bool,
               help_note: str | None = None) -> dict:
    source = next(iter(src.node_ids))
    path = shortest(graph, source, dst.node_ids, step_free=step_free, slow=slow)
    baseline = shortest(graph, source, dst.node_ids, step_free=step_free, slow=slow, ignore_closed=True)
    dest_node = path.nodes[-1] if path else (baseline.nodes[-1] if baseline else None)
    dest_area = dst.area or (graph.area_for_node(dest_node.id) if dest_node else None)
    start_node = graph.nodes[source]
    help_text = help_note or "Ask at the Information Desk and a member of staff will help you."
    result: dict = {
        "from": node_view(start_node),
        "from_area": area_view(src.area or graph.area_for_node(source)),
        "to": node_view(dest_node) if dest_node else None,
        "to_area": area_view(dest_area),
        "to_label": dest_area.name if dest_area else dst.label,
        "step_free_requested": step_free,
        "pace": "slow" if slow else "normal",
        "notices": [{**n, "text": n["text"] + (" Your route avoids it." if path else "")}
                    for n in closure_notices(closed_on(baseline))],
    }
    if path is None:
        result.update(found=False, explanation=explain_no_route(graph, source, dst, step_free, slow, baseline,
                                                                  help_text),
                      notices=[], steps=[], segments=[], markers=[], floors=[])
        return result
    d = directions(graph, path, dest_area, src.area)
    floors = []   # floors you walk on, not the ones an elevator passes
    for lv in [path.nodes[0].level, *(seg["floor_level"] for seg in d["segments"]), path.nodes[-1].level]:
        if lv not in floors:
            floors.append(lv)
    result.update(
        found=True,
        explanation=None,
        distance_m=round(path.distance_m),
        duration_s=round(path.cost_s),
        duration_min=max(1, round(path.cost_s / 60)),
        step_free=path.step_free,
        floors=floors,
        node_ids=[n.id for n in path.nodes],
        **d,
    )
    return result


def explain_no_route(graph: Graph, source: str, dst: Point, step_free: bool, slow: bool,
                     baseline: Path | None, help_text: str) -> str:
    kind = "step-free route" if step_free else "route"
    if baseline is not None:
        closed = closure_notices(blocking_closures(graph, source, dst.node_ids, step_free, slow))
        what = " ".join(n["text"] for n in closed)
        lead = f"The only {kind} there is closed right now." if len(closed) == 1 else \
            f"Every {kind} there is closed right now."
        text = f"{lead} {what}"
        if step_free and shortest(graph, source, dst.node_ids, step_free=False, slow=slow):
            text += " There is a route with stairs if you can use them."
        return f"{text} {help_text}"
    if step_free and shortest(graph, source, dst.node_ids, step_free=False, slow=slow, ignore_closed=True):
        return f"There is no step-free route to this place, only stairs or an escalator. {help_text}"
    return f"We can't find a way between these two places. {help_text}"


# --- Patient and public endpoints -----------------------------------------------------------------------


@router.get("/building")
def building(conn: DbConn, user: CurrentUser, building_id: str | None = None) -> dict:
    """Floor plans, places to search, starting points (sign codes) and current closures."""
    b = building_for(conn, user, building_id)
    g = load_graph(conn, b["id"])
    floors = []
    for level, f in g.floors.items():
        floors.append({
            **f,
            "areas": [
                {"id": a.id, "name": a.name, "label": a.label, "kind": a.kind, "polygon": a.polygon,
                 "label_x": a.label_x if a.label_x is not None else round(a.centroid[0], 1),
                 "label_y": a.label_y if a.label_y is not None else round(a.centroid[1], 1),
                 "slug": a.slug, "node_id": a.node_id}
                for a in g.areas if a.level == level
            ],
        })
    destinations = sorted(
        ({"id": a.id, "slug": a.slug, "name": a.name, "kind": a.kind, "floor_level": a.level,
          "floor_name": g.floors[a.level]["name"], "keywords": a.keywords}
         for a in g.areas if a.searchable and a.node_id and a.slug),
        key=lambda d: (d["name"], d["floor_level"]),
    )
    starts = sorted(
        ({"code": n.code, "name": n.name, "kind": n.kind, "floor_level": n.level, "floor_name": n.floor_name,
          "x": n.x, "y": n.y, "group": "Entrances" if n.kind == "entrance" else ("Parking" if n.level == 0 else "Signs")}
         for n in g.nodes.values() if n.code),
        # The street-level entrance first: it is the default start.
        key=lambda s: (["Entrances", "Parking", "Signs"].index(s["group"]), s["floor_level"] != 1, s["floor_level"],
                       s["name"] or ""),
    )
    return {"building": b, "floors": floors, "destinations": destinations, "starts": starts,
            "closed": closed_view(g)}


def closed_view(g: Graph) -> list[dict]:
    """Closed edges as map marks: a line for a corridor, a point on each floor for an elevator or stairs."""
    marks = []
    for e in g.edges.values():
        if not e.closed:
            continue
        a, b = g.nodes[e.a], g.nodes[e.b]
        if a.level == b.level:
            marks.append({"segment": e.segment, "reason": e.closed_reason, "floor_level": a.level,
                          "line": [[a.x, a.y], [b.x, b.y]]})
        else:
            for n in (a, b):
                marks.append({"segment": e.segment, "reason": e.closed_reason, "floor_level": n.level,
                              "point": [n.x, n.y]})
    return marks


@router.get("/signs/{code}")
def sign(code: str, conn: DbConn, user: CurrentUser) -> dict:
    """What a "You are here" sign points to."""
    b = building_for(conn, user)
    node = load_graph(conn, b["id"]).node_by_code(code)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "We don't recognize that sign code")
    return node_view(node)


@router.get("/route")
def route(
    conn: DbConn,
    user: CurrentUser,
    from_: Annotated[str, Query(alias="from", max_length=64)],
    to: Annotated[str, Query(max_length=64)],
    step_free: bool = False,
    slow: bool = False,
) -> dict:
    b = building_for(conn, user)
    g = load_graph(conn, b["id"])
    src = resolve(g, from_)
    dst = resolve(g, to, allow_nearest=True)
    return plan_route(g, src, dst, step_free=step_free, slow=slow, help_note=b["help_note"])


def destination_for(conn: Connection, organization_id: str, specialty: str, location_name: str | None) -> dict | None:
    """The desk to walk to for a practitioner's specialty and location, via wf_location_nodes."""
    loc = conn.execute(
        "SELECT id::text FROM locations WHERE organization_id = %s AND name = %s", (organization_id, location_name)
    ).fetchone() if location_name else None
    loc_id = loc["id"] if loc else None
    dept = conn.execute(
        """
        SELECT id::text FROM departments WHERE organization_id = %s AND specialty = %s
          AND (%s::text IS NULL OR location_id::text = %s) AND active
        ORDER BY (location_id::text = %s) DESC NULLS LAST LIMIT 1
        """,
        (organization_id, specialty, loc_id, loc_id, loc_id),
    ).fetchone()
    dept_id = dept["id"] if dept else None
    rows = conn.execute(
        """
        SELECT m.location_id::text, m.department_id::text, m.specialty, m.node_id::text, m.area_id::text,
               a.name AS area_name, a.slug, f.level AS floor_level, f.name AS floor_name
        FROM wf_location_nodes m
        JOIN wf_nodes n ON n.id = m.node_id JOIN wf_floors f ON f.id = n.floor_id
        LEFT JOIN wf_areas a ON a.id = m.area_id
        WHERE m.organization_id = %s
        """,
        (organization_id,),
    ).fetchall()

    def score(m: dict) -> int:
        if dept_id and m["department_id"] == dept_id:
            return 4
        if loc_id and m["location_id"] == loc_id and m["specialty"] == specialty and not m["department_id"]:
            return 3
        if loc_id and m["location_id"] == loc_id and not m["specialty"] and not m["department_id"]:
            return 2
        if not m["location_id"] and not m["department_id"] and m["specialty"] == specialty:
            return 1
        return 0

    ranked = sorted(((score(m), m) for m in rows), key=lambda t: -t[0])
    if not ranked or ranked[0][0] == 0:
        return None
    m = ranked[0][1]
    return {"node_id": m["node_id"], "area_id": m["area_id"], "name": m["area_name"], "slug": m["slug"],
            "floor_level": m["floor_level"], "floor_name": m["floor_name"]}


@router.get("/my-next-appointment")
def my_next_appointment(conn: DbConn, user: Patient) -> dict:
    """Where to walk for the patient's next in-person visit. Patients only; only their own visits."""
    rows = conn.execute(
        """
        SELECT a.id::text, s.starts_at, s.mode, pr.name AS practitioner_name, pr.specialty, pr.location_name,
               pr.organization_id::text AS organization_id, l.mode AS location_mode,
               (s.starts_at AT TIME ZONE %(tz)s)::date = (now() AT TIME ZONE %(tz)s)::date AS is_today
        FROM appointments a
        JOIN slots s ON s.id = a.slot_id
        JOIN practitioners pr ON pr.id = a.practitioner_id
        LEFT JOIN locations l ON l.organization_id = pr.organization_id AND l.name = pr.location_name
        LEFT JOIN appointment_encounters e ON e.appointment_id = a.id
        WHERE a.patient_id = %(p)s AND a.status = 'booked'
          AND coalesce(e.status, 'booked') NOT IN ('completed', 'no_show')
          AND s.starts_at > now() - interval '1 hour'
        ORDER BY s.starts_at LIMIT 10
        """,
        {"tz": clinic_tz(), "p": user.patient_id},
    ).fetchall()
    if not rows:
        return {"appointment": None, "destination": None, "check_in_link": None,
                "message": "You don't have an upcoming visit booked."}
    in_person = [r for r in rows if r["mode"] == "in_person" and r["location_mode"] != "virtual"]
    if not in_person:
        return {"appointment": _appt_view(rows[0]), "destination": None, "check_in_link": None,
                "message": "Your next visit is a video visit, so there's nowhere to walk to."}
    appt = in_person[0]
    dest = destination_for(conn, appt["organization_id"], appt["specialty"], appt["location_name"])
    if dest is None:
        return {"appointment": _appt_view(appt), "destination": None, "check_in_link": None,
                "message": f"Your next visit is at {appt['location_name']}, which isn't in this building. "
                           "Directions are on your visits page."}
    return {"appointment": _appt_view(appt), "destination": dest,
            "check_in_link": "/visits" if appt["is_today"] else None,
            "message": f"{appt['specialty']} with {appt['practitioner_name']}: go to {dest['name']}, "
                       f"{dest['floor_name']}."}


def _appt_view(r: dict) -> dict:
    return {"id": r["id"], "starts_at": r["starts_at"], "mode": r["mode"], "practitioner_name": r["practitioner_name"],
            "specialty": r["specialty"], "location_name": r["location_name"], "is_today": r["is_today"]}


# --- Staff and administrators --------------------------------------------------------------------------


def require_staff_or_admin(user: CurrentUser) -> User:
    if user.role not in ("staff", "admin"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Staff or administrator access required")
    return user


StaffOrAdmin = Annotated[User, Depends(require_staff_or_admin)]


def segments_view(conn: Connection, g: Graph, building_id: str) -> list[dict]:
    active = {
        r["segment"]: r for r in conn.execute(
            """
            SELECT c.id::text, c.segment, c.reason, c.closed_at, u.display_name AS closed_by
            FROM wf_closures c LEFT JOIN users u ON u.id = c.closed_by
            WHERE c.building_id = %s AND c.reopened_at IS NULL AND c.segment IS NOT NULL
            """,
            (building_id,),
        ).fetchall()
    }
    groups: dict[str, dict] = {}
    for e in g.edges.values():
        if not e.segment:
            continue
        s = groups.setdefault(e.segment, {"segment": e.segment, "kind": e.kind, "levels": set(), "edges": 0,
                                          "closed_edges": 0, "meters": 0.0})
        s["levels"].update({g.nodes[e.a].level, g.nodes[e.b].level})
        s["edges"] += 1
        s["closed_edges"] += e.closed
        s["meters"] += e.meters if e.kind == "walk" else 0
        if e.kind != "walk":
            s["kind"] = e.kind
    out = []
    for name, s in groups.items():
        levels = sorted(s["levels"])
        out.append({
            "segment": name, "kind": s["kind"], "levels": levels,
            "floors": [g.floors[lv]["short_name"] for lv in levels],
            "edges": s["edges"], "meters": round(s["meters"]),
            "status": "closed" if s["closed_edges"] == s["edges"] else ("partly_closed" if s["closed_edges"] else "open"),
            "closure": active.get(name),
        })
    order = {"elevator": 0, "escalator": 1, "stairs": 2, "walk": 3}
    return sorted(out, key=lambda s: (order[s["kind"]], s["levels"][0], s["segment"]))


def closures_view(conn: Connection, building_id: str, limit: int = 50) -> list[dict]:
    return conn.execute(
        """
        SELECT c.id::text, c.segment, cardinality(c.edge_ids) AS edges, c.reason, c.closed_at, c.reopened_at,
               cu.display_name AS closed_by, ru.display_name AS reopened_by, c.reopened_at IS NULL AS active
        FROM wf_closures c
        LEFT JOIN users cu ON cu.id = c.closed_by LEFT JOIN users ru ON ru.id = c.reopened_by
        WHERE c.building_id = %s ORDER BY c.closed_at DESC LIMIT %s
        """,
        (building_id, limit),
    ).fetchall()


def signs_view(g: Graph) -> list[dict]:
    return [
        {**node_view(n), "path": f"/find-your-way?from={n.code}",
         "area": (a.name if (a := g.area_for_node(n.id)) else None)}
        for n in sorted(g.nodes.values(), key=lambda n: (n.level, n.code or "")) if n.code
    ]


@router.get("/admin")
def admin_overview(conn: DbConn, user: Workforce) -> dict:
    """Floors and areas, closable segments with their status, and the closure log."""
    b = building_for(conn, user)
    g = load_graph(conn, b["id"])
    floors = [
        {"level": lv, "name": f["name"], "short_name": f["short_name"], "width_m": f["width_m"],
         "height_m": f["height_m"],
         "areas": [{"id": a.id, "name": a.name, "kind": a.kind, "slug": a.slug, "searchable": a.searchable,
                    "code": g.nodes[a.node_id].code if a.node_id else None}
                   for a in sorted(g.areas, key=lambda a: (a.kind == "corridor", a.name)) if a.level == lv],
         "nodes": sum(1 for n in g.nodes.values() if n.level == lv)}
        for lv, f in g.floors.items()
    ]
    return {"building": b, "floors": floors, "segments": segments_view(conn, g, b["id"]),
            "closures": closures_view(conn, b["id"]), "signs": signs_view(g),
            "can_edit": user.role in ("staff", "admin")}


@router.get("/signs")
def sign_sheet(conn: DbConn, user: Workforce) -> dict:
    b = building_for(conn, user)
    return {"building": b, "signs": signs_view(load_graph(conn, b["id"]))}


class ClosureIn(BaseModel):
    segment: str | None = Field(default=None, max_length=80)
    edge_ids: list[str] | None = Field(default=None, max_length=50)
    reason: str = Field(min_length=3, max_length=160)

    @field_validator("reason")
    @classmethod
    def clean(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 3:
            raise ValueError("Give a reason of at least 3 characters")
        return v

    @model_validator(mode="after")
    def one_target(self) -> "ClosureIn":
        if bool(self.segment) == bool(self.edge_ids):
            raise ValueError("Name a segment or a list of edges, not both")
        return self


@router.post("/closures", status_code=status.HTTP_201_CREATED)
def close(body: ClosureIn, conn: DbConn, user: StaffOrAdmin) -> dict:
    """Close a segment (a corridor, an elevator, a stairwell) or specific edges. Routes change at once."""
    b = building_for(conn, user)
    g = load_graph(conn, b["id"])
    if body.segment:
        edge_ids = g.segment_edges(body.segment)
        if not edge_ids:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such segment")
    else:
        edge_ids = sorted(set(body.edge_ids or []))
        if any(e not in g.edges for e in edge_ids):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such edge")
    if all(g.edges[e].closed for e in edge_ids):
        raise HTTPException(status.HTTP_409_CONFLICT, "Already closed")
    if body.segment and conn.execute(
        "SELECT 1 FROM wf_closures WHERE building_id = %s AND segment = %s AND reopened_at IS NULL",
        (b["id"], body.segment),
    ).fetchone():
        raise HTTPException(status.HTTP_409_CONFLICT, "Already closed")
    closure_id = conn.execute(
        """
        INSERT INTO wf_closures (building_id, segment, edge_ids, reason, closed_by)
        VALUES (%s, %s, %s::uuid[], %s, %s) RETURNING id::text
        """,
        (b["id"], body.segment, edge_ids, body.reason, user.id),
    ).fetchone()["id"]
    conn.execute(
        """
        UPDATE wf_edges SET closed = true, closed_reason = %s, closed_at = now()
        WHERE id = ANY(%s::uuid[]) AND NOT closed
        """,
        (body.reason, edge_ids),
    )
    audit.record(conn, action="wayfinding_closure_opened", entity_type="wf_closure", entity_id=closure_id,
                 actor=user, detail={"segment": body.segment, "edges": len(edge_ids), "reason": body.reason})
    return next(c for c in closures_view(conn, b["id"]) if c["id"] == closure_id)


@router.post("/closures/{closure_id}/reopen")
def reopen(closure_id: str, conn: DbConn, user: StaffOrAdmin) -> dict:
    b = building_for(conn, user)
    row = conn.execute(
        """
        SELECT id::text, segment, edge_ids::text[] AS edge_ids, reopened_at FROM wf_closures
        WHERE id::text = %s AND building_id = %s FOR UPDATE
        """,
        (closure_id if _UUID.match(closure_id or "") else None, b["id"]),
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Closure not found")
    if row["reopened_at"] is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already reopened")
    conn.execute("UPDATE wf_closures SET reopened_at = clock_timestamp(), reopened_by = %s WHERE id = %s",
                 (user.id, closure_id))
    # An edge stays closed while another active closure still covers it.
    conn.execute(
        """
        UPDATE wf_edges e SET
            closed = other.reason IS NOT NULL,
            closed_reason = other.reason,
            closed_at = CASE WHEN other.reason IS NULL THEN NULL ELSE e.closed_at END
        FROM (
            SELECT eid, (SELECT c.reason FROM wf_closures c
                         WHERE c.reopened_at IS NULL AND eid = ANY(c.edge_ids)
                         ORDER BY c.closed_at DESC LIMIT 1) AS reason
            FROM unnest(%s::uuid[]) AS eid
        ) other
        WHERE e.id = other.eid
        """,
        (row["edge_ids"],),
    )
    audit.record(conn, action="wayfinding_closure_reopened", entity_type="wf_closure", entity_id=closure_id,
                 actor=user, detail={"segment": row["segment"], "edges": len(row["edge_ids"])})
    return next(c for c in closures_view(conn, b["id"]) if c["id"] == closure_id)
