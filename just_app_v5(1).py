"""
JUST App v5.0 — Full UI Overhaul + Dark/Light Mode + Settings + Forgot PIN
by Luffy Applications ⚓
Run: python just_app_v5.py
Install: pip install pyrebase4 kivy
"""

# ════════════════════════════════════════════════════════════════════
#  IMPORTS
# ════════════════════════════════════════════════════════════════════
import sqlite3, os, random, string, threading, shutil
from datetime import datetime

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen, FadeTransition
from kivy.uix.scrollview import ScrollView
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle, RoundedRectangle, Line
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.core.window import Window

# ════════════════════════════════════════════════════════════════════
#  FIREBASE CONFIG
# ════════════════════════════════════════════════════════════════════
FIREBASE_CONFIG = {
    "apiKey":             "AIzaSyBWWPCoQRkndp1oCTaYttxLj8jAnupiwSo",
    "authDomain":         "just-apk.firebaseapp.com",
    "databaseURL":        "https://just-apk-default-rtdb.firebaseio.com",
    "projectId":          "just-apk",
    "storageBucket":      "just-apk.firebasestorage.app",
    "messagingSenderId":  "1090389134319",
    "appId":              "1:1090389134319:web:a1b7bf15be0a099380c41a"
}

# Try to connect Firebase — app still works offline if pyrebase4 not installed
firebase_db = None
def _init_firebase():
    global firebase_db
    try:
        import pyrebase
        fb  = pyrebase.initialize_app(FIREBASE_CONFIG)
        firebase_db = fb.database()
        print("✅ Firebase connected!")
    except Exception as e:
        print(f"⚠️  Firebase not available: {e}. Running in offline mode.")

threading.Thread(target=_init_firebase, daemon=True).start()

# ── Firebase chat helpers ─────────────────────────────────────────
def fb_send_message(group_id, sender, message):
    """Push a message to Firebase (non-blocking)."""
    if firebase_db is None:
        return
    def _push():
        try:
            firebase_db.child("chats").child(str(group_id)).push({
                "sender":  sender,
                "message": message,
                "sent_at": datetime.now().strftime("%d %b %Y %I:%M %p"),
                "ts":      {".sv": "timestamp"}   # server timestamp for ordering
            })
        except Exception as e:
            print(f"Firebase send error: {e}")
    threading.Thread(target=_push, daemon=True).start()

def fb_get_messages(group_id, limit=60):
    """Fetch latest messages from Firebase. Returns list of dicts."""
    if firebase_db is None:
        return []
    try:
        data = (firebase_db.child("chats").child(str(group_id))
                .order_by_child("ts").limit_to_last(limit).get())
        if data.val() is None:
            return []
        msgs = []
        for key, val in data.val().items():
            msgs.append({
                "sender":  val.get("sender",  "Unknown"),
                "message": val.get("message", ""),
                "sent_at": val.get("sent_at", ""),
            })
        return msgs   # oldest first
    except Exception as e:
        print(f"Firebase fetch error: {e}")
        return []

# Firebase connection status for UI badge
def fb_online():
    return firebase_db is not None

# ════════════════════════════════════════════════════════════════════
#  DATABASE
# ════════════════════════════════════════════════════════════════════
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'just_app.db')

def _conn():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

