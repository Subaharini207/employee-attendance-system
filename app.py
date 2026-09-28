from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from datetime import datetime
from pathlib import Path

app = Flask(__name__)
app.secret_key = "attendance-demo-secret"
DB = Path(__file__).with_name("attendance.db")

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS employees(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        department TEXT NOT NULL,
        designation TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        joining_date TEXT
    );
    CREATE TABLE IF NOT EXISTS attendance(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id TEXT NOT NULL,
        date TEXT NOT NULL,
        check_in TEXT,
        check_out TEXT,
        hours REAL DEFAULT 0,
        status TEXT DEFAULT 'Present',
        UNIQUE(emp_id,date)
    );
    CREATE TABLE IF NOT EXISTS leaves(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        emp_id TEXT NOT NULL,
        leave_type TEXT NOT NULL,
        from_date TEXT NOT NULL,
        to_date TEXT NOT NULL,
        reason TEXT,
        status TEXT DEFAULT 'Pending'
    );
    """)
    con.commit()
    con.close()

def stats():
    con = db()
    today = datetime.now().strftime("%Y-%m-%d")
    total = con.execute("SELECT COUNT(*) c FROM employees").fetchone()["c"]
    present = con.execute("SELECT COUNT(*) c FROM attendance WHERE date=? AND status='Present'", (today,)).fetchone()["c"]
    leave = con.execute("SELECT COUNT(*) c FROM leaves WHERE from_date<=? AND to_date>=? AND status='Approved'", (today,today)).fetchone()["c"]
    late = con.execute("SELECT COUNT(*) c FROM attendance WHERE date=? AND check_in > '09:15'", (today,)).fetchone()["c"]
    con.close()
    return {"total":total, "present":present, "absent":max(total-present-leave,0), "leave":leave, "late":late}

@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == "admin" and request.form.get("password") == "admin123":
            session["user"] = "admin"
            return redirect(url_for("dashboard"))
        flash("Invalid login. Use admin / admin123.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

def protected():
    return "user" in session

@app.route("/dashboard")
def dashboard():
    if not protected(): return redirect(url_for("login"))
    con=db()
    recent=con.execute("""SELECT a.*, e.name, e.department FROM attendance a
                          LEFT JOIN employees e ON e.emp_id=a.emp_id
                          ORDER BY a.id DESC LIMIT 8""").fetchall()
    con.close()
    return render_template("dashboard.html", s=stats(), recent=recent)

@app.route("/employees")
def employees():
    if not protected(): return redirect(url_for("login"))
    con=db(); rows=con.execute("SELECT * FROM employees ORDER BY id DESC").fetchall(); con.close()
    return render_template("employees.html", employees=rows)

@app.route("/employees/add", methods=["POST"])
def add_employee():
    if not protected(): return redirect(url_for("login"))
    try:
        con=db()
        con.execute("""INSERT INTO employees(emp_id,name,department,designation,email,phone,joining_date)
                       VALUES(?,?,?,?,?,?,?)""",
                    tuple(request.form.get(x) for x in ["emp_id","name","department","designation","email","phone","joining_date"]))
        con.commit(); con.close()
        flash("Employee added successfully.")
    except sqlite3.IntegrityError:
        flash("Employee ID already exists.")
    return redirect(url_for("employees"))

@app.route("/employees/delete/<int:eid>", methods=["POST"])
def delete_employee(eid):
    if not protected(): return redirect(url_for("login"))
    con=db(); con.execute("DELETE FROM employees WHERE id=?", (eid,)); con.commit(); con.close()
    flash("Employee deleted.")
    return redirect(url_for("employees"))

@app.route("/attendance")
def attendance():
    if not protected(): return redirect(url_for("login"))
    con=db()
    employees=con.execute("SELECT * FROM employees ORDER BY name").fetchall()
    rows=con.execute("""SELECT a.*,e.name,e.department FROM attendance a
                        LEFT JOIN employees e ON e.emp_id=a.emp_id ORDER BY a.date DESC,a.id DESC""").fetchall()
    con.close()
    return render_template("attendance.html", employees=employees, rows=rows)

@app.route("/attendance/checkin", methods=["POST"])
def checkin():
    if not protected(): return redirect(url_for("login"))
    emp=request.form.get("emp_id"); now=datetime.now(); date=now.strftime("%Y-%m-%d")
    con=db()
    try:
        con.execute("INSERT INTO attendance(emp_id,date,check_in,status) VALUES(?,?,?,?)",
                    (emp,date,now.strftime("%H:%M:%S"),"Present"))
        con.commit(); flash("Check-in recorded.")
    except sqlite3.IntegrityError:
        flash("This employee already has attendance for today.")
    con.close(); return redirect(url_for("attendance"))

@app.route("/attendance/checkout/<int:aid>", methods=["POST"])
def checkout(aid):
    if not protected():
        return redirect(url_for("login"))

    con = db()
    row = con.execute(
        "SELECT * FROM attendance WHERE id=?",
        (aid,)
    ).fetchone()

    if row and row["check_in"] and not row["check_out"]:
        check_in_time = datetime.strptime(
            row["check_in"], "%H:%M:%S"
        ).time()

        start = datetime.combine(
            datetime.now().date(),
            check_in_time
        )

        end = datetime.now()
        hours = round((end - start).total_seconds() / 3600, 2)

        con.execute(
            "UPDATE attendance SET check_out=?,hours=? WHERE id=?",
            (end.strftime("%H:%M:%S"), hours, aid)
        )
        con.commit()
        flash("Check-out recorded.")

    con.close()
    return redirect(url_for("attendance"))
def leave():
    if not protected(): return redirect(url_for("login"))
    con=db()
    employees=con.execute("SELECT emp_id,name FROM employees ORDER BY name").fetchall()
    rows=con.execute("""SELECT l.*,e.name FROM leaves l LEFT JOIN employees e ON e.emp_id=l.emp_id
                        ORDER BY l.id DESC""").fetchall()
    con.close(); return render_template("leave.html", employees=employees, rows=rows)

@app.route("/leave/add", methods=["POST"])
def add_leave():
    if not protected(): return redirect(url_for("login"))
    con=db(); con.execute("""INSERT INTO leaves(emp_id,leave_type,from_date,to_date,reason)
                            VALUES(?,?,?,?,?)""", tuple(request.form.get(x) for x in ["emp_id","leave_type","from_date","to_date","reason"]))
    con.commit(); con.close(); flash("Leave request created."); return redirect(url_for("leave"))

@app.route("/leave/status/<int:lid>/<status>", methods=["POST"])
def leave_status(lid,status):
    if not protected(): return redirect(url_for("login"))
    if status not in ("Approved","Rejected"): return redirect(url_for("leave"))
    con=db(); con.execute("UPDATE leaves SET status=? WHERE id=?", (status,lid)); con.commit(); con.close()
    return redirect(url_for("leave"))

@app.route("/payroll")
def payroll():
    if not protected(): return redirect(url_for("login"))
    con=db(); emps=con.execute("SELECT * FROM employees ORDER BY name").fetchall()
    today=datetime.now().strftime("%Y-%m")
    data=[]
    for e in emps:
        present=con.execute("SELECT COUNT(*) c FROM attendance WHERE emp_id=? AND date LIKE ? AND status='Present'",(e["emp_id"],today+"%")).fetchone()["c"]
        hours=con.execute("SELECT COALESCE(SUM(hours),0) h FROM attendance WHERE emp_id=? AND date LIKE ?",(e["emp_id"],today+"%")).fetchone()["h"]
        data.append({"emp":e,"present":present,"hours":round(hours or 0,2),"salary":round(25000*(present/26),2)})
    con.close(); return render_template("payroll.html", data=data, month=today)

@app.route("/reports")
def reports():
    if not protected(): return redirect(url_for("login"))
    con=db(); rows=con.execute("""SELECT a.*,e.name,e.department FROM attendance a
                                  LEFT JOIN employees e ON e.emp_id=a.emp_id
                                  ORDER BY a.date DESC,a.id DESC""").fetchall(); con.close()
    return render_template("reports.html", rows=rows)

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
