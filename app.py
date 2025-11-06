import os
from functools import wraps
from datetime import date, datetime

from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key_123")


# create instance folder if missing
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
os.makedirs(INSTANCE_DIR, exist_ok=True)

# database path
db_path = os.path.join(INSTANCE_DIR, "user_auth.db")
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# --- Database Models ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    attempts = db.relationship("Attempt", backref="user", lazy=True)

class Attempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    site_name = db.Column(db.String(200), nullable=False)
    roast_given = db.Column(db.String(500))
    task_entered = db.Column(db.String(500))
    timestamp = db.Column(db.DateTime, default=db.func.now(), nullable=False)

# --- Decorator ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("You must be logged in to access this page.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# --- CLI Command ---
@app.cli.command("init-db")
def init_db_command():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username="testuser").first():
            db.session.add(User(username="testuser", password=generate_password_hash("password123")))
        if not User.query.filter_by(username="admin").first():
            db.session.add(User(username="admin", password=generate_password_hash("admin")))
        db.session.commit()
        print("Database initialized with sample users.")

# --- Routes ---
@app.route("/")
def index():
    return redirect(url_for("dashboard")) if "user_id" in session else redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if not username or not password:
            flash("Username and password are required.", "error")
            return redirect(url_for("register"))

        if User.query.filter_by(username=username).first():
            flash("That username is already taken.", "error")
            return redirect(url_for("register"))

        new_user = User(username=username, password=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session["user_id"] = user.id
            session["username"] = user.username
            flash("Login successful!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password.", "error")
            return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    # fetch all attempts for this user
    attempts = Attempt.query.filter_by(
        user_id=session["user_id"]
    ).order_by(Attempt.timestamp.desc()).all()

    # count scrolls per site for the chart
    site_counts = {}
    for a in attempts:
        if a.site_name:
            site_counts[a.site_name] = site_counts.get(a.site_name, 0) + 1

    labels = list(site_counts.keys()) or ["No Data"]
    values = list(site_counts.values()) or [0]

    # streak logic
    unique_days = {a.timestamp.date() for a in attempts}
    streak = 0
    if unique_days:
        today = date.today()
        current_day = today
        if current_day in unique_days:
            streak += 1
            current_day = date.fromordinal(current_day.toordinal() - 1)
        while current_day in unique_days:
            streak += 1
            current_day = date.fromordinal(current_day.toordinal() - 1)
            if streak > 730:
                break

    # focus timer logic
    session_time = session.get("last_scroll_time")
    if session_time:
        last_focus_start = datetime.fromisoformat(session_time)
    else:
        last_attempt = Attempt.query.filter_by(
            user_id=session["user_id"]
        ).order_by(Attempt.timestamp.desc()).first()
        last_focus_start = last_attempt.timestamp if last_attempt else None

    if last_focus_start:
        now = datetime.utcnow()
        focus_seconds = int((now - last_focus_start).total_seconds())
    else:
        focus_seconds = 0

    return render_template(
        "dashboard.html",
        attempts=attempts,
        username=session.get("username"),
        labels=labels,
        values=values,
        streak=streak,
        focus_seconds=focus_seconds,
    )

@app.route("/block/<site_name>", methods=["GET", "POST"])
@login_required
def block(site_name):
    roast_line = "you think your goals finish themselves while you doom scroll?"
    if request.method == "POST":
        task = request.form["task"]
        attempt = Attempt(
            user_id=session["user_id"],
            site_name=site_name,
            roast_given=roast_line,
            task_entered=task,
        )
        db.session.add(attempt)
        db.session.commit()
        session["last_scroll_time"] = datetime.utcnow().isoformat()
        return redirect(url_for("dashboard"))
    return render_template("block.html", roast=roast_line, site_name=site_name)

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))

# --- Run ---
if __name__ == "__main__":
    with app.app_context():
        db.create_all()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