def init_db():
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS groups (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            name                 TEXT    NOT NULL UNIQUE,
            code                 TEXT    NOT NULL UNIQUE,
            teacher_pin          TEXT    NOT NULL,
            parent_reply_allowed INTEGER NOT NULL DEFAULT 0,
            pdf_export_allowed   INTEGER NOT NULL DEFAULT 0,
            created_at           TEXT    NOT NULL
        );
        CREATE TABLE IF NOT EXISTS parent_numbers (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
            number   TEXT    NOT NULL,
            UNIQUE(group_id, number)
        );
        CREATE TABLE IF NOT EXISTS students (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
            name     TEXT    NOT NULL,
            UNIQUE(group_id, name)
        );
        CREATE TABLE IF NOT EXISTS subjects (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
            name     TEXT    NOT NULL,
            UNIQUE(group_id, name)
        );
        CREATE TABLE IF NOT EXISTS attendance (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            date_key   TEXT    NOT NULL,
            status     TEXT    NOT NULL CHECK(status IN ('P','A')),
            UNIQUE(student_id, date_key)
        );
        CREATE TABLE IF NOT EXISTS exams (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
            name     TEXT    NOT NULL,
            UNIQUE(group_id, name)
        );
        CREATE TABLE IF NOT EXISTS marks (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            exam_id    INTEGER NOT NULL REFERENCES exams(id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
            subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            score      TEXT    NOT NULL DEFAULT '-',
            UNIQUE(exam_id, student_id, subject_id)
        );
        CREATE TABLE IF NOT EXISTS chat (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
            sender   TEXT    NOT NULL,
            message  TEXT    NOT NULL,
            sent_at  TEXT    NOT NULL
        );
        """)
        # migrations
        for sql in [
            "ALTER TABLE groups ADD COLUMN pdf_export_allowed INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE groups ADD COLUMN recovery_code TEXT NOT NULL DEFAULT ''",
        ]:
            try: con.execute(sql)
            except Exception: pass
        con.execute("""
            UPDATE groups SET recovery_code = substr(hex(randomblob(4)),1,8)
            WHERE recovery_code = '' OR recovery_code IS NULL
        """)

def _gen_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def _now():
    return datetime.now().strftime("%d %b %Y %I:%M %p")

def _row(con, sql, params=()):
    r = con.execute(sql, params).fetchone()
    return dict(r) if r else None

def _rows(con, sql, params=()):
    return [dict(r) for r in con.execute(sql, params).fetchall()]

# Groups
def create_group(name, pin):
    code     = _gen_code()
    rec_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    try:
        with _conn() as con:
            con.execute(
                "INSERT INTO groups(name,code,teacher_pin,created_at,recovery_code) VALUES(?,?,?,?,?)",
                (name, code, pin, _now(), rec_code))
        return get_group_by_name(name)
    except sqlite3.IntegrityError:
        return None

def get_group_by_name(name):
    with _conn() as con:
        return _row(con, "SELECT * FROM groups WHERE name=?", (name,))

def get_group_by_code(code):
    with _conn() as con:
        return _row(con, "SELECT * FROM groups WHERE code=?", (code.upper(),))

def verify_teacher_pin(group_id, pin):
    with _conn() as con:
        r = _row(con, "SELECT teacher_pin FROM groups WHERE id=?", (group_id,))
    return r and r['teacher_pin'] == pin

def set_toggle(group_id, field, val):
    with _conn() as con:
        con.execute(f"UPDATE groups SET {field}=? WHERE id=?", (1 if val else 0, group_id))

def get_toggle(group_id, field):
    with _conn() as con:
        r = _row(con, f"SELECT {field} FROM groups WHERE id=?", (group_id,))
    return bool(r[field]) if r else False

# Parents
def add_parent_number(group_id, number):
    try:
        with _conn() as con:
            con.execute("INSERT INTO parent_numbers(group_id,number) VALUES(?,?)", (group_id, number))
        return True
    except sqlite3.IntegrityError:
        return False

def get_parent_numbers(group_id):
    with _conn() as con:
        return [r['number'] for r in con.execute(
            "SELECT number FROM parent_numbers WHERE group_id=?", (group_id,)).fetchall()]

def number_in_group(group_id, number):
    with _conn() as con:
        return con.execute(
            "SELECT 1 FROM parent_numbers WHERE group_id=? AND number=?",
            (group_id, number)).fetchone() is not None

def remove_parent_number(group_id, number):
    with _conn() as con:
        con.execute("DELETE FROM parent_numbers WHERE group_id=? AND number=?", (group_id, number))

# Students
def add_student(group_id, name):
    try:
        with _conn() as con:
            con.execute("INSERT INTO students(group_id,name) VALUES(?,?)", (group_id, name))
        return True
    except sqlite3.IntegrityError:
        return False

def get_students(group_id):
    with _conn() as con:
        return _rows(con, "SELECT * FROM students WHERE group_id=? ORDER BY name", (group_id,))

def remove_student(student_id):
    with _conn() as con:
        con.execute("DELETE FROM students WHERE id=?", (student_id,))

# Subjects
def add_subject(group_id, name):
    try:
        with _conn() as con:
            con.execute("INSERT INTO subjects(group_id,name) VALUES(?,?)", (group_id, name))
        return True
    except sqlite3.IntegrityError:
        return False

def get_subjects(group_id):
    with _conn() as con:
        return _rows(con, "SELECT * FROM subjects WHERE group_id=? ORDER BY name", (group_id,))

def remove_subject(subject_id):
    with _conn() as con:
        con.execute("DELETE FROM subjects WHERE id=?", (subject_id,))

# Attendance
def save_attendance(student_id, date_key, status):
    with _conn() as con:
        con.execute(
            "INSERT INTO attendance(student_id,date_key,status) VALUES(?,?,?) "
            "ON CONFLICT(student_id,date_key) DO UPDATE SET status=excluded.status",
            (student_id, date_key, status))

def get_attendance(student_id):
    with _conn() as con:
        return _rows(con,
            "SELECT date_key,status FROM attendance WHERE student_id=? ORDER BY date_key DESC",
            (student_id,))

def get_attendance_on_date(group_id, date_key):
    with _conn() as con:
        rows = con.execute("""
            SELECT s.id, a.status FROM students s
            LEFT JOIN attendance a ON a.student_id=s.id AND a.date_key=?
            WHERE s.group_id=?
        """, (date_key, group_id)).fetchall()
    return {r['id']: r['status'] or 'P' for r in rows}

# Exams
def add_exam(group_id, name):
    try:
        with _conn() as con:
            con.execute("INSERT INTO exams(group_id,name) VALUES(?,?)", (group_id, name))
    except sqlite3.IntegrityError:
        pass
    return True

def get_exams(group_id):
    with _conn() as con:
        return _rows(con, "SELECT * FROM exams WHERE group_id=? ORDER BY name", (group_id,))

def get_exam_by_name(group_id, name):
    with _conn() as con:
        return _row(con, "SELECT * FROM exams WHERE group_id=? AND name=?", (group_id, name))

# Marks
def save_mark(exam_id, student_id, subject_id, score):
    with _conn() as con:
        con.execute(
            "INSERT INTO marks(exam_id,student_id,subject_id,score) VALUES(?,?,?,?) "
            "ON CONFLICT(exam_id,student_id,subject_id) DO UPDATE SET score=excluded.score",
            (exam_id, student_id, subject_id, score))

def get_marks(exam_id, student_id):
    with _conn() as con:
        return _rows(con, """
            SELECT sub.name AS subject, m.score FROM marks m
            JOIN subjects sub ON sub.id=m.subject_id
            WHERE m.exam_id=? AND m.student_id=? ORDER BY sub.name
        """, (exam_id, student_id))

# Chat
def send_chat(group_id, sender, message):
    with _conn() as con:
        con.execute("INSERT INTO chat(group_id,sender,message,sent_at) VALUES(?,?,?,?)",
                    (group_id, sender, message, _now()))

def get_chat(group_id, limit=60):
    with _conn() as con:
        return _rows(con,
            "SELECT sender,message,sent_at FROM chat WHERE group_id=? ORDER BY id DESC LIMIT ?",
            (group_id, limit))


# ════════════════════════════════════════════════════════════════════
#  PDF EXPORT
# ════════════════════════════════════════════════════════════════════
def export_report_card(group_name, student_name, student_id, exam_name, exam_id, out_path):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                         Table, TableStyle, HRFlowable)
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import cm
        from reportlab.graphics.shapes import Drawing, Rect, String
        from reportlab.graphics import renderPDF

        doc = SimpleDocTemplate(out_path, pagesize=A4,
                                leftMargin=2*cm, rightMargin=2*cm,
                                topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()
        story  = []

        title_style = ParagraphStyle('T', fontSize=22, textColor=colors.HexColor('#29C4A9'),
                                      alignment=1, spaceAfter=4, fontName='Helvetica-Bold')
        sub_style   = ParagraphStyle('S', fontSize=12, textColor=colors.HexColor('#888EA8'),
                                      alignment=1, spaceAfter=2)
        head_style  = ParagraphStyle('H', fontSize=14, textColor=colors.HexColor('#FFc838'),
                                      fontName='Helvetica-Bold', spaceAfter=4)
        body_style  = styles['Normal']

        story.append(Paragraph('🏴 JUST App', title_style))
        story.append(Paragraph('Student Report Card', sub_style))
        story.append(Paragraph(f'Group: {group_name}', sub_style))
        story.append(HRFlowable(width='100%', thickness=1,
                                 color=colors.HexColor('#29C4A9'), spaceAfter=10))

        # Student info
        story.append(Paragraph('Student Details', head_style))
        info_data = [
            ['Student Name', student_name],
            ['Exam',         exam_name],
            ['Generated',    datetime.now().strftime('%d %b %Y %I:%M %p')],
        ]
        info_tbl = Table(info_data, colWidths=[5*cm, 11*cm])
        info_tbl.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#0F1826')),
            ('BACKGROUND', (1,0), (1,-1), colors.HexColor('#17273D')),
            ('TEXTCOLOR',  (0,0), (-1,-1), colors.HexColor('#E6E8F0')),
            ('FONTNAME',   (0,0), (0,-1), 'Helvetica-Bold'),
            ('FONTSIZE',   (0,0), (-1,-1), 11),
            ('ROWBACKGROUNDS', (0,0), (-1,-1), [colors.HexColor('#0F1826'), colors.HexColor('#17273D')]),
            ('GRID',       (0,0), (-1,-1), 0.5, colors.HexColor('#29C4A9')),
            ('PADDING',    (0,0), (-1,-1), 8),
        ]))
        story.append(info_tbl)
        story.append(Spacer(1, 16))

        # Attendance
        story.append(Paragraph('Attendance Summary', head_style))
        records = get_attendance(student_id)
        total   = len(records)
        present = sum(1 for r in records if r['status'] == 'P')
        absent  = total - present
        pct     = f'{present/total*100:.1f}%' if total else 'N/A'

        att_data = [['Total Days', 'Present', 'Absent', 'Percentage'],
                    [str(total), str(present), str(absent), pct]]
        att_tbl = Table(att_data, colWidths=[4*cm]*4)
        att_tbl.setStyle(TableStyle([
            ('BACKGROUND',  (0,0), (-1,0),  colors.HexColor('#29C4A9')),
            ('TEXTCOLOR',   (0,0), (-1,0),  colors.white),
            ('FONTNAME',    (0,0), (-1,0),  'Helvetica-Bold'),
            ('BACKGROUND',  (0,1), (-1,-1), colors.HexColor('#17273D')),
            ('TEXTCOLOR',   (0,1), (-1,-1), colors.HexColor('#E6E8F0')),
            ('ALIGN',       (0,0), (-1,-1), 'CENTER'),
            ('GRID',        (0,0), (-1,-1), 0.5, colors.HexColor('#29C4A9')),
            ('FONTSIZE',    (0,0), (-1,-1), 11),
            ('PADDING',     (0,0), (-1,-1), 8),
        ]))
        story.append(att_tbl)
        story.append(Spacer(1, 16))

        # Bar chart for attendance
        if total > 0:
            d = Drawing(400, 80)
            bar_w = 100
            p_w   = int(bar_w * present / total)
            a_w   = bar_w - p_w
            # bg
            d.add(Rect(20, 30, bar_w, 20, fillColor=colors.HexColor('#FF4444'), strokeColor=None))
            d.add(Rect(20, 30, p_w,   20, fillColor=colors.HexColor('#27D270'), strokeColor=None))
            d.add(String(130, 38, f'Present {pct}', fontSize=10,
                         fillColor=colors.HexColor('#E6E8F0')))
            story.append(Spacer(1, 4))
            renderPDF.draw(d, doc, 0, 0)
            story.append(Spacer(1, 8))

        # Marks
        story.append(Paragraph(f'Marks — {exam_name}', head_style))
        marks = get_marks(exam_id, student_id)
        if marks:
            total_score = 0; count = 0
            marks_data = [['Subject', 'Score', 'Status']]
            for m in marks:
                try:
                    val  = float(m['score'])
                    status = 'Pass' if val >= 35 else 'Fail'
                    total_score += val; count += 1
                except ValueError:
                    status = '-'
                marks_data.append([m['subject'], m['score'], status])
            if count:
                avg = total_score / count
                marks_data.append(['', f'Avg: {avg:.1f}', 'Pass' if avg >= 35 else 'Fail'])

            marks_tbl = Table(marks_data, colWidths=[8*cm, 4*cm, 4*cm])
            marks_tbl.setStyle(TableStyle([
                ('BACKGROUND',  (0,0), (-1,0),  colors.HexColor('#FFc838')),
                ('TEXTCOLOR',   (0,0), (-1,0),  colors.HexColor('#0A1020')),
                ('FONTNAME',    (0,0), (-1,0),  'Helvetica-Bold'),
                ('BACKGROUND',  (0,1), (-1,-2), colors.HexColor('#17273D')),
                ('BACKGROUND',  (0,-1),(-1,-1), colors.HexColor('#0F1826')),
                ('TEXTCOLOR',   (0,1), (-1,-1), colors.HexColor('#E6E8F0')),
                ('GRID',        (0,0), (-1,-1), 0.5, colors.HexColor('#FFc838')),
                ('ALIGN',       (1,0), (-1,-1), 'CENTER'),
                ('FONTSIZE',    (0,0), (-1,-1), 11),
                ('PADDING',     (0,0), (-1,-1), 8),
            ]))
            story.append(marks_tbl)
        else:
            story.append(Paragraph('No marks entered for this exam.', body_style))

        story.append(Spacer(1, 20))
        story.append(HRFlowable(width='100%', thickness=0.5,
                                 color=colors.HexColor('#29C4A9')))
        story.append(Paragraph('Generated by JUST App — Luffy Applications',
                                ParagraphStyle('F', fontSize=9,
                                               textColor=colors.HexColor('#555A6E'),
                                               alignment=1)))
        doc.build(story)
        return True
    except Exception as e:
        print(f"PDF error: {e}")
        return False


# ════════════════════════════════════════════════════════════════════
#  THEME SYSTEM — Dark / Light switchable
# ════════════════════════════════════════════════════════════════════
_DARK = {
    'PRIMARY' : (0.06, 0.10, 0.20, 1),
    'ACCENT'  : (0.18, 0.82, 0.72, 1),
    'ACCENT2' : (1.00, 0.80, 0.25, 1),
    'BG'      : (0.03, 0.06, 0.12, 1),
    'CARD'    : (0.08, 0.14, 0.26, 1),
    'CARD2'   : (0.11, 0.19, 0.32, 1),
    'CARD3'   : (0.06, 0.11, 0.22, 1),
    'TEXT'    : (0.96, 0.97, 0.99, 1),
    'SUBTEXT' : (0.50, 0.59, 0.72, 1),
    'SUCCESS' : (0.12, 0.85, 0.50, 1),
    'DANGER'  : (0.95, 0.28, 0.30, 1),
    'WARN'    : (1.00, 0.66, 0.08, 1),
    'DIVIDER' : (0.14, 0.23, 0.38, 1),
}
_LIGHT = {
    'PRIMARY' : (0.88, 0.92, 0.98, 1),
    'ACCENT'  : (0.04, 0.60, 0.52, 1),
    'ACCENT2' : (0.80, 0.55, 0.00, 1),
    'BG'      : (0.95, 0.96, 0.98, 1),
    'CARD'    : (1.00, 1.00, 1.00, 1),
    'CARD2'   : (0.90, 0.93, 0.97, 1),
    'CARD3'   : (0.82, 0.86, 0.92, 1),
    'TEXT'    : (0.08, 0.10, 0.16, 1),
    'SUBTEXT' : (0.38, 0.44, 0.56, 1),
    'SUCCESS' : (0.05, 0.65, 0.30, 1),
    'DANGER'  : (0.82, 0.12, 0.14, 1),
    'WARN'    : (0.80, 0.48, 0.00, 1),
    'DIVIDER' : (0.78, 0.82, 0.90, 1),
}

# Global theme state
_theme_is_dark = True

def _T(key):
    """Get current theme color by key."""
    return (_DARK if _theme_is_dark else _LIGHT)[key]

# Convenience globals — updated on theme switch
def _apply_theme():
    global PRIMARY, ACCENT, ACCENT2, BG, CARD, CARD2, CARD3
    global TEXT, SUBTEXT, SUCCESS, DANGER, WARN, DIVIDER
    t = _DARK if _theme_is_dark else _LIGHT
    PRIMARY  = t['PRIMARY'];  ACCENT   = t['ACCENT'];  ACCENT2 = t['ACCENT2']
    BG       = t['BG'];       CARD     = t['CARD'];    CARD2   = t['CARD2']
    CARD3    = t['CARD3'];    TEXT     = t['TEXT'];    SUBTEXT = t['SUBTEXT']
    SUCCESS  = t['SUCCESS'];  DANGER   = t['DANGER'];  WARN    = t['WARN']
    DIVIDER  = t['DIVIDER']
    Window.clearcolor = BG

_apply_theme()

def toggle_theme():
    global _theme_is_dark
    _theme_is_dark = not _theme_is_dark
    _apply_theme()
    # save preference
    prefs = _load_prefs()
    prefs['dark_mode'] = _theme_is_dark
    _save_prefs(prefs)

# ── preferences (simple JSON file) ───────────────────────────────
import json
PREFS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'just_prefs.json')

def _load_prefs():
    try:
        with open(PREFS_PATH) as f:
            return json.load(f)
    except Exception:
        return {'dark_mode': True, 'font_size': 'Medium', 'notify_sound': True, 'font_color': 'default'}

def _save_prefs(p):
    try:
        with open(PREFS_PATH, 'w') as f:
            json.dump(p, f)
    except Exception:
        pass

# Font color options
FONT_COLORS = {
    'default': None,                    # uses theme default
    'black':   (0.05, 0.05, 0.05, 1),
    'white':   (0.97, 0.97, 0.97, 1),
    'teal':    (0.18, 0.82, 0.72, 1),
}

def get_font_color():
    """Returns the user chosen font color, or None to use theme default."""
    p = _load_prefs()
    key = p.get('font_color', 'default')
    return FONT_COLORS.get(key, None)

def set_font_color(key):
    p = _load_prefs()
    p['font_color'] = key
    _save_prefs(p)

def _init_prefs():
    global _theme_is_dark
    p = _load_prefs()
    _theme_is_dark = p.get('dark_mode', True)
    _apply_theme()

session = dict(group_id=None, group_name=None, group_code=None, role=None, phone=None)
EXAM_PRESETS = ['Mid Term', 'Half Yearly', 'Annual Exam', 'Unit Test 1', 'Unit Test 2', 'Pre-Board']

# ── canvas helpers ────────────────────────────────────────────────
def _attach_bg(widget, color, radius=0):
    with widget.canvas.before:
        c = Color(*color)
        r = (RoundedRectangle(pos=widget.pos, size=widget.size, radius=[dp(radius)])
             if radius else Rectangle(pos=widget.pos, size=widget.size))
    widget.bind(pos=lambda i, v: setattr(r, 'pos', v),
                size=lambda i, v: setattr(r, 'size', v))
    return c, r

def _full_bg(root):
    with root.canvas.before:
        Color(*BG)
        r = Rectangle(pos=root.pos, size=root.size)
    root.bind(pos=lambda i, v: setattr(r, 'pos', v),
              size=lambda i, v: setattr(r, 'size', v))

def _divider():
    d = Widget(size_hint_y=None, height=dp(1))
    with d.canvas:
        Color(*DIVIDER)
        r = Rectangle(pos=d.pos, size=d.size)
    d.bind(pos=lambda i, v: setattr(r, 'pos', v),
           size=lambda i, v: setattr(r, 'size', v))
    return d

# ── layout primitives ─────────────────────────────────────────────
def page():
    l = BoxLayout(orientation='vertical', padding=[dp(16), dp(16)],
                  spacing=dp(10), size_hint_y=None)
    l.bind(minimum_height=l.setter('height'))
    _attach_bg(l, BG)
    return l

def card(padding=16, spacing=10):
    l = BoxLayout(orientation='vertical', padding=dp(padding),
                  spacing=dp(spacing), size_hint_y=None)
    l.bind(minimum_height=l.setter('height'))
    _attach_bg(l, CARD, radius=20)
    return l

def row(height=48, spacing=8):
    return BoxLayout(size_hint_y=None, height=dp(height), spacing=dp(spacing))

# ── text helpers ──────────────────────────────────────────────────
def lbl(text, size=15, color=None, bold=False, align='left', height=None):
    # If no color given, check font color preference
    if color is None:
        fc = get_font_color()
        color = fc if fc else TEXT
    h = dp(height) if height else dp(size + 18)
    l = Label(text=text, font_size=dp(size), color=color, bold=bold,
              size_hint_y=None, height=h, halign=align, valign='middle')
    l.bind(width=lambda i, v: setattr(i, 'text_size', (v, None)))
    return l

def h1(text, color=None):
    return lbl(text, 24, color or ACCENT, bold=True, align='center', height=48)

def h2(text, color=None):
    return lbl(text, 15, color or ACCENT2, bold=True, align='center', height=34)

def caption(text):
    return lbl(text, 12, SUBTEXT, align='center')

def spacer(h=12):
    return Label(size_hint_y=None, height=dp(h))

# ── form inputs ───────────────────────────────────────────────────
def field(hint, password=False, height=52):
    ti = TextInput(
        hint_text=hint, password=password, multiline=False,
        size_hint_y=None, height=dp(height), font_size=dp(15),
        foreground_color=TEXT, hint_text_color=SUBTEXT,
        background_color=(0, 0, 0, 0),
        cursor_color=ACCENT,
        padding=[dp(16), dp(15)])
    with ti.canvas.before:
        Color(*CARD2)
        bg = RoundedRectangle(pos=ti.pos, size=ti.size, radius=[dp(14)])
        Color(*ACCENT[:3], 0.35)
        border = Line(rounded_rectangle=[ti.x, ti.y, ti.width, ti.height, dp(14)], width=1.2)
    ti.bind(
        pos =lambda i, v: (setattr(bg, 'pos', v),
                           setattr(border, 'rectangle', [v[0], v[1], i.width, i.height])),
        size=lambda i, v: (setattr(bg, 'size', v),
                           setattr(border, 'rectangle', [i.x, i.y, v[0], v[1]])))
    return ti

def mkspinner(values, default=None):
    s = Spinner(
        text=default or (values[0] if values else '-'),
        values=values, size_hint_y=None, height=dp(52),
        font_size=dp(14), color=TEXT,
        background_color=(0, 0, 0, 0), background_normal='')
    with s.canvas.before:
        Color(*CARD2)
        bg = RoundedRectangle(pos=s.pos, size=s.size, radius=[dp(14)])
    s.bind(pos=lambda i, v: setattr(bg, 'pos', v),
           size=lambda i, v: setattr(bg, 'size', v))
    return s

# ── buttons ───────────────────────────────────────────────────────
def btn(text, bg=None, fg=None, size=15, height=52, radius=22, bold=True):
    bg = bg or ACCENT
    fg = fg or TEXT
    b = Button(text=text, size_hint_y=None, height=dp(height),
               font_size=dp(size), bold=bold, color=fg,
               background_normal='', background_color=(0, 0, 0, 0))
    col, _ = _attach_bg(b, bg, radius)
    orig = tuple(bg)
    def _press(*_): col.rgba = tuple(max(0, x - 0.10) for x in orig[:3]) + (orig[3],)
    def _rel(*_):   col.rgba = orig
    b.bind(on_press=_press, on_release=_rel)
    return b

def icon_btn(icon, text, bg=None, fg=None, height=56, radius=22):
    return btn(f'{icon}  {text}', bg=bg or ACCENT, fg=fg or TEXT, height=height, radius=radius)

def back_btn(manager, target, text='‹  Back'):
    b = btn(text, bg=CARD2, fg=SUBTEXT, height=46, size=14, radius=22)
    b.bind(on_release=lambda *_: setattr(manager, 'current', target))
    return b

def nav_btn(icon, label, active=False):
    """Bottom nav tab button."""
    color = ACCENT if active else SUBTEXT
    b = Button(
        text=f'{icon}\n{label}', font_size=dp(10), bold=active,
        color=color, halign='center', valign='middle',
        background_normal='', background_color=(0,0,0,0))
    if active:
        with b.canvas.before:
            Color(*ACCENT[:3], 0.15)
            RoundedRectangle(pos=b.pos, size=b.size, radius=[dp(12)])
    return b

# ── bottom nav bar ────────────────────────────────────────────────
def bottom_nav(manager, items, active_target):
    """
    items = [('🏠', 'Home', 'teacher_home'), ('💬', 'Chat', 'teacher_chat'), ...]
    """
    bar = BoxLayout(size_hint_y=None, height=dp(62), spacing=0)
    with bar.canvas.before:
        Color(*CARD)
        r = RoundedRectangle(pos=bar.pos, size=bar.size, radius=[dp(18), dp(18), 0, 0])
    bar.bind(pos=lambda i, v: setattr(r, 'pos', v),
             size=lambda i, v: setattr(r, 'size', v))
    for icon, label, target in items:
        active = (target == active_target)
        b = nav_btn(icon, label, active)
        if not active:
            b.bind(on_release=lambda *_, t=target: setattr(manager, 'current', t))
        bar.add_widget(b)
    return bar

# ── popups ────────────────────────────────────────────────────────
def popup(title, msg, on_ok=None, ok_text='OK'):
    body = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(14),
                     size_hint_y=None, height=dp(180))
    _attach_bg(body, CARD, radius=20)
    body.add_widget(lbl(msg, 14, TEXT, align='center', height=80))
    ok = btn(ok_text, height=46, radius=22)
    body.add_widget(ok)
    p = Popup(title=title, content=body, size_hint=(0.88, None), height=dp(240),
              title_color=ACCENT, separator_color=ACCENT, background_color=CARD3)
    ok.bind(on_release=lambda *_: (p.dismiss(), on_ok() if on_ok else None))
    p.open()

def confirm(title, msg, on_yes, yes_text='Confirm', no_text='Cancel'):
    body = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(14),
                     size_hint_y=None, height=dp(200))
    _attach_bg(body, CARD, radius=20)
    body.add_widget(lbl(msg, 14, TEXT, align='center', height=80))
    btns = row(height=48, spacing=10)
    y = btn(yes_text, bg=DANGER, height=46, radius=22)
    n = btn(no_text,  bg=CARD2,  fg=SUBTEXT, height=46, radius=22)
    btns.add_widget(y); btns.add_widget(n)
    body.add_widget(btns)
    p = Popup(title=title, content=body, size_hint=(0.88, None), height=dp(260),
              title_color=ACCENT, separator_color=ACCENT, background_color=CARD3)
    y.bind(on_release=lambda *_: (p.dismiss(), on_yes()))
    n.bind(on_release=p.dismiss)
    p.open()

def _recolor_btn(b, color):
    b.canvas.before.clear()
    with b.canvas.before:
        c = Color(*color)
        r = RoundedRectangle(pos=b.pos, size=b.size, radius=[dp(22)])
    b.bind(pos=lambda i, v: setattr(r, 'pos', v),
           size=lambda i, v: setattr(r, 'size', v))

# ── settings row helper ───────────────────────────────────────────
def setting_row(icon, title, subtitle, on_tap=None, right_widget=None):
    """A tappable settings list row."""
    r = BoxLayout(size_hint_y=None, height=dp(64), spacing=dp(12), padding=[dp(4), 0])
    _attach_bg(r, CARD, radius=14)

    # icon badge
    ib = BoxLayout(size_hint_x=None, width=dp(44), size_hint_y=None, height=dp(44))
    _attach_bg(ib, CARD2, radius=12)
    ib.add_widget(Label(text=icon, font_size=dp(22), size_hint_y=None, height=dp(44)))

    # text
    txt = BoxLayout(orientation='vertical', spacing=dp(2))
    txt.add_widget(lbl(title, 15, TEXT, bold=True, height=24))
    if subtitle:
        txt.add_widget(lbl(subtitle, 12, SUBTEXT, height=20))

    r.add_widget(ib)
    r.add_widget(txt)
    if right_widget:
        r.add_widget(right_widget)
    else:
        r.add_widget(lbl('›', 20, SUBTEXT, align='right', height=44))

    if on_tap:
        b = Button(size_hint=(1,1), background_normal='',
                   background_color=(0,0,0,0), opacity=0)
        b.bind(on_release=lambda *_: on_tap())
        from kivy.uix.floatlayout import FloatLayout
        fl = FloatLayout(size_hint_y=None, height=dp(64))
        r.size_hint_y = None; r.height = dp(64)
        fl.add_widget(r)
        fl.add_widget(b)
        return fl
    return r


# ════════════════════════════════════════════════════════════════════
#  BAR CHART WIDGET
# ════════════════════════════════════════════════════════════════════
class AttendanceBarChart(Widget):
    def __init__(self, students_data, **kwargs):
        super().__init__(**kwargs)
        self.students_data = students_data  # [(name, present, total), ...]
        self.size_hint_y = None
        self.height = dp(max(60 + len(students_data) * 44, 120))
        self.bind(pos=self._draw, size=self._draw)
        Clock.schedule_once(lambda *_: self._draw(), 0.05)

    def _draw(self, *_):
        self.canvas.clear()
        if not self.students_data:
            return
        x0     = self.x + dp(16)
        bar_w  = self.width - dp(140)
        bar_h  = dp(22)
        y_start= self.top - dp(30)

        with self.canvas:
            # Title
            Color(*ACCENT2)

            for i, (name, present, total) in enumerate(self.students_data):
                y    = y_start - i * dp(44)
                pct  = present / total if total > 0 else 0

                # Background bar
                Color(*CARD2)
                RoundedRectangle(pos=(x0, y - bar_h), size=(bar_w, bar_h), radius=[dp(6)])

                # Fill bar
                fill_w = max(dp(6), bar_w * pct)
                if pct >= 0.75:
                    Color(*SUCCESS)
                elif pct >= 0.5:
                    Color(*WARN)
                else:
                    Color(*DANGER)
                RoundedRectangle(pos=(x0, y - bar_h), size=(fill_w, bar_h), radius=[dp(6)])

                # Name label drawn via Label widget (canvas labels not trivial in Kivy)
                # pct text
                Color(*TEXT)


# ════════════════════════════════════════════════════════════════════
#  SCREENS
# ════════════════════════════════════════════════════════════════════

class SplashScreen(Screen):
    def on_pre_enter(self):
        self.clear_widgets()
        root = BoxLayout(orientation='vertical', padding=dp(40))
        _full_bg(root)
        root.add_widget(Label())
        self._icon_lbl = Label(text='\U0001F3F4\u200d\u2620\uFE0F', font_size=dp(80),
                               size_hint_y=None, height=dp(110), opacity=0)
        self._title_lbl = lbl('LUFFY APPLICATIONS', 28, ACCENT2, bold=True,
                               align='center', height=56)
        self._title_lbl.opacity = 0
        self._sub_lbl = lbl('Powering JUST App', 13, SUBTEXT, align='center', height=30)
        self._sub_lbl.opacity = 0
        root.add_widget(self._icon_lbl)
        root.add_widget(spacer(12))
        root.add_widget(self._title_lbl)
        root.add_widget(self._sub_lbl)
        root.add_widget(Label())
        self.add_widget(root)
        Clock.schedule_once(lambda *_: self._fade(self._icon_lbl),  0.15)
        Clock.schedule_once(lambda *_: self._fade(self._title_lbl), 0.45)
        Clock.schedule_once(lambda *_: self._fade(self._sub_lbl),   0.70)
        Clock.schedule_once(lambda *_: setattr(self.manager, 'current', 'role_select'), 2.4)

    def _fade(self, widget, steps=12):
        step = 1.0 / steps
        def _tick(dt, _w=widget, _s=step):
            _w.opacity = min(1.0, _w.opacity + _s)
        Clock.schedule_interval(_tick, 0.03)


class RoleSelectScreen(Screen):
    def on_pre_enter(self):
        self.clear_widgets()
        root = BoxLayout(orientation='vertical', padding=[dp(28), dp(36)], spacing=dp(14))
        _full_bg(root)
        root.add_widget(Label())
        root.add_widget(Label(text='🎓', font_size=dp(68), size_hint_y=None, height=dp(96)))
        root.add_widget(h1('JUST'))
        root.add_widget(lbl('Smart Attendance Manager', 14, SUBTEXT, align='center', height=30))
        root.add_widget(spacer(32))
        t = icon_btn('👨\u200d🏫', 'Login as Teacher', height=60)
        p = icon_btn('👨\u200d👩\u200d👧', 'Join as Parent',  bg=CARD2, height=60)
        t.bind(on_release=lambda *_: setattr(self.manager, 'current', 'teacher_login'))
        p.bind(on_release=lambda *_: setattr(self.manager, 'current', 'parent_login'))
        root.add_widget(t); root.add_widget(spacer(4)); root.add_widget(p)
        root.add_widget(Label())
        root.add_widget(caption('JUST v3.0  •  by Luffy Applications'))
        root.add_widget(spacer(12))
        self.add_widget(root)


class TeacherLoginScreen(Screen):
    def on_pre_enter(self):
        self.clear_widgets()
        root = BoxLayout(orientation='vertical', padding=[dp(28), dp(32)], spacing=dp(14))
        _full_bg(root)
        root.add_widget(Label())
        root.add_widget(Label(text='👨\u200d🏫', font_size=dp(60), size_hint_y=None, height=dp(84)))
        root.add_widget(h1('Teacher Login'))
        root.add_widget(lbl('Create a group or open an existing one', 13, SUBTEXT, align='center', height=30))
        root.add_widget(spacer(12))
        self.grp = field('Group Name')
        self.pin = field('PIN  (min 4 digits)', password=True)
        create = icon_btn('➕', 'Create New Group', height=54)
        login  = icon_btn('🔓', 'Open Existing Group', bg=CARD2, height=54)
        back   = back_btn(self.manager, 'role_select')
        create.bind(on_release=self._create); login.bind(on_release=self._login)
        forgot = btn('🔐  Forgot PIN?', bg=CARD3, fg=SUBTEXT, height=42, size=13, radius=22)
        forgot.bind(on_release=lambda *_: setattr(self.manager, 'current', 'forgot_pin'))
        for w in [self.grp, spacer(4), self.pin, spacer(8), create, spacer(4), login,
                  spacer(6), forgot, spacer(10), back]:
            root.add_widget(w)
        root.add_widget(Label()); self.add_widget(root)

    def _create(self, *_):
        name, pin = self.grp.text.strip(), self.pin.text.strip()
        if not name or not pin: popup('Error', 'Fill both fields!'); return
        if len(pin) < 4: popup('Error', 'PIN must be at least 4 digits!'); return
        grp = create_group(name, pin)
        if grp is None: popup('Error', f'Group "{name}" already exists!'); return
        session.update(group_id=grp['id'], group_name=grp['name'],
                       group_code=grp['code'], role='teacher')
        popup('Group Created! 🎉',
              f'Group: {name}\nCode: {grp["code"]}\n\nShare code with parents!',
              on_ok=lambda: setattr(self.manager, 'current', 'teacher_home'))

    def _login(self, *_):
        name, pin = self.grp.text.strip(), self.pin.text.strip()
        if not name or not pin: popup('Error', 'Fill both fields!'); return
        grp = get_group_by_name(name)
        if grp is None: popup('Error', 'Group not found!'); return
        if not verify_teacher_pin(grp['id'], pin): popup('Wrong PIN', 'Incorrect PIN!'); return
        session.update(group_id=grp['id'], group_name=grp['name'],
                       group_code=grp['code'], role='teacher')
        self.manager.current = 'teacher_home'


TEACHER_NAV = [
    ('🏠', 'Home',      'teacher_home'),
    ('📅', 'Attend',    'mark_attendance'),
    ('📊', 'Marks',     'enter_marks'),
    ('💬', 'Chat',      'teacher_chat'),
    ('⚙️', 'Settings',  'settings'),
]

PARENT_NAV = [
    ('🏠', 'Home',     'parent_home'),
    ('📅', 'Attend',   'view_attendance'),
    ('💬', 'Chat',     'parent_chat'),
    ('📊', 'Marks',    'view_marks'),
    ('⚙️', 'Settings', 'settings'),
]

class TeacherHomeScreen(Screen):
    def on_pre_enter(self):
        self.clear_widgets()
        gid = session['group_id']; gname = session['group_name']; code = session['group_code']

        outer = BoxLayout(orientation='vertical')
        _full_bg(outer)

        sv = ScrollView(size_hint_y=1)
        root = page()

        # ── header card ──
        info = card(padding=20, spacing=8)
        # top row: name + settings shortcut
        hr = row(height=44, spacing=8)
        hr.add_widget(h1(f'📋  {gname}'))
        outer.add_widget(spacer(4))
        info.add_widget(hr)
        # code badge
        code_box = BoxLayout(size_hint_y=None, height=dp(44), padding=[dp(20), 0])
        _attach_bg(code_box, CARD3, radius=14)
        code_box.add_widget(lbl(f'🔑  {code}', 18, ACCENT2, bold=True, align='center', height=44))
        info.add_widget(code_box)
        info.add_widget(spacer(4))
        r = row(height=32, spacing=20)
        r.add_widget(lbl(f'👥  {len(get_parent_numbers(gid))} parents',  13, SUBTEXT, align='center'))
        r.add_widget(lbl(f'👤  {len(get_students(gid))} students', 13, SUBTEXT, align='center'))
        info.add_widget(r)
        root.add_widget(info); root.add_widget(spacer(8))

        # ── manage section ──
        root.add_widget(h2('⚙️  Manage', color=TEXT))
        root.add_widget(spacer(4))
        mg = row(height=60, spacing=10)
        for icon, label, target in [('👤','Students','manage_students'),
                                     ('📚','Subjects','manage_subjects'),
                                     ('📱','Parents','manage_parents')]:
            b = btn(f'{icon}\n{label}', bg=CARD2, height=60, size=12)
            b.bind(on_release=lambda *_, t=target: setattr(self.manager, 'current', t))
            mg.add_widget(b)
        root.add_widget(mg); root.add_widget(spacer(8))

        # ── quick actions ──
        root.add_widget(h2('⚡  Quick Actions', color=TEXT))
        root.add_widget(spacer(4))
        for label, target, color in [
            ('📅  Mark Attendance', 'mark_attendance', ACCENT),
            ('📊  Enter Marks',      'enter_marks',     CARD2),
            ('📈  Attendance Chart', 'att_chart',       CARD2)]:
            b = btn(label, bg=color, height=56)
            b.bind(on_release=lambda *_, t=target: setattr(self.manager, 'current', t))
            root.add_widget(b)

        root.add_widget(spacer(10))
        out = btn('🚪  Logout', bg=DANGER, height=48)
        out.bind(on_release=lambda *_: confirm('Logout', 'Sure you want to logout?',
                                                on_yes=self._logout))
        root.add_widget(out)
        sv.add_widget(root)
        outer.add_widget(sv)
        outer.add_widget(bottom_nav(self.manager, TEACHER_NAV, 'teacher_home'))
        self.add_widget(outer)

    def _logout(self):
        session.update(group_id=None, group_name=None, group_code=None, role=None, phone=None)
        self.manager.current = 'role_select'


class ManageStudentsScreen(Screen):
    def on_pre_enter(self):
        self.clear_widgets()
        gid = session['group_id']; sv = ScrollView(); root = page()
        root.add_widget(h1('👤  Students'))
        root.add_widget(spacer(4))
        add = card(padding=16, spacing=10)
        add.add_widget(h2('Add New Student'))
        self.sf = field('Student full name')
        ab = btn('➕  Add Student', height=50)
        ab.bind(on_release=self._add)
        add.add_widget(self.sf); add.add_widget(spacer(4)); add.add_widget(ab)
        root.add_widget(add); root.add_widget(spacer(6))
        students = get_students(gid)
        if students:
            root.add_widget(h2(f'{len(students)} Student(s)', color=SUBTEXT))
            root.add_widget(spacer(2))
            for s in students:
                r = row(height=54, spacing=10)
                _attach_bg(r._proxy_ref if hasattr(r, '_proxy_ref') else r, CARD2, radius=14) \
                    if False else None   # skip – use card-like Label instead
                name_box = BoxLayout(size_hint_y=None, height=dp(44), padding=[dp(14), 0])
                _attach_bg(name_box, CARD2, radius=14)
                name_box.add_widget(lbl(f'👤  {s["name"]}', 15, TEXT, height=44))
                d = btn('✕', bg=DANGER, height=44, size=14, radius=14)
                d.size_hint_x = 0.18
                d.bind(on_release=lambda *_, sid=s['id'], sn=s['name']:
                       confirm('Remove', f'Remove {sn}?',
                               on_yes=lambda: (remove_student(sid), self.on_pre_enter())))
                r.add_widget(name_box); r.add_widget(d); root.add_widget(r)
        else:
            root.add_widget(spacer(8))
            root.add_widget(lbl('  No students yet.', 14, SUBTEXT, align='center'))
        root.add_widget(spacer(12)); root.add_widget(back_btn(self.manager, 'teacher_home'))
        sv.add_widget(root); self.add_widget(sv)

    def _add(self, *_):
        name = self.sf.text.strip()
        if not name: popup('Error', 'Enter student name!'); return
        if not add_student(session['group_id'], name):
            popup('Duplicate ⚠️', f'"{name}" already exists in this group!'); return
        self.sf.text = ''; self.on_pre_enter()


class ManageSubjectsScreen(Screen):
    def on_pre_enter(self):
        self.clear_widgets()
        gid = session['group_id']; sv = ScrollView(); root = page()
        root.add_widget(h1('📚  Subjects'))
        root.add_widget(spacer(4))
        add = card(padding=16, spacing=10)
        add.add_widget(h2('Add New Subject'))
        self.sf = field('Subject name')
        ab = btn('➕  Add Subject', height=50)
        ab.bind(on_release=self._add)
        add.add_widget(self.sf); add.add_widget(spacer(4)); add.add_widget(ab)
        root.add_widget(add); root.add_widget(spacer(6))
        subjects = get_subjects(gid)
        if subjects:
            root.add_widget(h2(f'{len(subjects)} Subject(s)', color=SUBTEXT))
            root.add_widget(spacer(2))
            for s in subjects:
                r = row(height=54, spacing=10)
                name_box = BoxLayout(size_hint_y=None, height=dp(44), padding=[dp(14), 0])
                _attach_bg(name_box, CARD2, radius=14)
                name_box.add_widget(lbl(f'📚  {s["name"]}', 15, TEXT, height=44))
                d = btn('✕', bg=DANGER, height=44, size=14, radius=14)
                d.size_hint_x = 0.18
                d.bind(on_release=lambda *_, sid=s['id'], sn=s['name']:
                       confirm('Remove', f'Remove {sn}?',
                               on_yes=lambda: (remove_subject(sid), self.on_pre_enter())))
                r.add_widget(name_box); r.add_widget(d); root.add_widget(r)
        else:
            root.add_widget(spacer(8))
            root.add_widget(lbl('  No subjects yet.', 14, SUBTEXT, align='center'))
        root.add_widget(spacer(12)); root.add_widget(back_btn(self.manager, 'teacher_home'))
        sv.add_widget(root); self.add_widget(sv)

    def _add(self, *_):
        name = self.sf.text.strip()
        if not name: popup('Error', 'Enter subject name!'); return
        if not add_subject(session['group_id'], name):
            popup('Duplicate ⚠️', f'"{name}" already exists!'); return
        self.sf.text = ''; self.on_pre_enter()


class ManageParentsScreen(Screen):
    def on_pre_enter(self):
        self.clear_widgets()
        gid = session['group_id']; code = session['group_code']
        sv = ScrollView(); root = page()
        root.add_widget(h1('📱  Parent Numbers'))
        root.add_widget(spacer(4))
        info = card(padding=18, spacing=6)
        info.add_widget(lbl('Share this invite code with parents:', 13, SUBTEXT, align='center'))
        info.add_widget(spacer(4))
        code_box = BoxLayout(size_hint_y=None, height=dp(56), padding=[dp(20), 0])
        _attach_bg(code_box, CARD3, radius=16)
        code_box.add_widget(lbl(code, 32, ACCENT2, bold=True, align='center', height=56))
        info.add_widget(code_box)
        info.add_widget(spacer(2))
        info.add_widget(lbl('Parents join using: Code + Phone Number', 12, SUBTEXT, align='center'))
        root.add_widget(info); root.add_widget(spacer(6))
        add = card(padding=16, spacing=10)
        add.add_widget(h2('Register a Number'))
        self.nf = field('Phone number')
        ab = btn('➕  Add Number', height=50)
        ab.bind(on_release=self._add)
        add.add_widget(self.nf); add.add_widget(spacer(4)); add.add_widget(ab)
        root.add_widget(add); root.add_widget(spacer(6))
        numbers = get_parent_numbers(gid)
        if numbers:
            root.add_widget(h2(f'{len(numbers)} Registered', color=SUBTEXT))
            root.add_widget(spacer(2))
            for num in numbers:
                r = row(height=54, spacing=10)
                name_box = BoxLayout(size_hint_y=None, height=dp(44), padding=[dp(14), 0])
                _attach_bg(name_box, CARD2, radius=14)
                name_box.add_widget(lbl(f'📱  {num}', 15, TEXT, height=44))
                d = btn('✕', bg=DANGER, height=44, size=14, radius=14)
                d.size_hint_x = 0.18
                d.bind(on_release=lambda *_, n=num:
                       confirm('Remove', f'Remove {n}?',
                               on_yes=lambda: (remove_parent_number(gid, n), self.on_pre_enter())))
                r.add_widget(name_box); r.add_widget(d); root.add_widget(r)
        else:
            root.add_widget(spacer(8))
            root.add_widget(lbl('  No numbers registered yet.', 14, SUBTEXT, align='center'))
        root.add_widget(spacer(12)); root.add_widget(back_btn(self.manager, 'teacher_home'))
        sv.add_widget(root); self.add_widget(sv)

    def _add(self, *_):
        num = self.nf.text.strip()
        if not num: popup('Error', 'Enter phone number!'); return
        if not add_parent_number(session['group_id'], num):
            popup('Duplicate ⚠️', f'{num} already added!'); return
        self.nf.text = ''; self.on_pre_enter()


class MarkAttendanceScreen(Screen):
    def on_pre_enter(self):
        self.clear_widgets()
        gid = session['group_id']; now = datetime.now()
        date_key = now.strftime('%Y-%m-%d %A')
        date_fmt = now.strftime('%d %B %Y  —  %A')
        students = get_students(gid); existing = get_attendance_on_date(gid, date_key)
        self._status = {s['id']: existing.get(s['id'], 'P') for s in students}
        self._btn_refs = {}; self._date_key = date_key
        sv = ScrollView(); root = page()
        root.add_widget(h1('📅  Mark Attendance'))
        root.add_widget(spacer(2))

        # date badge
        date_box = BoxLayout(size_hint_y=None, height=dp(38), padding=[dp(16), 0])
        _attach_bg(date_box, CARD3, radius=14)
        date_box.add_widget(lbl(date_fmt, 13, ACCENT2, align='center', height=38))
        root.add_widget(date_box); root.add_widget(spacer(8))

        if not students:
            root.add_widget(spacer(16))
            root.add_widget(lbl('  No students yet.', 14, SUBTEXT, align='center'))
        else:
            p_count = sum(1 for v in self._status.values() if v == 'P')
            sr = row(height=44, spacing=12)
            sr_p = BoxLayout(size_hint_y=None, height=dp(36), padding=[dp(12), 0])
            _attach_bg(sr_p, (0.08, 0.30, 0.18, 1), radius=14)
            sr_p.add_widget(lbl(f'✅  Present: {p_count}', 13, SUCCESS, align='center', height=36))
            sr_a = BoxLayout(size_hint_y=None, height=dp(36), padding=[dp(12), 0])
            _attach_bg(sr_a, (0.28, 0.08, 0.08, 1), radius=14)
            sr_a.add_widget(lbl(f'❌  Absent: {len(students)-p_count}', 13, DANGER, align='center', height=36))
            sr.add_widget(sr_p); sr.add_widget(sr_a)
            root.add_widget(sr); root.add_widget(spacer(6))

            for s in students:
                sid = s['id']; status = self._status[sid]
                r = row(height=58, spacing=8)
                name = lbl(f'  {s["name"]}', 15, TEXT, height=58); name.size_hint_x = 0.50
                pb = btn('✔  P', bg=SUCCESS if status=='P' else CARD2, height=46, size=13, radius=16)
                ab = btn('✘  A', bg=DANGER  if status=='A' else CARD2, height=46, size=13, radius=16)
                pb.size_hint_x = ab.size_hint_x = 0.25
                self._btn_refs[sid] = (pb, ab)
                pb.bind(on_release=lambda *_, i=sid: self._set(i, 'P'))
                ab.bind(on_release=lambda *_, i=sid: self._set(i, 'A'))
                r.add_widget(name); r.add_widget(pb); r.add_widget(ab); root.add_widget(r)
            root.add_widget(spacer(10))
            save = btn('💾  Save Attendance', height=56)
            save.bind(on_release=self._save); root.add_widget(save)
        root.add_widget(spacer(6)); root.add_widget(back_btn(self.manager, 'teacher_home'))
        sv.add_widget(root); self.add_widget(sv)

    def _set(self, sid, val):
        self._status[sid] = val
        pb, ab = self._btn_refs[sid]
        _recolor_btn(pb, SUCCESS if val=='P' else CARD2)
        _recolor_btn(ab, DANGER  if val=='A' else CARD2)

    def _save(self, *_):
        for sid, status in self._status.items():
            save_attendance(sid, self._date_key, status)
        popup('Saved ✅', 'Attendance saved!',
              on_ok=lambda: setattr(self.manager, 'current', 'teacher_home'))


class EnterMarksScreen(Screen):
    def on_pre_enter(self):
        self.clear_widgets()
        gid = session['group_id']
        students = get_students(gid); subjects = get_subjects(gid)
        sv = ScrollView(); root = page()
        root.add_widget(h1('📊  Enter Marks'))
        root.add_widget(spacer(4))
        if not students or not subjects:
            root.add_widget(lbl('  Add students AND subjects first!', 14, SUBTEXT, align='center'))
            root.add_widget(spacer(8)); root.add_widget(back_btn(self.manager, 'teacher_home'))
            sv.add_widget(root); self.add_widget(sv); return
        ec = card(padding=16, spacing=10); ec.add_widget(h2('Select Exam'))
        existing = [e['name'] for e in get_exams(gid)]
        all_exams = list(dict.fromkeys(existing + EXAM_PRESETS))
        self.exam_sp  = mkspinner(all_exams)
        self.exam_new = field('Or type a new exam name...')
        ec.add_widget(self.exam_sp); ec.add_widget(spacer(4)); ec.add_widget(self.exam_new)
        root.add_widget(ec); root.add_widget(spacer(6))
        self._inputs = {}
        for s in students:
            sc = card(padding=16, spacing=8)
            sc.add_widget(h2(f'👤  {s["name"]}'))
            sc.add_widget(_divider())
            self._inputs[s['id']] = {}
            for sub in subjects:
                r = row(height=52, spacing=10)
                r.add_widget(lbl(f'  {sub["name"]}', 14, TEXT, height=52))
                ti = field('Marks', height=46); ti.size_hint_x = 0.34
                self._inputs[s['id']][sub['id']] = ti; r.add_widget(ti); sc.add_widget(r)
            root.add_widget(sc); root.add_widget(spacer(4))
        root.add_widget(spacer(6))
        save = btn('💾  Save All Marks', height=56)
        save.bind(on_release=self._save); root.add_widget(save)
        root.add_widget(spacer(6)); root.add_widget(back_btn(self.manager, 'teacher_home'))
        sv.add_widget(root); self.add_widget(sv)

    def _save(self, *_):
        gid = session['group_id']
        exam_name = self.exam_new.text.strip() or self.exam_sp.text
        if not exam_name: popup('Error', 'Select or type an exam name!'); return
        add_exam(gid, exam_name)
        exam = get_exam_by_name(gid, exam_name)
        if not exam: popup('Error', 'Could not create exam!'); return
        for sid, subs in self._inputs.items():
            for subj_id, ti in subs.items():
                save_mark(exam['id'], sid, subj_id, ti.text.strip() or '-')
        popup('Saved ✅', f'Marks saved for "{exam_name}"!',
              on_ok=lambda: setattr(self.manager, 'current', 'teacher_home'))


class AttendanceChartScreen(Screen):
    def on_pre_enter(self):
        self.clear_widgets()
        gid = session['group_id']; students = get_students(gid)
        sv = ScrollView(); root = page()
        root.add_widget(h1('📈  Attendance Chart'))
        root.add_widget(spacer(4))

        if not students:
            root.add_widget(lbl('  No students yet.', 14, SUBTEXT, align='center'))
        else:
            chart_data = []
            for s in students:
                records = get_attendance(s['id'])
                total   = len(records)
                present = sum(1 for r in records if r['status'] == 'P')
                chart_data.append((s['name'], present, total))

            # Legend pill row
            leg = card(padding=14, spacing=6)
            leg.add_widget(h2('Legend', color=TEXT))
            r = row(height=34, spacing=10)
            for text, color in [('🟢 ≥75%  Good', SUCCESS), ('🟡 50–74%  OK', WARN), ('🔴 <50%  Low', DANGER)]:
                pill = BoxLayout(size_hint_y=None, height=dp(28), padding=[dp(10), 0])
                _attach_bg(pill, CARD3, radius=10)
                pill.add_widget(lbl(text, 12, color, align='center', height=28))
                r.add_widget(pill)
            leg.add_widget(r); root.add_widget(leg); root.add_widget(spacer(8))

            # Per-student bar cards
            for name, present, total in chart_data:
                pct   = present / total if total > 0 else 0
                pct_s = f'{pct*100:.0f}%'
                color = SUCCESS if pct >= 0.75 else (WARN if pct >= 0.5 else DANGER)

                sc = card()
                sc.add_widget(lbl(f'👤  {name}', 14, TEXT, bold=True, height=28))

                # Bar row
                bar_row = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(6))
                # bg
                bg_bar = Widget(size_hint_x=1, size_hint_y=None, height=dp(20))
                with bg_bar.canvas:
                    Color(*CARD2)
                    bg_r = RoundedRectangle(pos=bg_bar.pos, size=bg_bar.size, radius=[dp(6)])
                bg_bar.bind(pos=lambda i, v: setattr(bg_r, 'pos', v),
                            size=lambda i, v: setattr(bg_r, 'size', v))

                fill_bar = Widget(size_hint_x=pct if pct > 0 else 0.01, size_hint_y=None, height=dp(20))
                fill_col = color
                with fill_bar.canvas:
                    fc = Color(*fill_col)
                    fill_r = RoundedRectangle(pos=fill_bar.pos, size=fill_bar.size, radius=[dp(6)])
                fill_bar.bind(pos=lambda i, v: setattr(fill_r, 'pos', v),
                              size=lambda i, v: setattr(fill_r, 'size', v))

                bar_inner = BoxLayout(size_hint_y=None, height=dp(20))
                bar_inner.add_widget(fill_bar)
                bar_inner.add_widget(Widget(size_hint_x=max(0, 1-pct)))

                bar_row.add_widget(bar_inner)
                sc.add_widget(bar_row)

                stat = row(height=22, spacing=10)
                stat.add_widget(lbl(f'Present: {present}', 12, SUCCESS, align='left'))
                stat.add_widget(lbl(f'Absent: {total-present}', 12, DANGER, align='center'))
                stat.add_widget(lbl(pct_s, 13, color, bold=True, align='right'))
                sc.add_widget(stat)
                root.add_widget(sc)

        root.add_widget(spacer(8))
        target = 'teacher_home' if session['role'] == 'teacher' else 'parent_home'
        root.add_widget(back_btn(self.manager, target))
        sv.add_widget(root); self.add_widget(sv)


class ViewAttendanceScreen(Screen):
    def on_pre_enter(self):
        self.clear_widgets()
        gid = session['group_id']; students = get_students(gid)
        sv = ScrollView(); root = page()
        root.add_widget(h1('📅 Attendance'))
        if not students:
            root.add_widget(lbl('  No students found.', color=SUBTEXT))
        else:
            for s in students:
                records = get_attendance(s['id'])
                total   = len(records)
                present = sum(1 for r in records if r['status'] == 'P')
                absent  = total - present
                pct     = f'{present/total*100:.0f}%' if total else 'N/A'
                sc = card(); sc.add_widget(h2(f'👤  {s["name"]}'))
                sr = row(height=32, spacing=10)
                sr.add_widget(lbl(f'✅ {present}', 13, SUCCESS, align='center'))
                sr.add_widget(lbl(f'❌ {absent}',  13, DANGER,  align='center'))
                sr.add_widget(lbl(f'📊 {pct}',     13, ACCENT2, align='center'))
                sc.add_widget(sr)
                for rec in records[:12]:
                    color  = SUCCESS if rec['status']=='P' else DANGER
                    marker = '✅' if rec['status']=='P' else '❌'
                    sc.add_widget(lbl(f'  {marker}  {rec["date_key"]}', 13, color, height=28))
                if total > 12:
                    sc.add_widget(caption(f'+ {total-12} more records'))
                root.add_widget(sc)
        root.add_widget(spacer(8)); root.add_widget(back_btn(self.manager, 'parent_home'))
        sv.add_widget(root); self.add_widget(sv)


class ViewMarksScreen(Screen):
    def on_pre_enter(self):
        self.clear_widgets()
        gid = session['group_id']
        exams = get_exams(gid); students = get_students(gid)
        sv = ScrollView(); root = page()
        root.add_widget(h1('📊 Marks & Results'))

        if not exams or not students:
            root.add_widget(lbl('  No results published yet.', color=SUBTEXT))
            root.add_widget(spacer(8)); root.add_widget(back_btn(self.manager, 'parent_home'))
            sv.add_widget(root); self.add_widget(sv); return

        sel = card(); sel.add_widget(h2('Step 1 — Select Exam'))
        self.exam_sp = mkspinner([e['name'] for e in exams])
        sel.add_widget(self.exam_sp); sel.add_widget(spacer(4))
        sel.add_widget(h2('Step 2 — Select Student'))
        self.stu_sp = mkspinner([s['name'] for s in students])
        sel.add_widget(self.stu_sp); root.add_widget(sel)

        view_b = btn('🔍  View Marks', height=52)
        view_b.bind(on_release=self._view); root.add_widget(view_b)

        # PDF export button (only if teacher allowed)
        if get_toggle(gid, 'pdf_export_allowed'):
            pdf_b = btn('📄  Export Report Card PDF', bg=ACCENT2, fg=(0.05,0.05,0.05,1), height=50)
            pdf_b.bind(on_release=self._export_pdf); root.add_widget(pdf_b)

        self._result = page(); root.add_widget(self._result)
        root.add_widget(spacer(8)); root.add_widget(back_btn(self.manager, 'parent_home'))
        sv.add_widget(root); self.add_widget(sv)

    def _view(self, *_):
        gid = session['group_id']
        exam = get_exam_by_name(gid, self.exam_sp.text)
        stu  = next((s for s in get_students(gid) if s['name'] == self.stu_sp.text), None)
        self._result.clear_widgets()
        if not exam or not stu:
            self._result.add_widget(lbl('  Data not found.', color=SUBTEXT)); return
        marks = get_marks(exam['id'], stu['id'])
        if not marks:
            self._result.add_widget(lbl('  No marks entered yet.', color=SUBTEXT)); return
        rc = card(); rc.add_widget(h2(f'{stu["name"]}  —  {exam["name"]}', color=ACCENT))
        total = 0; count = 0
        for m in marks:
            r = row(height=36, spacing=8)
            r.add_widget(lbl(f'  📚  {m["subject"]}', 14, TEXT, height=36))
            try:
                val = float(m['score']); color = SUCCESS if val >= 35 else DANGER
                total += val; count += 1
            except ValueError:
                color = SUBTEXT
            r.add_widget(lbl(m['score'], 15, color, bold=True, align='right', height=36))
            rc.add_widget(r)
        if count:
            avg = total / count; color = SUCCESS if avg >= 35 else DANGER
            rc.add_widget(spacer(4))
            rc.add_widget(lbl(f'Average:  {avg:.1f}', 16, color, bold=True, align='center', height=34))
        self._result.add_widget(rc)

    def _export_pdf(self, *_):
        gid  = session['group_id']
        exam = get_exam_by_name(gid, self.exam_sp.text)
        stu  = next((s for s in get_students(gid) if s['name'] == self.stu_sp.text), None)
        if not exam or not stu:
            popup('Error', 'Select exam and student first!'); return
        fname = f'ReportCard_{stu["name"].replace(" ","_")}_{exam["name"].replace(" ","_")}.pdf'
        out   = os.path.join(os.path.dirname(os.path.abspath(__file__)), fname)
        ok = export_report_card(session['group_name'], stu['name'], stu['id'],
                                exam['name'], exam['id'], out)
        if ok:
            popup('PDF Exported ✅', f'Saved as:\n{fname}')
        else:
            popup('Error ❌', 'Could not generate PDF.\nInstall: pip install reportlab')


def _bubble(sender, message, time, is_teacher):
    bg     = CARD  if is_teacher else (0.08, 0.22, 0.16, 1)
    name_c = ACCENT if is_teacher else SUCCESS
    icon   = '👨\u200d🏫' if is_teacher else '👨\u200d👩\u200d👧'
    wrap   = BoxLayout(size_hint_y=None, padding=[dp(6), dp(4)], orientation='horizontal')
    inner  = BoxLayout(orientation='vertical', size_hint_y=None, padding=[dp(14), dp(10)], spacing=dp(6))
    inner.bind(minimum_height=inner.setter('height'))
    _attach_bg(inner, bg, radius=18)
    inner.add_widget(lbl(f'{icon}  {sender}', 12, name_c, bold=True, height=24))
    inner.add_widget(lbl(message, 14, TEXT, height=None))
    inner.add_widget(lbl(time, 11, SUBTEXT, align='right', height=22))
    wrap.add_widget(inner)
    wrap.bind(minimum_height=wrap.setter('height'))
    return wrap


class TeacherChatScreen(Screen):
    _poll_event = None

    def on_pre_enter(self):
        self.clear_widgets()
        self._build_ui()
        # start polling Firebase every 4 seconds
        if self._poll_event:
            self._poll_event.cancel()
        self._poll_event = Clock.schedule_interval(self._refresh_messages, 4)

    def on_leave(self):
        if self._poll_event:
            self._poll_event.cancel()
            self._poll_event = None

    def _build_ui(self):
        gid = session['group_id']
        chat_allowed = get_toggle(gid, 'parent_reply_allowed')
        pdf_allowed  = get_toggle(gid, 'pdf_export_allowed')

        self.outer = BoxLayout(orientation='vertical', padding=[dp(16), dp(16)], spacing=dp(10))
        _full_bg(self.outer)

        # header row with online badge
        hrow = row(height=52, spacing=8)
        hrow.add_widget(h1('💬  Chat Box'))
        status_col = SUCCESS if fb_online() else WARN
        status_txt = '🟢 Live' if fb_online() else '🟡 Offline'
        badge = BoxLayout(size_hint_x=None, width=dp(80), size_hint_y=None, height=dp(30),
                          padding=[dp(8), 0])
        _attach_bg(badge, CARD3, radius=12)
        badge.add_widget(lbl(status_txt, 11, status_col, align='center', height=30))
        hrow.add_widget(badge)
        self.outer.add_widget(hrow)

        # toggles
        tog_row = row(height=50, spacing=10)
        chat_tog = btn('🟢  Reply ON' if chat_allowed else '⚫  Reply OFF',
                       bg=SUCCESS if chat_allowed else CARD2, height=46, size=13, radius=22)
        pdf_tog  = btn('🟢  PDF ON'   if pdf_allowed  else '⚫  PDF OFF',
                       bg=SUCCESS if pdf_allowed  else CARD2, height=46, size=13, radius=22)
        chat_tog.bind(on_release=lambda *_: (
            set_toggle(gid, 'parent_reply_allowed', not chat_allowed), self.on_pre_enter()))
        pdf_tog.bind(on_release=lambda *_: (
            set_toggle(gid, 'pdf_export_allowed', not pdf_allowed), self.on_pre_enter()))
        tog_row.add_widget(chat_tog); tog_row.add_widget(pdf_tog)
        self.outer.add_widget(tog_row)

        # scrollable message area
        self.sv = ScrollView(size_hint_y=1)
        self.col = BoxLayout(orientation='vertical', size_hint_y=None,
                             padding=dp(4), spacing=dp(8))
        self.col.bind(minimum_height=self.col.setter('height'))
        self._load_messages()
        self.sv.add_widget(self.col)
        self.outer.add_widget(self.sv)

        # input bar
        inp = row(height=56, spacing=8)
        self.mf = field('Type message...', height=50)
        sb = btn('Send ➤', height=50, size=14, radius=22)
        sb.size_hint_x = 0.28
        sb.bind(on_release=self._send)
        inp.add_widget(self.mf); inp.add_widget(sb)
        self.outer.add_widget(inp)
        self.outer.add_widget(back_btn(self.manager, 'teacher_home'))
        self.add_widget(self.outer)

    def _load_messages(self):
        self.col.clear_widgets()
        gid  = session['group_id']
        # try Firebase first, fall back to SQLite
        msgs = fb_get_messages(gid) if fb_online() else get_chat(gid)
        if not msgs:
            self.col.add_widget(lbl('  No messages yet.', 14, SUBTEXT, align='center'))
            return
        # Firebase returns oldest-first; SQLite returns newest-first
        if not fb_online():
            msgs = list(reversed(msgs))
        for m in msgs:
            self.col.add_widget(
                _bubble(m['sender'], m['message'], m['sent_at'], m['sender'] == 'Teacher'))
        # auto-scroll to bottom
        Clock.schedule_once(lambda *_: setattr(self.sv, 'scroll_y', 0), 0.1)

    def _refresh_messages(self, dt):
        self._load_messages()

    def _send(self, *_):
        msg = self.mf.text.strip()
        if not msg:
            return
        gid = session['group_id']
        # save to both Firebase and local SQLite (offline backup)
        fb_send_message(gid, 'Teacher', msg)
        send_chat(gid, 'Teacher', msg)
        self.mf.text = ''
        Clock.schedule_once(lambda *_: self._load_messages(), 0.8)


class ParentChatScreen(Screen):
    _poll_event = None

    def on_pre_enter(self):
        self.clear_widgets()
        self._build_ui()
        if self._poll_event:
            self._poll_event.cancel()
        self._poll_event = Clock.schedule_interval(self._refresh_messages, 4)

    def on_leave(self):
        if self._poll_event:
            self._poll_event.cancel()
            self._poll_event = None

    def _build_ui(self):
        gid     = session['group_id']
        allowed = get_toggle(gid, 'parent_reply_allowed')

        self.outer = BoxLayout(orientation='vertical', padding=[dp(16), dp(16)], spacing=dp(10))
        _full_bg(self.outer)

        # header + online badge
        hrow = row(height=52, spacing=8)
        hrow.add_widget(h1('💬  Chat Box'))
        status_col = SUCCESS if fb_online() else WARN
        status_txt = '🟢 Live' if fb_online() else '🟡 Offline'
        badge = BoxLayout(size_hint_x=None, width=dp(80), size_hint_y=None,
                          height=dp(30), padding=[dp(8), 0])
        _attach_bg(badge, CARD3, radius=12)
        badge.add_widget(lbl(status_txt, 11, status_col, align='center', height=30))
        hrow.add_widget(badge)
        self.outer.add_widget(hrow)

        status = '✅  You can reply' if allowed else '🔒  Read-only — Teacher has not allowed replies'
        self.outer.add_widget(lbl(status, 13, SUCCESS if allowed else SUBTEXT,
                                  align='center', height=30))

        self.sv = ScrollView(size_hint_y=1)
        self.col = BoxLayout(orientation='vertical', size_hint_y=None,
                             padding=dp(4), spacing=dp(8))
        self.col.bind(minimum_height=self.col.setter('height'))
        self._load_messages()
        self.sv.add_widget(self.col)
        self.outer.add_widget(self.sv)

        if allowed:
            inp = row(height=56, spacing=8)
            self.mf = field('Type your message...', height=50)
            sb = btn('Send ➤', height=50, size=14, radius=22)
            sb.size_hint_x = 0.28
            sb.bind(on_release=self._send)
            inp.add_widget(self.mf); inp.add_widget(sb)
            self.outer.add_widget(inp)

        self.outer.add_widget(back_btn(self.manager, 'parent_home'))
        self.add_widget(self.outer)

    def _load_messages(self):
        self.col.clear_widgets()
        gid  = session['group_id']
        msgs = fb_get_messages(gid) if fb_online() else get_chat(gid)
        if not msgs:
            self.col.add_widget(lbl('  No messages yet.', 14, SUBTEXT, align='center'))
            return
        if not fb_online():
            msgs = list(reversed(msgs))
        for m in msgs:
            self.col.add_widget(
                _bubble(m['sender'], m['message'], m['sent_at'], m['sender'] == 'Teacher'))
        Clock.schedule_once(lambda *_: setattr(self.sv, 'scroll_y', 0), 0.1)

    def _refresh_messages(self, dt):
        self._load_messages()

    def _send(self, *_):
        msg = self.mf.text.strip()
        if not msg:
            return
        gid    = session['group_id']
        sender = f'Parent ({session["phone"]})'
        fb_send_message(gid, sender, msg)
        send_chat(gid, sender, msg)
        self.mf.text = ''
        Clock.schedule_once(lambda *_: self._load_messages(), 0.8)


class ParentLoginScreen(Screen):
    def on_pre_enter(self):
        self.clear_widgets()
        root = BoxLayout(orientation='vertical', padding=[dp(28), dp(36)], spacing=dp(14))
        _full_bg(root)
        root.add_widget(Label())
        root.add_widget(Label(text='👨\u200d👩\u200d👧', font_size=dp(60), size_hint_y=None, height=dp(84)))
        root.add_widget(h1('Join Group'))
        root.add_widget(lbl('Enter the invite code your teacher shared', 13, SUBTEXT, align='center', height=30))
        root.add_widget(spacer(12))
        self.code_f = field('Group Invite Code  (e.g. AB12CD)')
        self.num_f  = field('Your Phone Number')
        join = icon_btn('📲', 'Join Group', height=56)
        back = back_btn(self.manager, 'role_select')
        join.bind(on_release=self._join)
        for w in [self.code_f, spacer(4), self.num_f, spacer(8), join, spacer(8), back]:
            root.add_widget(w)
        root.add_widget(Label()); self.add_widget(root)

    def _join(self, *_):
        code = self.code_f.text.strip().upper(); number = self.num_f.text.strip()
        if not code or not number: popup('Error', 'Fill both fields!'); return
        grp = get_group_by_code(code)
        if grp is None: popup('Invalid Code', 'No group found with that code!'); return
        if not number_in_group(grp['id'], number):
            popup('Not Registered', 'Your number is not registered.\nAsk your teacher to add you!'); return
        session.update(group_id=grp['id'], group_name=grp['name'],
                       group_code=grp['code'], role='parent', phone=number)
        self.manager.current = 'parent_home'


class ParentHomeScreen(Screen):
    def on_pre_enter(self):
        self.clear_widgets()
        gname = session['group_name']; phone = session['phone']
        gid   = session['group_id']

        outer = BoxLayout(orientation='vertical')
        _full_bg(outer)
        sv = ScrollView(size_hint_y=1)
        root = page()

        info = card(padding=20, spacing=8)
        info.add_widget(Label(text='👨\u200d👩\u200d👧', font_size=dp(52),
                              size_hint_y=None, height=dp(72)))
        info.add_widget(h1(gname))
        info.add_widget(spacer(2))
        phone_box = BoxLayout(size_hint_y=None, height=dp(36), padding=[dp(16), 0])
        _attach_bg(phone_box, CARD3, radius=12)
        phone_box.add_widget(lbl(f'📱  {phone}', 13, SUBTEXT, align='center', height=36))
        info.add_widget(phone_box)
        root.add_widget(info); root.add_widget(spacer(8))

        root.add_widget(h2('📋  Quick Access', color=TEXT))
        root.add_widget(spacer(4))
        for label, target, color in [
            ('📅  View Attendance',    'view_attendance', ACCENT),
            ('💬  Chat Box',           'parent_chat',     CARD2),
            ('📊  Marks & Results',    'view_marks',      CARD2),
            ('📈  Attendance Chart',   'att_chart',       CARD2)]:
            b = btn(label, bg=color, height=58)
            b.bind(on_release=lambda *_, t=target: setattr(self.manager, 'current', t))
            root.add_widget(b)

        root.add_widget(spacer(10))
        out = btn('🚪  Leave Group', bg=DANGER, height=48)
        out.bind(on_release=lambda *_: confirm('Leave', 'Leave this group?', on_yes=self._leave))
        root.add_widget(out)
        sv.add_widget(root)
        outer.add_widget(sv)
        outer.add_widget(bottom_nav(self.manager, PARENT_NAV, 'parent_home'))
        self.add_widget(outer)

    def _leave(self):
        session.update(group_id=None, group_name=None, group_code=None, role=None, phone=None)
        self.manager.current = 'role_select'


# ════════════════════════════════════════════════════════════════════
#  SETTINGS SCREEN
# ════════════════════════════════════════════════════════════════════
class SettingsScreen(Screen):
    def on_pre_enter(self):
        self.clear_widgets()
        role = session.get('role', 'teacher')
        prefs = _load_prefs()

        outer = BoxLayout(orientation='vertical')
        _full_bg(outer)
        sv = ScrollView(size_hint_y=1)
        root = page()

        root.add_widget(h1('⚙️  Settings'))
        root.add_widget(spacer(4))

        # ── Profile card ──
        gname = session.get('group_name') or 'Not logged in'
        phone = session.get('phone') or ''
        pc = card(padding=18, spacing=6)
        pr = row(height=64, spacing=14)
        # avatar
        av = BoxLayout(size_hint_x=None, width=dp(56), size_hint_y=None, height=dp(56))
        _attach_bg(av, ACCENT, radius=28)
        av.add_widget(Label(text='👤', font_size=dp(28), size_hint_y=None, height=dp(56)))
        info_col = BoxLayout(orientation='vertical', spacing=dp(2))
        info_col.add_widget(lbl(gname, 16, TEXT, bold=True, height=28))
        info_col.add_widget(lbl(phone or ('Teacher' if role=='teacher' else 'Parent'),
                                13, SUBTEXT, height=22))
        pr.add_widget(av); pr.add_widget(info_col)
        pc.add_widget(pr)
        root.add_widget(pc); root.add_widget(spacer(8))

        # ── Appearance ──
        root.add_widget(lbl('  APPEARANCE', 11, SUBTEXT, height=24))
        root.add_widget(spacer(4))
        # Dark/Light toggle
        mode_lbl = '🌙  Dark Mode' if _theme_is_dark else '☀️  Light Mode'
        mode_sub  = 'Currently dark' if _theme_is_dark else 'Currently light'
        dm_btn = btn(mode_lbl, bg=CARD2, fg=TEXT, height=56, size=14)
        dm_btn.bind(on_release=lambda *_: self._toggle_theme())
        root.add_widget(dm_btn)
        root.add_widget(spacer(8))

        # ── Font Color ──
        root.add_widget(lbl('  FONT COLOR', 11, SUBTEXT, height=24))
        root.add_widget(spacer(4))
        prefs     = _load_prefs()
        cur_color = prefs.get('font_color', 'default')
        fc_row    = row(height=58, spacing=10)

        color_opts = [
            ('default', 'Default', TEXT),
            ('black',   'Black',   (0.05, 0.05, 0.05, 1)),
            ('white',   'White',   (0.97, 0.97, 0.97, 1)),
            ('teal',    'Teal',    (0.18, 0.82, 0.72, 1)),
        ]
        for key, label, clr in color_opts:
            active = (cur_color == key)
            b = Button(
                text=label, font_size=dp(13), bold=active,
                color=clr if key != 'default' else TEXT,
                size_hint_y=None, height=dp(52),
                background_normal='', background_color=(0,0,0,0))
            border_color = ACCENT if active else CARD2
            with b.canvas.before:
                Color(*border_color)
                rr = RoundedRectangle(pos=b.pos, size=b.size, radius=[dp(16)])
                Color(*CARD2 if not active else (*ACCENT[:3], 0.2))
                ri = RoundedRectangle(pos=(b.x+2, b.y+2),
                                      size=(b.width-4, b.height-4), radius=[dp(14)])
            b.bind(pos=lambda i, r=rr, ri=ri: (setattr(r,'pos',i.pos), setattr(ri,'pos',(i.x+2,i.y+2))),
                   size=lambda i, r=rr, ri=ri: (setattr(r,'size',i.size), setattr(ri,'size',(i.width-4,i.height-4))))
            b.bind(on_release=lambda *_, k=key: self._set_font_color(k))
            fc_row.add_widget(b)

        root.add_widget(fc_row)
        root.add_widget(spacer(6))
        root.add_widget(lbl('  ACCOUNT', 11, SUBTEXT, height=24))
        root.add_widget(spacer(4))
        if role == 'teacher':
            cp = btn('🔑  Change PIN', bg=CARD2, fg=TEXT, height=54, size=14)
            cp.bind(on_release=lambda *_: self._change_pin())
            root.add_widget(cp); root.add_widget(spacer(6))

        # ── Data ──
        root.add_widget(lbl('  DATA', 11, SUBTEXT, height=24))
        root.add_widget(spacer(4))
        bk = btn('💾  Backup Database', bg=CARD2, fg=TEXT, height=54, size=14)
        rs = btn('📂  Restore Database', bg=CARD2, fg=TEXT, height=54, size=14)
        cc = btn('🗑️  Clear Chat History', bg=CARD2, fg=TEXT, height=54, size=14)
        bk.bind(on_release=lambda *_: self._backup())
        rs.bind(on_release=lambda *_: self._restore())
        cc.bind(on_release=lambda *_: self._clear_chat())
        root.add_widget(bk); root.add_widget(spacer(4))
        root.add_widget(rs); root.add_widget(spacer(4))
        root.add_widget(cc); root.add_widget(spacer(8))

        # ── About ──
        root.add_widget(lbl('  ABOUT', 11, SUBTEXT, height=24))
        root.add_widget(spacer(4))
        ab = card(padding=16, spacing=4)
        ab.add_widget(lbl('JUST App', 16, ACCENT, bold=True, align='center', height=30))
        ab.add_widget(lbl('Version 5.0', 13, SUBTEXT, align='center', height=24))
        ab.add_widget(lbl('by Luffy Applications 🏴\u200d☠️', 13, SUBTEXT, align='center', height=24))
        ab.add_widget(lbl('Firebase Realtime Chat Enabled', 12, SUCCESS, align='center', height=22))
        root.add_widget(ab); root.add_widget(spacer(10))

        # logout
        out = btn('🚪  Logout', bg=DANGER, height=50)
        out.bind(on_release=lambda *_: confirm('Logout', 'Sure?', on_yes=self._logout))
        root.add_widget(out)

        sv.add_widget(root)
        outer.add_widget(sv)
        nav = TEACHER_NAV if role == 'teacher' else PARENT_NAV
        outer.add_widget(bottom_nav(self.manager, nav, 'settings'))
        self.add_widget(outer)

    def _toggle_theme(self):
        toggle_theme()
        self.on_pre_enter()

    def _set_font_color(self, key):
        set_font_color(key)
        self.on_pre_enter()
        popup('Done!', f'Font color set to {key.capitalize()}!')

    def _change_pin(self):
        body = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(12),
                         size_hint_y=None, height=dp(280))
        _attach_bg(body, CARD, radius=20)
        body.add_widget(h2('Change PIN'))
        old_f = field('Current PIN', password=True)
        new_f = field('New PIN (min 4 digits)', password=True)
        cnf_f = field('Confirm New PIN', password=True)
        ok    = btn('✅  Update PIN', height=48)
        body.add_widget(old_f); body.add_widget(new_f)
        body.add_widget(cnf_f); body.add_widget(spacer(4)); body.add_widget(ok)
        p = Popup(title='Change PIN', content=body, size_hint=(0.9, None), height=dp(340),
                  title_color=ACCENT, separator_color=ACCENT, background_color=CARD3)
        def _do(*_):
            gid = session['group_id']
            if not verify_teacher_pin(gid, old_f.text.strip()):
                popup('Error', 'Current PIN is wrong!'); return
            if len(new_f.text.strip()) < 4:
                popup('Error', 'New PIN must be 4+ digits!'); return
            if new_f.text.strip() != cnf_f.text.strip():
                popup('Error', 'PINs do not match!'); return
            with _conn() as con:
                con.execute("UPDATE groups SET teacher_pin=? WHERE id=?",
                            (new_f.text.strip(), gid))
            p.dismiss(); popup('✅ Success', 'PIN changed successfully!')
        ok.bind(on_release=_do); p.open()

    def _backup(self):
        try:
            bk = DB_PATH + '.backup'
            shutil.copy2(DB_PATH, bk)
            popup('✅ Backup Done', f'Saved to:\n{bk}')
        except Exception as e:
            popup('Error', str(e))

    def _restore(self):
        bk = DB_PATH + '.backup'
        if not os.path.exists(bk):
            popup('No Backup', 'No backup file found!'); return
        confirm('Restore', 'This will replace current data with backup!',
                on_yes=self._do_restore)

    def _do_restore(self):
        try:
            shutil.copy2(DB_PATH + '.backup', DB_PATH)
            popup('✅ Restored', 'Database restored from backup!')
        except Exception as e:
            popup('Error', str(e))

    def _clear_chat(self):
        gid = session.get('group_id')
        if not gid: return
        confirm('Clear Chat', 'Delete ALL chat messages?',
                on_yes=lambda: self._do_clear(gid))

    def _do_clear(self, gid):
        with _conn() as con:
            con.execute("DELETE FROM chat WHERE group_id=?", (gid,))
        popup('✅ Done', 'Chat history cleared!')

    def _logout(self):
        session.update(group_id=None, group_name=None, group_code=None, role=None, phone=None)
        self.manager.current = 'role_select'


# ════════════════════════════════════════════════════════════════════
#  FORGOT PIN SCREEN
# ════════════════════════════════════════════════════════════════════
class ForgotPINScreen(Screen):
    def on_pre_enter(self):
        self.clear_widgets()
        root = BoxLayout(orientation='vertical', padding=[dp(28), dp(36)], spacing=dp(14))
        _full_bg(root)
        root.add_widget(Label())
        root.add_widget(Label(text='🔐', font_size=dp(64), size_hint_y=None, height=dp(88)))
        root.add_widget(h1('Forgot PIN'))
        root.add_widget(lbl('Enter your group name to get your recovery code',
                            13, SUBTEXT, align='center', height=36))
        root.add_widget(spacer(8))
        self.gf = field('Group Name')
        find = btn('🔍  Find Recovery Code', height=54)
        find.bind(on_release=self._find)
        back = back_btn(self.manager, 'teacher_login')
        for w in [self.gf, spacer(8), find, spacer(8), back]:
            root.add_widget(w)
        root.add_widget(Label())
        self.add_widget(root)

    def _find(self, *_):
        name = self.gf.text.strip()
        if not name:
            popup('Error', 'Enter your group name!'); return
        g = get_group_by_name(name)
        if not g:
            popup('Not Found', f'No group named "{name}" found!'); return
        rc = g.get('recovery_code') or '(not set — old group)'
        body = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(12),
                         size_hint_y=None, height=dp(240))
        _attach_bg(body, CARD, radius=20)
        body.add_widget(h2('Your Recovery Code'))
        body.add_widget(spacer(4))
        code_box = BoxLayout(size_hint_y=None, height=dp(56), padding=[dp(16), 0])
        _attach_bg(code_box, CARD3, radius=14)
        code_box.add_widget(lbl(rc, 28, ACCENT2, bold=True, align='center', height=56))
        body.add_widget(code_box)
        body.add_widget(spacer(4))
        body.add_widget(lbl('Show this to your admin to verify identity.\nThen reset your PIN in Settings.',
                            12, SUBTEXT, align='center', height=48))
        ok = btn('OK  Got it!', height=46)
        body.add_widget(ok)
        p = Popup(title=f'Group: {name}', content=body, size_hint=(0.9, None), height=dp(300),
                  title_color=ACCENT, separator_color=ACCENT, background_color=CARD3)
        ok.bind(on_release=p.dismiss); p.open()


# ════════════════════════════════════════════════════════════════════
#  APP
# ════════════════════════════════════════════════════════════════════
class JustApp(App):
    title = 'JUST — Smart Attendance v5'

    def build(self):
        init_db()
        _init_prefs()
        sm = ScreenManager(transition=FadeTransition(duration=0.22))
        for s in [
            SplashScreen         (name='splash'),
            RoleSelectScreen     (name='role_select'),
            TeacherLoginScreen   (name='teacher_login'),
            ForgotPINScreen      (name='forgot_pin'),
            TeacherHomeScreen    (name='teacher_home'),
            ManageStudentsScreen (name='manage_students'),
            ManageSubjectsScreen (name='manage_subjects'),
            ManageParentsScreen  (name='manage_parents'),
            MarkAttendanceScreen (name='mark_attendance'),
            EnterMarksScreen     (name='enter_marks'),
            AttendanceChartScreen(name='att_chart'),
            ViewAttendanceScreen (name='view_attendance'),
            ViewMarksScreen      (name='view_marks'),
            TeacherChatScreen    (name='teacher_chat'),
            ParentChatScreen     (name='parent_chat'),
            ParentLoginScreen    (name='parent_login'),
            ParentHomeScreen     (name='parent_home'),
            SettingsScreen       (name='settings'),
        ]:
            sm.add_widget(s)
        return sm


if __name__ == '__main__':
    JustApp().run()
