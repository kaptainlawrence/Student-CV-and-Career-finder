import os
import io
import re
import hmac
import hashlib
import secrets
import sqlite3
from datetime import date, datetime
from contextlib import contextmanager

import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.utils import simpleSplit

APP_TITLE = "CareerLaunch"
DB_PATH = os.environ.get("CAREERLAUNCH_DB", "careerlaunch.db")

st.set_page_config(page_title=APP_TITLE, page_icon="🎓", layout="wide")

# ---------- Database ----------
@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS profiles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            full_name TEXT DEFAULT '', phone TEXT DEFAULT '', location TEXT DEFAULT '',
            email TEXT DEFAULT '', summary TEXT DEFAULT '', education TEXT DEFAULT '',
            experience TEXT DEFAULT '', projects TEXT DEFAULT '', skills TEXT DEFAULT '',
            certifications TEXT DEFAULT '', links TEXT DEFAULT '', updated_at TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            company TEXT NOT NULL, role TEXT NOT NULL, location TEXT DEFAULT '',
            application_date TEXT DEFAULT '', deadline TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Saved', job_url TEXT DEFAULT '',
            notes TEXT DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            answers TEXT NOT NULL, score INTEGER NOT NULL, total INTEGER NOT NULL,
            strengths TEXT NOT NULL, created_at TEXT NOT NULL
        );
        """)
init_db()

# ---------- Security helpers ----------
def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 310_000)
    return salt, digest.hex()

def verify_password(password, salt, expected):
    _, actual = password_hash(password, salt)
    return hmac.compare_digest(actual, expected)

def current_user():
    return st.session_state.get("user")

def get_profile(user_id):
    with db() as c:
        row = c.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    return dict(row) if row else {}

def save_profile(user_id, values):
    fields = ["full_name","phone","location","email","summary","education","experience","projects","skills","certifications","links"]
    values = {k: (values.get(k) or "").strip() for k in fields}
    with db() as c:
        c.execute("""
        INSERT INTO profiles (user_id, full_name, phone, location, email, summary, education,
          experience, projects, skills, certifications, links, updated_at)
        VALUES (:user_id, :full_name, :phone, :location, :email, :summary, :education,
          :experience, :projects, :skills, :certifications, :links, :updated_at)
        ON CONFLICT(user_id) DO UPDATE SET
          full_name=excluded.full_name, phone=excluded.phone, location=excluded.location,
          email=excluded.email, summary=excluded.summary, education=excluded.education,
          experience=excluded.experience, projects=excluded.projects, skills=excluded.skills,
          certifications=excluded.certifications, links=excluded.links, updated_at=excluded.updated_at
        """, {"user_id": user_id, **values, "updated_at": datetime.now().isoformat(timespec="seconds")})

def pdf_bytes(profile):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=18*mm, leftMargin=18*mm,
                            topMargin=16*mm, bottomMargin=16*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="CVName", parent=styles["Title"], fontName="Helvetica-Bold",
                              fontSize=21, leading=25, textColor=colors.HexColor("#17365D"),
                              alignment=TA_CENTER, spaceAfter=4))
    styles.add(ParagraphStyle(name="CVContact", parent=styles["Normal"], fontSize=9,
                              leading=13, alignment=TA_CENTER, textColor=colors.HexColor("#555555")))
    styles.add(ParagraphStyle(name="CVSection", parent=styles["Heading2"], fontSize=11,
                              leading=14, textColor=colors.HexColor("#17365D"), spaceBefore=10, spaceAfter=4))
    styles.add(ParagraphStyle(name="CVBody", parent=styles["BodyText"], fontSize=9.5, leading=13, spaceAfter=4))
    def safe(text):
        text = str(text or "")
        return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("\n", "<br/>"))
    story = [Paragraph(safe(profile.get("full_name") or "Your Name"), styles["CVName"])]
    contact = " | ".join(x for x in [profile.get("email"), profile.get("phone"), profile.get("location"), profile.get("links")] if x)
    if contact:
        story += [Paragraph(safe(contact), styles["CVContact"])]
    story.append(Spacer(1, 8))
    sections = [
        ("PROFESSIONAL SUMMARY", "summary"),
        ("EDUCATION", "education"),
        ("EXPERIENCE", "experience"),
        ("PROJECTS", "projects"),
        ("SKILLS", "skills"),
        ("CERTIFICATIONS & ACHIEVEMENTS", "certifications"),
    ]
    for heading, key in sections:
        content = (profile.get(key) or "").strip()
        if content:
            story += [Paragraph(heading, styles["CVSection"]),
                      HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#CBD5E1")),
                      Spacer(1, 4),
                      Paragraph(safe(content), styles["CVBody"])]
    doc.build(story)
    return buffer.getvalue()

# ---------- UI ----------
st.markdown("""
<style>
.block-container {padding-top: 1.6rem; max-width: 1200px;}
.hero {padding: 1.2rem 1.4rem; border-radius: 16px; background: linear-gradient(120deg,#17365D,#2563EB); color:white; margin-bottom:1rem;}
.hero h1 {color:white; margin-bottom:.3rem;}
.small-note {color:#64748b; font-size:.88rem;}
</style>
""", unsafe_allow_html=True)

if not current_user():
    st.markdown('<div class="hero"><h1>🎓 CareerLaunch</h1><p>Your CV, career skills, and job search in one place.</p></div>', unsafe_allow_html=True)
    login_tab, register_tab = st.tabs(["Sign in", "Create account"])
    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username or email")
            password = st.text_input("Password", type="password")
            login = st.form_submit_button("Sign in", use_container_width=True)
        if login:
            with db() as c:
                row = c.execute("SELECT * FROM users WHERE username=? OR email=?", (username.strip().lower(), username.strip().lower())).fetchone()
            if row and verify_password(password, row["salt"], row["password_hash"]):
                st.session_state.user = {"id": row["id"], "username": row["username"], "email": row["email"]}
                st.rerun()
            else:
                st.error("Incorrect username/email or password.")
    with register_tab:
        st.info("Create an account to keep your CV and applications private to your account.")
        with st.form("register_form"):
            new_username = st.text_input("Username", key="reg_username")
            new_email = st.text_input("Email address", key="reg_email")
            p1 = st.text_input("Password (at least 8 characters)", type="password", key="reg_p1")
            p2 = st.text_input("Confirm password", type="password", key="reg_p2")
            register = st.form_submit_button("Create account", use_container_width=True)
        if register:
            un, em = new_username.strip().lower(), new_email.strip().lower()
            if not re.fullmatch(r"[a-z0-9_.-]{3,30}", un):
                st.error("Username must be 3–30 characters and use letters, numbers, dots, underscores, or hyphens.")
            elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", em):
                st.error("Enter a valid email address.")
            elif len(p1) < 8:
                st.error("Use a password with at least 8 characters.")
            elif p1 != p2:
                st.error("Passwords do not match.")
            else:
                salt, hashed = password_hash(p1)
                try:
                    with db() as c:
                        c.execute("INSERT INTO users(username,email,password_hash,salt,created_at) VALUES(?,?,?,?,?)",
                                  (un, em, hashed, salt, datetime.now().isoformat(timespec="seconds")))
                    st.success("Account created. Sign in using the Sign in tab.")
                except sqlite3.IntegrityError:
                    st.error("That username or email is already registered.")
    st.caption("Privacy note: this starter app stores data in a local SQLite database. Anyone with access to the server or database file may be able to access stored profile data. Use HTTPS, backups, access controls, and appropriate hosting security before deploying publicly.")
    st.stop()

user = current_user()
with st.sidebar:
    st.markdown("## 🎓 CareerLaunch")
    st.caption(f"Signed in as **{user['username']}**")
    page = st.radio("Navigate", ["Dashboard", "CV Builder", "Cover Letter", "Applications", "Skills Assessment", "Account"])
    st.divider()
    if st.button("Sign out", use_container_width=True):
        del st.session_state.user
        st.rerun()

profile = get_profile(user["id"])

if page == "Dashboard":
    st.markdown('<div class="hero"><h1>Welcome, {}</h1><p>Build your career one step at a time.</p></div>'.format(
        (profile.get("full_name") or user["username"]).replace("<","&lt;").replace(">","&gt;")), unsafe_allow_html=True)
    with db() as c:
        apps = c.execute("SELECT * FROM applications WHERE user_id=?", (user["id"],)).fetchall()
        assessments = c.execute("SELECT * FROM assessments WHERE user_id=? ORDER BY id DESC LIMIT 1", (user["id"],)).fetchone()
    total_apps = len(apps)
    interviews = sum(1 for a in apps if a["status"] == "Interview")
    offers = sum(1 for a in apps if a["status"] == "Offer")
    cv_ready = bool(profile.get("full_name") and profile.get("education") and profile.get("skills"))
    cols = st.columns(4)
    cols[0].metric("CV status", "Ready" if cv_ready else "In progress")
    cols[1].metric("Applications", total_apps)
    cols[2].metric("Interviews", interviews)
    cols[3].metric("Offers", offers)
    st.subheader("Your next steps")
    todo = []
    if not cv_ready: todo.append("Complete your CV profile, especially education and skills.")
    if not profile.get("summary"): todo.append("Add a short professional summary to your CV.")
    if total_apps == 0: todo.append("Add your first job or internship opportunity.")
    if not assessments: todo.append("Complete the skills assessment to identify development areas.")
    if not todo: todo = ["Keep your CV updated and follow up on active applications."]
    for item in todo:
        st.write("• " + item)
    st.subheader("Recent applications")
    if apps:
        st.dataframe([{"Company": a["company"], "Role": a["role"], "Status": a["status"], "Deadline": a["deadline"]} for a in apps[-5:][::-1]], use_container_width=True, hide_index=True)
    else:
        st.info("Your application tracker is empty. Add opportunities in Applications.")

elif page == "CV Builder":
    st.title("CV Builder")
    st.write("Fill in your details. Use one item per line for skills, education, projects, and experience.")
    with st.form("profile_form"):
        c1, c2 = st.columns(2)
        full_name = c1.text_input("Full name", value=profile.get("full_name",""))
        email = c2.text_input("Professional email", value=profile.get("email", user["email"]))
        phone = c1.text_input("Phone", value=profile.get("phone",""))
        location = c2.text_input("City / country", value=profile.get("location",""))
        summary = st.text_area("Professional summary", value=profile.get("summary",""), height=90,
                               placeholder="Student interested in ... with experience in ...")
        education = st.text_area("Education", value=profile.get("education",""), height=110,
                                 placeholder="Degree / course — Institution — Dates\nRelevant coursework or achievements")
        experience = st.text_area("Work / volunteer experience", value=profile.get("experience",""), height=110,
                                  placeholder="Role — Organization — Dates\n• Action you took and result")
        projects = st.text_area("Projects", value=profile.get("projects",""), height=100,
                                placeholder="Project name\n• What you built and the tools used")
        skills = st.text_area("Skills", value=profile.get("skills",""), height=80,
                              placeholder="Python\nCommunication\nResearch")
        certifications = st.text_area("Certifications and achievements", value=profile.get("certifications",""), height=80)
        links = st.text_input("Portfolio / LinkedIn / GitHub link", value=profile.get("links",""))
        save = st.form_submit_button("Save CV profile", use_container_width=True)
    if save:
        save_profile(user["id"], locals())
        st.success("CV profile saved.")
        st.rerun()
    profile = get_profile(user["id"])
    st.subheader("Download your CV")
    if profile.get("full_name"):
        st.download_button("📄 Download CV as PDF", data=pdf_bytes(profile),
                           file_name="student_cv.pdf", mime="application/pdf", use_container_width=True)
    else:
        st.info("Save your CV profile before downloading the PDF.")
    with st.expander("CV writing tips"):
        st.markdown("- Tailor your CV to each opportunity.\n- Use clear action verbs and specific achievements.\n- Keep formatting consistent and check spelling.\n- Never invent qualifications or experience.\n- For students with limited work experience, include relevant projects, volunteering, and coursework.")

elif page == "Cover Letter":
    st.title("Cover Letter Generator")
    st.write("Create an editable draft from your saved profile. Review and personalize it before sending.")
    company = st.text_input("Company / organization")
    role = st.text_input("Role or internship title")
    hiring_contact = st.text_input("Hiring manager (optional)")
    job_desc = st.text_area("Job description or key requirements", height=140)
    tone = st.selectbox("Writing style", ["Professional", "Enthusiastic", "Concise"])
    if st.button("Generate cover letter draft", type="primary"):
        if not company.strip() or not role.strip():
            st.error("Enter the company and role first.")
        else:
            name = profile.get("full_name") or user["username"]
            skills = profile.get("skills") or "my academic and transferable skills"
            projects = profile.get("projects") or "my academic projects and learning"
            greeting = f"Dear {hiring_contact.strip()}," if hiring_contact.strip() else "Dear Hiring Manager,"
            opening = (f"I am writing to apply for the {role.strip()} opportunity at {company.strip()}. "
                       f"As a student developing my skills in {skills.replace(chr(10), ', ')}, I am excited by the opportunity to contribute and learn.")
            if tone == "Enthusiastic":
                opening = (f"I am excited to apply for the {role.strip()} opportunity at {company.strip()}. "
                           f"My background in {skills.replace(chr(10), ', ')} has encouraged me to keep learning and seek opportunities to make a useful contribution.")
            elif tone == "Concise":
                opening = f"I am applying for the {role.strip()} position at {company.strip}. I bring a willingness to learn and skills in {skills.replace(chr(10), ', ')}."
            body = f"My relevant experience includes {projects.replace(chr(10), '; ')}. I would welcome the opportunity to apply these skills, learn from your team, and contribute to your goals."
            if job_desc.strip():
                body += "\n\nI am particularly interested in the requirements you shared: " + job_desc.strip()[:700]
            letter = f"{name}\n{profile.get('email') or user['email']}\n{profile.get('phone','')}\n\n{date.today().strftime('%d %B %Y')}\n\n{greeting}\n\n{opening}\n\n{body}\n\nThank you for considering my application. I would welcome the opportunity to discuss how my skills and enthusiasm align with the role.\n\nYours sincerely,\n{name}"
            st.session_state.generated_letter = letter
    if "generated_letter" in st.session_state:
        letter = st.text_area("Edit your cover letter", value=st.session_state.generated_letter, height=420, key="letter_editor")
        st.download_button("Download cover letter (.txt)", data=letter, file_name="cover_letter.txt", mime="text/plain")
        st.caption("This is a draft, not a verified match to the job description. Check every claim and personalize it before use.")

elif page == "Applications":
    st.title("Job and Internship Tracker")
    with st.expander("＋ Add an opportunity", expanded=True):
        with st.form("application_form"):
            c1, c2 = st.columns(2)
            company = c1.text_input("Company / organization *")
            role = c2.text_input("Role *")
            location = c1.text_input("Location / remote")
            status = c2.selectbox("Status", ["Saved", "Preparing", "Applied", "Interview", "Offer", "Rejected", "Withdrawn"])
            applied_date = c1.date_input("Application date", value=date.today())
            deadline = c2.date_input("Deadline (optional)", value=None)
            job_url = st.text_input("Job posting URL (optional)")
            notes = st.text_area("Notes")
            add = st.form_submit_button("Add opportunity", use_container_width=True)
        if add:
            if not company.strip() or not role.strip():
                st.error("Company and role are required.")
            else:
                with db() as c:
                    c.execute("""INSERT INTO applications(user_id,company,role,location,application_date,deadline,status,job_url,notes,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (user["id"], company.strip(), role.strip(), location.strip(), applied_date.isoformat(),
                     deadline.isoformat() if deadline else "", status, job_url.strip(), notes.strip(),
                     datetime.now().isoformat(timespec="seconds")))
                st.success("Opportunity added.")
                st.rerun()
    with db() as c:
        rows = c.execute("SELECT * FROM applications WHERE user_id=? ORDER BY id DESC", (user["id"],)).fetchall()
    if rows:
        for row in rows:
            with st.container(border=True):
                col1, col2 = st.columns([3,1])
                col1.markdown(f"**{row['role']}** at **{row['company']}**")
                col1.caption(f"{row['location'] or 'Location not specified'} · Applied: {row['application_date'] or 'Not set'} · Deadline: {row['deadline'] or 'Not set'}")
                col1.write(f"Status: **{row['status']}**")
                if row["job_url"]:
                    col1.markdown(f"[Open job posting]({row['job_url']})")
                if row["notes"]:
                    col1.caption(row["notes"])
                new_status = col2.selectbox("Update status", ["Saved", "Preparing", "Applied", "Interview", "Offer", "Rejected", "Withdrawn"],
                                           index=["Saved", "Preparing", "Applied", "Interview", "Offer", "Rejected", "Withdrawn"].index(row["status"]),
                                           key=f"status_{row['id']}")
                if col2.button("Save status", key=f"save_status_{row['id']}"):
                    with db() as c:
                        c.execute("UPDATE applications SET status=? WHERE id=? AND user_id=?", (new_status, row["id"], user["id"]))
                    st.rerun()
                if col2.button("Delete", key=f"delete_{row['id']}"):
                    st.session_state[f"confirm_delete_{row['id']}"] = True
                if st.session_state.get(f"confirm_delete_{row['id']}"):
                    st.warning("Delete this opportunity?")
                    yes, no = st.columns(2)
                    if yes.button("Confirm delete", key=f"yes_{row['id']}"):
                        with db() as c:
                            c.execute("DELETE FROM applications WHERE id=? AND user_id=?", (row["id"], user["id"]))
                        del st.session_state[f"confirm_delete_{row['id']}"]
                        st.rerun()
                    if no.button("Keep", key=f"no_{row['id']}"):
                        del st.session_state[f"confirm_delete_{row['id']}"]
                        st.rerun()
    else:
        st.info("No opportunities yet. Add your first one above.")

elif page == "Skills Assessment":
    st.title("Skills Assessment")
    st.write("Rate your current confidence. This is a self-reflection tool, not a validated aptitude or psychometric test.")
    questions = {
        "communication": "Communication and writing",
        "problem_solving": "Problem-solving and critical thinking",
        "digital": "Digital tools and technology",
        "teamwork": "Teamwork and collaboration",
        "leadership": "Leadership and initiative",
        "research": "Research and information literacy",
        "time_management": "Time management and organization",
        "creativity": "Creativity and idea generation",
    }
    with st.form("skills_form"):
        answers = {}
        for key, label in questions.items():
            answers[key] = st.slider(label, min_value=1, max_value=5, value=3,
                                     help="1 = developing, 3 = comfortable, 5 = very confident")
        submitted = st.form_submit_button("Assess my skills", use_container_width=True)
    if submitted:
        ranked = sorted(answers.items(), key=lambda x: x[1], reverse=True)
        strengths = [questions[k] for k, v in ranked if v >= 4]
        improve = [questions[k] for k, v in ranked if v <= 2]
        score = sum(answers.values())
        st.session_state.skills_result = {"answers": answers, "strengths": strengths, "improve": improve, "score": score}
        with db() as c:
            c.execute("INSERT INTO assessments(user_id,answers,score,total,strengths,created_at) VALUES(?,?,?,?,?,?)",
                      (user["id"], str(answers), score, len(answers)*5, ", ".join(strengths),
                       datetime.now().isoformat(timespec="seconds")))
    result = st.session_state.get("skills_result")
    if result:
        st.subheader(f"Self-rating: {result['score']} / 40")
        st.progress(result["score"] / 40)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Current strengths")
            if result["strengths"]:
                for item in result["strengths"]: st.write("✅ " + item)
            else:
                st.write("Keep practicing to build confidence in your skills.")
        with c2:
            st.markdown("#### Areas to develop")
            if result["improve"]:
                for item in result["improve"]: st.write("📈 " + item)
            else:
                st.write("No skills rated 1–2. Choose a stretch goal to keep growing.")
        st.markdown("#### Suggested next steps")
        st.write("- Practice one skill each week using a small project.")
        st.write("- Gather examples of your skills for your CV and interviews.")
        st.write("- Ask a teacher, mentor, or teammate for feedback.")
        st.caption("Career suggestions should also consider your interests, education, opportunities, and lived experience—not just this score.")

elif page == "Account":
    st.title("Account")
    st.write(f"**Username:** {user['username']}")
    st.write(f"**Email:** {user['email']}")
    st.warning("This starter application does not yet include password reset or account deletion. Back up the SQLite database regularly and protect access to the hosting environment.")
    st.subheader("Data and privacy")
    st.write("Each user's CV, assessment history, and applications are associated with their account. Passwords are stored as salted PBKDF2 hashes, not as plain text.")
    st.write("For public deployment, configure HTTPS, secure secrets, database backups, access restrictions, and a privacy notice.")
