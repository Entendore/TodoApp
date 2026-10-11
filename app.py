import json
import os
import uuid
import sys
from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLineEdit, QPushButton, QLabel, QCheckBox, QComboBox, QDialog,
    QScrollArea, QTextEdit, QProgressBar, QSizePolicy, QFrame, QMenu,
    QMessageBox
)
from PySide6.QtCore import Qt, Signal, QTimer, QMimeData, QByteArray, QDataStream, QIODevice
from PySide6.QtGui import QColor, QClipboard, QDrag, QShortcut, QKeySequence, QAction

# --- Theme Definitions (Hex Colors for QSS) ---
DARK_THEME = {
    'BG_COLOR': '#262626', 'TEXT_COLOR': '#E6E6E6',
    'COMPLETED_COLOR': '#808080', 'ACCENT_COLOR': '#4D99FF',
    'DELETE_COLOR': '#E64D4D', 'EDIT_COLOR': '#33B3E6',
    'INPUT_BG': '#404040', 'CARD_BG': '#333333',
    'CARD_HOVER': '#3A3A3A', 'PROGRESS_BG': '#4D4D4D', 'PROGRESS_FG': '#33CC66',
    'POPUP_BG': '#1A1A1A', 'KANBAN_COL_BG': '#2E2E2E',
    'IS_DARK': True
}
LIGHT_THEME = {
    'BG_COLOR': '#F2F2F2', 'TEXT_COLOR': '#1A1A1A',
    'COMPLETED_COLOR': '#808080', 'ACCENT_COLOR': '#3380E6',
    'DELETE_COLOR': '#E63333', 'EDIT_COLOR': '#1A99CC',
    'INPUT_BG': '#FFFFFF', 'CARD_BG': '#FFFFFF',
    'CARD_HOVER': '#F9F9F9', 'PROGRESS_BG': '#CCCCCC', 'PROGRESS_FG': '#4DCC66',
    'POPUP_BG': '#FFFFFF', 'KANBAN_COL_BG': '#E6E6E6',
    'IS_DARK': False
}

PRIORITY_COLORS_DARK = {'High': '#E64D4D', 'Medium': '#E6B333', 'Low': '#4DCC66'}
PRIORITY_COLORS_LIGHT = {'High': '#CC1A1A', 'Medium': '#E69900', 'Low': '#1A991A'}

STAGES = ['To Do', 'In Progress', 'Review', 'Done']
REPEATS = ['None', 'Daily', 'Weekly', 'Monthly']
ARCHIVE_FILE = 'todo_archive.json'
DATA_FILE = 'todo_kanban_data.json'

def clear_layout(layout):
    while layout.count():
        child = layout.takeAt(0)
        if child.widget():
            child.widget().deleteLater()
        elif child.layout():
            clear_layout(child.layout())

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
        self.save_callback(task_id, name, priority, stage, category, context, tags, due_date, description, repeats, subtasks)
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
        
        layout.addWidget(self.cb)
        layout.addWidget(self.lbl)

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

        top_row.addWidget(self.checkbox)
        top_row.addWidget(self.label, 1)
        top_row.addWidget(priority_lbl)
        top_row.addWidget(repeat_lbl)
        top_row.addWidget(edit_btn)
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

        mid_row.addWidget(stage_lbl)
        mid_row.addWidget(date_lbl, 1)
        mid_row.addWidget(subtask_lbl)

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
        else:
            self.task_data['completed_date'] = ""
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

    def update_subtask_progress(self):
        self.toggle_signal.emit()

    def on_checkbox_active(self, state):
        self.task_data['completed'] = bool(state)
        if self.task_data['completed']:
            self.task_data['completed_date'] = datetime.now().strftime('%Y-%m-%d')
            self.task_data['stage'] = 'Done'
            if self.task_data.get('repeats') != 'None':
                self.handle_recurring()
        else:
            self.task_data['completed_date'] = ""
            if self.task_data['stage'] == 'Done': self.task_data['stage'] = 'To Do'
        
        self.update_title_style()
        self.toggle_signal.emit()

    def handle_recurring(self):
        new_task = self.task_data.copy()
        new_task['id'] = uuid.uuid4().hex[:8]
        new_task['completed'] = False
        new_task['completed_date'] = ""
        new_task['stage'] = 'To Do'
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


class TodoApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ultimate Tasks")
        self.resize(450, 700)
        
        self.tasks = []
        self.archive = []
        self.current_view = 'list'
        self.current_status_filter = 'all'
        self.current_cat_filter = 'All'
        self.current_sort = 'Default'
        self.search_query = ''
        self.deleted_buffer = None
        self.theme = DARK_THEME
        
        self.load_data()
        self.init_ui()
        self.apply_theme()
        self.refresh_ui()
        self.check_due_today()

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
        self.quick_input.setPlaceholderText('⚡ Quick Add (e.g., Task tomorrow high @Office)')
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
        archive_done_btn = QPushButton('Archive Done')
        
        self.btn_all.clicked.connect(lambda: self.set_status_filter('all'))
        self.btn_active.clicked.connect(lambda: self.set_status_filter('active'))
        self.btn_completed.clicked.connect(lambda: self.set_status_filter('completed'))
        archive_done_btn.clicked.connect(self.archive_completed)

        for btn in [self.btn_all, self.btn_active, self.btn_completed, archive_done_btn]:
            filter_bar.addWidget(btn)
        self.root_layout.addLayout(filter_bar)

        # 5. View Container
        self.view_scroll = QScrollArea()
        self.view_scroll.setWidgetResizable(True)
        self.view_container_widget = QWidget()
        self.view_container_layout = QVBoxLayout(self.view_container_widget)
        self.view_container_layout.setAlignment(Qt.AlignTop)
        self.view_scroll.setWidget(self.view_container_widget)
        self.root_layout.addWidget(self.view_scroll, 1)

        # 6. Footer
        footer = QHBoxLayout()
        self.status_label = QLabel()
        self.undo_btn = QPushButton('Undo')
        self.undo_btn.setFixedWidth(80)
        self.undo_btn.hide()
        self.undo_btn.clicked.connect(self.undo_delete)
        footer.addWidget(self.status_label, 1)
        footer.addWidget(self.undo_btn)
        self.root_layout.addLayout(footer)

        # Shortcuts
        QShortcut(QKeySequence("Ctrl+N"), self, self.quick_input.setFocus)
        QShortcut(QKeySequence("Ctrl+F"), self, self.search_input.setFocus)

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

    def check_due_today(self):
        today_str = datetime.now().strftime('%Y-%m-%d')
        due_today = [t for t in self.tasks if t.get('due_date') == today_str and not t['completed']]
        if due_today:
            tasks_txt = "\n".join([f"• {t['text']}" for t in due_today])
            QMessageBox.information(self, "Tasks Due Today", f"You have {len(due_today)} task(s) due today:\n\n{tasks_txt}")

    def toggle_theme(self):
        self.theme = LIGHT_THEME if self.theme['IS_DARK'] else DARK_THEME
        self.apply_theme()
        self.refresh_ui()

    def toggle_view(self):
        self.current_view = 'board' if self.current_view == 'list' else 'list'
        self.refresh_ui()

    def load_data(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r') as f:
                    self.tasks = json.load(f)
                    for t in self.tasks:
                        if 'id' not in t: t['id'] = uuid.uuid4().hex[:8]
                        if 'stage' not in t: t['stage'] = 'Done' if t.get('completed') else 'To Do'
                        if 'repeats' not in t: t['repeats'] = 'None'
                        if 'subtasks' not in t: t['subtasks'] = []
            except: self.tasks = []
        else: self.tasks = []
        
        if os.path.exists(ARCHIVE_FILE):
            try:
                with open(ARCHIVE_FILE, 'r') as f: self.archive = json.load(f)
            except: self.archive = []
        else: self.archive = []

    def save_tasks(self):
        with open(DATA_FILE, 'w') as f: json.dump(self.tasks, f, indent=4)

    def save_archive(self):
        with open(ARCHIVE_FILE, 'w') as f: json.dump(self.archive, f, indent=4)

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
            else: name_words.append(word)
        
        name = ' '.join(name_words)
        if name:
            new_task = {
                'id': uuid.uuid4().hex[:8], 'text': name, 'completed': False, 'priority': priority,
                'stage': 'To Do', 'category': category, 'context': context, 'tags': '',
                'due_date': due_date, 'description': '', 'completed_date': '', 'repeats': 'None', 'subtasks': []
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
        for t in self.tasks: md_text += f"- [{'x' if t['completed'] else ' '}] **{t['text']}** | Stage: {t['stage']}\n"
        QApplication.clipboard().setText(md_text)
        self.export_btn.setText("✅")
        QTimer.singleShot(1500, lambda: self.export_btn.setText("📋"))

    def process_task_form(self, task_id, name, priority, stage, category, context, tags, due_date, description, repeats, subtasks):
        completed = True if stage == 'Done' else False
        completed_date = datetime.now().strftime('%Y-%m-%d') if completed else ""
        
        if task_id:
            for t in self.tasks:
                if t['id'] == task_id:
                    t.update({'text': name, 'priority': priority, 'stage': stage, 'category': category,
                              'context': context, 'tags': tags, 'due_date': due_date, 'description': description,
                              'completed': completed, 'completed_date': completed_date, 'repeats': repeats, 'subtasks': subtasks})
                    break
        else:
            self.tasks.append({'id': uuid.uuid4().hex[:8], 'text': name, 'completed': completed,
                               'priority': priority, 'stage': stage, 'category': category, 'context': context,
                               'tags': tags, 'due_date': due_date, 'description': description, 'completed_date': completed_date,
                               'repeats': repeats, 'subtasks': subtasks})
        
        self.save_tasks()
        self.update_category_spinner()
        self.refresh_ui()

    def handle_toggle(self):
        self.save_tasks()
        self.refresh_ui()

    def handle_delete(self, task_data):
        if task_data in self.tasks:
            self.tasks.remove(task_data)
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

    def handle_move_task(self, task_data, new_stage):
        for t in self.tasks:
            if t['id'] == task_data['id']:
                t['stage'] = new_stage
                t['completed'] = (new_stage == 'Done')
                t['completed_date'] = datetime.now().strftime('%Y-%m-%d') if t['completed'] else ""
                break
        self.save_tasks()
        self.refresh_ui()

    def handle_kanban_drop(self, task_id, new_stage):
        for t in self.tasks:
            if t['id'] == task_id:
                t['stage'] = new_stage
                t['completed'] = (new_stage == 'Done')
                t['completed_date'] = datetime.now().strftime('%Y-%m-%d') if t['completed'] else ""
                break
        self.save_tasks()
        self.refresh_ui()

    def archive_completed(self):
        done_tasks = [t for t in self.tasks if t['completed']]
        if done_tasks:
            self.archive.extend(done_tasks)
            self.tasks = [t for t in self.tasks if not t['completed']]
            self.save_tasks()
            self.save_archive()
            self.update_category_spinner()
            self.refresh_ui()

    def restore_from_archive(self, task_data):
        if task_data in self.archive:
            self.archive.remove(task_data)
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
        except: return False

    def refresh_ui(self):
        clear_layout(self.view_container_layout)
        if self.current_view == 'list':
            self.view_container_layout.setAlignment(Qt.AlignTop)
            self.render_list_view()
        else:
            self.view_container_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self.render_kanban_view()
        self.update_bottom_bar()

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

        archive_done_btn = self.sender() if self.sender() and isinstance(self.sender(), QPushButton) else None
        # Keep archive button styled
        for i in range(self.root_layout.count()): 
            item = self.root_layout.itemAt(i)
            if item.layout():
                for j in range(item.layout().count()):
                    widget = item.layout().itemAt(j).widget()
                    if isinstance(widget, QPushButton) and widget.text() == 'Archive Done':
                        widget.setStyleSheet(f"background-color: {self.theme['DELETE_COLOR']}; color: white; border: none; border-radius: 3px; font-weight: bold;")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = TodoApp()
    window.show()
    sys.exit(app.exec())