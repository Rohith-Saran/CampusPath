import os
from typing import Dict, List, Set

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from registration import CourseRegistration

app = Flask(__name__)

app.secret_key = "campuspath-secret-key-change-me"  # use env var in real deployments

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COURSES_PATH = os.path.join(BASE_DIR, "courses.json")

# In-memory user storage (no database needed)
# user_id -> {full_name, student_id, email, password, completed_courses: set, enrolled_courses: set}
USERS: Dict[str, Dict] = {}

registration = CourseRegistration(COURSES_PATH)


def current_user() -> Dict:
    uid = session.get("student_id")
    if not uid:
        return {}
    return USERS.get(uid, {})


def require_login():
    if not session.get("student_id"):
        return False
    return True


@app.route("/")
def root():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        # Find matching user by email
        matched = None
        for uid, u in USERS.items():
            if u.get("email") == email and u.get("password") == password:
                matched = u
                matched_uid = uid
                break

        if not matched:
            return render_template("login.html", error="Invalid credentials")

        session["student_id"] = matched_uid
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        student_id = request.form.get("student_id", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        if not full_name or not student_id or not email or not password:
            return render_template("signup.html", error="All fields are required")

        if student_id in USERS:
            return render_template("signup.html", error="Student ID already exists")

        # Basic collision check on email
        for u in USERS.values():
            if u.get("email") == email:
                return render_template("signup.html", error="Email already registered")

        USERS[student_id] = {
            "full_name": full_name,
            "student_id": student_id,
            "email": email,
            "password": password,
            "completed_courses": set(),
            "enrolled_courses": set(),
        }

        return redirect(url_for("login"))

    return render_template("signup.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    if not require_login():
        return redirect(url_for("login"))

    user = current_user()
    completed: Set[str] = set(user.get("completed_courses", set()))
    enrolled: Set[str] = set(user.get("enrolled_courses", set()))

    all_courses = registration.get_all_courses()
    remaining_courses = [c for c in all_courses if c.id not in completed]

    # Personalized remaining plan
    plan = registration.get_remaining_plan(completed)
    # Flatten for easier checks
    next_takes = []
    for sem in plan:
        for cid in sem:
            next_takes.append(cid)
        break

    return render_template(
        "dashboard.html",
        user=user,
        total_courses=len(all_courses),
        completed_count=len(completed),
        remaining_count=len(remaining_courses),
        plan=plan,
        completed_courses=sorted(completed),
        next_courses=next_takes,
        enrolled_courses=sorted(enrolled),
        prereq_info=_build_course_prereq_view(completed, next_takes, enrolled),
    )


def _build_course_prereq_view(completed: Set[str], next_courses: List[str], enrolled: Set[str]):
    # For the dashboard: show which next courses are truly available now vs locked.
    view = []
    for cid in next_courses:
        ok, missing = registration.graph.can_enroll(cid, completed)
        view.append({"id": cid, "ok": ok, "missing": missing, "enrolled": cid in enrolled})
    return view


@app.route("/courses")
def courses_page():
    if not require_login():
        return redirect(url_for("login"))

    user = current_user()
    completed: Set[str] = set(user.get("completed_courses", set()))
    enrolled: Set[str] = set(user.get("enrolled_courses", set()))

    courses = registration.get_all_courses()

    rendered = []
    for c in courses:
        if c.id in completed:
            status = "Completed"
        elif c.id in enrolled:
            status = "Enrolled"
        else:
            ok, _missing = registration.graph.can_enroll(c.id, completed)
            status = "Available" if ok else "Locked"
        ok, missing = registration.graph.can_enroll(c.id, completed)
        rendered.append({
            "id": c.id,
            "name": c.name,
            "credits": c.credits,
            "prerequisites": c.prerequisites,
            "seats_left": c.remaining_seats(),
            "status": status,
            "can_enroll": ok,
            "missing": missing,
        })

    return render_template("courses.html", user=user, courses=rendered)


@app.route("/enroll", methods=["POST"])
def enroll():
    if not require_login():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    user = current_user()
    student_id = user["student_id"]

    data = request.get_json(force=True)
    course_id = data.get("course_id")

    completed: Set[str] = set(user.get("completed_courses", set()))

    res = registration.enroll_student(student_id, course_id, completed)
    if res.get("ok"):
        user["enrolled_courses"].add(course_id)

    return jsonify(res)


@app.route("/plan")
def plan_json():
    if not require_login():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    user = current_user()
    completed: Set[str] = set(user.get("completed_courses", set()))
    plan = registration.get_remaining_plan(completed)
    return jsonify({"plan": plan})


if __name__ == "__main__":
    app.run(debug=True, port=5000)

