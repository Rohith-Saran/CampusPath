import os
import subprocess
from typing import Dict, List, Set

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

from registration import CourseRegistration


app = Flask(__name__)

# In-memory user storage (no database needed)
# user_id -> {full_name, student_id, email, password, completed_courses: set, enrolled_courses: set}
USERS: Dict[str, Dict] = {}

# alias used by debug prints in issue investigation
student_data = {}

app.secret_key = "campuspath-secret-key-change-me"  # use env var in real deployments

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COURSES_PATH = os.path.join(BASE_DIR, "courses.json")

registration = CourseRegistration(COURSES_PATH)


def current_user() -> Dict:
    uid = session.get("student_id")
    if uid:
        return USERS.get(uid, {})
    # fallback to email-keyed lookup for sessions that store email
    email = session.get("email")
    if email:
        return student_data.get(email, {})
    return {}


def require_login() -> bool:
    return bool(current_user())


@app.route("/")
def root():
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        matched = None
        matched_uid = None
        for uid, u in USERS.items():
            if u.get("email") == email and u.get("password") == password:
                matched = u
                matched_uid = uid
                break

        if not matched:
            return render_template("login.html", error="Invalid credentials")

        session["student_id"] = matched_uid
        # keep an email key for compatibility with some debug paths
        session["email"] = matched.get("email")
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

        for u in USERS.values():
            if u.get("email") == email:
                return render_template("signup.html", error="Email already registered")

        user = {
            "full_name": full_name,
            "student_id": student_id,
            "email": email,
            "password": password,
            "completed_courses": set(),
            "enrolled_courses": set(),
        }
        USERS[student_id] = user
        # also keep an email-keyed mapping for compatibility with debug/legacy paths
        student_data[email] = user

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

    # Personalized plan (using course objects is fine for UI; we only display IDs)
    plan_course_objects = registration.get_personalized_plan(list(completed))
    plan: List[List[str]] = [[c.id for c in sem] for sem in plan_course_objects]

    next_takes: List[str] = []
    for sem in plan:
        for cid in sem:
            next_takes.append(cid)
        break

    prereq_info = _build_course_prereq_view(completed, next_takes, enrolled)

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
        prereq_info=prereq_info,
    )


def _build_course_prereq_view(completed: Set[str], next_courses: List[str], enrolled: Set[str]):
    view = []
    for cid in next_courses:
        can = registration.graph.can_enroll(cid, list(completed))
        view.append({"id": cid, "ok": can["can_enroll"], "missing": can["missing"], "enrolled": cid in enrolled})
    return view


@app.route("/courses")
def courses_page():
    if not require_login():
        return redirect(url_for("login"))

    user = current_user()
    completed: Set[str] = set(user.get("completed_courses", set()))
    enrolled: Set[str] = set(user.get("enrolled_courses", set()))

    rendered = []
    for c in registration.get_all_courses():
        if c.id in completed:
            status = "Completed"
        elif c.id in enrolled:
            status = "Enrolled"
        else:
            check = registration.graph.can_enroll(c.id, list(completed))
            status = "Available" if check["can_enroll"] else "Locked"

        # For UI prerequisites list
        rendered.append(
            {
                "id": c.id,
                "name": c.name,
                "credits": c.credits,
                "prerequisites": c.prerequisites,
                "seats_left": c.remaining_seats(),
                "status": status,
                "can_enroll": status == "Available",
                "missing": registration.graph.can_enroll(c.id, list(completed))["missing"],
            }
        )

    return render_template("courses.html", user=user, courses=rendered)


@app.route("/enroll", methods=["POST"])
def enroll():
    if not require_login():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    user = current_user()
    data = request.get_json(force=True)
    course_id = data.get("course_id")
    if not course_id:
        return jsonify({"ok": False, "error": "missing_course_id"}), 400
    # derive student_id from user record or session (be tolerant to different session keys)
    student_id = user.get("student_id") or session.get("student_id") or user.get("email")
    completed: Set[str] = set(user.get("completed_courses", set()))

    res = registration.enroll_student(student_id, course_id, completed)
    if res.get("ok"):
        user["enrolled_courses"].add(course_id)

    return jsonify(res)


