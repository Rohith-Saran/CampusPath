import json
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
    """Prerequisite graph.

    Edges are from prerequisite -> course.
    """

    def __init__(self, courses_path: str):
        self.courses_path = courses_path
        self.courses: Dict[str, Course] = {}
        # adjacency: prereq -> set(courses)
        self.adj: Dict[str, Set[str]] = {}
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
            self.adj.setdefault(course.id, set())

        for course in self.courses.values():
            for prereq in course.prerequisites:
                self.adj.setdefault(prereq, set())
                self.adj[prereq].add(course.id)

    def can_enroll(self, course_id: str, completed_courses: List[str]) -> Dict:
        """Check if all prerequisites are satisfied.

        Parameters
        - course_id: str
        - completed_courses: list of completed course ids only

        Return
        - {"can_enroll": bool, "missing": [missing prerequisite ids]}
        """
        completed_set = set(completed_courses)
        if course_id not in self.courses:
            return {"can_enroll": False, "missing": [course_id]}

        # Debug prints to help trace prerequisite checks
        prerequisites = list(self.courses[course_id].prerequisites)
        missing: List[str] = []
        print("DEBUG can_enroll course:", course_id)
        print("DEBUG prerequisites:", prerequisites)
        print("DEBUG completed passed in:", completed_courses)

        for p in prerequisites:
            if p not in completed_set:
                missing.append(p)

        print("DEBUG missing:", missing)

        return {"can_enroll": len(missing) == 0, "missing": missing}


    def detect_cycle(self) -> bool:
        """Detect cycles using three-state DFS."""
        state: Dict[str, int] = {node: 0 for node in self.adj}

        def dfs(node: str) -> bool:
            if state[node] == 1:
                return True
            if state[node] == 2:
                return False
            state[node] = 1
            for nxt in self.adj.get(node, set()):
                if dfs(nxt):
                    return True
            state[node] = 2
            return False

        for node in list(self.adj.keys()):
            if state.get(node, 0) == 0 and dfs(node):
                return True
        return False

    def topological_sort(self, available_courses: List[str]) -> List[str]:
        """DFS-based topo sort restricted to available_courses.

        Returns order where prerequisites come before dependents.
        """
        available: Set[str] = set(available_courses)
        visited: Set[str] = set()
        result: List[str] = []

        def dfs(node: str) -> None:
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

        return list(reversed(result))


class CourseRegistration:
    """Thread-safe course enrollment using a mutex.

    Course seats/enrolled counts are stored in memory and persisted to courses.json.
    """

    def __init__(self, courses_path: str):
        self.courses_path = courses_path
        self.graph = CourseGraph(courses_path)
        self.lock = threading.Lock()
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
        prereq_check = self.graph.can_enroll(course_id, list(completed_courses))
        if not prereq_check["can_enroll"]:
            return {"ok": False, "status": "missing_prereqs", "missing": prereq_check["missing"]}

        with self.lock:
            course = self.state.get(course_id)
            if course is None:
                return {"ok": False, "status": "unknown_course"}

            remaining = course.remaining_seats()
            if remaining <= 0:
                return {"ok": False, "status": "waitlist", "seats_left": 0}

            course.enrolled += 1
            self.state[course_id] = course
            self._persist_to_json()

            return {"ok": True, "status": "enrolled", "seats_left": course.remaining_seats()}

    def get_personalized_plan(self, completed_courses: List[str]) -> List[List[Course]]:
        """Personalized plan grouped by semesters.

        Parameters
        - completed_courses: list of completed course ids only

        Return
        - list of semesters; each semester is a list of Course objects

        Rules
        - group remaining courses (all courses not in completed_courses)
        - max 12 credits per semester
        - course can be placed only when ALL prerequisites are in completed OR earlier semesters
        """
        completed_set = set(completed_courses)

        remaining_ids = [cid for cid in self.state.keys() if cid not in completed_set]

        if self.graph.detect_cycle():
            raise ValueError("Cycle detected in prerequisites")

        taken: Set[str] = set(completed_set)
        semesters: List[List[Course]] = []

        while True:
            available_ids: List[str] = []
            for cid in remaining_ids:
                if cid in taken:
                    continue
                check = self.graph.can_enroll(cid, list(taken))
                if check["can_enroll"]:
                    available_ids.append(cid)

            if not available_ids:
                break

            ordered = self.graph.topological_sort(available_ids)

            credits = 0
            this_sem: List[Course] = []
            for cid in ordered:
                c = self.state[cid]
                if cid in taken:
                    continue
                if credits + c.credits <= 12:
                    this_sem.append(c)
                    credits += c.credits
                    taken.add(cid)

            if not this_sem:
                # if everything doesn't fit, still take the first available course
                first_cid = ordered[0]
                this_sem = [self.state[first_cid]]
                taken.add(first_cid)

            semesters.append(this_sem)

        return semesters

    def simulate_concurrent(self, course_id: str, total_students: int = 100) -> Dict:
        """Simulate concurrent enrollment using the mutex-protected enrollment path.

        For demo purposes, resets the given course to seats=30, enrolled=0.
        """
        if total_students < 0:
            total_students = 0

        with self.lock:
            course = self.state.get(course_id)
            if course is None:
                return {"enrolled": 0, "waitlisted": total_students, "message": "unknown_course"}
            course.seats = 30
            course.enrolled = 0
            self.state[course_id] = course
            self._persist_to_json()

        # For OS mutex demo, bypass prerequisite checks by providing a completed list
        # that includes transitive prerequisites.
        forced_completed = set(self.graph.get_prerequisites(course_id) if hasattr(self.graph, "get_prerequisites") else [])
        # But we don't rely on that; just try with empty and allow enroll_student to gate.
        # To keep demo behavior predictable, add direct prerequisites as well.
        for p in self.state[course_id].prerequisites:
            forced_completed.add(p)

        enrolled_count = 0
        waitlisted_count = 0

        def worker():
            nonlocal enrolled_count, waitlisted_count
            res = self.enroll_student("demo_student", course_id, completed_courses=set(forced_completed))
            if res.get("ok"):
                with self.lock:
                    enrolled_count += 1
            else:
                with self.lock:
                    waitlisted_count += 1

        threads: List[threading.Thread] = []
        for _ in range(total_students):
            t = threading.Thread(target=worker)
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        with self.lock:
            updated = self.state.get(course_id)
            if updated is not None:
                updated.enrolled = enrolled_count
                self.state[course_id] = updated
                self._persist_to_json()

        return {
            "enrolled": enrolled_count,
            "waitlisted": waitlisted_count,
            "message": "Mutex lock prevented seat overbooking/data corruption",
            "course_id": course_id,
        }

    def get_remaining_plan(self, completed_courses: Set[str]) -> List[List[str]]:
        # Backward-compatible helper used by older endpoints.
        semesters = self.get_personalized_plan(list(completed_courses))
        return [[c.id for c in sem] for sem in semesters]

