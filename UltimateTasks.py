import json, os, uuid, sys, random, webbrowser, threading, shutil
from datetime import datetime, timedelta, date
from calendar import monthcalendar, month_name

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QLabel, QCheckBox, QComboBox, QDialog,
    QScrollArea, QTextEdit, QProgressBar, QSizePolicy, QFrame, QMenu,
    QMessageBox, QTabWidget, QStackedWidget, QSystemTrayIcon, QStyle,
    QSpinBox, QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QGridLayout, QFileDialog
)
from PySide6.QtCore import Qt, Signal, QTimer, QMimeData, QByteArray, QDataStream, QIODevice, QObject
from PySide6.QtGui import QColor, QClipboard, QDrag, QShortcut, QKeySequence, QAction, QIcon, QFont

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build as gcal_build
    GCAL_AVAILABLE = True
except ImportError:
    GCAL_AVAILABLE = False

# ── Data file paths ──
DATA_FILE = 'todo_kanban_data.json'
ARCHIVE_FILE = 'todo_archive.json'
TREE_FILE = 'decision_tree_data.json'
PROSCONS_FILE = 'proscons_data.json'
MATRIX_FILE = 'decision_matrix_data.json'
PICKER_FILE = 'random_picker_data.json'
GCAL_TOKEN_FILE = 'google_calendar_token.json'
GCAL_CREDS_FILE = 'google_calendar_credentials.json'
GCAL_SETTINGS_FILE = 'gcal_settings.json'
NOTIF_SETTINGS_FILE = 'notification_settings.json'
TIMEBOX_FILE = 'timebox_sessions.json'
STATE_FILE = 'app_ui_state.json'
BACKUP_COUNT = 3  # number of .bak files to keep
GCAL_SCOPES = ['https://www.googleapis.com/auth/calendar.events',
               'https://www.googleapis.com/auth/calendar.readonly']


DARK_THEME = {
    'BG_COLOR': '#262626', 'TEXT_COLOR': '#E6E6E6',
    'COMPLETED_COLOR': '#808080', 'ACCENT_COLOR': '#4D99FF',
    'DELETE_COLOR': '#E64D4D', 'EDIT_COLOR': '#33B3E6',
    'INPUT_BG': '#404040', 'CARD_BG': '#333333',
    'CARD_HOVER': '#3A3A3A', 'PROGRESS_BG': '#4D4D4D', 'PROGRESS_FG': '#33CC66',
    'POPUP_BG': '#1A1A1A', 'KANBAN_COL_BG': '#2E2E2E',
    'FOCUS_BG': '#1E1E2E', 'FOCUS_ACTIVE': '#A6E3A1',
    'IS_DARK': True
}
LIGHT_THEME = {
    'BG_COLOR': '#F2F2F2', 'TEXT_COLOR': '#1A1A1A',
    'COMPLETED_COLOR': '#808080', 'ACCENT_COLOR': '#3380E6',
    'DELETE_COLOR': '#E63333', 'EDIT_COLOR': '#1A99CC',
    'INPUT_BG': '#FFFFFF', 'CARD_BG': '#FFFFFF',
    'CARD_HOVER': '#F9F9F9', 'PROGRESS_BG': '#CCCCCC', 'PROGRESS_FG': '#4DCC66',
    'POPUP_BG': '#FFFFFF', 'KANBAN_COL_BG': '#E6E6E6',
    'FOCUS_BG': '#EFF5F0', 'FOCUS_ACTIVE': '#2E7D32',
    'IS_DARK': False
}

PRIORITY_COLORS_DARK = {'High': '#E64D4D', 'Medium': '#E6B333', 'Low': '#4DCC66'}
PRIORITY_COLORS_LIGHT = {'High': '#CC1A1A', 'Medium': '#E69900', 'Low': '#1A991A'}

STAGES = ['To Do', 'In Progress', 'Review', 'Done']
REPEATS = ['None', 'Daily', 'Weekly', 'Monthly']