@app.route("/status", methods=["GET"])
def status():
    """Return course statuses for the logged-in student."""
    if not require_login():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    user = current_user()

    # Debug statements to verify completion unlock logic
    # Exact debug statements requested for investigation
    email = session.get('email') or session.get('user')
    print("DEBUG email:", email)
    print("DEBUG student_data keys:", list(student_data.keys()))
    print("DEBUG student record:", student_data.get(email))
    # Also show CS201 prereqs loaded from JSON
    try:
        print("DEBUG CS201 prereqs from json:", registration.graph.courses.get("CS201").prerequisites)
    except Exception:
        print("DEBUG CS201 prereqs from json: <missing or load error>")
    completed: Set[str] = set(user.get("completed_courses", set()))
    enrolled: Set[str] = set(user.get("enrolled_courses", set()))
    waitlisted: Set[str] = set()  # this app does not persist waitlist items separately

    courses_payload = []

    all_courses = registration.get_all_courses()
    for c in all_courses:
        course_id = c.id

        if course_id in completed:
            status_str = "completed"
            missing = []
        elif course_id in enrolled:
            status_str = "enrolled"
            missing = []
        elif course_id in waitlisted:
            status_str = "waitlisted"
            missing = []
        else:
            check = registration.graph.can_enroll(course_id, list(completed))
            if check["can_enroll"]:
                status_str = "available"
                missing = []
            else:
                status_str = "locked"
                missing = check["missing"]

        courses_payload.append(
            {
                "id": course_id,
                "status": status_str,
                "seats": c.seats,
                "missing": missing,
            }
        )

    return jsonify({"ok": True, "courses": courses_payload})


@app.route("/complete", methods=["POST"])
def complete_course():
    if not require_login():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    user = current_user()
    data = request.get_json(force=True)
    course_id = data.get("course_id")
    if not course_id:
        return jsonify({"ok": False, "error": "missing_course_id"}), 400

    completed_courses: Set[str] = set(user.get("completed_courses", set()))
    enrolled_courses: Set[str] = set(user.get("enrolled_courses", set()))

    if course_id not in enrolled_courses:
        return jsonify({"ok": False, "error": "not_enrolled"}), 400

    # Update user's lists
    enrolled_courses.remove(course_id)
    completed_courses.add(course_id)
    user["completed_courses"] = completed_courses
    user["enrolled_courses"] = enrolled_courses

    # Update plan (side effect-free for demo UI; but required by prompt)
    _ = registration.get_personalized_plan(list(completed_courses))

    return jsonify(
        {
            "success": True,
            "completed": sorted(list(completed_courses)),
            "enrolled": sorted(list(enrolled_courses)),
            "message": f"Course {course_id} marked complete",
        }
    )


@app.route("/cpp-demo")
def cpp_demo():
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    cpp_path = os.path.join(repo_dir, "mutex_demo.cpp")

    try:
        with open(cpp_path, "r", encoding="utf-8") as f:
            cpp_code = f.read()
    except Exception as e:
        return render_template(
            "cpp_demo.html",
            without_lock_output="",
            with_lock_output="",
            cpp_code="",
            error=True,
            error_message=f"Failed to read mutex_demo.cpp: {e}",
        )

    compile_cmd = ["g++", "-std=c++17", "-pthread", "mutex_demo.cpp", "-o", "mutex_demo"]
    try:
        compile_proc = subprocess.run(
            compile_cmd,
            cwd=repo_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if compile_proc.returncode != 0:
            return render_template(
                "cpp_demo.html",
                without_lock_output="",
                with_lock_output="",
                cpp_code=cpp_code,
                error=True,
                error_message=compile_proc.stdout.strip() or "Compilation failed",
            )

        run_proc = subprocess.run(
            [os.path.join(repo_dir, "mutex_demo")],
            cwd=repo_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

        output = run_proc.stdout

        marker = "=== WITH MUTEX LOCK ==="
        if marker not in output:
            return render_template(
                "cpp_demo.html",
                without_lock_output=output,
                with_lock_output="",
                cpp_code=cpp_code,
                error=True,
                error_message="Unexpected output format: missing separator '=== WITH MUTEX LOCK ==='",
            )

        before, after = output.split(marker, 1)
        without_lock_output = before.strip()
        with_lock_output = after.strip()

        return render_template(
            "cpp_demo.html",
            without_lock_output=without_lock_output,
            with_lock_output=with_lock_output,
            cpp_code=cpp_code,
            error=False,
            error_message="",
        )

    except Exception as e:
        return render_template(
            "cpp_demo.html",
            without_lock_output="",
            with_lock_output="",
            cpp_code=cpp_code,
            error=True,
            error_message=str(e),
        )


if __name__ == "__main__":
    app.run(debug=True, port=5000)

