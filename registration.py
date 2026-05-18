import json
import os
import threading
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple


@dataclass
class Course:
    id: str
    name: str
    credits: int
    prerequisites: List[str]
    seats: int
    enrolled: int

    def remaining_seats(self) -> int:
        return self.seats - self.enrolled


class CourseGraph:
    """Directed graph to model course prerequisites.

    Edges are from prerequisites -> course.

    Topological Sort notes (DFS-based):
    - We visit prerequisites first (post-order) and then reverse the result.
    - A DFS back-edge indicates a cycle (impossible curriculum).

    Decrease-and-conquer idea:
    - A topo order repeatedly places nodes whose prerequisites are satisfied.
    - DFS approach computes an order consistent with dependency constraints.
    """

    def __init__(self, courses_path: str):
        self.courses_path = courses_path
        self.courses: Dict[str, Course] = {}
        self.adj: Dict[str, Set[str]] = {}  # prerequisite -> set(courses)
        self._load()

    def _load(self) -> None:
        with open(self.courses_path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        self.courses = {}
        self.adj = {}

        for c in payload.get("courses", []):
            course = Course(
                id=c["id"],
                name=c["name"],
                credits=int(c["credits"]),
                prerequisites=list(c.get("prerequisites", [])),
                seats=int(c["seats"]),
                enrolled=int(c.get("enrolled", 0)),
            )
            self.courses[course.id] = course
            if course.id not in self.adj:
                self.adj[course.id] = set()

        # Build adjacency list: prereq -> courses that depend on it
        for course in self.courses.values():
            self.adj.setdefault(course.id, set())
            for prereq in course.prerequisites:
                self.adj.setdefault(prereq, set())
                self.adj[prereq].add(course.id)

    def get_prerequisites(self, course_id: str) -> List[str]:
        """Return all prerequisites recursively for a course (transitive closure)."""
        if course_id not in self.courses:
            return []

        # Since edges are prereq -> course, we need reverse edges for traversal.
        reverse: Dict[str, Set[str]] = {}
        for cid, course in self.courses.items():
            reverse.setdefault(cid, set())
            for p in course.prerequisites:
                reverse.setdefault(cid, set()).add(p)

        seen: Set[str] = set()
        stack = list(self.courses[course_id].prerequisites)
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            for p in self.courses.get(node, Course(node, "", 0, [], 0, 0)).prerequisites:
                if p not in seen:
                    stack.append(p)
        return list(seen)

    def detect_cycle(self) -> bool:
        """Detect cycles using three-state DFS."""
        state: Dict[str, int] = {node: 0 for node in self.adj}

        def dfs(node: str) -> bool:
            if state[node] == 1:
                return True
            if state[node] == 2:
                return False
            state[node] = 1
            for nxt in self.adj.get(node, []):
                if dfs(nxt):
                    return True
            state[node] = 2
            return False

        for node in list(self.adj.keys()):
            if state.get(node, 0) == 0:
                if dfs(node):
                    return True
        return False

    def topological_sort(self, available_courses: List[str]) -> List[str]:
        """Run DFS-based topological sort restricted to available_courses.

        Returns an order where each course appears after its prerequisites.
        """
        available: Set[str] = set(available_courses)

        # Build dependency edges inside available set using prerequisite->course adjacency.
        # For DFS visitation, we need to walk from node to its dependent courses.
        # We then reverse at the end to ensure dependencies come first.
        visited: Set[str] = set()
        result: List[str] = []

        def dfs(node: str):
            if node in visited:
                return
            visited.add(node)
            for dependent in self.adj.get(node, set()):
                if dependent in available:
                    dfs(dependent)
            result.append(node)

        for node in list(available):
            if node not in visited:
                dfs(node)

        # reverse so prerequisites appear before dependents (because we appended after exploring dependents)
        return list(reversed(result))

    def can_enroll(self, course_id: str, completed_courses: Set[str]) -> Tuple[bool, List[str]]:
        """Check if all prerequisites are satisfied for a course."""
        if course_id not in self.courses:
            return False, [course_id]
        missing: List[str] = []
        for p in self.courses[course_id].prerequisites:
            if p not in completed_courses:
                missing.append(p)
        return (len(missing) == 0), missing


class CourseRegistration:
    """Thread-safe course enrollment using a mutex.

    Mutex lock purpose:
    - Multiple concurrent enrollments may try to decrement the same
      seats counter. Without a lock, seats can go negative or enrolled
      counts can become inconsistent.
    """

    def __init__(self, courses_path: str):
        self.courses_path = courses_path
        self.graph = CourseGraph(courses_path)
        self.lock = threading.Lock()

        # Keep a local mutable snapshot of seats/enrolled to simulate DB in-memory.
        # We'll also persist back to JSON so the UI can show updated seats.
        self._sync_from_json()

    def _sync_from_json(self) -> None:
        with open(self.courses_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        self.state: Dict[str, Course] = {}
        for c in payload.get("courses", []):
            course = Course(
                id=c["id"],
                name=c["name"],
                credits=int(c["credits"]),
                prerequisites=list(c.get("prerequisites", [])),
                seats=int(c["seats"]),
                enrolled=int(c.get("enrolled", 0)),
            )
            self.state[course.id] = course

    def _persist_to_json(self) -> None:
        payload = {"courses": []}
        for cid in sorted(self.state.keys()):
            c = self.state[cid]
            payload["courses"].append(
                {
                    "id": c.id,
                    "name": c.name,
                    "credits": c.credits,
                    "prerequisites": c.prerequisites,
                    "seats": c.seats,
                    "enrolled": c.enrolled,
                }
            )
        with open(self.courses_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def get_course(self, course_id: str) -> Course:
        return self.state[course_id]

    def get_all_courses(self) -> List[Course]:
        return [self.state[cid] for cid in sorted(self.state.keys())]

    def enroll_student(self, student_id: str, course_id: str, completed_courses: Set[str]) -> Dict:
        """Enroll a student if prerequisites are met and seats are available."""
        can, missing = self.graph.can_enroll(course_id, completed_courses)
        if not can:
            return {"ok": False, "status": "missing_prereqs", "missing": missing}

        # critical section
        acquired = False
        try:
            self.lock.acquire()
            acquired = True

            course = self.state.get(course_id)
            if course is None:
                return {"ok": False, "status": "unknown_course"}

            remaining = course.remaining_seats()
            if remaining <= 0:
                return {"ok": False, "status": "waitlist", "seats_left": 0}

            course.enrolled += 1
            self.state[course_id] = course
            self._persist_to_json()

            return {
                "ok": True,
                "status": "enrolled",
                "seats_left": course.remaining_seats(),
            }
        finally:
            if acquired:
                self.lock.release()

    def get_remaining_plan(self, completed_courses: Set[str]) -> List[List[str]]:
        """Personalized remaining plan grouped by semester.

        Rules:
        - Consider only remaining courses.
        - Each semester max 12 credits.
        - A course can be taken in a semester if all prerequisites are already
          satisfied by completed_courses or earlier semesters.
        """
        remaining = [cid for cid in self.state.keys() if cid not in completed_courses]

        # If there is a cycle anywhere, we cannot compute a plan.
        if self.graph.detect_cycle():
            raise ValueError("Cycle detected in prerequisites")

        taken: Set[str] = set(completed_courses)
        semesters: List[List[str]] = []

        while True:
            # Find courses whose prerequisites are already satisfied.
            available: List[str] = []
            for cid in remaining:
                if cid in taken:
                    continue
                can, _missing = self.graph.can_enroll(cid, taken)
                if can:
                    available.append(cid)

            if not available:
                break

            # Order available courses using topo sort limited to available.
            ordered = self.graph.topological_sort(available)

            credits = 0
            this_sem: List[str] = []
            for cid in ordered:
                c = self.state[cid]
                if cid in taken:
                    continue
                if credits + c.credits <= 12:
                    this_sem.append(cid)
                    credits += c.credits
                    taken.add(cid)

            if not this_sem:
                # Remaining courses can't fit under the 12-credit cap.
                # Force-progress by taking at least the first course.
                first = ordered[0]
                this_sem = [first]
                taken.add(first)

            semesters.append(this_sem)

        return semesters