def fmt_duration(seconds):
    """Format seconds into HH:MM:SS or MM:SS string."""
    seconds = int(seconds)
    h, seconds = divmod(seconds, 3600)
    m, s = divmod(seconds, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def fmt_time_badge(task_data, theme):
    """Return (text, color) for a time spent/estimate badge, or None."""
    spent = task_data.get('time_spent_seconds', 0) or 0
    estimate = task_data.get('time_estimate_minutes', 0) or 0
    if not spent and not estimate:
        return None
    parts = []
    if spent:
        parts.append(f"\u23f1{fmt_duration(spent)}")
    if estimate:
        parts.append(f"\u23f0{estimate}m")
    text = " ".join(parts)
    if estimate and spent >= estimate * 60:
        color = theme['DELETE_COLOR']  # over estimate
    elif spent:
        color = theme['PROGRESS_FG']  # has tracked time
    else:
        color = theme['ACCENT_COLOR']  # only estimate
    return (text, color)


def clear_layout(layout):
    while layout.count():
        child = layout.takeAt(0)
        if child.widget():
            child.widget().deleteLater()
        elif child.layout():
            clear_layout(child.layout())


def atomic_write(filepath, data_str):
    """Write data atomically: write to temp file, then rename. Returns True on success."""
    tmp = filepath + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            f.write(data_str)
        for i in range(BACKUP_COUNT - 1, 0, -1):
            src = f"{filepath}.bak{i}" if i > 1 else f"{filepath}.bak"
            dst = f"{filepath}.bak{i + 1}" if i > 1 else f"{filepath}.bak2"
            if os.path.exists(src):
                shutil.copy2(src, dst)
        if os.path.exists(filepath):
            shutil.copy2(filepath, filepath + '.bak')
        os.replace(tmp, filepath)
        return True
    except Exception:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass
        return False


def safe_json_dump(filepath, obj, indent=4):
    """Serialize and atomically write a JSON file. Returns True on success."""
    try:
        data_str = json.dumps(obj, indent=indent, ensure_ascii=False)
        return atomic_write(filepath, data_str)
    except Exception:
        return False


def safe_json_load(filepath, default=None):
    """Load JSON with fallback to backup files. Returns default on all failures."""
    if default is None:
        default = []
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    for suffix in ['.bak', '.bak2', '.bak3']:
        bak_path = filepath + suffix
        if os.path.exists(bak_path):
            try:
                with open(bak_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                try:
                    shutil.copy2(bak_path, filepath)
                except Exception:
                    pass
                return data
            except Exception:
                continue
    return default


class TaskFormDialog(QDialog):
    def __init__(self, save_callback, task_to_edit=None, theme=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Task" if task_to_edit else "Add New Task")
        self.resize(450, 500)
        self.theme = theme or DARK_THEME
        self.save_callback = save_callback
        self.task_to_edit = task_to_edit

        layout = QVBoxLayout(self)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText('Task Name *')
        layout.addWidget(self.name_input)

        self.desc_input = QTextEdit()
        self.desc_input.setPlaceholderText('Description')
        self.desc_input.setMaximumHeight(80)
        layout.addWidget(self.desc_input)

        row1 = QHBoxLayout()
        self.priority_combo = QComboBox()
        self.priority_combo.addItems(['High', 'Medium', 'Low'])
        self.stage_combo = QComboBox()
        self.stage_combo.addItems(STAGES)
        self.repeats_combo = QComboBox()
        self.repeats_combo.addItems(REPEATS)
        row1.addWidget(self.priority_combo)
        row1.addWidget(self.stage_combo)
        row1.addWidget(self.repeats_combo)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.category_input = QLineEdit()
        self.category_input.setPlaceholderText('Project (e.g., Work)')
        self.context_input = QLineEdit()
        self.context_input.setPlaceholderText('Context (@Office)')
        row2.addWidget(self.category_input)
        row2.addWidget(self.context_input)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.tags_input = QLineEdit()
        self.tags_input.setPlaceholderText('Tags (comma sep)')
        self.date_input = QLineEdit()
        self.date_input.setPlaceholderText('Due (YYYY-MM-DD)')
        row3.addWidget(self.tags_input)
        row3.addWidget(self.date_input)
        layout.addLayout(row3)

        # Time estimate row
        time_row = QHBoxLayout()
        self.estimate_spin = QSpinBox()
        self.estimate_spin.setRange(0, 480)
        self.estimate_spin.setValue(0)
        self.estimate_spin.setSuffix(' min')
        self.estimate_spin.setSpecialValueText('No estimate')
        self.estimate_spin.setToolTip('Estimated time to complete (minutes)')
        time_row.addWidget(QLabel('Time Est:'))
        time_row.addWidget(self.estimate_spin)
        time_row.addStretch()
        layout.addLayout(time_row)

        self.subtask_input = QLineEdit()
        self.subtask_input.setPlaceholderText('Subtasks (comma separated)')
        layout.addWidget(self.subtask_input)

        self.save_btn = QPushButton('Save Task')
        self.save_btn.clicked.connect(self.save_task)
        layout.addWidget(self.save_btn)

        if self.task_to_edit:
            self.name_input.setText(self.task_to_edit['text'])
            self.desc_input.setText(self.task_to_edit.get('description', ''))
            self.priority_combo.setCurrentText(self.task_to_edit['priority'])
            self.stage_combo.setCurrentText(self.task_to_edit['stage'])
            self.repeats_combo.setCurrentText(self.task_to_edit.get('repeats', 'None'))
            self.category_input.setText(self.task_to_edit['category'])
            self.context_input.setText(self.task_to_edit.get('context', ''))
            self.tags_input.setText(self.task_to_edit.get('tags', ''))
            self.date_input.setText(self.task_to_edit.get('due_date', ''))
            self.estimate_spin.setValue(self.task_to_edit.get('time_estimate_minutes', 0))
            subs = self.task_to_edit.get('subtasks', [])
            self.subtask_input.setText(", ".join([s['text'] for s in subs]))

        self.apply_theme()

    def apply_theme(self):
        self.setStyleSheet(f"""
            QDialog {{ background-color: {self.theme['POPUP_BG']}; color: {self.theme['TEXT_COLOR']}; }}
            QLineEdit, QTextEdit, QComboBox {{
                background-color: {self.theme['INPUT_BG']}; color: {self.theme['TEXT_COLOR']};
                border: 1px solid {self.theme['PROGRESS_BG']}; padding: 5px; border-radius: 3px;
            }}
            QPushButton {{
                background-color: {self.theme['ACCENT_COLOR']}; color: white; border: none; padding: 8px; border-radius: 3px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {self.theme['EDIT_COLOR']}; }}
        """)

    def save_task(self):
        name = self.name_input.text().strip()
        if not name: return
        
        priority = self.priority_combo.currentText()
        stage = self.stage_combo.currentText()
        repeats = self.repeats_combo.currentText()
        category = self.category_input.text().strip() or 'General'
        context = self.context_input.text().strip()
        tags = self.tags_input.text().strip()
        due_date = self.date_input.text().strip()
        description = self.desc_input.toPlainText().strip()
        
        subtask_str = self.subtask_input.text().strip()
        subtasks = []
        if subtask_str:
            existing_subs = {}
            if self.task_to_edit:
                for s in self.task_to_edit.get('subtasks', []): existing_subs[s['text']] = s['done']
            for st in subtask_str.split(','):
                st = st.strip()
                if st: subtasks.append({'text': st, 'done': existing_subs.get(st, False)})

        if due_date:
            try: datetime.strptime(due_date, '%Y-%m-%d')
            except ValueError:
                self.date_input.setText("")
                self.date_input.setPlaceholderText("Invalid! Use YYYY-MM-DD")
                return

        task_id = self.task_to_edit['id'] if self.task_to_edit else None
        self.save_callback(task_id, name, priority, stage, category, context, tags, due_date, description, repeats, subtasks, self.estimate_spin.value())
        self.accept()


class ArchiveDialog(QDialog):
    def __init__(self, archive_list, restore_callback, theme, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🗄️ Archive")
        self.resize(400, 500)
        self.theme = theme
        self.restore_callback = restore_callback
        self.archive_list = archive_list

        layout = QVBoxLayout(self)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self.list_layout = QVBoxLayout(container)
        self.list_layout.setAlignment(Qt.AlignTop)
        
        if not archive_list:
            self.list_layout.addWidget(QLabel("Archive is empty."))
        else:
            for t in archive_list:
                row = QHBoxLayout()
                lbl = QLabel(t['text'])
                lbl.setStyleSheet(f"color: {self.theme['COMPLETED_COLOR']};")
                btn = QPushButton("Restore")
                btn.setFixedWidth(80)
                btn.clicked.connect(lambda checked, task=t: self.restore_task(task))
                row.addWidget(lbl)
                row.addWidget(btn)
                self.list_layout.addLayout(row)

        scroll.setWidget(container)
        layout.addWidget(scroll)

        close_btn = QPushButton('Close')
        close_btn.clicked.connect(self.close)
        layout.addWidget(close_btn)
        
        self.apply_theme()

    def restore_task(self, task):
        self.restore_callback(task)
        clear_layout(self.list_layout)
        self.archive_list = [t for t in self.archive_list if t['id'] != task['id']]
        if not self.archive_list:
            self.list_layout.addWidget(QLabel("Archive is empty."))
        else:
            for t in self.archive_list:
                row = QHBoxLayout()
                lbl = QLabel(t['text'])
                lbl.setStyleSheet(f"color: {self.theme['COMPLETED_COLOR']};")
                btn = QPushButton("Restore")
                btn.setFixedWidth(80)
                btn.clicked.connect(lambda checked, task=t: self.restore_task(task))
                row.addWidget(lbl)
                row.addWidget(btn)
                self.list_layout.addLayout(row)

    def apply_theme(self):
        self.setStyleSheet(f"""
            QDialog {{ background-color: {self.theme['POPUP_BG']}; color: {self.theme['TEXT_COLOR']}; }}
            QPushButton {{ background-color: {self.theme['ACCENT_COLOR']}; color: white; border: none; padding: 5px; border-radius: 3px; }}
            QScrollArea {{ border: none; }}
        """)


class SubtaskRow(QWidget):
    delete_signal = Signal()

    def __init__(self, subtask_dict, update_callback, theme):
        super().__init__()
        self.subtask_dict = subtask_dict
        self.update_callback = update_callback
        self.theme = theme
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 20, 0)
        
        self.cb = QCheckBox()
        self.cb.setChecked(subtask_dict['done'])
        self.cb.stateChanged.connect(self.on_toggle)
        
        self.lbl = QLabel(subtask_dict['text'])
        self.update_label_style()

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(20, 20)
        del_btn.setStyleSheet(f"background:{theme['DELETE_COLOR']};color:white;border:none;border-radius:3px;font-size:10px;")
        del_btn.clicked.connect(self.delete_signal.emit)
        
        layout.addWidget(self.cb)
        layout.addWidget(self.lbl, 1)
        layout.addWidget(del_btn)

    def on_toggle(self, state):
        self.subtask_dict['done'] = bool(state)
        self.update_callback()
        self.update_label_style()

    def update_label_style(self):
        color = self.theme['COMPLETED_COLOR'] if self.subtask_dict['done'] else self.theme['TEXT_COLOR']
        deco = "line-through" if self.subtask_dict['done'] else "none"
        self.lbl.setStyleSheet(f"color: {color}; text-decoration: {deco};")


class TaskItemWidget(QWidget):
    toggle_signal = Signal()
    delete_signal = Signal(dict)
    edit_signal = Signal(dict)
    add_recurring_signal = Signal(dict)
    add_subtask_signal = Signal(dict, str)
    delete_subtask_signal = Signal(dict, str)  # task_data, subtask_text
    start_timer_signal = Signal(dict)  # task_data — for quick-focus

    def __init__(self, task_data, theme):
        super().__init__()
        self.task_data = task_data
        self.theme = theme
        self.p_colors = PRIORITY_COLORS_DARK if theme['IS_DARK'] else PRIORITY_COLORS_LIGHT
        self.is_expanded = False

        self.setAutoFillBackground(True)
        self.apply_card_style()
        self.setMouseTracking(True)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 8, 10, 8)
        main_layout.setSpacing(4)

        # Top Row
        top_row = QHBoxLayout()
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(self.task_data['completed'])
        self.checkbox.stateChanged.connect(self.on_checkbox_active)
        
        self.label = QLabel(self.task_data['text'])
        self.label.setWordWrap(True)
        self.update_title_style()

        p_color = self.p_colors.get(self.task_data['priority'], self.theme['TEXT_COLOR'])
        priority_lbl = QLabel(f"[{self.task_data['priority']}]")
        priority_lbl.setStyleSheet(f"color: {p_color}; font-weight: bold; font-size: 12px;")

        repeat_icon = "🔄" if self.task_data.get('repeats') != 'None' else ""
        repeat_lbl = QLabel(repeat_icon)
        repeat_lbl.setStyleSheet(f"font-size: 14px; color: {self.theme['ACCENT_COLOR']};")

        edit_btn = QPushButton("✏️")
        edit_btn.setFixedSize(30, 30)
        edit_btn.setStyleSheet(f"background-color: {self.theme['EDIT_COLOR']}; border: none; border-radius: 5px;")
        edit_btn.clicked.connect(lambda: self.edit_signal.emit(self.task_data))

        delete_btn = QPushButton("X")
        delete_btn.setFixedSize(30, 30)
        delete_btn.setStyleSheet(f"background-color: {self.theme['DELETE_COLOR']}; color: white; border: none; border-radius: 5px;")
        delete_btn.clicked.connect(lambda: self.delete_signal.emit(self.task_data))

        timer_btn = QPushButton("\u23f1")
        timer_btn.setFixedSize(30, 30)
        timer_btn.setToolTip("Start focus timer for this task")
        timer_btn.setStyleSheet(f"background-color: {self.theme['ACCENT_COLOR']}; color: white; border: none; border-radius: 5px;")
        timer_btn.clicked.connect(lambda: self.start_timer_signal.emit(self.task_data))

        top_row.addWidget(self.checkbox)
        top_row.addWidget(self.label, 1)
        top_row.addWidget(priority_lbl)
        top_row.addWidget(repeat_lbl)
        top_row.addWidget(edit_btn)
        top_row.addWidget(timer_btn)
        top_row.addWidget(delete_btn)

        # Mid Row
        mid_row = QHBoxLayout()
        stage_color = self.theme['ACCENT_COLOR'] if self.task_data['stage'] != 'Done' else self.theme['PROGRESS_FG']
        stage_lbl = QLabel(f"🔄 {self.task_data['stage']}")
        stage_lbl.setStyleSheet(f"color: {stage_color}; font-size: 12px;")
        
        date_text = self.task_data.get('due_date', '')
        date_color = self.theme['TEXT_COLOR']
        if self.task_data['completed'] and self.task_data.get('completed_date'):
            date_text = f"Done: {self.task_data['completed_date']}"
            date_color = self.theme['COMPLETED_COLOR']
        elif not self.task_data['completed'] and date_text:
            try:
                due_dt = datetime.strptime(date_text, '%Y-%m-%d')
                now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                if due_dt < now: 
                    date_text = f"{date_text} (OVERDUE)"
                    date_color = "#FF4D4D"
                elif due_dt == now: 
                    date_text = f"{date_text} (TODAY)"
                    date_color = "#FFCC33"
            except ValueError: pass
        
        date_lbl = QLabel(date_text)
        date_lbl.setStyleSheet(f"color: {date_color}; font-size: 12px;")

        subs = self.task_data.get('subtasks', [])
        subtask_text = ""
        subtask_color = self.theme['TEXT_COLOR']
        if subs:
            done_subs = sum(1 for s in subs if s['done'])
            subtask_text = f"📋 {done_subs}/{len(subs)}"
            subtask_color = self.theme['PROGRESS_FG'] if done_subs == len(subs) else self.theme['ACCENT_COLOR']
            
        subtask_lbl = QLabel(subtask_text)
        subtask_lbl.setAlignment(Qt.AlignRight)
        subtask_lbl.setStyleSheet(f"color: {subtask_color}; font-size: 12px;")

        time_badge = fmt_time_badge(self.task_data, self.theme)
        time_lbl = None
        if time_badge:
            time_lbl = QLabel(time_badge[0])
            time_lbl.setAlignment(Qt.AlignRight)
            time_lbl.setStyleSheet(f"color: {time_badge[1]}; font-size: 12px;")

        mid_row.addWidget(stage_lbl)
        mid_row.addWidget(date_lbl, 1)
        mid_row.addWidget(subtask_lbl)
        if time_lbl:
            mid_row.addWidget(time_lbl)

        # Bot Row
        bot_row = QHBoxLayout()
        ctx_text = f"📍 {self.task_data['context']}" if self.task_data.get('context') else ""
        tags_text = f"🏷️ {self.task_data['tags']}" if self.task_data.get('tags') else ""
        ctx_lbl = QLabel(ctx_text)
        ctx_lbl.setStyleSheet("color: #99CC99; font-size: 12px;")
        tags_lbl = QLabel(tags_text)
        tags_lbl.setStyleSheet("color: #CC80CC; font-size: 12px;")
        bot_row.addWidget(ctx_lbl)
        bot_row.addStretch()
        bot_row.addWidget(tags_lbl)

        main_layout.addLayout(top_row)
        main_layout.addLayout(mid_row)
        main_layout.addLayout(bot_row)

        # Subtask Area
        self.subtask_layout = QVBoxLayout()
        self.subtask_layout.setSpacing(2)
        main_layout.addLayout(self.subtask_layout)

        if subs:
            expand_btn = QPushButton("Toggle Subtasks")
            expand_btn.setFixedHeight(25)
            expand_btn.setStyleSheet(f"background-color: {self.theme['INPUT_BG']}; color: {self.theme['TEXT_COLOR']}; border: none; border-radius: 3px; font-size: 11px;")
            expand_btn.clicked.connect(self.toggle_expand)
            main_layout.addWidget(expand_btn)

    def apply_card_style(self):
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(self.theme['CARD_BG']))
        self.setPalette(pal)
        self.setStyleSheet(f"TaskItemWidget {{ background-color: {self.theme['CARD_BG']}; border-radius: 5px; border: 1px solid {self.theme['PROGRESS_BG']}; }}")

    def update_title_style(self):
        color = self.theme['COMPLETED_COLOR'] if self.task_data['completed'] else self.theme['TEXT_COLOR']
        deco = "line-through" if self.task_data['completed'] else "none"
        self.label.setStyleSheet(f"color: {color}; font-weight: bold; text-decoration: {deco};")

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(self.theme['POPUP_BG'] + f" color: {self.theme['TEXT_COLOR']};")
        
        edit_action = menu.addAction("✏️ Edit Task")
        delete_action = menu.addAction("❌ Delete Task")
        menu.addSeparator()
        move_menu = menu.addMenu("➡️ Move to Stage")
        
        for stage in STAGES:
            if stage != self.task_data['stage']:
                action = move_menu.addAction(stage)
                action.triggered.connect(lambda checked, s=stage: self.change_stage(s))
                
        action = menu.exec(event.globalPos())
        if action == edit_action:
            self.edit_signal.emit(self.task_data)
        elif action == delete_action:
            self.delete_signal.emit(self.task_data)

    def change_stage(self, new_stage):
        self.task_data['stage'] = new_stage
        self.task_data['completed'] = (new_stage == 'Done')
        if self.task_data['completed']:
            self.task_data['completed_date'] = datetime.now().strftime('%Y-%m-%d')
            for sub in self.task_data.get('subtasks', []):
                sub['done'] = True
        else:
            self.task_data['completed_date'] = ""
            if any(not s['done'] for s in self.task_data.get('subtasks', [])):
                pass  # keep subtask states as-is when moving away from Done
        self.update_title_style()
        self.toggle_signal.emit()

    def toggle_expand(self):
        self.is_expanded = not self.is_expanded
        if self.is_expanded:
            self.render_subtasks()
        else:
            clear_layout(self.subtask_layout)
        self.updateGeometry()

    def render_subtasks(self):
        clear_layout(self.subtask_layout)
        subs = self.task_data.get('subtasks', [])
        for s in subs:
            row = SubtaskRow(s, self.update_subtask_progress, self.theme)
            row.delete_signal.connect(lambda checked=None, sub=s: self.delete_subtask_signal.emit(self.task_data, sub['text']))
            self.subtask_layout.addWidget(row)
        
        # Inline Subtask Addition
        inline_add = QLineEdit()
        inline_add.setPlaceholderText("➕ Add new subtask and press Enter...")
        inline_add.setStyleSheet(f"background-color: {self.theme['INPUT_BG']}; color: {self.theme['TEXT_COLOR']}; border: 1px solid {self.theme['PROGRESS_BG']}; padding: 3px; border-radius: 2px;")
        inline_add.returnPressed.connect(lambda: self.add_inline_subtask(inline_add))
        self.subtask_layout.addWidget(inline_add)

    def add_inline_subtask(self, input_widget):
        text = input_widget.text().strip()
        if text:
            self.add_subtask_signal.emit(self.task_data, text)
            input_widget.clear()

    def _auto_complete_parent(self):
        """If all subtasks are done, auto-complete the parent task.
        If any subtask is unchecked and parent is done, revert parent."""
        subs = self.task_data.get('subtasks', [])
        if not subs:
            return
        all_done = all(s['done'] for s in subs)
        any_undone = any(not s['done'] for s in subs)

        if all_done and not self.task_data['completed']:
            # All subtasks completed → complete the parent
            self.task_data['completed'] = True
            self.task_data['completed_date'] = datetime.now().strftime('%Y-%m-%d')
            self.task_data['stage'] = 'Done'
            self.checkbox.blockSignals(True)
            self.checkbox.setChecked(True)
            self.checkbox.blockSignals(False)
            self.update_title_style()
            if self.task_data.get('repeats') != 'None':
                self.handle_recurring()
        elif any_undone and self.task_data['completed']:
            # A subtask was un-checked while parent is done → revert parent
            self.task_data['completed'] = False
            self.task_data['completed_date'] = ""
            if self.task_data['stage'] == 'Done':
                self.task_data['stage'] = 'To Do'
            self.checkbox.blockSignals(True)
            self.checkbox.setChecked(False)
            self.checkbox.blockSignals(False)
            self.update_title_style()

    def update_subtask_progress(self):
        self._auto_complete_parent()
        self.toggle_signal.emit()

    def on_checkbox_active(self, state):
        checked = bool(state)
        self.task_data['completed'] = checked
        if checked:
            self.task_data['completed_date'] = datetime.now().strftime('%Y-%m-%d')
            self.task_data['stage'] = 'Done'
            # Check all subtasks when parent is checked
            for sub in self.task_data.get('subtasks', []):
                sub['done'] = True
            if self.task_data.get('repeats') != 'None':
                self.handle_recurring()
        else:
            self.task_data['completed_date'] = ""
            if self.task_data['stage'] == 'Done': self.task_data['stage'] = 'To Do'
            # Don't uncheck subtasks — user may want to keep individual progress
            # (consistent with change_stage behavior when moving away from Done)
        
        self.update_title_style()
        # Re-render expanded subtasks to reflect new check states
        if self.is_expanded:
            self.render_subtasks()
        self.toggle_signal.emit()

    def handle_recurring(self):
        new_task = self.task_data.copy()
        new_task['id'] = uuid.uuid4().hex[:8]
        new_task['completed'] = False
        new_task['completed_date'] = ""
        new_task['stage'] = 'To Do'
        new_task['gcal_event_id'] = ''
        new_task['time_spent_seconds'] = 0
        new_task['subtasks'] = [{'text': s['text'], 'done': False} for s in self.task_data.get('subtasks', [])]

        old_date_str = self.task_data.get('due_date')
        if old_date_str:
            try:
                old_dt = datetime.strptime(old_date_str, '%Y-%m-%d')
                if self.task_data['repeats'] == 'Daily': new_dt = old_dt + timedelta(days=1)
                elif self.task_data['repeats'] == 'Weekly': new_dt = old_dt + timedelta(weeks=1)
                elif self.task_data['repeats'] == 'Monthly': new_dt = old_dt + timedelta(days=30)
                new_task['due_date'] = new_dt.strftime('%Y-%m-%d')
            except ValueError: pass
        
        self.add_recurring_signal.emit(new_task)


class KanbanCardWidget(QWidget):
    edit_signal = Signal(dict)
    delete_signal = Signal(dict)
    move_signal = Signal(dict, str)
    add_recurring_signal = Signal(dict)  # for recurring when moved to Done

    def __init__(self, task_data, theme):
        super().__init__()
        self.task_data = task_data
        self.theme = theme
        self.p_colors = PRIORITY_COLORS_DARK if theme['IS_DARK'] else PRIORITY_COLORS_LIGHT

        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(self.theme['CARD_BG']))
        self.setPalette(pal)
        self.setStyleSheet(f"KanbanCardWidget {{ background-color: {self.theme['CARD_BG']}; border-radius: 5px; border: 1px solid {self.theme['PROGRESS_BG']}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        top_row = QHBoxLayout()
        p_color = self.p_colors.get(self.task_data['priority'], self.theme['TEXT_COLOR'])
        repeat_icon = "🔄 " if self.task_data.get('repeats') != 'None' else ""
        top_row.addWidget(QLabel(f"{repeat_icon}[{self.task_data['priority']}]"))
        top_row[-1].setStyleSheet(f"color: {p_color}; font-weight: bold; font-size: 12px;")
        
        title_lbl = QLabel(self.task_data['text'])
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet(f"color: {self.theme['TEXT_COLOR']}; font-size: 14px; font-weight: bold;")
        top_row.addWidget(title_lbl, 1)
        
        edit_btn = QPushButton("✏️")
        edit_btn.setFixedSize(25, 25)
        edit_btn.setStyleSheet(f"background-color: {self.theme['EDIT_COLOR']}; border: none; border-radius: 3px;")
        edit_btn.clicked.connect(lambda: self.edit_signal.emit(self.task_data))
        top_row.addWidget(edit_btn)

        mid_row = QHBoxLayout()
        tags_text = f"🏷️ {self.task_data['tags']}" if self.task_data.get('tags') else ""
        mid_row.addWidget(QLabel(tags_text))
        mid_row[-1].setStyleSheet("color: #CC80CC; font-size: 11px;")
        
        sub_text = ""; sub_color = self.theme['TEXT_COLOR']
        subs = self.task_data.get('subtasks', [])
        if subs:
            done_subs = sum(1 for s in subs if s['done']); sub_text = f"📋 {done_subs}/{len(subs)}"
            sub_color = self.theme['PROGRESS_FG'] if done_subs == len(subs) else self.theme['ACCENT_COLOR']
        sub_lbl = QLabel(sub_text)
        sub_lbl.setAlignment(Qt.AlignRight)
        sub_lbl.setStyleSheet(f"color: {sub_color}; font-size: 11px;")
        mid_row.addWidget(sub_lbl)

        # Time badge
        time_badge = fmt_time_badge(self.task_data, self.theme)
        if time_badge:
            time_lbl = QLabel(time_badge[0])
            time_lbl.setAlignment(Qt.AlignRight)
            time_lbl.setStyleSheet(f"color: {time_badge[1]}; font-size: 11px;")
            mid_row.addWidget(time_lbl)

        layout.addLayout(top_row)
        layout.addLayout(mid_row)

    # --- Drag & Drop Support ---
    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            drag = QDrag(self)
            mime = QMimeData()
            mime.setText(self.task_data['id'])
            drag.setMimeData(mime)
            drag.exec(Qt.MoveAction)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(f"background-color: {self.theme['POPUP_BG']}; color: {self.theme['TEXT_COLOR']};")
        
        edit_action = menu.addAction("✏️ Edit Task")
        delete_action = menu.addAction("❌ Delete Task")
        menu.addSeparator()
        move_menu = menu.addMenu("➡️ Move to Stage")
        
        for stage in STAGES:
            if stage != self.task_data['stage']:
                action = move_menu.addAction(stage)
                action.triggered.connect(lambda checked, s=stage: self.move_signal.emit(self.task_data, s))
                
        action = menu.exec(event.globalPos())
        if action == edit_action:
            self.edit_signal.emit(self.task_data)
        elif action == delete_action:
            self.delete_signal.emit(self.task_data)


class KanbanColumnWidget(QWidget):
    """Custom widget to accept drops for Kanban columns"""
    task_dropped = Signal(str, str) # task_id, new_stage

    def __init__(self, stage_name, theme):
        super().__init__()
        self.stage_name = stage_name
        self.theme = theme
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
            self.setStyleSheet(f"background-color: {self.theme['KANBAN_COL_BG']}; border: 2px dashed {self.theme['ACCENT_COLOR']}; border-radius: 5px;")
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
         self.setStyleSheet(f"background-color: {self.theme['KANBAN_COL_BG']}; border-radius: 5px;")

    def dropEvent(self, event):
        task_id = event.mimeData().text()
        self.task_dropped.emit(task_id, self.stage_name)
        event.acceptProposedAction()
        self.setStyleSheet(f"background-color: {self.theme['KANBAN_COL_BG']}; border-radius: 5px;")


class DecisionToolsPanel(QWidget):
    """Tabbed panel containing all decision-making tools."""
    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tree_widget = DecisionTreeWidget(theme)
        self.proscons_widget = ProsConsWidget(theme)
        self.matrix_widget = DecisionMatrixWidget(theme)
        self.picker_widget = RandomPickerWidget(theme)
        self.tabs.addTab(self.tree_widget, "\U0001f333 Tree")
        self.tabs.addTab(self.proscons_widget, "\u2696\ufe0f Pros/Cons")
        self.tabs.addTab(self.matrix_widget, "\U0001f4ca Matrix")
        self.tabs.addTab(self.picker_widget, "\U0001f3b2 Random")
        layout.addWidget(self.tabs)

    def apply_theme(self, theme):
        self.theme = theme
        self.tree_widget.apply_theme(theme)
        self.proscons_widget.apply_theme(theme)
        self.matrix_widget.apply_theme(theme)
        self.picker_widget.apply_theme(theme)

    def save_all(self):
        self.tree_widget.save_data()
        self.proscons_widget.save_data()
        self.matrix_widget.save_data()
        self.picker_widget._save_data()


class TodoApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ultimate Tasks")
        self.resize(500, 750)
        
        self.tasks = []
        self.archive = []
        self.current_view = 'list'
        self.current_main_view = 'tasks'
        self.current_status_filter = 'all'
        self.current_cat_filter = 'All'
        self.current_sort = 'Default'
        self.search_query = ''
        self._saved_cat_filter = 'All'
        self._saved_theme_is_light = False
        self.theme = DARK_THEME

        self.load_data()
        self.init_ui()
        self.apply_theme()

        self._restore_ui_state()
        self.refresh_ui()
        self.check_due_today()
        self._setup_autosave()
        self.gcal_manager = GoogleCalendarManager()
        self.notif_manager = NotificationManager(self, self.theme)
        self.notif_manager.show_tray()
        self.notif_manager.check_notifications(self.tasks)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.root_layout = QVBoxLayout(central_widget)
        self.root_layout.setSpacing(6)
        self.root_layout.setContentsMargins(15, 15, 15, 15)

        # 1. Header
        header = QHBoxLayout()
        self.header_title = QLabel("Ultimate Tasks")
        self.header_title.setStyleSheet(f"font-size: 22px; color: {self.theme['ACCENT_COLOR']}; font-weight: bold;")
        header.addWidget(self.header_title, 1)
        
        self.archive_btn = QPushButton('🗄️')
        self.archive_btn.setToolTip("Archive")
        self.archive_btn.clicked.connect(self.open_archive)
        self.view_btn = QPushButton('🗂️')
        self.view_btn.setToolTip("Toggle List/Board View")
        self.view_btn.clicked.connect(self.toggle_view)
        self.theme_btn = QPushButton('🌙')
        self.theme_btn.setToolTip("Toggle Theme")
        self.theme_btn.clicked.connect(self.toggle_theme)
        self.export_btn = QPushButton('📋')
        self.export_btn.setToolTip("Export to Clipboard")
        self.export_btn.clicked.connect(self.export_tasks)
        
        for btn in [self.archive_btn, self.view_btn, self.theme_btn, self.export_btn]:
            btn.setFixedSize(35, 35)
            header.addWidget(btn)
        self.root_layout.addLayout(header)

        # 2. Quick Add Bar
        quick_add = QHBoxLayout()
        self.quick_input = QLineEdit()
        self.quick_input.setPlaceholderText('⚡ Quick Add (e.g., Task tomorrow high @Office, buy milk yesterday)')
        self.quick_input.returnPressed.connect(self.process_quick_add)
        add_btn = QPushButton('+ Form')
        add_btn.clicked.connect(self.open_add_popup)
        add_btn.setFixedWidth(80)
        quick_add.addWidget(self.quick_input)
        quick_add.addWidget(add_btn)
        self.root_layout.addLayout(quick_add)

        # 3. Search & Sort
        search_sort = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('🔍 Search...')
        self.search_input.textChanged.connect(self.on_search)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(['Sort: Default', 'Sort: Date', 'Sort: Priority', 'Sort: Name'])
        self.sort_combo.currentTextChanged.connect(self.on_sort_change)
        search_sort.addWidget(self.search_input, 6)
        search_sort.addWidget(self.sort_combo, 4)
        self.root_layout.addLayout(search_sort)

        # 4. Progress & Filters
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(15)
        self.progress_label = QLabel()
        self.progress_label.setFixedHeight(20)
        self.root_layout.addWidget(self.progress_bar)
        self.root_layout.addWidget(self.progress_label)

        action_bar = QHBoxLayout()
        self.cat_combo = QComboBox()
        self.cat_combo.addItem('All')
        self.cat_combo.currentTextChanged.connect(self.on_cat_filter_change)
        action_bar.addWidget(self.cat_combo, 1)
        self.root_layout.addLayout(action_bar)

        filter_bar = QHBoxLayout()
        self.btn_all = QPushButton('All')
        self.btn_active = QPushButton('Active')
        self.btn_completed = QPushButton('Done')
        self.archive_done_btn = QPushButton('Archive Done')
        self.undo_btn = QPushButton('↩ Undo')
        self.undo_btn.setToolTip('Undo last delete (Ctrl+Z)')
        self.undo_btn.hide()
        self.deleted_buffer = None

        self.btn_all.clicked.connect(lambda: self.set_status_filter('all'))
        self.btn_active.clicked.connect(lambda: self.set_status_filter('active'))
        self.btn_completed.clicked.connect(lambda: self.set_status_filter('completed'))
        self.archive_done_btn.clicked.connect(self.archive_completed)
        self.undo_btn.clicked.connect(self.undo_delete)

        for btn in [self.btn_all, self.btn_active, self.btn_completed, self.archive_done_btn]:
            filter_bar.addWidget(btn)
        filter_bar.addWidget(self.undo_btn)
        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        filter_bar.addWidget(self.status_label, 1)
        self.root_layout.addLayout(filter_bar)
# 5. Navigation Bar
        nav_bar = QHBoxLayout()
        nav_bar.setSpacing(6)
        self.nav_tasks_btn = QPushButton("\U0001f4cb Tasks")
        self.nav_tasks_btn.clicked.connect(lambda: self.switch_main_view("tasks"))
        self.nav_calendar_btn = QPushButton("\U0001f4c5 Calendar")
        self.nav_calendar_btn.clicked.connect(lambda: self.switch_main_view("calendar"))
        self.nav_focus_btn = QPushButton("\u23f2 Focus")
        self.nav_focus_btn.clicked.connect(lambda: self.switch_main_view("focus"))
        self.nav_decisions_btn = QPushButton("\u2696 Decisions")
        self.nav_decisions_btn.clicked.connect(lambda: self.switch_main_view("decisions"))
        for btn in [self.nav_tasks_btn, self.nav_calendar_btn, self.nav_focus_btn, self.nav_decisions_btn]:
            btn.setFixedHeight(32)
            nav_bar.addWidget(btn)
        nav_bar.addStretch()
        self.gcal_btn = QPushButton("\U0001f4c4 GCal")
        self.gcal_btn.setFixedHeight(32)
        self.gcal_btn.clicked.connect(self.open_gcal_settings)
        self.notif_btn = QPushButton("\U0001f514 Notif")
        self.notif_btn.setFixedHeight(32)
        self.notif_btn.clicked.connect(self.open_notif_settings)
        nav_bar.addWidget(self.gcal_btn)
        nav_bar.addWidget(self.notif_btn)
        self.root_layout.addLayout(nav_bar)

        # 6. Stacked Widget for main views
        self.stacked = QStackedWidget()
        self.root_layout.addWidget(self.stacked, 1)

        # 6a. Tasks page (replaces old view_scroll)
        self.tasks_page = QWidget()
        self.tasks_page_layout = QVBoxLayout(self.tasks_page)
        self.tasks_page_layout.setContentsMargins(0, 0, 0, 0)
        self.view_scroll = QScrollArea()
        self.view_scroll.setWidgetResizable(True)
        self.view_container_widget = QWidget()
        self.view_container_layout = QVBoxLayout(self.view_container_widget)
        self.view_container_layout.setAlignment(Qt.AlignTop)
        self.view_scroll.setWidget(self.view_container_widget)
        self.tasks_page_layout.addWidget(self.view_scroll)
        self.stacked.addWidget(self.tasks_page)

        # 6b. Calendar page
        self.calendar_widget = CalendarWidget(self.theme)
        self.calendar_widget.task_edit_requested.connect(self.open_edit_popup)
        self.stacked.addWidget(self.calendar_widget)

        # 6c. Focus Timer page
        self.focus_widget = FocusTimerWidget(self.theme)
        self.focus_widget.time_logged.connect(self.handle_time_logged)
        self.stacked.addWidget(self.focus_widget)

        # 6d. Decisions page
        self.decisions_panel = DecisionToolsPanel(self.theme)
        self.stacked.addWidget(self.decisions_panel)

        self.stacked.setCurrentIndex(0)

        # Shortcuts
        QShortcut(QKeySequence("Ctrl+N"), self, self.quick_input.setFocus)
        QShortcut(QKeySequence("Ctrl+F"), self, self.search_input.setFocus)
        QShortcut(QKeySequence("Ctrl+Z"), self, self.undo_delete)

    def apply_theme(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background-color: {self.theme['BG_COLOR']}; color: {self.theme['TEXT_COLOR']}; }}
            QLineEdit, QComboBox {{ background-color: {self.theme['INPUT_BG']}; color: {self.theme['TEXT_COLOR']}; border: 1px solid {self.theme['PROGRESS_BG']}; padding: 5px; border-radius: 3px; }}
            QLineEdit::placeholder {{ color: {self.theme['COMPLETED_COLOR']}; }}
            QPushButton {{ background-color: {self.theme['INPUT_BG']}; color: {self.theme['TEXT_COLOR']}; border: none; padding: 5px; border-radius: 3px; }}
            QPushButton:hover {{ background-color: {self.theme['ACCENT_COLOR']}; color: white; }}
            QProgressBar {{ background-color: {self.theme['PROGRESS_BG']}; border: none; border-radius: 5px; }}
            QProgressBar::chunk {{ background-color: {self.theme['PROGRESS_FG']}; border-radius: 5px; }}
            QScrollArea {{ border: none; }}
            QComboBox QAbstractItemView {{ background-color: {self.theme['INPUT_BG']}; color: {self.theme['TEXT_COLOR']}; selection-background-color: {self.theme['ACCENT_COLOR']}; }}
            QMenu {{ background-color: {self.theme['POPUP_BG']}; color: {self.theme['TEXT_COLOR']}; border: 1px solid {self.theme['PROGRESS_BG']}; }}
            QMenu::item:selected {{ background-color: {self.theme['ACCENT_COLOR']}; }}
        """)
        self.update_bottom_bar()
        self._update_nav_style()

    def check_due_today(self):
        today_str = datetime.now().strftime('%Y-%m-%d')
        due_today = [t for t in self.tasks if t.get('due_date') == today_str and not t['completed']]
        if due_today:
            tasks_txt = "\n".join([f"• {t['text']}" for t in due_today])
            QMessageBox.information(self, "Tasks Due Today", f"You have {len(due_today)} task(s) due today:\n\n{tasks_txt}")

    # ---- Main View Navigation ----
    def switch_main_view(self, view):
        self.current_main_view = view
        self.stacked.setCurrentIndex({'tasks': 0, 'calendar': 1, 'focus': 2, 'decisions': 3}[view])
        if view == 'calendar':
            self.calendar_widget.set_tasks(self.tasks)
        elif view == 'focus':
            self.focus_widget.set_tasks(self.tasks)
        self._update_nav_style()

    def _update_nav_style(self):
        accent = self.theme['ACCENT_COLOR']
        bg = self.theme['INPUT_BG']
        fg = self.theme['TEXT_COLOR']
        for key, btn in [('tasks', self.nav_tasks_btn), ('calendar', self.nav_calendar_btn),
                          ('focus', self.nav_focus_btn), ('decisions', self.nav_decisions_btn)]:
            if key == self.current_main_view:
                btn.setStyleSheet(f"background:{accent};color:white;border:none;border-radius:4px;font-weight:bold;padding:4px 12px;")
            else:
                btn.setStyleSheet(f"background:{bg};color:{fg};border:none;border-radius:4px;padding:4px 12px;")

    # ---- Google Calendar ----
    def open_gcal_settings(self):
        dlg = GoogleCalendarSettingsDialog(self.gcal_manager, self.theme, self)
        result = dlg.exec()
        if result == 100:
            self.sync_to_gcal()
        elif result == 200:
            self.pull_from_gcal()

    def sync_to_gcal(self):
        if not self.gcal_manager.is_available():
            QMessageBox.warning(self, "Not Available",
                "google-api-python-client not installed.\nRun: pip install google-api-python-client google-auth-oauthlib")
            return
        if not self.gcal_manager.is_authenticated():
            ok, msg = self.gcal_manager.authenticate_interactive()
            if not ok:
                QMessageBox.warning(self, "Auth Failed", msg)
                return
        active = [t for t in self.tasks if not t['completed']]
        success, fail = self.gcal_manager.sync_all_tasks(active)
        self.save_tasks()
        QMessageBox.information(self, "Sync Complete", f"Pushed {success} task(s). Failed: {fail}")

    def pull_from_gcal(self):
        if not self.gcal_manager.is_available():
            QMessageBox.warning(self, "Not Available", "google-api-python-client not installed.")
            return
        if not self.gcal_manager.is_authenticated():
            ok, msg = self.gcal_manager.authenticate_interactive()
            if not ok:
                QMessageBox.warning(self, "Auth Failed", msg)
                return
        events = self.gcal_manager.pull_events()
        if not events:
            QMessageBox.information(self, "Pull", "No upcoming events found.")
            return
        reply = QMessageBox.question(self, "Pull Events",
            f"Found {len(events)} event(s). Import as tasks?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            for e in events:
                existing = [t for t in self.tasks if t.get('gcal_event_id') == e['id']]
                if not existing:
                    self.tasks.append({
                        'id': uuid.uuid4().hex[:8], 'text': e['text'], 'completed': False,
                        'priority': 'Medium', 'stage': 'To Do', 'category': 'Google Cal',
                        'context': '', 'tags': 'gcal-import',
                        'due_date': e.get('due_date', ''), 'description': e.get('description', ''),
                        'completed_date': '', 'repeats': 'None', 'subtasks': [],
                        'gcal_event_id': e['id'], 'time_estimate_minutes': 0, 'time_spent_seconds': 0
                    })
            self.save_tasks()
            self.update_category_spinner()
            self.refresh_ui()
            QMessageBox.information(self, "Imported", f"Imported {len(events)} event(s).")

    # ---- Notifications ----
    def open_notif_settings(self):
        dlg = self.notif_manager.open_settings()
        dlg.exec()
        self.notif_manager.update_theme(self.theme)

    def toggle_theme(self):
        self.theme = LIGHT_THEME if self.theme['IS_DARK'] else DARK_THEME
        self.theme_btn.setText('\u2600\ufe0f' if self.theme['IS_DARK'] else '\U0001f319')
        self.apply_theme()
        self.refresh_ui()
        self.calendar_widget.apply_theme(self.theme)
        self.focus_widget.apply_theme(self.theme)
        self.decisions_panel.apply_theme(self.theme)
        self.notif_manager.update_theme(self.theme)

    def toggle_view(self):
        self.current_view = 'board' if self.current_view == 'list' else 'list'
        self.refresh_ui()

    def load_data(self):
        self.tasks = safe_json_load(DATA_FILE, default=[])
        # Validate and migrate each task
        valid_tasks = []
        for t in self.tasks:
            if not isinstance(t, dict):
                continue
            if 'id' not in t:
                t['id'] = uuid.uuid4().hex[:8]
            if 'stage' not in t:
                t['stage'] = 'Done' if t.get('completed') else 'To Do'
            if 'repeats' not in t:
                t['repeats'] = 'None'
            if 'subtasks' not in t:
                t['subtasks'] = []
            if 'context' not in t:
                t['context'] = ''
            if 'description' not in t:
                t['description'] = ''
            if 'tags' not in t:
                t['tags'] = ''
            if 'gcal_event_id' not in t:
                t['gcal_event_id'] = ''
            if 'completed_date' not in t:
                t['completed_date'] = ''
            if 'time_estimate_minutes' not in t:
                t['time_estimate_minutes'] = 0
            if 'time_spent_seconds' not in t:
                t['time_spent_seconds'] = 0
            if 'text' not in t or not t['text']:
                continue
            valid_tasks.append(t)
        self.tasks = valid_tasks

        self.archive = safe_json_load(ARCHIVE_FILE, default=[])
        if not isinstance(self.archive, list):
            self.archive = []

        self._load_ui_state()

    def _load_ui_state(self):
        """Restore UI state from previous session."""
        state = None
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)
            except Exception:
                pass
        if not state or not isinstance(state, dict):
            return

        # Restore theme
        if state.get('theme') == 'light':
            self.theme = LIGHT_THEME
            # theme_btn not yet created; it will be set in _restore_ui_state
            self._saved_theme_is_light = True
        else:
            self._saved_theme_is_light = False

        # Restore window geometry
        geo = state.get('window_geometry')
        if geo and isinstance(geo, dict):
            try:
                self.resize(geo.get('width', 500), geo.get('height', 750))
                if geo.get('x') is not None and geo.get('y') is not None:
                    self.move(geo['x'], geo['y'])
                if geo.get('maximized'):
                    self.showMaximized()
            except Exception:
                pass

        # Restore view state
        self.current_view = state.get('view', 'list')
        self.current_main_view = state.get('main_view', 'tasks')
        self.current_status_filter = state.get('status_filter', 'all')
        self.current_sort = state.get('sort', 'Default')
        self.search_query = state.get('search_query', '')

        # Restore category filter (applied after UI is built)
        self._saved_cat_filter = state.get('cat_filter', 'All')

    def _save_ui_state(self):
        """Save current UI state for next session."""
        state = {
            'theme': 'light' if not self.theme['IS_DARK'] else 'dark',
            'view': self.current_view,
            'main_view': self.current_main_view,
            'status_filter': self.current_status_filter,
            'sort': self.current_sort,
            'search_query': self.search_query,
            'cat_filter': self.current_cat_filter,
            'window_geometry': {
                'width': self.width(),
                'height': self.height(),
                'x': self.x(),
                'y': self.y(),
                'maximized': self.isMaximized(),
            }
        }
        try:
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    def save_tasks(self, skip_gcal=False):
        safe_json_dump(DATA_FILE, self.tasks)
        self._autosave_indicator()
        # Auto-sync to Google Calendar if enabled
        if not skip_gcal and hasattr(self, 'gcal_manager') and self.gcal_manager.enabled and self.gcal_manager.is_authenticated():
            try:
                active = [t for t in self.tasks if not t['completed']]
                self.gcal_manager.sync_all_tasks(active)
            except Exception:
                pass

    def save_archive(self):
        safe_json_dump(ARCHIVE_FILE, self.archive)

    def _autosave_indicator(self):
        """Brief visual flash to confirm data was saved."""
        self.header_title.setText("Ultimate Tasks  \u2713")
        QTimer.singleShot(800, lambda: self.header_title.setText("Ultimate Tasks"))

    def _setup_autosave(self):
        """Start periodic autosave timer (every 30 seconds)."""
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave_tick)
        self._autosave_timer.start(30_000)  # 30 seconds

    def _autosave_tick(self):
        """Periodic autosave: save tasks, archive, and UI state."""
        safe_json_dump(DATA_FILE, self.tasks)
        self._save_ui_state()

    def _restore_ui_state(self):
        """Apply saved state to UI widgets (called after init_ui)."""
        # Theme button
        if getattr(self, '_saved_theme_is_light', False):
            self.theme_btn.setText('\u2600\ufe0f')

        # Search
        if self.search_query:
            self.search_input.setText(self.search_query)

        # Sort
        sort_text = f"Sort: {self.current_sort}"
        idx = self.sort_combo.findText(sort_text)
        if idx >= 0:
            self.sort_combo.setCurrentIndex(idx)

        # Status filter buttons
        for btn, key in [(self.btn_all, 'all'), (self.btn_active, 'active'), (self.btn_completed, 'completed')]:
            if self.current_status_filter == key:
                btn.click()
                break

        # Category filter
        if hasattr(self, '_saved_cat_filter') and self._saved_cat_filter != 'All':
            idx = self.cat_combo.findText(self._saved_cat_filter)
            if idx >= 0:
                self.cat_combo.setCurrentIndex(idx)

        # View toggle
        if self.current_view == 'board':
            self.view_btn.click()

        # Main view (tasks/calendar/focus/decisions)
        if self.current_main_view != 'tasks':
            self.switch_main_view(self.current_main_view)

    def process_quick_add(self):
        text = self.quick_input.text().strip()
        if not text: return
        
        priority = 'Medium'; context = ''; category = 'General'; due_date = ''; name_words = []
        today = datetime.now()
        
        for word in text.split():
            if word.lower() in ['high', 'medium', 'low']: priority = word.capitalize()
            elif word.startswith('@'): context = word[1:]
            elif word.startswith('#'): category = word[1:]
            elif word.lower() == 'today': due_date = today.strftime('%Y-%m-%d')
            elif word.lower() == 'tomorrow': due_date = (today + timedelta(days=1)).strftime('%Y-%m-%d')
            elif word.lower() == 'yesterday': due_date = (today - timedelta(days=1)).strftime('%Y-%m-%d')
            else: name_words.append(word)
        
        name = ' '.join(name_words)
        if name:
            new_task = {
                'id': uuid.uuid4().hex[:8], 'text': name, 'completed': False, 'priority': priority,
                'stage': 'To Do', 'category': category, 'context': context, 'tags': '',
                'due_date': due_date, 'description': '', 'completed_date': '', 'repeats': 'None', 'subtasks': [],
                'time_estimate_minutes': 0, 'time_spent_seconds': 0
            }
            self.tasks.append(new_task)
            self.save_tasks()
            self.update_category_spinner()
            self.refresh_ui()
        self.quick_input.clear()

    def open_add_popup(self):
        dlg = TaskFormDialog(self.process_task_form, theme=self.theme, parent=self)
        dlg.exec()

    def open_edit_popup(self, task_data):
        dlg = TaskFormDialog(self.process_task_form, task_to_edit=task_data, theme=self.theme, parent=self)
        dlg.exec()

    def open_archive(self):
        dlg = ArchiveDialog(self.archive, self.restore_from_archive, self.theme, self)
        dlg.exec()

    def export_tasks(self):
        md_text = "# 📋 Task Export\n\n"
        for t in self.tasks:
            time_str = f" | Time: {fmt_duration(t.get('time_spent_seconds', 0))}" if t.get('time_spent_seconds', 0) else ""
            md_text += f"- [{'x' if t['completed'] else ' '}] **{t['text']}** | Stage: {t['stage']}{time_str}\n"
        QApplication.clipboard().setText(md_text)
        self.export_btn.setText("✅")
        QTimer.singleShot(1500, lambda: self.export_btn.setText("📋"))

    def process_task_form(self, task_id, name, priority, stage, category, context, tags, due_date, description, repeats, subtasks, time_estimate_minutes=0):
        completed = True if stage == 'Done' else False
        
        if task_id:
            # Find existing task to preserve completed_date
            existing = next((t for t in self.tasks if t['id'] == task_id), None)
            if completed:
                completed_date = existing['completed_date'] if existing and existing.get('completed_date') else datetime.now().strftime('%Y-%m-%d')
            else:
                completed_date = ""
            if completed:
                for sub in subtasks:
                    sub['done'] = True
        else:
            completed_date = datetime.now().strftime('%Y-%m-%d') if completed else ""
            if completed:
                for sub in subtasks:
                    sub['done'] = True
        
        if task_id:
            for t in self.tasks:
                if t['id'] == task_id:
                    t.update({'text': name, 'priority': priority, 'stage': stage, 'category': category,
                              'context': context, 'tags': tags, 'due_date': due_date, 'description': description,
                              'completed': completed, 'completed_date': completed_date, 'repeats': repeats, 'subtasks': subtasks,
                              'time_estimate_minutes': time_estimate_minutes})
                    break
        else:
            self.tasks.append({'id': uuid.uuid4().hex[:8], 'text': name, 'completed': completed,
                               'priority': priority, 'stage': stage, 'category': category, 'context': context,
                               'tags': tags, 'due_date': due_date, 'description': description, 'completed_date': completed_date,
                               'repeats': repeats, 'subtasks': subtasks, 'time_estimate_minutes': time_estimate_minutes,
                               'time_spent_seconds': 0})
        
        self.save_tasks()
        self.update_category_spinner()
        self.refresh_ui()

    def handle_toggle(self):
        self.save_tasks()
        self.refresh_ui()

    def handle_delete(self, task_data):
        self.tasks = [t for t in self.tasks if t['id'] != task_data['id']]
        self.deleted_buffer = task_data
        self.save_tasks()
        self.update_category_spinner()
        self.refresh_ui()
        self.undo_btn.show()

    def handle_add_recurring(self, new_task):
        if new_task: self.tasks.append(new_task)
        self.save_tasks()

    def handle_add_subtask(self, task_data, subtask_text):
        for t in self.tasks:
            if t['id'] == task_data['id']:
                t['subtasks'].append({'text': subtask_text, 'done': False})
                break
        self.save_tasks()
        self.refresh_ui()

    def handle_delete_subtask(self, task_data, subtask_text):
        for t in self.tasks:
            if t['id'] == task_data['id']:
                t['subtasks'] = [s for s in t['subtasks'] if s['text'] != subtask_text]
                # Auto-complete parent if all remaining subtasks are done
                remaining = t['subtasks']
                if remaining and all(s['done'] for s in remaining) and not t['completed']:
                    t['completed'] = True
                    t['completed_date'] = datetime.now().strftime('%Y-%m-%d')
                    t['stage'] = 'Done'
                break
        self.save_tasks()
        self.refresh_ui()

    def handle_start_timer_for_task(self, task_data):
        """Switch to Focus tab and start timer for the given task."""
        self.switch_main_view('focus')
        self.focus_widget.start_for_task(
            task_data['id'], task_data['text'],
            task_data.get('time_estimate_minutes', 0)
        )

    def handle_time_logged(self, task_id, elapsed_seconds):
        """Accumulate time_spent_seconds on a task when a focus session completes."""
        for t in self.tasks:
            if t['id'] == task_id:
                t['time_spent_seconds'] = t.get('time_spent_seconds', 0) + elapsed_seconds
                break
        self.save_tasks(skip_gcal=True)

    def handle_move_task(self, task_data, new_stage):
        for t in self.tasks:
            if t['id'] == task_data['id']:
                t['stage'] = new_stage
                t['completed'] = (new_stage == 'Done')
                t['completed_date'] = datetime.now().strftime('%Y-%m-%d') if t['completed'] else ""
                if t['completed']:
                    for sub in t.get('subtasks', []):
                        sub['done'] = True
                    # Trigger recurring if moving to Done
                    if t.get('repeats') != 'None':
                        new_task = t.copy()
                        new_task['id'] = uuid.uuid4().hex[:8]
                        new_task['completed'] = False
                        new_task['completed_date'] = ""
                        new_task['stage'] = 'To Do'
                        new_task['gcal_event_id'] = ''
                        new_task['time_spent_seconds'] = 0
                        new_task['subtasks'] = [{'text': s['text'], 'done': False} for s in t.get('subtasks', [])]
                        old_date_str = t.get('due_date')
                        if old_date_str:
                            try:
                                old_dt = datetime.strptime(old_date_str, '%Y-%m-%d')
                                if t['repeats'] == 'Daily': new_task['due_date'] = (old_dt + timedelta(days=1)).strftime('%Y-%m-%d')
                                elif t['repeats'] == 'Weekly': new_task['due_date'] = (old_dt + timedelta(weeks=1)).strftime('%Y-%m-%d')
                                elif t['repeats'] == 'Monthly': new_task['due_date'] = (old_dt + timedelta(days=30)).strftime('%Y-%m-%d')
                            except ValueError: pass
                        self.tasks.append(new_task)
                break
        self.save_tasks()
        self.refresh_ui()

    def handle_kanban_drop(self, task_id, new_stage):
        for t in self.tasks:
            if t['id'] == task_id:
                t['stage'] = new_stage
                t['completed'] = (new_stage == 'Done')
                t['completed_date'] = datetime.now().strftime('%Y-%m-%d') if t['completed'] else ""
                if t['completed']:
                    for sub in t.get('subtasks', []):
                        sub['done'] = True
                    if t.get('repeats') != 'None':
                        new_task = t.copy()
                        new_task['id'] = uuid.uuid4().hex[:8]
                        new_task['completed'] = False
                        new_task['completed_date'] = ""
                        new_task['stage'] = 'To Do'
                        new_task['gcal_event_id'] = ''
                        new_task['time_spent_seconds'] = 0
                        new_task['subtasks'] = [{'text': s['text'], 'done': False} for s in t.get('subtasks', [])]
                        old_date_str = t.get('due_date')
                        if old_date_str:
                            try:
                                old_dt = datetime.strptime(old_date_str, '%Y-%m-%d')
                                if t['repeats'] == 'Daily': new_task['due_date'] = (old_dt + timedelta(days=1)).strftime('%Y-%m-%d')
                                elif t['repeats'] == 'Weekly': new_task['due_date'] = (old_dt + timedelta(weeks=1)).strftime('%Y-%m-%d')
                                elif t['repeats'] == 'Monthly': new_task['due_date'] = (old_dt + timedelta(days=30)).strftime('%Y-%m-%d')
                            except ValueError: pass
                        self.tasks.append(new_task)
                break
        self.save_tasks()
        self.refresh_ui()

    def archive_completed(self):
        done_tasks = [t for t in self.tasks if t['completed']]
        if not done_tasks:
            return
        reply = QMessageBox.question(self, "Archive Completed",
            f"Move {len(done_tasks)} completed task(s) to archive?", QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.archive.extend(done_tasks)
            self.tasks = [t for t in self.tasks if not t['completed']]
            self.save_tasks()
            self.save_archive()
            self.update_category_spinner()
            self.refresh_ui()

    def restore_from_archive(self, task_data):
        self.archive = [t for t in self.archive if t['id'] != task_data['id']]
        task_data['completed'] = False
        task_data['stage'] = 'To Do'
        task_data['completed_date'] = ""
        self.tasks.append(task_data)
        self.save_tasks()
        self.save_archive()
        self.update_category_spinner()
        self.refresh_ui()

    def undo_delete(self):
        if self.deleted_buffer:
            self.tasks.append(self.deleted_buffer)
            self.deleted_buffer = None
            self.save_tasks()
            self.update_category_spinner()
            self.refresh_ui()
            self.undo_btn.hide()

    def set_status_filter(self, filter_type): 
        self.current_status_filter = filter_type
        self.refresh_ui()

    def on_cat_filter_change(self, text): 
        self.current_cat_filter = text
        self.refresh_ui()

    def on_search(self, text): 
        self.search_query = text.strip().lower()
        self.refresh_ui()

    def on_sort_change(self, text): 
        self.current_sort = text.split(': ')[1]
        self.refresh_ui()
    
    def update_category_spinner(self):
        cats = sorted(set(t['category'] for t in self.tasks))
        self.cat_combo.blockSignals(True)
        self.cat_combo.clear()
        self.cat_combo.addItems(['All'] + cats)
        self.cat_combo.setCurrentText(self.current_cat_filter)
        self.cat_combo.blockSignals(False)

    def is_overdue(self, date_str):
        try: return datetime.strptime(date_str, '%Y-%m-%d') < datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        except Exception: return False

    def refresh_ui(self):
        clear_layout(self.view_container_layout)
        if self.current_view == 'list':
            self.view_container_layout.setAlignment(Qt.AlignTop)
            self.render_list_view()
        else:
            self.view_container_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self.render_kanban_view()
        self.update_bottom_bar()
        self.calendar_widget.set_tasks(self.tasks)
        self.focus_widget.set_tasks(self.tasks)
        self._update_nav_style()

    def render_list_view(self):
        filtered_tasks = self.get_filtered_tasks()
        if not filtered_tasks:
            lbl = QLabel("No tasks found.")
            lbl.setStyleSheet(f"color: {self.theme['COMPLETED_COLOR']}; font-size: 16px;")
            lbl.setAlignment(Qt.AlignCenter)
            self.view_container_layout.addWidget(lbl)
        else:
            for task in filtered_tasks:
                item = TaskItemWidget(task, self.theme)
                item.toggle_signal.connect(self.handle_toggle)
                item.delete_signal.connect(self.handle_delete)
                item.edit_signal.connect(self.open_edit_popup)
                item.add_recurring_signal.connect(self.handle_add_recurring)
                item.add_subtask_signal.connect(self.handle_add_subtask)
                item.delete_subtask_signal.connect(self.handle_delete_subtask)
                item.start_timer_signal.connect(self.handle_start_timer_for_task)
                self.view_container_layout.addWidget(item)

    def render_kanban_view(self):
        kanban_layout = QHBoxLayout()
        kanban_layout.setSpacing(10)
        
        filtered_tasks = self.get_filtered_tasks()

        for stage in STAGES:
            col_widget = KanbanColumnWidget(stage, self.theme)
            col_layout = QVBoxLayout(col_widget)
            col_layout.setContentsMargins(5, 0, 5, 0)
            col_widget.setFixedWidth(280)
            
            # Connect drag and drop signal
            col_widget.task_dropped.connect(self.handle_kanban_drop)

            col_lbl = QLabel(stage)
            col_lbl.setStyleSheet(f"color: {self.theme['ACCENT_COLOR']}; font-size: 16px; font-weight: bold; padding: 10px;")
            col_lbl.setAlignment(Qt.AlignCenter)
            col_layout.addWidget(col_lbl)
            
            stage_tasks = [t for t in filtered_tasks if t['stage'] == stage]
            if not stage_tasks:
                empty_lbl = QLabel("Empty")
                empty_lbl.setStyleSheet(f"color: {self.theme['COMPLETED_COLOR']}; font-size: 12px; padding: 5px;")
                empty_lbl.setAlignment(Qt.AlignCenter)
                col_layout.addWidget(empty_lbl)
            else:
                for t in stage_tasks:
                    card = KanbanCardWidget(t, self.theme)
                    card.edit_signal.connect(self.open_edit_popup)
                    card.delete_signal.connect(self.handle_delete)
                    card.move_signal.connect(self.handle_move_task)
                    col_layout.addWidget(card)
            
            col_layout.addStretch(1)
            kanban_layout.addWidget(col_widget)
        
        self.view_container_layout.addLayout(kanban_layout)

    def get_filtered_tasks(self):
        if self.search_query:
            tasks = [t for t in self.tasks if self.search_query in t['text'].lower() or self.search_query in t.get('description', '').lower() or self.search_query in t.get('tags', '').lower()]
        else: tasks = self.tasks[:]
        
        if self.current_cat_filter != 'All': tasks = [t for t in tasks if t['category'] == self.current_cat_filter]
        if self.current_status_filter == 'active': tasks = [t for t in tasks if not t['completed']]
        elif self.current_status_filter == 'completed': tasks = [t for t in tasks if t['completed']]

        def sort_default(t): return (t['completed'], 0 if t.get('due_date') and self.is_overdue(t['due_date']) else 1, {'High': 1, 'Medium': 2, 'Low': 3}.get(t['priority'], 2), t.get('due_date', '9999-12-31'))
        def sort_date(t): return (t['completed'], t.get('due_date', '9999-12-31'))
        def sort_priority(t): return (t['completed'], {'High': 1, 'Medium': 2, 'Low': 3}.get(t['priority'], 2))
        def sort_name(t): return (t['completed'], t['text'].lower())
        
        tasks.sort(key={'Default': sort_default, 'Date': sort_date, 'Priority': sort_priority, 'Name': sort_name}.get(self.current_sort, sort_default))
        return tasks

    def update_bottom_bar(self):
        total = len(self.tasks)
        comp = sum(1 for t in self.tasks if t['completed'])
        active_count = total - comp

        if hasattr(self, 'nav_tasks_btn'):
            self.nav_tasks_btn.setText(f"\U0001f4cb Tasks ({active_count})")
        if hasattr(self, 'nav_calendar_btn'):
            today_str = date.today().strftime('%Y-%m-%d')
            due_today = sum(1 for t in self.tasks if t.get('due_date') == today_str and not t['completed'])
            self.nav_calendar_btn.setText(f"\U0001f4c5 Calendar" + (f" ({due_today})" if due_today else ""))

        self.status_label.setText(f"{active_count} task{'s' if active_count != 1 else ''} left")
        self.status_label.setStyleSheet(f"color: {self.theme['COMPLETED_COLOR']}; font-size: 12px;")
        
        self.progress_bar.setValue(int((comp / total) * 100) if total > 0 else 0)
        self.progress_label.setText(f"{int((comp/total)*100) if total > 0 else 0}% Completed ({comp}/{total})")
        self.progress_label.setStyleSheet(f"color: {self.theme['COMPLETED_COLOR']}; font-size: 12px;")
        
        for btn, key in [(self.btn_all, 'all'), (self.btn_active, 'active'), (self.btn_completed, 'completed')]:
            if self.current_status_filter == key:
                btn.setStyleSheet(f"background-color: {self.theme['ACCENT_COLOR']}; color: white; border: none; border-radius: 3px; font-weight: bold;")
            else:
                btn.setStyleSheet(f"background-color: {self.theme['INPUT_BG']}; color: {self.theme['TEXT_COLOR']}; border: none; border-radius: 3px;")

        if hasattr(self, 'archive_done_btn'):
            self.archive_done_btn.setStyleSheet(
                f"background-color: {self.theme['DELETE_COLOR']}; color: white; border: none; border-radius: 3px; font-weight: bold;"
            )


    def closeEvent(self, event):
        # Final autosave on close
        safe_json_dump(DATA_FILE, self.tasks)
        safe_json_dump(ARCHIVE_FILE, self.archive)
        self._save_ui_state()
        if hasattr(self, 'decisions_panel'):
            self.decisions_panel.save_all()
        if hasattr(self, 'focus_widget'):
            self.focus_widget.save_data()
        self._autosave_timer.stop()
        event.accept()


class DecisionTreeWidget(QWidget):
    """Interactive decision tree: build question nodes with branching options."""
    save_signal = Signal()

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.nodes = {}
        self.root_id = None
        self.current_id = None
        self.history = []
        self._build_ui()
        self.load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # --- toolbar ---
        tb = QHBoxLayout()
        self.new_btn = QPushButton("+ New Tree")
        self.new_btn.clicked.connect(self._create_root)
        self.back_btn = QPushButton("\u2190 Back")
        self.back_btn.clicked.connect(self._go_back)
        self.back_btn.setEnabled(False)
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self.save_data)
        for b in (self.new_btn, self.back_btn, self.save_btn):
            tb.addWidget(b)
        layout.addLayout(tb)

        # --- tree name ---
        nr = QHBoxLayout()
        nr.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("My Decision Tree")
        nr.addWidget(self.name_edit, 1)
        layout.addLayout(nr)

        # --- scroll area ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.container = QWidget()
        self.clayout = QVBoxLayout(self.container)
        self.clayout.setAlignment(Qt.AlignTop)
        scroll.setWidget(self.container)
        layout.addWidget(scroll, 1)
        self._render_empty()

    # ---- data ----
    def _create_root(self):
        self.nodes.clear()
        self.history.clear()
        nid = uuid.uuid4().hex[:8]
        self.root_id = nid
        self.current_id = nid
        self.nodes[nid] = {'id': nid, 'question': 'What decision are you facing?', 'options': []}
        self.history = [nid]
        self._render_node()

    def save_data(self):
        data = {'name': self.name_edit.text(), 'root_id': self.root_id, 'nodes': self.nodes}
        safe_json_dump(TREE_FILE, data, indent=2)
        self.save_signal.emit()

    def load_data(self):
        data = safe_json_load(TREE_FILE, default=None)
        if data and isinstance(data, dict):
            self.name_edit.setText(data.get('name', ''))
            self.root_id = data.get('root_id')
            self.nodes = data.get('nodes', {})
            if self.root_id and self.root_id in self.nodes:
                self.current_id = self.root_id
                self.history = [self.root_id]
                self._render_node()

    # ---- navigation ----
    def _go_back(self):
        if len(self.history) > 1:
            self.history.pop()
            self.current_id = self.history[-1]
            self._render_node()

    def _navigate(self, nid):
        if nid in self.nodes:
            self.current_id = nid
            if nid not in self.history:
                self.history.append(nid)
            else:
                self.history = self.history[:self.history.index(nid) + 1]
            self._render_node()

    # ---- rendering ----
    def _render_empty(self):
        clear_layout(self.clayout)
        lbl = QLabel("No decision tree yet.\nClick \"+ New Tree\" to start.")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(f"color:{self.theme['COMPLETED_COLOR']};font-size:16px;")
        self.clayout.addWidget(lbl)

    def _render_node(self):
        # clear
        clear_layout(self.clayout)

        if not self.current_id or self.current_id not in self.nodes:
            self._render_empty()
            return

        node = self.nodes[self.current_id]

        # breadcrumb
        crumbs = " \u2192 ".join(self.nodes[h]['question'][:25] + ('...' if len(self.nodes[h]['question']) > 25 else '')
                                  for h in self.history if h in self.nodes)
        bc = QLabel(f"Path: {crumbs}")
        bc.setWordWrap(True)
        bc.setStyleSheet(f"color:{self.theme['COMPLETED_COLOR']};font-size:11px;padding:4px;")
        self.clayout.addWidget(bc)

        # question card
        card = QFrame()
        card.setStyleSheet(f"background:{self.theme['CARD_BG']};border:1px solid {self.theme['PROGRESS_BG']};border-radius:6px;")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 10, 12, 10)

        ql = QLabel("Question / Decision Point")
        ql.setStyleSheet(f"font-weight:bold;color:{self.theme['ACCENT_COLOR']};")
        cl.addWidget(ql)

        self.q_edit = QTextEdit()
        self.q_edit.setPlainText(node['question'])
        self.q_edit.setMaximumHeight(65)
        self.q_edit.setStyleSheet(f"background:{self.theme['INPUT_BG']};color:{self.theme['TEXT_COLOR']};border:1px solid {self.theme['PROGRESS_BG']};border-radius:3px;padding:4px;")
        self.q_edit.textChanged.connect(lambda: self._set_question(node['id']))
        cl.addWidget(self.q_edit)

        ol = QLabel(f"Options ({len(node['options'])})")
        ol.setStyleSheet(f"font-weight:bold;color:{self.theme['ACCENT_COLOR']};margin-top:6px;")
        cl.addWidget(ol)

        for i, opt in enumerate(node['options']):
            self._render_option(cl, node, i, opt)

        add_btn = QPushButton("+ Add Option")
        add_btn.setStyleSheet(f"background:{self.theme['INPUT_BG']};color:{self.theme['TEXT_COLOR']};border:1px dashed {self.theme['ACCENT_COLOR']};border-radius:3px;padding:5px;")
        add_btn.clicked.connect(lambda: self._add_option(node['id']))
        cl.addWidget(add_btn)

        self.clayout.addWidget(card)
        self.back_btn.setEnabled(len(self.history) > 1)

    def _render_option(self, parent_layout, node, idx, opt):
        row = QHBoxLayout()
        is_leaf = not opt.get('next_id') or opt['next_id'] not in self.nodes

        txt = QLineEdit(opt['text'])
        txt.setStyleSheet(f"background:{self.theme['INPUT_BG']};color:{self.theme['TEXT_COLOR']};border:1px solid {self.theme['PROGRESS_BG']};border-radius:3px;padding:3px;")
        txt.textChanged.connect(lambda t, i=idx: self._set_opt_text(node['id'], i, t))
        row.addWidget(txt, 3)

        conc = QLineEdit(opt.get('conclusion', ''))
        conc.setPlaceholderText("Conclusion (if leaf)")
        conc.setStyleSheet(f"background:{self.theme['INPUT_BG']};color:{self.theme['TEXT_COLOR']};border:1px solid {self.theme['PROGRESS_BG']};border-radius:3px;padding:3px;")
        conc.textChanged.connect(lambda t, i=idx: self._set_conclusion(node['id'], i, t))
        row.addWidget(conc, 3)

        if is_leaf:
            child_btn = QPushButton("+ Child")
            child_btn.setFixedWidth(70)
            child_btn.setStyleSheet(f"background:{self.theme['ACCENT_COLOR']};color:white;border:none;border-radius:3px;")
            child_btn.clicked.connect(lambda: self._add_child(node['id'], idx))
            row.addWidget(child_btn)
        else:
            go_btn = QPushButton("Go \u2192")
            go_btn.setFixedWidth(60)
            go_btn.setStyleSheet(f"background:{self.theme['PROGRESS_FG']};color:white;border:none;border-radius:3px;font-weight:bold;")
            go_btn.clicked.connect(lambda _, n=opt['next_id']: self._navigate(n))
            row.addWidget(go_btn)

        del_btn = QPushButton("\u2715")
        del_btn.setFixedSize(28, 28)
        del_btn.setStyleSheet(f"background:{self.theme['DELETE_COLOR']};color:white;border:none;border-radius:3px;")
        del_btn.clicked.connect(lambda: self._del_option(node['id'], idx))
        row.addWidget(del_btn)
        parent_layout.addLayout(row)

    # ---- mutators ----
    def _set_question(self, nid):
        if nid in self.nodes:
            self.nodes[nid]['question'] = self.q_edit.toPlainText()

    def _add_option(self, nid):
        self.nodes[nid]['options'].append({'text': 'New option', 'next_id': None, 'conclusion': ''})
        self._render_node()

    def _del_option(self, nid, idx):
        opt = self.nodes[nid]['options'].pop(idx)
        if opt.get('next_id'):
            self._del_subtree(opt['next_id'])
        self._render_node()

    def _del_subtree(self, nid):
        if nid in self.nodes:
            for o in self.nodes[nid]['options']:
                if o.get('next_id'):
                    self._del_subtree(o['next_id'])
            del self.nodes[nid]

    def _set_opt_text(self, nid, idx, txt):
        if nid in self.nodes and idx < len(self.nodes[nid]['options']):
            self.nodes[nid]['options'][idx]['text'] = txt

    def _set_conclusion(self, nid, idx, txt):
        if nid in self.nodes and idx < len(self.nodes[nid]['options']):
            self.nodes[nid]['options'][idx]['conclusion'] = txt

    def _add_child(self, parent_id, idx):
        new_id = uuid.uuid4().hex[:8]
        self.nodes[new_id] = {'id': new_id, 'question': 'Next question?', 'options': []}
        self.nodes[parent_id]['options'][idx]['next_id'] = new_id
        self._navigate(new_id)

    def apply_theme(self, theme):
        self.theme = theme
        self._render_node()


class ProsConsWidget(QWidget):
    """Weighted pros and cons analysis with visual balance bar."""
    save_signal = Signal()

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.pros = []
        self.cons = []
        self._build_ui()
        self.load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # title
        tr = QHBoxLayout()
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Decision: Should I ...?")
        self.title_edit.setStyleSheet(f"font-size:15px;font-weight:bold;background:{self.theme['INPUT_BG']};color:{self.theme['TEXT_COLOR']};border:none;padding:6px;border-radius:4px;")
        tr.addWidget(self.title_edit, 1)
        layout.addLayout(tr)

        # balance bar
        self.balance_frame = QFrame()
        self.balance_frame.setFixedHeight(28)
        self.balance_frame.setStyleSheet(f"background:{self.theme['PROGRESS_BG']};border-radius:14px;")
        hb = QHBoxLayout(self.balance_frame)
        hb.setContentsMargins(2, 2, 2, 2)
        self.pros_bar = QFrame()
        self.pros_bar.setStyleSheet("background:#4DCC66;border-radius:12px;")
        self.cons_bar = QFrame()
        self.cons_bar.setStyleSheet("background:#E64D4D;border-radius:12px;")
        hb.addWidget(self.pros_bar, 1)
        hb.addWidget(self.cons_bar, 1)
        layout.addWidget(self.balance_frame)

        self.balance_label = QLabel()
        self.balance_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.balance_label)

        # columns
        cols = QHBoxLayout()
        cols.setSpacing(10)

        # Pros column
        pros_group = QGroupBox("PROS")
        pg = QVBoxLayout(pros_group)
        self.pros_title = QLabel("Pros")
        self.pros_title.setStyleSheet(f"color:#4DCC66;font-weight:bold;font-size:14px;")
        pg.addWidget(self.pros_title)
        self.pros_scroll = QScrollArea()
        self.pros_scroll.setWidgetResizable(True)
        self.pros_container = QWidget()
        self.pros_layout = QVBoxLayout(self.pros_container)
        self.pros_layout.setAlignment(Qt.AlignTop)
        self.pros_scroll.setWidget(self.pros_container)
        pg.addWidget(self.pros_scroll, 1)

        pros_add = QHBoxLayout()
        self.pros_input = QLineEdit()
        self.pros_input.setPlaceholderText("Add a pro...")
        self.pros_input.returnPressed.connect(self._add_pro)
        self.pros_weight = QSpinBox()
        self.pros_weight.setRange(1, 10)
        self.pros_weight.setValue(5)
        self.pros_weight.setFixedWidth(50)
        pros_add.addWidget(self.pros_input, 1)
        pros_add.addWidget(self.pros_weight)
        pg.addLayout(pros_add)
        cols.addWidget(pros_group, 1)

        # Cons column
        cons_group = QGroupBox("CONS")
        cg = QVBoxLayout(cons_group)
        self.cons_title = QLabel("Cons")
        self.cons_title.setStyleSheet(f"color:#E64D4D;font-weight:bold;font-size:14px;")
        cg.addWidget(self.cons_title)
        self.cons_scroll = QScrollArea()
        self.cons_scroll.setWidgetResizable(True)
        self.cons_container = QWidget()
        self.cons_layout = QVBoxLayout(self.cons_container)
        self.cons_layout.setAlignment(Qt.AlignTop)
        self.cons_scroll.setWidget(self.cons_container)
        cg.addWidget(self.cons_scroll, 1)

        cons_add = QHBoxLayout()
        self.cons_input = QLineEdit()
        self.cons_input.setPlaceholderText("Add a con...")
        self.cons_input.returnPressed.connect(self._add_con)
        self.cons_weight = QSpinBox()
        self.cons_weight.setRange(1, 10)
        self.cons_weight.setValue(5)
        self.cons_weight.setFixedWidth(50)
        cons_add.addWidget(self.cons_input, 1)
        cons_add.addWidget(self.cons_weight)
        cg.addLayout(cons_add)
        cols.addWidget(cons_group, 1)

        layout.addLayout(cols, 1)

        # bottom buttons
        bb = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_data)
        clear_btn = QPushButton("Clear All")
        clear_btn.clicked.connect(self._clear_all)
        clear_btn.setStyleSheet(f"background:{self.theme['DELETE_COLOR']};color:white;border:none;border-radius:3px;")
        bb.addWidget(save_btn)
        bb.addWidget(clear_btn)
        layout.addLayout(bb)

    def _add_pro(self):
        txt = self.pros_input.text().strip()
        if txt:
            self.pros.append({'text': txt, 'weight': self.pros_weight.value()})
            self.pros_input.clear()
            self._refresh()

    def _add_con(self):
        txt = self.cons_input.text().strip()
        if txt:
            self.cons.append({'text': txt, 'weight': self.cons_weight.value()})
            self.cons_input.clear()
            self._refresh()

    def _remove_pro(self, idx):
        self.pros.pop(idx)
        self._refresh()

    def _remove_con(self, idx):
        self.cons.pop(idx)
        self._refresh()

    def _refresh(self):
        # pros
        clear_layout(self.pros_layout)
        for i, p in enumerate(self.pros):
            row = QHBoxLayout()
            w = QLabel(f"[{p['weight']}] {p['text']}")
            w.setWordWrap(True)
            w.setStyleSheet(f"color:{self.theme['TEXT_COLOR']};font-size:13px;")
            row.addWidget(w, 1)
            db = QPushButton("\u2715")
            db.setFixedSize(22, 22)
            db.setStyleSheet(f"background:{self.theme['DELETE_COLOR']};color:white;border:none;border-radius:3px;font-size:10px;")
            db.clicked.connect(lambda _, idx=i: self._remove_pro(idx))
            row.addWidget(db)
            self.pros_layout.addLayout(row)

        # cons
        clear_layout(self.cons_layout)
        for i, c in enumerate(self.cons):
            row = QHBoxLayout()
            w = QLabel(f"[{c['weight']}] {c['text']}")
            w.setWordWrap(True)
            w.setStyleSheet(f"color:{self.theme['TEXT_COLOR']};font-size:13px;")
            row.addWidget(w, 1)
            db = QPushButton("\u2715")
            db.setFixedSize(22, 22)
            db.setStyleSheet(f"background:{self.theme['DELETE_COLOR']};color:white;border:none;border-radius:3px;font-size:10px;")
            db.clicked.connect(lambda _, idx=i: self._remove_con(idx))
            row.addWidget(db)
            self.cons_layout.addLayout(row)

        self._update_balance()

    def _update_balance(self):
        p_total = sum(p['weight'] for p in self.pros) or 1
        c_total = sum(c['weight'] for c in self.cons) or 1
        total = p_total + c_total
        p_pct = int((p_total / total) * 100)
        c_pct = 100 - p_pct

        # Update stretch factors
        hb = self.balance_frame.layout()
        hb.setStretch(0, p_total)
        hb.setStretch(1, c_total)

        diff = p_total - c_total
        if diff > 0:
            self.balance_label.setText(f"Pros lead by {diff} points ({p_pct}%)")
            self.balance_label.setStyleSheet("color:#4DCC66;font-weight:bold;font-size:13px;")
        elif diff < 0:
            self.balance_label.setText(f"Cons lead by {-diff} points ({c_pct}%)")
            self.balance_label.setStyleSheet("color:#E64D4D;font-weight:bold;font-size:13px;")
        else:
            self.balance_label.setText("Evenly balanced (50/50)")
            self.balance_label.setStyleSheet(f"color:{self.theme['ACCENT_COLOR']};font-weight:bold;font-size:13px;")

    def _clear_all(self):
        self.pros.clear()
        self.cons.clear()
        self.title_edit.clear()
        self._refresh()

    def save_data(self):
        data = {'title': self.title_edit.text(), 'pros': self.pros, 'cons': self.cons}
        safe_json_dump(PROSCONS_FILE, data, indent=2)
        self.save_signal.emit()

    def load_data(self):
        data = safe_json_load(PROSCONS_FILE, default=None)
        if data and isinstance(data, dict):
            self.title_edit.setText(data.get('title', ''))
            self.pros = data.get('pros', [])
            self.cons = data.get('cons', [])
            self._refresh()

    def apply_theme(self, theme):
        self.theme = theme
        self._refresh()


class DecisionMatrixWidget(QWidget):
    """Weighted decision matrix: score options against criteria."""
    save_signal = Signal()

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.options = ['Option A', 'Option B']
        self.criteria = [{'name': 'Cost', 'weight': 5}, {'name': 'Time', 'weight': 3}]
        self.scores = {}  # (option_idx, crit_idx) -> score
        self._build_ui()
        self.load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # title
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Decision: e.g., Which car to buy?")
        self.title_edit.setStyleSheet(f"font-size:15px;font-weight:bold;background:{self.theme['INPUT_BG']};color:{self.theme['TEXT_COLOR']};border:none;padding:6px;border-radius:4px;")
        layout.addWidget(self.title_edit)

        # toolbar
        tb = QHBoxLayout()
        add_opt = QPushButton("+ Option")
        add_opt.clicked.connect(self._add_option)
        add_crit = QPushButton("+ Criterion")
        add_crit.clicked.connect(self._add_criterion)
        del_opt = QPushButton("- Option")
        del_opt.setStyleSheet(f"background:{self.theme['DELETE_COLOR']};color:white;border:none;border-radius:3px;")
        del_opt.clicked.connect(self._del_last_option)
        del_crit = QPushButton("- Criterion")
        del_crit.setStyleSheet(f"background:{self.theme['DELETE_COLOR']};color:white;border:none;border-radius:3px;")
        del_crit.clicked.connect(self._del_last_criterion)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.save_data)
        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(f"background:{self.theme['DELETE_COLOR']};color:white;border:none;border-radius:3px;")
        clear_btn.clicked.connect(self._clear_all)
        for b in (add_opt, add_crit, del_opt, del_crit, save_btn, clear_btn):
            tb.addWidget(b)
        layout.addLayout(tb)

        # table
        self.table = QTableWidget()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.table, 1)

        # result
        self.result_label = QLabel()
        self.result_label.setAlignment(Qt.AlignCenter)
        self.result_label.setStyleSheet(f"font-size:14px;font-weight:bold;padding:6px;")
        layout.addWidget(self.result_label)

        self._build_table()

    def _build_table(self):
        self.table.blockSignals(True)
        n_crit = len(self.criteria)
        n_opt = len(self.options)
        # Columns: Option name, crit1_weight, crit1_score_opt1, crit1_score_opt2, ..., crit2_weight, ...
        # Simpler: Rows = options, Cols = criteria (header shows weight), last col = weighted total
        self.table.setColumnCount(n_crit + 2)  # option name, criteria scores..., total
        self.table.setRowCount(n_opt + 1)  # options + weight row

        headers = ['Option']
        for c in self.criteria:
            headers.append(f"{c['name']} (w={c['weight']})")
        headers.append('TOTAL')
        self.table.setHorizontalHeaderLabels(headers)

        # Weight row (last row)
        weight_row = n_opt
        wlabel = QTableWidgetItem("Weight")
        wlabel.setFlags(wlabel.flags() & ~Qt.ItemIsEditable)
        wlabel.setBackground(QColor(self.theme['PROGRESS_BG']))
        wlabel.setForeground(QColor(self.theme['TEXT_COLOR']))
        self.table.setItem(weight_row, 0, wlabel)
        for j, c in enumerate(self.criteria):
            witem = QTableWidgetItem(str(c['weight']))
            witem.setBackground(QColor(self.theme['PROGRESS_BG']))
            witem.setForeground(QColor(self.theme['TEXT_COLOR']))
            self.table.setItem(weight_row, j + 1, witem)
        total_item = QTableWidgetItem("")
        total_item.setBackground(QColor(self.theme['PROGRESS_BG']))
        self.table.setItem(weight_row, n_crit + 1, total_item)

        # Data rows
        for i, opt in enumerate(self.options):
            name_item = QTableWidgetItem(opt)
            self.table.setItem(i, 0, name_item)
            for j in range(n_crit):
                key = (i, j)
                score = self.scores.get(key, 0)
                sitem = QTableWidgetItem(str(score))
                sitem.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, j + 1, sitem)
            # Total (computed)
            total = sum(self.scores.get((i, j), 0) * self.criteria[j]['weight'] for j in range(n_crit))
            titem = QTableWidgetItem(str(total))
            titem.setTextAlignment(Qt.AlignCenter)
            titem.setFlags(titem.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(i, n_crit + 1, titem)

        self._highlight_winner()
        self.table.blockSignals(False)

    def _highlight_winner(self):
        n_opt = len(self.options)
        n_crit = len(self.criteria)
        totals = []
        for i in range(n_opt):
            total = sum(self.scores.get((i, j), 0) * self.criteria[j]['weight'] for j in range(n_crit))
            totals.append((total, i))
        totals.sort(reverse=True)

        if totals:
            winner_idx = totals[0][1]
            winner_score = totals[0][0]
            if n_opt > 1 and totals[0][0] != totals[1][0]:
                self.result_label.setText(f"\u2b50 Best: {self.options[winner_idx]} (score: {winner_score})")
                self.result_label.setStyleSheet(f"color:{self.theme['PROGRESS_FG']};font-size:14px;font-weight:bold;padding:6px;")
            else:
                self.result_label.setText("Tie or insufficient data to determine winner.")
                self.result_label.setStyleSheet(f"color:{self.theme['ACCENT_COLOR']};font-size:14px;font-weight:bold;padding:6px;")

        # Color winner row
        for i in range(n_opt):
            for j in range(n_crit + 2):
                item = self.table.item(i, j)
                if item:
                    item.setBackground(QColor(self.theme['CARD_BG']))
        if totals and n_opt > 1 and totals[0][0] != totals[1][0]:
            for j in range(n_crit + 2):
                item = self.table.item(winner_idx, j)
                if item:
                    item.setBackground(QColor('#2a4a2a') if self.theme['IS_DARK'] else QColor('#d4edda'))

    def _on_cell_changed(self, row, col):
        n_opt = len(self.options)
        n_crit = len(self.criteria)
        self.table.blockSignals(True)

        if row < n_opt:
            if col == 0:
                # Option name
                item = self.table.item(row, col)
                if item and row < len(self.options):
                    self.options[row] = item.text()
            elif 1 <= col <= n_crit:
                # Score
                item = self.table.item(row, col)
                if item:
                    try:
                        self.scores[(row, col - 1)] = max(0, int(item.text()))
                    except ValueError:
                        self.scores[(row, col - 1)] = 0
                # Update totals
                total = sum(self.scores.get((row, j), 0) * self.criteria[j]['weight'] for j in range(n_crit))
                titem = self.table.item(row, n_crit + 1)
                if titem:
                    titem.setText(str(total))
                self._highlight_winner()
        elif row == n_opt and 1 <= col <= n_crit:
            # Weight edit
            item = self.table.item(row, col)
            if item and (col - 1) < len(self.criteria):
                try:
                    self.criteria[col - 1]['weight'] = max(1, int(item.text()))
                except ValueError:
                    pass
                # Rebuild header
                headers = ['Option']
                for c in self.criteria:
                    headers.append(f"{c['name']} (w={c['weight']})")
                headers.append('TOTAL')
                self.table.setHorizontalHeaderLabels(headers)
                # Recompute all totals
                for i in range(n_opt):
                    total = sum(self.scores.get((i, j), 0) * self.criteria[j]['weight'] for j in range(n_crit))
                    titem = self.table.item(i, n_crit + 1)
                    if titem:
                        titem.setText(str(total))
                self._highlight_winner()

        self.table.blockSignals(False)

    def _add_option(self):
        name = f"Option {len(self.options) + 1}"
        self.options.append(name)
        self._build_table()

    def _add_criterion(self):
        name = f"Criterion {len(self.criteria) + 1}"
        self.criteria.append({'name': name, 'weight': 5})
        self._build_table()

    def _del_last_option(self):
        if len(self.options) > 1:
            idx = len(self.options) - 1
            self.scores = {k: v for k, v in self.scores.items() if k[0] != idx}
            ns = {}
            for (oi, ci), v in self.scores.items():
                ns[(oi - 1 if oi > idx else oi, ci)] = v
            self.scores = ns
            self.options.pop()
            self._build_table()

    def _del_last_criterion(self):
        if len(self.criteria) > 1:
            idx = len(self.criteria) - 1
            self.scores = {k: v for k, v in self.scores.items() if k[1] != idx}
            ns = {}
            for (oi, ci), v in self.scores.items():
                ns[(oi, ci - 1 if ci > idx else ci)] = v
            self.scores = ns
            self.criteria.pop()
            self._build_table()

    def _clear_all(self):
        self.options = ['Option A', 'Option B']
        self.criteria = [{'name': 'Cost', 'weight': 5}, {'name': 'Time', 'weight': 3}]
        self.scores.clear()
        self.title_edit.clear()
        self._build_table()

    def save_data(self):
        data = {
            'title': self.title_edit.text(),
            'options': self.options,
            'criteria': self.criteria,
            'scores': {f"{k[0]},{k[1]}": v for k, v in self.scores.items()}
        }
        safe_json_dump(MATRIX_FILE, data, indent=2)
        self.save_signal.emit()

    def load_data(self):
        data = safe_json_load(MATRIX_FILE, default=None)
        if data and isinstance(data, dict):
            self.title_edit.setText(data.get('title', ''))
            self.options = data.get('options', self.options)
            self.criteria = data.get('criteria', self.criteria)
            raw = data.get('scores', {})
            self.scores = {(int(k.split(',')[0]), int(k.split(',')[1])): v for k, v in raw.items()}
            self._build_table()

    def apply_theme(self, theme):
        self.theme = theme
        self._build_table()


class RandomPickerWidget(QWidget):
    """Random choice picker with spin animation, coin flip, and dice roll."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.items = []
        self.spinning = False
        self._build_ui()
        self.load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Tabs for different modes
        tabs = QTabWidget()
        tabs.setStyleSheet(f"""
            QTabWidget::pane {{ border:1px solid {self.theme['PROGRESS_BG']}; border-radius:4px; background:{self.theme['CARD_BG']}; }}
            QTabBar::tab {{ background:{self.theme['INPUT_BG']}; color:{self.theme['TEXT_COLOR']}; padding:8px 16px; border-top-left-radius:4px; border-top-right-radius:4px; margin-right:2px; }}
            QTabBar::tab:selected {{ background:{self.theme['ACCENT_COLOR']}; color:white; }}
        """)

        # --- Picker Tab ---
        picker_widget = QWidget()
        pl = QVBoxLayout(picker_widget)

        # Item list
        self.picker_list_widget = QWidget()
        self.picker_list_layout = QVBoxLayout(self.picker_list_widget)
        self.picker_list_layout.setAlignment(Qt.AlignTop)
        picker_scroll = QScrollArea()
        picker_scroll.setWidgetResizable(True)
        picker_scroll.setWidget(self.picker_list_widget)
        pl.addWidget(picker_scroll, 1)

        # Add item
        add_row = QHBoxLayout()
        self.picker_input = QLineEdit()
        self.picker_input.setPlaceholderText("Add a choice...")
        self.picker_input.returnPressed.connect(self._add_picker_item)
        self.picker_input.setStyleSheet(f"background:{self.theme['INPUT_BG']};color:{self.theme['TEXT_COLOR']};border:1px solid {self.theme['PROGRESS_BG']};padding:5px;border-radius:3px;")
        add_row.addWidget(self.picker_input, 1)
        add_btn = QPushButton("+")
        add_btn.setFixedWidth(40)
        add_btn.clicked.connect(self._add_picker_item)
        add_row.addWidget(add_btn)
        pl.addLayout(add_row)

        # Spin button & result
        self.spin_btn = QPushButton("SPIN!")
        self.spin_btn.setFixedHeight(50)
        self.spin_btn.setStyleSheet(f"background:{self.theme['ACCENT_COLOR']};color:white;font-size:20px;font-weight:bold;border:none;border-radius:8px;")
        self.spin_btn.clicked.connect(self._spin)
        pl.addWidget(self.spin_btn)

        self.result_lbl = QLabel("")
        self.result_lbl.setAlignment(Qt.AlignCenter)
        self.result_lbl.setStyleSheet(f"font-size:24px;font-weight:bold;color:{self.theme['PROGRESS_FG']};padding:10px;")
        pl.addWidget(self.result_lbl)

        tabs.addTab(picker_widget, "Picker")

        # --- Coin Tab ---
        coin_widget = QWidget()
        cl = QVBoxLayout(coin_widget)
        cl.setAlignment(Qt.AlignCenter)
        self.coin_btn = QPushButton("FLIP COIN")
        self.coin_btn.setFixedSize(150, 150)
        self.coin_btn.setStyleSheet(f"""
            QPushButton {{ background:{self.theme['ACCENT_COLOR']};color:white;font-size:18px;font-weight:bold;border:none;border-radius:75px; }}
            QPushButton:hover {{ background:{self.theme['EDIT_COLOR']}; }}
        """)
        self.coin_btn.clicked.connect(self._flip_coin)
        cl.addWidget(self.coin_btn)
        self.coin_result = QLabel("")
        self.coin_result.setAlignment(Qt.AlignCenter)
        self.coin_result.setStyleSheet(f"font-size:28px;font-weight:bold;color:{self.theme['TEXT_COLOR']};padding:10px;")
        cl.addWidget(self.coin_result)
        self.coin_history = QLabel("")
        self.coin_history.setAlignment(Qt.AlignCenter)
        self.coin_history.setStyleSheet(f"color:{self.theme['COMPLETED_COLOR']};font-size:12px;")
        cl.addWidget(self.coin_history)
        self._coin_flips = []
        tabs.addTab(coin_widget, "Coin")

        # --- Dice Tab ---
        dice_widget = QWidget()
        dl = QVBoxLayout(dice_widget)
        dl.setAlignment(Qt.AlignCenter)
        self.dice_btn = QPushButton("ROLL DICE")
        self.dice_btn.setFixedSize(150, 150)
        self.dice_btn.setStyleSheet(f"""
            QPushButton {{ background:{self.theme['PROGRESS_FG']};color:white;font-size:18px;font-weight:bold;border:none;border-radius:20px; }}
            QPushButton:hover {{ background:{self.theme['ACCENT_COLOR']}; }}
        """)
        self.dice_btn.clicked.connect(self._roll_dice)
        dl.addWidget(self.dice_btn)
        self.dice_result = QLabel("")
        self.dice_result.setAlignment(Qt.AlignCenter)
        self.dice_result.setStyleSheet(f"font-size:48px;font-weight:bold;color:{self.theme['TEXT_COLOR']};padding:10px;")
        dl.addWidget(self.dice_result)

        # Dice count
        dc_row = QHBoxLayout()
        dc_row.setAlignment(Qt.AlignCenter)
        dc_row.addWidget(QLabel("Number of dice:"))
        self.dice_count = QSpinBox()
        self.dice_count.setRange(1, 10)
        self.dice_count.setValue(1)
        self.dice_count.setFixedWidth(60)
        dc_row.addWidget(self.dice_count)
        dl.addLayout(dc_row)
        tabs.addTab(dice_widget, "Dice")

        layout.addWidget(tabs, 1)

    # ---- Picker ----
    def _add_picker_item(self):
        txt = self.picker_input.text().strip()
        if txt:
            self.items.append(txt)
            self.picker_input.clear()
            self._refresh_picker_list()
            self._save_data()

    def _remove_picker_item(self, idx):
        self.items.pop(idx)
        self._refresh_picker_list()
        self._save_data()

    def _refresh_picker_list(self):
        clear_layout(self.picker_list_layout)
        for i, item in enumerate(self.items):
            row = QHBoxLayout()
            lbl = QLabel(f"{i + 1}. {item}")
            lbl.setStyleSheet(f"color:{self.theme['TEXT_COLOR']};font-size:13px;")
            row.addWidget(lbl, 1)
            db = QPushButton("\u2715")
            db.setFixedSize(22, 22)
            db.setStyleSheet(f"background:{self.theme['DELETE_COLOR']};color:white;border:none;border-radius:3px;font-size:10px;")
            db.clicked.connect(lambda _, idx=i: self._remove_picker_item(idx))
            row.addWidget(db)
            self.picker_list_layout.addLayout(row)

    def _spin(self):
        if not self.items or self.spinning:
            return
        self.spinning = True
        self.spin_btn.setEnabled(False)
        self.result_lbl.setText("")
        self.result_lbl.setStyleSheet(f"font-size:24px;font-weight:bold;color:{self.theme['TEXT_COLOR']};padding:10px;")

        steps = random.randint(15, 30)
        self._spin_step(0, steps)

    def _spin_step(self, current, total):
        if current >= total:
            winner = random.choice(self.items)
            self.result_lbl.setText(f"\U0001f3c6 {winner}")
            self.result_lbl.setStyleSheet(f"font-size:24px;font-weight:bold;color:{self.theme['PROGRESS_FG']};padding:10px;")
            self.spinning = False
            self.spin_btn.setEnabled(True)
            return
        idx = current % len(self.items)
        self.result_lbl.setText(self.items[idx])
        delay = 50 + int(current * (current / total) * 200)
        QTimer.singleShot(delay, lambda: self._spin_step(current + 1, total))

    # ---- Coin ----
    def _flip_coin(self):
        result = random.choice(["HEADS", "TAILS"])
        self._coin_flips.append(result)
        self.coin_result.setText(result)
        h = self._coin_flips.count("HEADS")
        t = self._coin_flips.count("TAILS")
        total = len(self._coin_flips)
        self.coin_history.setText(f"History: {h}H / {t}T ({total} flips)")

    # ---- Dice ----
    def _roll_dice(self):
        n = self.dice_count.value()
        rolls = [random.randint(1, 6) for _ in range(n)]
        total = sum(rolls)
        if n == 1:
            self.dice_result.setText(str(rolls[0]))
        else:
            self.dice_result.setText(f"{' + '.join(map(str, rolls))} = {total}")

    # ---- persistence ----
    def _save_data(self):
        data = {'items': self.items}
        safe_json_dump(PICKER_FILE, data, indent=2)

    def load_data(self):
        data = safe_json_load(PICKER_FILE, default=None)
        if data and isinstance(data, dict):
            self.items = data.get('items', [])
            self._refresh_picker_list()

    def apply_theme(self, theme):
        self.theme = theme
        self._refresh_picker_list()

