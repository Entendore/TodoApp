import sys
import json
import os
from datetime import datetime, date
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTreeWidget, QTreeWidgetItem, QPushButton, QLabel, QLineEdit, 
    QTextEdit, QComboBox, QSplitter, QHeaderView, QDateEdit, QMenu
)
from PySide6.QtCore import Qt, QDate, QSettings
from PySide6.QtGui import QFont, QColor, QAction, QKeySequence

STATUSES = ["Draft", "Not Started", "In Progress", "Blocked", "Completed"]
PRIORITIES = ["Low", "Medium", "High"]
DATA_FILE = "todo_data.json"

class TaskNode(QTreeWidgetItem):
    def __init__(self, title="New Task"):
        super().__init__()
        self.title = title
        self.priority = "Medium"
        self.justification = ""
        self.status = "Draft"
        self.due_date = None  # Stored as 'YYYY-MM-DD' string or None
        self.update_display()

    def update_display(self):
        # Calculate progress if it's a parent
        display_title = self.title
        if self.childCount() > 0:
            completed_count = sum(1 for i in range(self.childCount()) if self.child(i).status == "Completed")
            display_title += f"  [{completed_count}/{self.childCount()} Completed]"

        self.setText(0, display_title)
        self.setText(1, self.priority)
        self.setText(2, self.status)
        self.setText(3, self.due_date if self.due_date else "")

        # Priority Colors
        priority_colors = {"High": QColor("red"), "Medium": QColor("orange"), "Low": QColor("green")}
        self.setForeground(1, priority_colors.get(self.priority, QColor("black")))

        # Status Colors & Fonts
        font = QFont()
        status_colors = {
            "Draft": QColor("blue"),
            "Not Started": QColor("black"),
            "In Progress": QColor("darkCyan"),
            "Blocked": QColor("darkRed"),
            "Completed": QColor("gray")
        }
        self.setForeground(2, status_colors.get(self.status, QColor("black")))
        self.setForeground(0, status_colors.get(self.status, QColor("black")))

        if self.status == "Completed":
            font.setStrikeOut(True)
        self.setFont(0, font)

        # Overdue Highlighting
        if self.due_date and self.status != "Completed":
            try:
                due = datetime.strptime(self.due_date, "%Y-%m-%d").date()
                if due < date.today():
                    self.setForeground(3, QColor("red"))
                    font.setBold(True)
                    self.setFont(3, font)
            except ValueError:
                pass

    def to_dict(self):
        return {
            "title": self.title,
            "priority": self.priority,
            "justification": self.justification,
            "status": self.status,
            "due_date": self.due_date,
            "children": [self.child(i).to_dict() for i in range(self.childCount())]
        }

    @staticmethod
    def from_dict(data):
        node = TaskNode(data.get("title", "New Task"))
        node.priority = data.get("priority", "Medium")
        node.justification = data.get("justification", "")
        node.status = data.get("status", "Draft")
        node.due_date = data.get("due_date")
        for child_data in data.get("children", []):
            node.addChild(TaskNode.from_dict(child_data))
        return node

class TodoApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Advanced Todo List Manager")
        self.resize(1000, 650)
        
        self.is_updating_ui = False
        self.settings = QSettings("MyCompany", "TodoApp")
        
        self.setup_ui()
        self.setup_shortcuts()
        self.apply_styles()
        self.load_data()
        self.restore_state()
        
        self.update_status_bar()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # --- Left Panel ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # Search Bar
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Search tasks...")
        self.search_input.textChanged.connect(self.filter_tree)
        search_layout.addWidget(self.search_input)
        left_layout.addLayout(search_layout)

        # Buttons Layout
        btn_layout = QHBoxLayout()
        self.btn_add_task = QPushButton("Add Task")
        self.btn_add_subtask = QPushButton("Add Subtask")
        self.btn_delete = QPushButton("Delete")
        self.btn_delete.setStyleSheet("background-color: #ff6666; color: white;")
        
        btn_layout.addWidget(self.btn_add_task)
        btn_layout.addWidget(self.btn_add_subtask)
        btn_layout.addWidget(self.btn_delete)
        left_layout.addLayout(btn_layout)

        # Tree Widget
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Task / Subtask", "Priority", "Status", "Due Date"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        left_layout.addWidget(self.tree)

        # --- Right Panel ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        self.detail_title = QLabel("Task Details")
        self.detail_title.setStyleSheet("font-weight: bold; font-size: 16px;")
        right_layout.addWidget(self.detail_title)

        # Title
        right_layout.addWidget(QLabel("Title:"))
        self.input_title = QLineEdit()
        right_layout.addWidget(self.input_title)

        # Priority & Status Grid
        grid_layout = QHBoxLayout()
        
        grid_layout.addWidget(QLabel("Priority:"))
        self.combo_priority = QComboBox()
        self.combo_priority.addItems(PRIORITIES)
        grid_layout.addWidget(self.combo_priority)
        
        grid_layout.addSpacing(20)
        
        grid_layout.addWidget(QLabel("Status:"))
        self.combo_status = QComboBox()
        self.combo_status.addItems(STATUSES)
        grid_layout.addWidget(self.combo_status)
        right_layout.addLayout(grid_layout)

        # Due Date
        date_layout = QHBoxLayout()
        date_layout.addWidget(QLabel("Due Date:"))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.date_edit.setSpecialValueText("No Date")
        date_layout.addWidget(self.date_edit)
        
        self.btn_clear_date = QPushButton("Clear Date")
        self.btn_clear_date.clicked.connect(self.clear_due_date)
        date_layout.addWidget(self.btn_clear_date)
        right_layout.addLayout(date_layout)

        # Justification
        right_layout.addWidget(QLabel("Justification / Notes:"))
        self.input_justification = QTextEdit()
        right_layout.addWidget(self.input_justification)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([600, 400])

        self.toggle_details_panel(False)

        # --- Connections ---
        self.btn_add_task.clicked.connect(self.add_task)
        self.btn_add_subtask.clicked.connect(self.add_subtask)
        self.btn_delete.clicked.connect(self.delete_task)
        self.tree.itemClicked.connect(self.load_task_details)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        
        self.input_title.textChanged.connect(self.update_task_from_ui)
        self.combo_priority.currentTextChanged.connect(self.update_task_from_ui)
        self.combo_status.currentTextChanged.connect(self.update_task_from_ui)
        self.date_edit.dateChanged.connect(self.update_task_from_ui)
        self.input_justification.textChanged.connect(self.update_task_from_ui)

    def setup_shortcuts(self):
        self.shortcut_del = QShortcut(QKeySequence.Delete, self.tree)
        self.shortcut_del.activated.connect(self.delete_task)
        
        self.shortcut_add = QShortcut(QKeySequence("Ctrl+N"), self)
        self.shortcut_add.activated.connect(self.add_task)
        
        self.shortcut_sub = QShortcut(QKeySequence("Ctrl+Shift+N"), self)
        self.shortcut_sub.activated.connect(self.add_subtask)

    def clear_due_date(self):
        self.date_edit.setDate(self.date_edit.minimumDate())

    def toggle_details_panel(self, enabled):
        for w in [self.input_title, self.combo_priority, self.combo_status, self.date_edit, self.input_justification, self.btn_clear_date]:
            w.setEnabled(enabled)

    def add_task(self):
        new_task = TaskNode("New Task")
        self.tree.addTopLevelItem(new_task)
        self.tree.setCurrentItem(new_task)
        self.load_task_details(new_task)
        self.update_status_bar()

    def add_subtask(self):
        parent = self.tree.currentItem()
        if not parent or not isinstance(parent, TaskNode):
            self.add_task()
            return
            
        new_subtask = TaskNode("New Subtask")
        parent.addChild(new_subtask)
        parent.setExpanded(True)
        self.tree.setCurrentItem(new_subtask)
        self.load_task_details(new_subtask)

    def delete_task(self):
        current = self.tree.currentItem()
        if current and isinstance(current, TaskNode):
            parent = current.parent()
            if parent:
                parent.removeChild(current)
            else:
                index = self.tree.indexOfTopLevelItem(current)
                self.tree.takeTopLevelItem(index)
            self.toggle_details_panel(False)
            self.update_status_bar()

    def load_task_details(self, item, column=None):
        if not isinstance(item, TaskNode): return
            
        self.is_updating_ui = True
        self.toggle_details_panel(True)
        
        self.detail_title.setText(f"Editing: {item.title}")
        self.input_title.setText(item.title)
        self.combo_priority.setCurrentText(item.priority)
        self.combo_status.setCurrentText(item.status)
        
        if item.due_date:
            self.date_edit.setDate(QDate.fromString(item.due_date, "yyyy-MM-dd"))
        else:
            self.date_edit.setDate(self.date_edit.minimumDate())
            
        self.input_justification.setText(item.justification)
        self.is_updating_ui = False

    def update_task_from_ui(self):
        if self.is_updating_ui: return
            
        current = self.tree.currentItem()
        if not isinstance(current, TaskNode): return

        current.title = self.input_title.text()
        current.priority = self.combo_priority.currentText()
        current.status = self.combo_status.currentText()
        current.justification = self.input_justification.toPlainText()
        
        # Handle "No Date" special value
        if self.date_edit.date() == self.date_edit.minimumDate():
            current.due_date = None
        else:
            current.due_date = self.date_edit.date().toString("yyyy-MM-dd")

        current.update_display()
        
        # Update parents recursively if they exist
        p = current.parent()
        while p:
            p.update_display()
            p = p.parent()
            
        self.detail_title.setText(f"Editing: {current.title}")
        self.update_status_bar()

    def filter_tree(self, text):
        text = text.lower()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            self.filter_item_recursive(item, text)

    def filter_item_recursive(self, item, text):
        if not isinstance(item, TaskNode): return False
        
        # Check if this item matches
        matches = text in item.title.lower() or text in item.justification.lower()
        
        # Check children
        child_matches = False
        for i in range(item.childCount()):
            if self.filter_item_recursive(item.child(i), text):
                child_matches = True
                
        item.setHidden(not (matches or child_matches))
        return matches or child_matches

    def show_context_menu(self, position):
        item = self.tree.itemAt(position)
        menu = QMenu(self)
        
        if item and isinstance(item, TaskNode):
            action_complete = menu.addAction("Mark as Completed")
            action_complete.triggered.connect(lambda: self.quick_change_status(item, "Completed"))
            
            action_progress = menu.addAction("Mark as In Progress")
            action_progress.triggered.connect(lambda: self.quick_change_status(item, "In Progress"))
            
            menu.addSeparator()
            action_add_sub = menu.addAction("Add Subtask")
            action_add_sub.triggered.connect(self.add_subtask)
            
            action_del = menu.addAction("Delete")
            action_del.triggered.connect(self.delete_task)
        else:
            action_add = menu.addAction("Add Task")
            action_add.triggered.connect(self.add_task)
            
        menu.exec_(self.tree.viewport().mapToGlobal(position))

    def quick_change_status(self, item, status):
        item.status = status
        item.update_display()
        if self.tree.currentItem() == item:
            self.load_task_details(item)
        self.update_status_bar()

    def update_status_bar(self):
        total = 0
        completed = 0
        active = 0
        
        def count_recursive(item):
            nonlocal total, completed, active
            if not isinstance(item, TaskNode): return
            total += 1
            if item.status == "Completed":
                completed += 1
            else:
                active += 1
            for i in range(item.childCount()):
                count_recursive(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            count_recursive(self.tree.topLevelItem(i))
            
        self.statusBar().showMessage(f"Total Tasks: {total}  |  Active: {active}  |  Completed: {completed}")

    # --- Data Persistence ---
    def load_data(self):
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                try:
                    data = json.load(f)
                    self.tree.clear()
                    for task_data in data:
                        node = TaskNode.from_dict(task_data)
                        self.tree.addTopLevelItem(node)
                except Exception as e:
                    print(f"Error loading data: {e}")
        self.update_status_bar()

    def save_data(self):
        data = []
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if isinstance(item, TaskNode):
                data.append(item.to_dict())
        
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=4)

    def save_state(self):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        splitter = self.findChild(QSplitter)
        if splitter:
            self.settings.setValue("splitterSizes", splitter.saveState())

    def restore_state(self):
        geometry = self.settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
        state = self.settings.value("windowState")
        if state:
            self.restoreState(state)
        splitter_state = self.settings.value("splitterSizes")
        if splitter_state:
            splitter = self.findChild(QSplitter)
            if splitter:
                splitter.restoreState(splitter_state)

    def closeEvent(self, event):
        self.save_data()
        self.save_state()
        event.accept()

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #f4f4f4; }
            QTreeWidget { 
                background-color: white; 
                border: 1px solid #ddd; 
                border-radius: 4px;
                font-size: 14px;
            }
            QTreeWidget::item:selected { 
                background-color: #0078d7; 
                color: white; 
            }
            QPushButton {
                background-color: #0078d7;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #005a9e; }
            QPushButton:pressed { background-color: #004578; }
            QTextEdit, QLineEdit, QComboBox, QDateEdit {
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 4px;
                background-color: white;
            }
            QStatusBar {
                background-color: #e4e4e4;
                color: #333;
                font-weight: bold;
            }
            QMenu {
                background-color: white;
                border: 1px solid #ccc;
            }
            QMenu::item:selected {
                background-color: #0078d7;
                color: white;
            }
        """)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TodoApp()
    window.show()
    sys.exit(app.exec())