class CalendarWidget(QWidget):
    """Custom calendar view showing tasks on their due dates."""
    task_edit_requested = Signal(dict)

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.tasks = []
        self.view_year = date.today().year
        self.view_month = date.today().month
        self.selected_date = date.today()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # --- header: month nav ---
        nav = QHBoxLayout()
        self.prev_btn = QPushButton("\u25c0 Prev")
        self.prev_btn.setFixedWidth(80)
        self.prev_btn.clicked.connect(self._prev_month)
        self.month_label = QLabel()
        self.month_label.setAlignment(Qt.AlignCenter)
        self.month_label.setStyleSheet(f"font-size:18px;font-weight:bold;color:{self.theme['ACCENT_COLOR']};")
        self.next_btn = QPushButton("Next \u25b6")
        self.next_btn.setFixedWidth(80)
        self.next_btn.clicked.connect(self._next_month)
        self.today_btn = QPushButton("Today")
        self.today_btn.setFixedWidth(70)
        self.today_btn.clicked.connect(self._go_today)
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.month_label, 1)
        nav.addWidget(self.today_btn)
        nav.addWidget(self.next_btn)
        layout.addLayout(nav)

        self.month_stats = QLabel()
        self.month_stats.setAlignment(Qt.AlignCenter)
        self.month_stats.setStyleSheet(f"color:{self.theme['COMPLETED_COLOR']};font-size:11px;padding:2px;")
        layout.addWidget(self.month_stats)

        # --- calendar grid ---
        grid_frame = QFrame()
        grid_frame.setStyleSheet(f"background:{self.theme['CARD_BG']};border:1px solid {self.theme['PROGRESS_BG']};border-radius:6px;")
        self.grid_layout = QGridLayout(grid_frame)
        self.grid_layout.setSpacing(2)
        self.grid_layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(grid_frame)

        # --- task list for selected day ---
        self.day_header = QLabel()
        self.day_header.setStyleSheet(f"font-size:15px;font-weight:bold;color:{self.theme['ACCENT_COLOR']};padding:6px;")
        layout.addWidget(self.day_header)

        self.task_scroll = QScrollArea()
        self.task_scroll.setWidgetResizable(True)
        self.task_container = QWidget()
        self.task_list_layout = QVBoxLayout(self.task_container)
        self.task_list_layout.setAlignment(Qt.AlignTop)
        self.task_scroll.setWidget(self.task_container)
        layout.addWidget(self.task_scroll, 1)

        self._render_calendar()

    def set_tasks(self, tasks):
        self.tasks = tasks
        self._render_calendar()
        self._render_day_tasks()

    def _prev_month(self):
        if self.view_month == 1:
            self.view_month = 12
            self.view_year -= 1
        else:
            self.view_month -= 1
        self._render_calendar()

    def _next_month(self):
        if self.view_month == 12:
            self.view_month = 1
            self.view_year += 1
        else:
            self.view_month += 1
        self._render_calendar()

    def _go_today(self):
        self.view_year = date.today().year
        self.view_month = date.today().month
        self.selected_date = date.today()
        self._render_calendar()

    def _render_calendar(self):
        # Clear grid
        clear_layout(self.grid_layout)

        self.month_label.setText(f"{month_name[self.view_month]} {self.view_year}")

        # Day headers
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        for i, d in enumerate(days):
            lbl = QLabel(d)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedHeight(28)
            lbl.setStyleSheet(f"color:{self.theme['COMPLETED_COLOR']};font-weight:bold;font-size:12px;")
            self.grid_layout.addWidget(lbl, 0, i)

        # Build date->tasks map
        date_tasks = {}
        for t in self.tasks:
            ds = t.get('due_date', '')
            if ds:
                try:
                    dt = datetime.strptime(ds, '%Y-%m-%d').date()
                    date_tasks.setdefault(dt, []).append(t)
                except ValueError:
                    pass

        # Calendar weeks
        weeks = monthcalendar(self.view_year, self.view_month)
        today = date.today()

        for row_idx, week in enumerate(weeks):
            for col_idx, day_num in enumerate(week):
                if day_num == 0:
                    empty = QLabel("")
                    self.grid_layout.addWidget(empty, row_idx + 1, col_idx)
                    continue

                d = date(self.view_year, self.view_month, day_num)
                tasks_on_day = date_tasks.get(d, [])

                btn = QPushButton(str(day_num))
                btn.setFixedSize(48, 48)
                btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

                is_today = (d == today)
                is_selected = (d == self.selected_date)
                has_tasks = len(tasks_on_day) > 0
                has_overdue = any(not t['completed'] for t in tasks_on_day) and d < today

                # Style
                if is_selected:
                    bg = self.theme['ACCENT_COLOR']
                    fg = 'white'
                elif is_today:
                    bg = '#E6B333'
                    fg = 'white'
                else:
                    bg = self.theme['INPUT_BG']
                    fg = self.theme['TEXT_COLOR']

                extra = ""
                if has_overdue:
                    extra = f"border:2px solid #E64D4D;"
                elif has_tasks:
                    extra = f"border:2px solid {self.theme['PROGRESS_FG']};"

                btn.setStyleSheet(f"""
                    QPushButton {{
                        background:{bg};color:{fg};border:none;border-radius:6px;
                        font-size:14px;font-weight:bold;{extra}
                    }}
                """)

                if has_tasks:
                    # Show dot indicator
                    done_count = sum(1 for t in tasks_on_day if t['completed'])
                    total_count = len(tasks_on_day)
                    if done_count == total_count:
                        dot_color = self.theme['PROGRESS_FG']
                    else:
                        dot_color = '#E64D4D' if has_overdue else self.theme['ACCENT_COLOR']
                    btn.setText(f"{day_num}\n\u2022{total_count}")
                    btn.setStyleSheet(f"""
                        QPushButton {{
                            background:{bg};color:{fg};border:none;border-radius:6px;
                            font-size:11px;font-weight:bold;{extra}
                        }}
                    """)

                btn.clicked.connect(lambda checked, dd=d: self._select_date(dd))
                self.grid_layout.addWidget(btn, row_idx + 1, col_idx)

        # Add stretch at bottom
        spacer = QWidget()
        self.grid_layout.addWidget(spacer, len(weeks) + 2, 0, 1, 7)

        mp = f"{self.view_year}-{self.view_month:02d}"
        mt = [t for t in self.tasks if (t.get("due_date") or "").startswith(mp)]
        dn = sum(1 for t in mt if t["completed"])
        od = sum(1 for t in mt if not t["completed"] and t.get("due_date","") < date.today().strftime("%Y-%m-%d"))
        self.month_stats.setText(f"{len(mt)} tasks | {dn} done | {od} overdue")

    def _select_date(self, d):
        self.selected_date = d
        self._update_calendar_selection()
        self._render_day_tasks()

    def _update_calendar_selection(self):
        """Re-style calendar buttons to reflect current selection without full rebuild."""
        today = date.today()
        for i in range(self.grid_layout.count()):
            item = self.grid_layout.itemAt(i)
            w = item.widget() if item else None
            if w and isinstance(w, QPushButton) and w.text() and w.text()[0].isdigit():
                try:
                    day_num = int(w.text().split('\n')[0])
                    d = date(self.view_year, self.view_month, day_num)
                except (ValueError, IndexError):
                    continue
                is_today = (d == today)
                is_selected = (d == self.selected_date)
                ds = d.strftime('%Y-%m-%d')
                tasks_on_day = [t for t in self.tasks if t.get('due_date') == ds]
                has_tasks = len(tasks_on_day) > 0
                has_overdue = any(not t['completed'] for t in tasks_on_day) and d < today

                if is_selected:
                    bg = self.theme['ACCENT_COLOR']
                    fg = 'white'
                elif is_today:
                    bg = '#E6B333'
                    fg = 'white'
                else:
                    bg = self.theme['INPUT_BG']
                    fg = self.theme['TEXT_COLOR']

                extra = ""
                if has_overdue:
                    extra = f"border:2px solid #E64D4D;"
                elif has_tasks:
                    extra = f"border:2px solid {self.theme['PROGRESS_FG']};"

                if has_tasks:
                    done_count = sum(1 for t in tasks_on_day if t['completed'])
                    total_count = len(tasks_on_day)
                    if done_count == total_count:
                        dot_color = self.theme['PROGRESS_FG']
                    else:
                        dot_color = '#E64D4D' if has_overdue else self.theme['ACCENT_COLOR']
                    w.setText(f"{day_num}\n•{total_count}")
                    w.setStyleSheet(f"""
                        QPushButton {{
                            background:{bg};color:{fg};border:none;border-radius:6px;
                            font-size:11px;font-weight:bold;{extra}
                        }}
                    """)
                else:
                    w.setText(str(day_num))
                    w.setStyleSheet(f"""
                        QPushButton {{
                            background:{bg};color:{fg};border:none;border-radius:6px;
                            font-size:14px;font-weight:bold;{extra}
                        }}
                    """)

    def _render_day_tasks(self):
        # Clear
        clear_layout(self.task_list_layout)

        ds = self.selected_date.strftime('%Y-%m-%d')
        self.day_header.setText(f"Tasks for {self.selected_date.strftime('%A, %B %d, %Y')}")

        day_tasks = [t for t in self.tasks if t.get('due_date') == ds]

        if not day_tasks:
            lbl = QLabel("No tasks for this day.")
            lbl.setStyleSheet(f"color:{self.theme['COMPLETED_COLOR']};font-size:13px;padding:10px;")
            lbl.setAlignment(Qt.AlignCenter)
            self.task_list_layout.addWidget(lbl)
            return

        for t in day_tasks:
            card = QFrame()
            card.setStyleSheet(f"background:{self.theme['CARD_BG']};border:1px solid {self.theme['PROGRESS_BG']};border-radius:5px;margin:2px;")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(10, 6, 10, 6)
            cl.setSpacing(2)

            # Task name
            name = t['text']
            if t['completed']:
                name = f"\u2713 {name}"
            name_lbl = QLabel(name)
            name_lbl.setWordWrap(True)
            p_color = '#E64D4D' if t['priority'] == 'High' else ('#E6B333' if t['priority'] == 'Medium' else '#4DCC66')
            if t['completed']:
                p_color = self.theme['COMPLETED_COLOR']
            name_lbl.setStyleSheet(f"color:{p_color};font-size:13px;font-weight:bold;")
            cl.addWidget(name_lbl)

            # Meta
            meta_parts = [f"[{t['priority']}]"]
            if t.get('category') and t['category'] != 'General':
                meta_parts.append(f"#{t['category']}")
            if t.get('context'):
                meta_parts.append(f"@{t['context']}")
            if t.get('repeats', 'None') != 'None':
                meta_parts.append(f"{t['repeats']}")
            meta_lbl = QLabel("  ".join(meta_parts))
            meta_lbl.setStyleSheet(f"color:{self.theme['COMPLETED_COLOR']};font-size:11px;")
            cl.addWidget(meta_lbl)

            # Description
            if t.get('description'):
                desc_lbl = QLabel(t['description'])
                desc_lbl.setWordWrap(True)
                desc_lbl.setStyleSheet(f"color:{self.theme['TEXT_COLOR']};font-size:11px;")
                cl.addWidget(desc_lbl)

            # Edit button
            edit_btn = QPushButton("Edit Task")
            edit_btn.setFixedHeight(24)
            edit_btn.setStyleSheet(f"background:{self.theme['EDIT_COLOR']};color:white;border:none;border-radius:3px;font-size:11px;")
            edit_btn.clicked.connect(lambda checked, task=t: self.task_edit_requested.emit(task))
            cl.addWidget(edit_btn)

            self.task_list_layout.addWidget(card)

    def apply_theme(self, theme):
        self.theme = theme
        self._render_calendar()
        self._render_day_tasks()

class FocusTimerWidget(QWidget):
    """Time boxing / Focus timer: work for a set duration or on a specific activity."""
    time_logged = Signal(str, int)  # task_id, elapsed_seconds

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.sessions = []
        self.total_seconds = 25 * 60
        self.remaining = self.total_seconds
        self.is_running = False
        self.is_paused = False
        self.timer = QTimer()
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self._build_ui()
        self.load_data()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # --- Setup Section ---
        self.setup_frame = QFrame()
        self.setup_frame.setStyleSheet(f"background:{self.theme['CARD_BG']}; border:1px solid {self.theme['PROGRESS_BG']}; border-radius:8px; padding:12px;")
        sl = QVBoxLayout(self.setup_frame)
        sl.setContentsMargins(12, 10, 12, 10)

        # Activity name
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Activity:"))
        self.activity_input = QLineEdit()
        self.activity_input.setPlaceholderText("What are you working on? (e.g., Deep Work, Code Review, Study)")
        name_row.addWidget(self.activity_input, 1)
        sl.addLayout(name_row)

        # Or link to a task
        task_row = QHBoxLayout()
        task_row.addWidget(QLabel("Or pick a task:"))
        self.task_combo = QComboBox()
        self.task_combo.addItem("-- None --", None)
        task_row.addWidget(self.task_combo, 1)
        sl.addLayout(task_row)

        # Duration presets
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Duration:"))
        self.presets = [(15, "15m"), (25, "25m"), (45, "45m"), (60, "1h"), (90, "1.5h"), (120, "2h")]
        self.preset_btns = []
        for mins, label in self.presets:
            b = QPushButton(label)
            b.setFixedWidth(50)
            b.clicked.connect(lambda _, m=mins: self._set_duration(m * 60))
            self.preset_btns.append(b)
            preset_row.addWidget(b)
        sl.addLayout(preset_row)

        # Custom duration
        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("Custom:"))
        self.hours_spin = QSpinBox()
        self.hours_spin.setRange(0, 8)
        self.hours_spin.setSuffix("h")
        self.hours_spin.setFixedWidth(60)
        self.mins_spin = QSpinBox()
        self.mins_spin.setRange(0, 59)
        self.mins_spin.setSuffix("m")
        self.mins_spin.setFixedWidth(60)
        self.mins_spin.setValue(25)
        custom_btn = QPushButton("Set")
        custom_btn.setFixedWidth(50)
        custom_btn.clicked.connect(lambda: self._set_duration(self.hours_spin.value() * 3600 + self.mins_spin.value() * 60))
        custom_row.addWidget(self.hours_spin)
        custom_row.addWidget(QLabel(":"))
        custom_row.addWidget(self.mins_spin)
        custom_row.addWidget(custom_btn)
        custom_row.addStretch()
        sl.addLayout(custom_row)

        layout.addWidget(self.setup_frame)

        # --- Timer Display ---
        self.timer_frame = QFrame()
        self.timer_frame.setStyleSheet(f"background:{self.theme['FOCUS_BG']}; border:2px solid {self.theme['PROGRESS_BG']}; border-radius:12px;")
        tl = QVBoxLayout(self.timer_frame)
        tl.setContentsMargins(20, 20, 20, 20)
        tl.setSpacing(8)

        self.activity_display = QLabel("Ready to focus")
        self.activity_display.setAlignment(Qt.AlignCenter)
        self.activity_display.setStyleSheet(f"color:{self.theme['COMPLETED_COLOR']}; font-size:14px;")
        tl.addWidget(self.activity_display)

        self.time_label = QLabel("25:00")
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet(f"font-size:72px; font-weight:bold; color:{self.theme['TEXT_COLOR']}; font-family:monospace;")
        tl.addWidget(self.time_label)

        # Progress bar
        self.focus_progress = QProgressBar()
        self.focus_progress.setTextVisible(False)
        self.focus_progress.setFixedHeight(8)
        self.focus_progress.setStyleSheet(f"""
            QProgressBar {{ background:{self.theme['PROGRESS_BG']}; border:none; border-radius:4px; }}
            QProgressBar::chunk {{ background:{self.theme['FOCUS_ACTIVE']}; border-radius:4px; }}
        """)
        tl.addWidget(self.focus_progress)

        # Status
        self.status_label = QLabel("Set an activity and duration, then press Start")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet(f"color:{self.theme['COMPLETED_COLOR']}; font-size:12px;")
        tl.addWidget(self.status_label)

        # Control buttons
        ctrl_row = QHBoxLayout()
        ctrl_row.setAlignment(Qt.AlignCenter)
        self.start_btn = QPushButton("\u25b6 Start")
        self.start_btn.setFixedSize(120, 44)
        self.start_btn.setStyleSheet(f"background:{self.theme['PROGRESS_FG']}; color:white; font-size:16px; font-weight:bold; border:none; border-radius:8px;")
        self.start_btn.clicked.connect(self._toggle_timer)
        ctrl_row.addWidget(self.start_btn)

        self.reset_btn = QPushButton("\u21ba Reset")
        self.reset_btn.setFixedSize(100, 44)
        self.reset_btn.setStyleSheet(f"background:{self.theme['INPUT_BG']}; color:{self.theme['TEXT_COLOR']}; font-size:14px; font-weight:bold; border:none; border-radius:8px;")
        self.reset_btn.clicked.connect(self._reset_timer)
        ctrl_row.addWidget(self.reset_btn)

        self.skip_btn = QPushButton("\u23ed Skip")
        self.skip_btn.setFixedSize(100, 44)
        self.skip_btn.setStyleSheet(f"background:{self.theme['DELETE_COLOR']}; color:white; font-size:14px; font-weight:bold; border:none; border-radius:8px;")
        self.skip_btn.clicked.connect(self._skip_session)
        ctrl_row.addWidget(self.skip_btn)

        tl.addLayout(ctrl_row)
        layout.addWidget(self.timer_frame, 1)

        # --- Today's Stats ---
        self.stats_frame = QFrame()
        self.stats_frame.setStyleSheet(f"background:{self.theme['CARD_BG']}; border:1px solid {self.theme['PROGRESS_BG']}; border-radius:8px;")
        stl = QHBoxLayout(self.stats_frame)
        stl.setContentsMargins(12, 8, 12, 8)
        self.sessions_today_label = QLabel("Today: 0 sessions | 0m focused")
        self.sessions_today_label.setStyleSheet(f"color:{self.theme['TEXT_COLOR']}; font-size:13px; font-weight:bold;")
        stl.addWidget(self.sessions_today_label)
        stl.addStretch()
        self.clear_history_btn = QPushButton("Clear History")
        self.clear_history_btn.setFixedHeight(28)
        self.clear_history_btn.setStyleSheet(f"background:{self.theme['DELETE_COLOR']}; color:white; border:none; border-radius:4px; font-size:11px;")
        self.clear_history_btn.clicked.connect(self._clear_history)
        stl.addWidget(self.clear_history_btn)
        layout.addWidget(self.stats_frame)

        # --- Timing Metrics ---
        self.metrics_frame = QFrame()
        self.metrics_frame.setStyleSheet(f"background:{self.theme['CARD_BG']}; border:1px solid {self.theme['PROGRESS_BG']}; border-radius:8px;")
        self.metrics_layout = QVBoxLayout(self.metrics_frame)
        self.metrics_layout.setContentsMargins(10, 6, 10, 6)
        self.metrics_layout.setSpacing(3)
        self.metrics_title = QLabel("Timing Metrics")
        self.metrics_title.setStyleSheet(f"color:{self.theme['ACCENT_COLOR']};font-size:13px;font-weight:bold;")
        self.metrics_layout.addWidget(self.metrics_title)
        self.metrics_content = QLabel()
        self.metrics_content.setWordWrap(True)
        self.metrics_content.setStyleSheet(f"color:{self.theme['TEXT_COLOR']};font-size:12px;")
        self.metrics_layout.addWidget(self.metrics_content)
        layout.addWidget(self.metrics_frame)

        # --- Session History ---
        self.history_label = QLabel("Recent Sessions")
        self.history_label.setStyleSheet(f"color:{self.theme['ACCENT_COLOR']}; font-size:14px; font-weight:bold; padding:4px;")
        layout.addWidget(self.history_label)

        self.history_scroll = QScrollArea()
        self.history_scroll.setWidgetResizable(True)
        self.history_container = QWidget()
        self.history_layout = QVBoxLayout(self.history_container)
        self.history_layout.setAlignment(Qt.AlignTop)
        self.history_scroll.setWidget(self.history_container)
        layout.addWidget(self.history_scroll, 1)

        self._set_duration(25 * 60)
        self._update_stats()
        self._render_metrics()

    def _set_duration(self, seconds):
        if self.is_running:
            return
        self.total_seconds = max(60, seconds)
        self.remaining = self.total_seconds
        self._update_display()

    def _toggle_timer(self):
        if not self.is_running:
            activity = self.activity_input.text().strip()
            if not activity:
                idx = self.task_combo.currentIndex()
                if idx > 0:
                    activity = self.task_combo.currentText()
                else:
                    self.status_label.setText("Enter an activity name first!")
                    return
            self.activity_display.setText(activity)
            self.is_running = True
            self.is_paused = False
            self.start_btn.setText("\u23f8 Pause")
            self.start_btn.setStyleSheet(f"background:{self.theme['FOCUS_ACTIVE']}; color:#1e1e2e; font-size:16px; font-weight:bold; border:none; border-radius:8px;")
            self.activity_input.setEnabled(False)
            self.task_combo.setEnabled(False)
            self.status_label.setText("Focusing... Stay on track!")
            self.timer.start()
        elif not self.is_paused:
            self.is_paused = True
            self.timer.stop()
            self.start_btn.setText("\u25b6 Resume")
            self.start_btn.setStyleSheet(f"background:{self.theme['ACCENT_COLOR']}; color:white; font-size:16px; font-weight:bold; border:none; border-radius:8px;")
            self.status_label.setText("Paused")
        else:
            self.is_paused = False
            self.timer.start()
            self.start_btn.setText("\u23f8 Pause")
            self.start_btn.setStyleSheet(f"background:{self.theme['FOCUS_ACTIVE']}; color:#1e1e2e; font-size:16px; font-weight:bold; border:none; border-radius:8px;")
            self.status_label.setText("Focusing... Stay on track!")

    def _reset_timer(self):
        self.timer.stop()
        self.is_running = False
        self.is_paused = False
        self.remaining = self.total_seconds
        self._update_display()
        self.start_btn.setText("\u25b6 Start")
        self.start_btn.setStyleSheet(f"background:{self.theme['PROGRESS_FG']}; color:white; font-size:16px; font-weight:bold; border:none; border-radius:8px;")
        self.activity_input.setEnabled(True)
        self.task_combo.setEnabled(True)
        self.status_label.setText("Timer reset")

    def _skip_session(self):
        if self.is_running:
            elapsed = self.total_seconds - self.remaining
            if elapsed > 0:
                self._record_session(elapsed)
            self._reset_timer()

    def _tick(self):
        if self.remaining > 0:
            self.remaining -= 1
            self._update_display()
        else:
            self.timer.stop()
            self._record_session(self.total_seconds)
            self.is_running = False
            self.is_paused = False
            self.remaining = self.total_seconds
            self._update_display()
            self.start_btn.setText("\u25b6 Start")
            self.start_btn.setStyleSheet(f"background:{self.theme['PROGRESS_FG']}; color:white; font-size:16px; font-weight:bold; border:none; border-radius:8px;")
            self.activity_input.setEnabled(True)
            self.task_combo.setEnabled(True)
            self.status_label.setText("Session complete! Great work.")
            # Flash the window title
            if self.window():
                self.window().setWindowTitle("\u2b50 Session Complete! - Ultimate Tasks")
                QTimer.singleShot(5000, lambda: self.window().setWindowTitle("Ultimate Tasks") if self.window() else None)

    def _update_display(self):
        self.time_label.setText(fmt_duration(self.remaining))
        pct = int(((self.total_seconds - self.remaining) / self.total_seconds) * 100) if self.total_seconds > 0 else 0
        self.focus_progress.setValue(pct)

    def _record_session(self, elapsed_seconds):
        activity = self.activity_display.text()
        if activity == "Ready to focus":
            activity = "Untitled Session"
        task_id = self.task_combo.currentData() or ''
        session = {
            'id': uuid.uuid4().hex[:8],
            'activity': activity,
            'task_id': task_id,
            'duration_minutes': self.total_seconds // 60,
            'elapsed_seconds': elapsed_seconds,
            'completed': elapsed_seconds >= self.total_seconds,
            'timestamp': datetime.now().isoformat()
        }
        self.sessions.append(session)
        # Accumulate time on the linked task
        if task_id and elapsed_seconds > 0:
            self.time_logged.emit(task_id, elapsed_seconds)
        self.save_data()
        self._update_stats()
        self._render_metrics()
        self._render_history()

    def _update_stats(self):
        today = datetime.now().strftime('%Y-%m-%d')
        today_sessions = [s for s in self.sessions if s['timestamp'].startswith(today)]
        total_secs = sum(s['elapsed_seconds'] for s in today_sessions)
        completed = sum(1 for s in today_sessions if s['completed'])
        self.sessions_today_label.setText(
            f"Today: {len(today_sessions)} sessions ({completed} completed) | {fmt_duration(total_secs)} focused"
        )

    def _render_metrics(self):
        """Render enhanced timing metrics: weekly, avg, streak, top activities, per-task."""
        if not self.sessions:
            self.metrics_content.setText("No sessions recorded yet.")
            return

        today = datetime.now().strftime('%Y-%m-%d')
        now_dt = datetime.now()

        # --- This week's total ---
        week_start = (now_dt - timedelta(days=now_dt.weekday())).strftime('%Y-%m-%d')
        week_sessions = [s for s in self.sessions if s['timestamp'][:10] >= week_start]
        week_secs = sum(s['elapsed_seconds'] for s in week_sessions)

        # --- All-time total ---
        all_secs = sum(s['elapsed_seconds'] for s in self.sessions)

        # --- Average session (today) ---
        today_sessions = [s for s in self.sessions if s['timestamp'].startswith(today)]
        today_secs = sum(s['elapsed_seconds'] for s in today_sessions)
        avg_today = int(today_secs / len(today_sessions)) if today_sessions else 0

        # --- Completion rate ---
        total_sessions = len(self.sessions)
        completed_sessions = sum(1 for s in self.sessions if s['completed'])
        comp_rate = int((completed_sessions / total_sessions) * 100) if total_sessions else 0

        # --- Streak (consecutive days with >= 1 completed session) ---
        streak = 0
        check_date = now_dt.date()
        for _ in range(365):
            day_str = check_date.strftime('%Y-%m-%d')
            day_completed = any(s['timestamp'].startswith(day_str) and s['completed'] for s in self.sessions)
            if day_completed:
                streak += 1
                check_date -= timedelta(days=1)
            else:
                break

        # --- Top activities by time ---
        activity_time = {}
        for s in self.sessions:
            activity_time[s['activity']] = activity_time.get(s['activity'], 0) + s['elapsed_seconds']
        top_activities = sorted(activity_time.items(), key=lambda x: x[1], reverse=True)[:5]

        # --- Per-task time (from sessions with task_id) ---
        task_time = {}
        for s in self.sessions:
            tid = s.get('task_id', '')
            if tid:
                task_time[tid] = task_time.get(tid, 0) + s['elapsed_seconds']
        top_tasks = sorted(task_time.items(), key=lambda x: x[1], reverse=True)[:3]

        # Build display text
        lines = []
        lines.append(f"This week: {fmt_duration(week_secs)} ({len(week_sessions)} sessions)")
        lines.append(f"All time:  {fmt_duration(all_secs)} ({total_sessions} sessions)")
        lines.append(f"Avg today: {fmt_duration(avg_today)} | Completion: {comp_rate}%")
        lines.append(f"Streak: {streak} day{'s' if streak != 1 else ''}")

        if top_activities:
            act_parts = [f"{a[:18]}({fmt_duration(t)})" for a, t in top_activities if a != "Untitled Session"]
            if act_parts:
                lines.append(f"Top: {' | '.join(act_parts[:3])}")

        if top_tasks:
            task_parts = [f"{fmt_duration(t)}" for _, t in top_tasks]
            lines.append(f"Task time: {' | '.join(task_parts)}")

        self.metrics_content.setText("\n".join(lines))
        # Color streak
        if streak >= 7:
            streak_color = self.theme['PROGRESS_FG']
        elif streak >= 3:
            streak_color = self.theme['ACCENT_COLOR']
        else:
            streak_color = self.theme['TEXT_COLOR']

    def _render_history(self):
        clear_layout(self.history_layout)
        # Show recent sessions (last 50, newest first)
        recent = list(reversed(self.sessions[-50:]))
        if not recent:
            lbl = QLabel("No sessions yet. Start focusing!")
            lbl.setStyleSheet(f"color:{self.theme['COMPLETED_COLOR']}; font-size:13px; padding:10px;")
            lbl.setAlignment(Qt.AlignCenter)
            self.history_layout.addWidget(lbl)
            return
        for s in recent:
            row = QHBoxLayout()
            icon = "\u2705" if s['completed'] else "\u274c"
            status_color = self.theme['PROGRESS_FG'] if s['completed'] else self.theme['DELETE_COLOR']
            icon_lbl = QLabel(icon)
            icon_lbl.setStyleSheet(f"font-size:14px;")
            row.addWidget(icon_lbl)
            act_lbl = QLabel(s['activity'])
            act_lbl.setStyleSheet(f"color:{self.theme['TEXT_COLOR']}; font-size:13px; font-weight:bold;")
            act_lbl.setWordWrap(True)
            row.addWidget(act_lbl, 1)
            info_parts = []
            info_parts.append(f"{s['duration_minutes']}m planned")
            info_parts.append(f"did {fmt_duration(s['elapsed_seconds'])}")
            try:
                dt = datetime.fromisoformat(s['timestamp'])
                info_parts.append(dt.strftime('%H:%M'))
            except Exception:
                pass
            info_lbl = QLabel(" | ".join(info_parts))
            info_lbl.setStyleSheet(f"color:{self.theme['COMPLETED_COLOR']}; font-size:11px;")
            info_lbl.setAlignment(Qt.AlignRight)
            row.addWidget(info_lbl)
            self.history_layout.addLayout(row)

    def _clear_history(self):
        if self.sessions:
            reply = QMessageBox.question(self, "Clear History",
                f"Delete all {len(self.sessions)} session(s)?", QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.sessions.clear()
                self.save_data()
                self._update_stats()
                self._render_history()

    def set_tasks(self, tasks):
        """Update task combo for linking focus sessions to tasks."""
        current_data = self.task_combo.currentData()
        self.task_combo.blockSignals(True)
        self.task_combo.clear()
        self.task_combo.addItem("-- None --", None)
        active = [t for t in tasks if not t['completed']]
        for t in active:
            self.task_combo.addItem(t['text'], t['id'])
        # Restore selection by data
        if current_data:
            for i in range(self.task_combo.count()):
                if self.task_combo.itemData(i) == current_data:
                    self.task_combo.setCurrentIndex(i)
                    break
        self.task_combo.blockSignals(False)

    def save_data(self):
        safe_json_dump(TIMEBOX_FILE, self.sessions, indent=2)

    def load_data(self):
        self.sessions = safe_json_load(TIMEBOX_FILE, default=[])
        self._render_history()

    def apply_theme(self, theme):
        self.theme = theme
        # Restyle fixed widgets that don't get rebuilt
        self.setup_frame.setStyleSheet(f"background:{self.theme['CARD_BG']}; border:1px solid {self.theme['PROGRESS_BG']}; border-radius:8px; padding:12px;")
        self.timer_frame.setStyleSheet(f"background:{self.theme['FOCUS_BG']}; border:2px solid {self.theme['PROGRESS_BG']}; border-radius:12px;")
        self.activity_display.setStyleSheet(f"color:{self.theme['COMPLETED_COLOR']}; font-size:14px;")
        self.time_label.setStyleSheet(f"font-size:72px; font-weight:bold; color:{self.theme['TEXT_COLOR']}; font-family:monospace;")
        self.focus_progress.setStyleSheet(f"""
            QProgressBar {{ background:{self.theme['PROGRESS_BG']}; border:none; border-radius:4px; }}
            QProgressBar::chunk {{ background:{self.theme['FOCUS_ACTIVE']}; border-radius:4px; }}
        """)
        self.status_label.setStyleSheet(f"color:{self.theme['COMPLETED_COLOR']}; font-size:12px;")
        self.history_label.setStyleSheet(f"color:{self.theme['ACCENT_COLOR']}; font-size:14px; font-weight:bold; padding:4px;")
        self.metrics_frame.setStyleSheet(f"background:{self.theme['CARD_BG']}; border:1px solid {self.theme['PROGRESS_BG']}; border-radius:8px;")
        self.sessions_today_label.setStyleSheet(f"color:{self.theme['TEXT_COLOR']}; font-size:13px; font-weight:bold;")
        self.clear_history_btn.setStyleSheet(f"background:{self.theme['DELETE_COLOR']}; color:white; border:none; border-radius:4px; font-size:11px;")
        # Restyle control buttons based on current state
        if not self.is_running:
            self.start_btn.setStyleSheet(f"background:{self.theme['PROGRESS_FG']}; color:white; font-size:16px; font-weight:bold; border:none; border-radius:8px;")
        self.reset_btn.setStyleSheet(f"background:{self.theme['INPUT_BG']}; color:{self.theme['TEXT_COLOR']}; font-size:14px; font-weight:bold; border:none; border-radius:8px;")
        self.skip_btn.setStyleSheet(f"background:{self.theme['DELETE_COLOR']}; color:white; font-size:14px; font-weight:bold; border:none; border-radius:8px;")
        # Restyle preset buttons
        for b in self.preset_btns:
            b.setStyleSheet(f"background:{self.theme['INPUT_BG']};color:{self.theme['TEXT_COLOR']};border:none;border-radius:3px;")
        self._update_display()
        self._render_history()
        self._render_metrics()

    def start_for_task(self, task_id, task_text, estimate_minutes=0):
        """Pre-configure and start the timer for a specific task."""
        if self.is_running:
            return
        # Select the task in combo
        for i in range(self.task_combo.count()):
            if self.task_combo.itemData(i) == task_id:
                self.task_combo.setCurrentIndex(i)
                break
        self.activity_input.setText(task_text)
        # Set duration from estimate, or default to 25min
        duration = estimate_minutes * 60 if estimate_minutes > 0 else 25 * 60
        self._set_duration(duration)
        # Auto-start
        self._toggle_timer()


class GoogleCalendarManager:
    """Handles Google Calendar API auth and operations."""

    def __init__(self):
        self.service = None
        self.creds = None
        self.enabled = False
        self.auto_sync = False
        self._load_settings()
        if self.enabled:
            self._authenticate()

    def is_available(self):
        return GCAL_AVAILABLE

    def _load_settings(self):
        if os.path.exists(GCAL_SETTINGS_FILE):
            try:
                with open(GCAL_SETTINGS_FILE, 'r') as f:
                    s = json.load(f)
                self.enabled = s.get('enabled', False)
                self.auto_sync = s.get('auto_sync', False)
            except Exception:
                pass

    def save_settings(self, enabled, auto_sync):
        self.enabled = enabled
        self.auto_sync = auto_sync
        with open(GCAL_SETTINGS_FILE, 'w') as f:
            json.dump({'enabled': enabled, 'auto_sync': auto_sync}, f, indent=2)

    def _authenticate(self):
        if not GCAL_AVAILABLE:
            return False
        self.creds = None
        if os.path.exists(GCAL_TOKEN_FILE):
            try:
                self.creds = Credentials.from_authorized_user_file(GCAL_TOKEN_FILE, GCAL_SCOPES)
            except Exception:
                self.creds = None
        if self.creds and self.creds.expired and self.creds.refresh_token:
            try:
                self.creds.refresh(Request())
                with open(GCAL_TOKEN_FILE, 'w') as f:
                    f.write(self.creds.to_json())
            except Exception:
                self.creds = None
        if not self.creds and os.path.exists(GCAL_CREDS_FILE):
            try:
                flow = InstalledAppFlow.from_client_secrets_file(GCAL_CREDS_FILE, GCAL_SCOPES)
                self.creds = flow.run_local_server(port=0)
                with open(GCAL_TOKEN_FILE, 'w') as f:
                    f.write(self.creds.to_json())
            except Exception:
                return False
        if self.creds:
            try:
                self.service = gcal_build('calendar', 'v3', credentials=self.creds)
                return True
            except Exception:
                return False
        return False

    def is_authenticated(self):
        return self.service is not None

    def authenticate_interactive(self):
        """Run OAuth flow, returns (success, message)."""
        if not GCAL_AVAILABLE:
            return False, "google-api-python-client not installed.\nRun: pip install google-api-python-client google-auth-oauthlib"
        if not os.path.exists(GCAL_CREDS_FILE):
            return False, "Credentials file not found.\nPlease provide your Google OAuth2 credentials JSON file."
        # Run in thread to avoid blocking UI
        result = [False, ""]
        def auth_thread():
            result[0] = self._authenticate()
            result[1] = "Connected!" if result[0] else "Authentication failed."
        t = threading.Thread(target=auth_thread, daemon=True)
        t.start()
        t.join(timeout=120)
        return result[0], result[1]

    def push_task(self, task):
        """Push a single task as a Google Calendar event. Returns (success, event_id_or_error)."""
        if not self.service:
            return False, "Not authenticated"
        try:
            event = {
                'summary': task['text'],
                'description': task.get('description', ''),
                'start': {},
                'end': {},
            }
            due = task.get('due_date', '')
            if due:
                try:
                    dt = datetime.strptime(due, '%Y-%m-%d')
                    event['start'] = {'date': due}
                    event['end'] = {'date': (dt + timedelta(days=1)).strftime('%Y-%m-%d')}
                except ValueError:
                    pass
            else:
                today = datetime.now().strftime('%Y-%m-%d')
                event['start'] = {'date': today}
                event['end'] = {'date': today}

            if task['completed']:
                event['status'] = 'confirmed'
            else:
                event['status'] = 'tentative'

            # Add priority as color
            color_map = {'High': '11', 'Medium': '6', 'Low': '9'}  # Google Calendar color IDs
            if task['priority'] in color_map:
                event['colorId'] = color_map[task['priority']]

            result = self.service.events().insert(calendarId='primary', body=event).execute()
            return True, result.get('id', '')
        except Exception as e:
            return False, str(e)

    def update_task(self, task, gcal_event_id):
        """Update an existing Google Calendar event. Returns (success, message)."""
        if not self.service:
            return False, "Not authenticated"
        try:
            event = self.service.events().get(calendarId='primary', eventId=gcal_event_id).execute()
            event['summary'] = task['text']
            event['description'] = task.get('description', '')
            due = task.get('due_date', '')
            if due:
                try:
                    dt = datetime.strptime(due, '%Y-%m-%d')
                    event['start'] = {'date': due}
                    event['end'] = {'date': (dt + timedelta(days=1)).strftime('%Y-%m-%d')}
                except ValueError:
                    pass
            color_map = {'High': '11', 'Medium': '6', 'Low': '9'}
            if task['priority'] in color_map:
                event['colorId'] = color_map[task['priority']]
            self.service.events().update(calendarId='primary', eventId=gcal_event_id, body=event).execute()
            return True, "Updated"
        except Exception as e:
            return False, str(e)

    def delete_event(self, gcal_event_id):
        """Delete a Google Calendar event."""
        if not self.service:
            return False
        try:
            self.service.events().delete(calendarId='primary', eventId=gcal_event_id).execute()
            return True
        except Exception:
            return False

    def pull_events(self, days_ahead=30):
        """Pull upcoming events from Google Calendar. Returns list of event dicts."""
        if not self.service:
            return []
        try:
            now = datetime.now(datetime.timezone.utc).isoformat()
            end = (datetime.now(datetime.timezone.utc) + timedelta(days=days_ahead)).isoformat()
            events_result = self.service.events().list(
                calendarId='primary', timeMin=now, timeMax=end,
                maxResults=50, singleEvents=True, orderBy='startTime'
            ).execute()
            events = []
            for e in events_result.get('items', []):
                start = e.get('start', {}).get('date', '')
                summary = e.get('summary', 'Untitled Event')
                desc = e.get('description', '')
                eid = e.get('id', '')
                events.append({
                    'id': eid, 'text': summary, 'due_date': start,
                    'description': desc, 'source': 'google_calendar'
                })
            return events
        except Exception:
            return []

    def sync_all_tasks(self, tasks):
        """Push all tasks to Google Calendar. Returns (success_count, fail_count)."""
        if not self.service:
            return 0, len(tasks)
        success = 0
        fail = 0
        for t in tasks:
            gcal_id = t.get('gcal_event_id', '')
            if gcal_id:
                ok, _ = self.update_task(t, gcal_id)
            else:
                ok, eid = self.push_task(t)
                if ok:
                    t['gcal_event_id'] = eid
            if ok:
                success += 1
            else:
                fail += 1
        return success, fail


class GoogleCalendarSettingsDialog(QDialog):
    """Settings dialog for Google Calendar integration."""
    settings_changed = Signal(bool, bool)  # enabled, auto_sync

    def __init__(self, manager, theme, parent=None):
        super().__init__(parent)
        self.manager = manager
        self.theme = theme
        self.setWindowTitle("Google Calendar Settings")
        self.resize(450, 400)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Status
        self.status_lbl = QLabel()
        self._update_status()
        self.status_lbl.setWordWrap(True)
        layout.addWidget(self.status_lbl)

        # Enable checkbox
        self.enable_cb = QCheckBox("Enable Google Calendar Sync")
        self.enable_cb.setChecked(self.manager.enabled)
        layout.addWidget(self.enable_cb)

        # Auto sync
        self.auto_cb = QCheckBox("Auto-sync tasks on save")
        self.auto_cb.setChecked(self.manager.auto_sync)
        layout.addWidget(self.auto_cb)

        # Credentials file
        cred_row = QHBoxLayout()
        self.cred_label = QLabel(GCAL_CREDS_FILE if os.path.exists(GCAL_CREDS_FILE) else "No credentials file")
        cred_row.addWidget(QLabel("Credentials:"))
        cred_row.addWidget(self.cred_label, 1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_creds)
        cred_row.addWidget(browse_btn)
        layout.addLayout(cred_row)

        # Auth button
        if not GCAL_AVAILABLE:
            layout.addWidget(QLabel("Install: pip install google-api-python-client google-auth-oauthlib"))
        else:
            self.auth_btn = QPushButton("Authenticate with Google")
            self.auth_btn.clicked.connect(self._authenticate)
            layout.addWidget(self.auth_btn)

        # Sync all button
        self.sync_btn = QPushButton("Sync All Tasks Now")
        self.sync_btn.clicked.connect(self._request_sync)
        layout.addWidget(self.sync_btn)

        # Pull events button
        self.pull_btn = QPushButton("Pull Events from Google Calendar")
        self.pull_btn.clicked.connect(self._request_pull)
        layout.addWidget(self.pull_btn)

        # Help
        help_text = QLabel(
            "Setup:\n"
            "1. Go to Google Cloud Console\n"
            "2. Create OAuth 2.0 credentials\n"
            "3. Download JSON credentials file\n"
            "4. Browse and select it above\n"
            "5. Click 'Authenticate with Google'"
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet(f"color:{self.theme['COMPLETED_COLOR']};font-size:11px;padding:8px;")
        layout.addWidget(help_text)

        # Save/Close
        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save Settings")
        save_btn.clicked.connect(self._save)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self.apply_theme()

    def _update_status(self):
        if not GCAL_AVAILABLE:
            self.status_lbl.setText("Google Calendar library not installed.")
            self.status_lbl.setStyleSheet(f"color:#E64D4D;font-weight:bold;")
        elif self.manager.is_authenticated():
            self.status_lbl.setText("Connected to Google Calendar")
            self.status_lbl.setStyleSheet(f"color:#4DCC66;font-weight:bold;")
        else:
            self.status_lbl.setText("Not connected")
            self.status_lbl.setStyleSheet(f"color:{self.theme['COMPLETED_COLOR']};")

    def _browse_creds(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Google OAuth Credentials", "", "JSON Files (*.json)")
        if path:
            shutil.copy2(path, GCAL_CREDS_FILE)
            self.cred_label.setText(GCAL_CREDS_FILE)

    def _authenticate(self):
        self.auth_btn.setEnabled(False)
        self.auth_btn.setText("Authenticating...")
        ok, msg = self.manager.authenticate_interactive()
        self.auth_btn.setEnabled(True)
        self.auth_btn.setText("Authenticate with Google")
        if ok:
            QMessageBox.information(self, "Success", "Connected to Google Calendar!")
        else:
            QMessageBox.warning(self, "Error", f"Failed: {msg}")
        self._update_status()

    def _request_sync(self):
        self.done(100)  # Special code for sync request

    def _request_pull(self):
        self.done(200)  # Special code for pull request

    def _save(self):
        self.manager.save_settings(self.enable_cb.isChecked(), self.auto_cb.isChecked())
        self.settings_changed.emit(self.enable_cb.isChecked(), self.auto_cb.isChecked())
        QMessageBox.information(self, "Saved", "Settings saved!")
        self.close()

    def apply_theme(self):
        self.setStyleSheet(f"""
            QDialog {{ background:{self.theme['POPUP_BG']}; color:{self.theme['TEXT_COLOR']}; }}
            QLabel {{ color:{self.theme['TEXT_COLOR']}; }}
            QCheckBox {{ color:{self.theme['TEXT_COLOR']}; }}
            QPushButton {{ background:{self.theme['ACCENT_COLOR']}; color:white; border:none; padding:8px; border-radius:4px; font-weight:bold; }}
            QPushButton:hover {{ background:{self.theme['EDIT_COLOR']}; }}
        """)

class NotificationManager(QObject):
    """System tray notification manager with periodic task checking."""
    notification_triggered = Signal(str)  # message

    def __init__(self, parent_app, theme):
        super().__init__(parent_app)
        self.app = parent_app
        self.theme = theme
        self.enabled = True
        self.interval_minutes = 30
        self.overdue_enabled = True
        self.due_today_enabled = True
        self.due_soon_enabled = True
        self.due_soon_days = 3
        self.sound_enabled = False

        # System tray
        self.tray_icon = QSystemTrayIcon(parent_app)
        self.tray_icon.setIcon(parent_app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.tray_icon.setToolTip("Ultimate Tasks")

        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show Window")
        show_action.triggered.connect(parent_app.show)
        tray_menu.addSeparator()
        check_action = tray_menu.addAction("Check Now")
        check_action.triggered.connect(lambda: self.check_notifications(parent_app.tasks if hasattr(parent_app, 'tasks') else []))
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(parent_app.close)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)

        # Timer
        self.timer = QTimer()
        self.timer.timeout.connect(self._periodic_check)

        self._load_settings()
        # Start timer with the loaded interval (not the default)
        self.timer.start(self.interval_minutes * 60 * 1000)

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.app.show()
            self.app.raise_()

    def show_tray(self):
        if self.tray_icon.isSystemTrayAvailable():
            self.tray_icon.show()

    def _load_settings(self):
        if os.path.exists(NOTIF_SETTINGS_FILE):
            try:
                with open(NOTIF_SETTINGS_FILE, 'r') as f:
                    s = json.load(f)
                self.enabled = s.get('enabled', True)
                self.interval_minutes = s.get('interval_minutes', 30)
                self.overdue_enabled = s.get('overdue_enabled', True)
                self.due_today_enabled = s.get('due_today_enabled', True)
                self.due_soon_enabled = s.get('due_soon_enabled', True)
                self.due_soon_days = s.get('due_soon_days', 3)
                self.sound_enabled = s.get('sound_enabled', False)
            except Exception:
                pass

    def _save_settings(self):
        data = {
            'enabled': self.enabled, 'interval_minutes': self.interval_minutes,
            'overdue_enabled': self.overdue_enabled, 'due_today_enabled': self.due_today_enabled,
            'due_soon_enabled': self.due_soon_enabled, 'due_soon_days': self.due_soon_days,
            'sound_enabled': self.sound_enabled
        }
        with open(NOTIF_SETTINGS_FILE, 'w') as f:
            json.dump(data, f, indent=2)

    def _periodic_check(self):
        tasks = self.app.tasks if hasattr(self.app, 'tasks') else []
        self.check_notifications(tasks)

    def check_notifications(self, tasks):
        if not self.enabled:
            return

        now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_str = now.strftime('%Y-%m-%d')
        messages = []
        overdue = []
        due_today = []

        # Overdue
        if self.overdue_enabled:
            overdue = [t for t in tasks if not t['completed'] and t.get('due_date') and
                       t['due_date'] < today_str]
            if overdue:
                messages.append(f"OVERDUE: {len(overdue)} task(s) overdue!")

        # Due today
        if self.due_today_enabled:
            due_today = [t for t in tasks if not t['completed'] and t.get('due_date') == today_str]
            if due_today:
                messages.append(f"DUE TODAY: {len(due_today)} task(s) due today")

        # Due soon
        if self.due_soon_enabled:
            soon_date = (now + timedelta(days=self.due_soon_days)).strftime('%Y-%m-%d')
            due_soon = [t for t in tasks if not t['completed'] and t.get('due_date') and
                        today_str < t['due_date'] <= soon_date]
            if due_soon:
                messages.append(f"COMING UP: {len(due_soon)} task(s) due in next {self.due_soon_days} days")

        if messages:
            full_msg = "\n".join(messages)
            self._show_notification("Task Reminders", full_msg)
            self.notification_triggered.emit(full_msg)
            if hasattr(self.app, 'status_label') and self.app.isVisible():
                det = []
                if self.overdue_enabled and overdue:
                    det.append("Overdue: " + ", ".join(t["text"][:25] for t in overdue[:3]))
                if self.due_today_enabled and due_today:
                    det.append("Today: " + ", ".join(t["text"][:25] for t in due_today[:3]))
                if det:
                    self.app.status_label.setText(" | ".join(det))

    def _show_notification(self, title, message):
        if self.tray_icon.isSystemTrayAvailable():
            self.tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 5000)
        else:
            self.notification_triggered.emit(f"{title}: {message}")

    def update_theme(self, theme):
        self.theme = theme

    def open_settings(self):
        """Open notification settings dialog. Returns dialog."""
        dlg = NotificationSettingsDialog(self, self.theme)
        return dlg


class NotificationSettingsDialog(QDialog):
    """Settings dialog for notifications."""

    def __init__(self, notif_manager, theme, parent=None):
        super().__init__(parent)
        self.nm = notif_manager
        self.theme = theme
        self.setWindowTitle("Notification Settings")
        self.resize(380, 350)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # Master toggle
        self.enable_cb = QCheckBox("Enable Notifications")
        self.enable_cb.setChecked(self.nm.enabled)
        self.enable_cb.toggled.connect(self._on_toggle)
        layout.addWidget(self.enable_cb)

        # Interval
        int_row = QHBoxLayout()
        int_row.addWidget(QLabel("Check every (minutes):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 1440)
        self.interval_spin.setValue(self.nm.interval_minutes)
        int_row.addWidget(self.interval_spin)
        layout.addLayout(int_row)

        # Categories
        self.overdue_cb = QCheckBox("Notify for overdue tasks")
        self.overdue_cb.setChecked(self.nm.overdue_enabled)
        layout.addWidget(self.overdue_cb)

        self.today_cb = QCheckBox("Notify for tasks due today")
        self.today_cb.setChecked(self.nm.due_today_enabled)
        layout.addWidget(self.today_cb)

        self.soon_cb = QCheckBox("Notify for tasks due soon")
        self.soon_cb.setChecked(self.nm.due_soon_enabled)
        layout.addWidget(self.soon_cb)

        soon_row = QHBoxLayout()
        soon_row.addWidget(QLabel("  Days ahead:"))
        self.soon_days_spin = QSpinBox()
        self.soon_days_spin.setRange(1, 30)
        self.soon_days_spin.setValue(self.nm.due_soon_days)
        soon_row.addWidget(self.soon_days_spin)
        soon_row.addStretch()
        layout.addLayout(soon_row)

        self.sound_cb = QCheckBox("Enable notification sound")
        self.sound_cb.setChecked(self.nm.sound_enabled)
        layout.addWidget(self.sound_cb)

        layout.addStretch()

        # Test button
        test_btn = QPushButton("Test Notification")
        test_btn.clicked.connect(self._test)
        layout.addWidget(test_btn)

        # Save
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save)
        layout.addWidget(save_btn)

        self.apply_theme()

    def _on_toggle(self, checked):
        widgets = [self.interval_spin, self.overdue_cb, self.today_cb,
                   self.soon_cb, self.soon_days_spin, self.sound_cb]
        for w in widgets:
            w.setEnabled(checked)

    def _test(self):
        self.nm._show_notification("Test", "Notifications are working!")

    def _save(self):
        self.nm.enabled = self.enable_cb.isChecked()
        self.nm.interval_minutes = self.interval_spin.value()
        self.nm.overdue_enabled = self.overdue_cb.isChecked()
        self.nm.due_today_enabled = self.today_cb.isChecked()
        self.nm.due_soon_enabled = self.soon_cb.isChecked()
        self.nm.due_soon_days = self.soon_days_spin.value()
        self.nm.sound_enabled = self.sound_cb.isChecked()
        self.nm._save_settings()

        # Restart timer with new interval
        self.nm.timer.stop()
        self.nm.timer.start(self.nm.interval_minutes * 60 * 1000)

        self.accept()

    def apply_theme(self):
        self.setStyleSheet(f"""
            QDialog {{ background:{self.theme['POPUP_BG']}; color:{self.theme['TEXT_COLOR']}; }}
            QLabel {{ color:{self.theme['TEXT_COLOR']}; }}
            QCheckBox {{ color:{self.theme['TEXT_COLOR']}; }}
            QSpinBox {{ background:{self.theme['INPUT_BG']}; color:{self.theme['TEXT_COLOR']}; border:1px solid {self.theme['PROGRESS_BG']}; padding:3px; border-radius:3px; }}
            QPushButton {{ background:{self.theme['ACCENT_COLOR']}; color:white; border:none; padding:8px; border-radius:4px; font-weight:bold; }}
            QPushButton:hover {{ background:{self.theme['EDIT_COLOR']}; }}
        """)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    window = TodoApp()
    window.show()
    sys.exit(app.exec())
