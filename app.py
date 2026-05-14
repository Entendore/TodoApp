import json
import os
import uuid
import re
from datetime import datetime, timedelta
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.checkbox import CheckBox
from kivy.uix.spinner import Spinner
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.metrics import dp

# --- Theme Definitions ---
DARK_THEME = {
    'BG_COLOR': (0.15, 0.15, 0.15, 1), 'TEXT_COLOR': (0.9, 0.9, 0.9, 1),
    'COMPLETED_COLOR': (0.5, 0.5, 0.5, 1), 'ACCENT_COLOR': (0.3, 0.6, 1, 1),
    'DELETE_COLOR': (0.9, 0.3, 0.3, 1), 'EDIT_COLOR': (0.2, 0.7, 0.9, 1),
    'INPUT_BG': (0.25, 0.25, 0.25, 1), 'CARD_BG': (0.2, 0.2, 0.2, 1),
    'PROGRESS_BG': (0.3, 0.3, 0.3, 1), 'PROGRESS_FG': (0.2, 0.8, 0.4, 1),
    'POPUP_BG': (0.1, 0.1, 0.1, 1), 'KANBAN_COL_BG': (0.18, 0.18, 0.18, 1),
    'IS_DARK': True
}
LIGHT_THEME = {
    'BG_COLOR': (0.95, 0.95, 0.95, 1), 'TEXT_COLOR': (0.1, 0.1, 0.1, 1),
    'COMPLETED_COLOR': (0.5, 0.5, 0.5, 1), 'ACCENT_COLOR': (0.2, 0.5, 0.9, 1),
    'DELETE_COLOR': (0.9, 0.2, 0.2, 1), 'EDIT_COLOR': (0.1, 0.6, 0.8, 1),
    'INPUT_BG': (1, 1, 1, 1), 'CARD_BG': (1, 1, 1, 1),
    'PROGRESS_BG': (0.8, 0.8, 0.8, 1), 'PROGRESS_FG': (0.3, 0.8, 0.4, 1),
    'POPUP_BG': (1, 1, 1, 1), 'KANBAN_COL_BG': (0.9, 0.9, 0.9, 1),
    'IS_DARK': False
}

PRIORITY_COLORS_DARK = {'High': (0.9, 0.3, 0.3, 1), 'Medium': (0.9, 0.7, 0.2, 1), 'Low': (0.3, 0.8, 0.3, 1)}
PRIORITY_COLORS_LIGHT = {'High': (0.8, 0.1, 0.1, 1), 'Medium': (0.9, 0.6, 0.0, 1), 'Low': (0.1, 0.6, 0.1, 1)}

STAGES = ['To Do', 'In Progress', 'Review', 'Done']
REPEATS = ['None', 'Daily', 'Weekly', 'Monthly']
ARCHIVE_FILE = 'todo_archive.json'
DATA_FILE = 'todo_kanban_data.json'

Window.size = (450, 700)

class SubtaskRow(BoxLayout):
    def __init__(self, subtask_dict, update_callback, theme, **kwargs):
        super().__init__(**kwargs)
        self.subtask_dict = subtask_dict
        self.update_callback = update_callback
        self.theme = theme
        self.size_hint_y = None
        self.height = 30
        self.padding = [20, 2, 20, 2]

        cb = CheckBox(active=subtask_dict['done'], size_hint_x=0.1, color=theme['ACCENT_COLOR'])
        cb.bind(active=self.on_toggle)
        lbl = Label(text=subtask_dict['text'], halign='left', valign='middle',
                    color=theme['COMPLETED_COLOR'] if subtask_dict['done'] else theme['TEXT_COLOR'],
                    font_name='Roboto-Italic' if subtask_dict['done'] else 'Roboto', size_hint_x=0.9)
        lbl.bind(size=lbl.setter('text_size'))

        self.add_widget(cb)
        self.add_widget(lbl)

    def on_toggle(self, instance, value):
        self.subtask_dict['done'] = value
        self.update_callback()


class TaskItem(BoxLayout):
    def __init__(self, task_data, toggle_callback, delete_callback, edit_callback, archive_callback, theme, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.size_hint_y = None
        self.spacing = 2
        self.padding = [10, 8, 10, 8]
        self.task_data = task_data
        self.toggle_callback = toggle_callback
        self.delete_callback = delete_callback
        self.edit_callback = edit_callback
        self.archive_callback = archive_callback
        self.theme = theme
        self.p_colors = PRIORITY_COLORS_DARK if theme['IS_DARK'] else PRIORITY_COLORS_LIGHT
        self.is_expanded = False

        with self.canvas.before:
            Color(*self.theme['CARD_BG'])
            self.rect = Rectangle(size=self.size, pos=self.pos)
        self.bind(size=self.update_rect, pos=self.update_rect)

        # --- Row 1: Checkbox, Title, Priority, Buttons ---
        top_row = BoxLayout(spacing=10)
        self.checkbox = CheckBox(active=self.task_data['completed'], size_hint_x=0.1, color=self.theme['ACCENT_COLOR'])
        self.checkbox.bind(active=self.on_checkbox_active)
        self.label = Label(text=self.task_data['text'], halign='left', valign='middle',
                           color=self.theme['COMPLETED_COLOR'] if self.task_data['completed'] else self.theme['TEXT_COLOR'],
                           font_name='Roboto-Italic' if self.task_data['completed'] else 'Roboto', size_hint_x=0.45)
        self.label.bind(size=self.label.setter('text_size'))
        
        p_color = self.p_colors.get(self.task_data['priority'], self.theme['TEXT_COLOR'])
        priority_lbl = Label(text=f"[{self.task_data['priority']}]", size_hint_x=0.12, color=p_color, font_size='12sp', bold=True)
        
        repeat_icon = "🔄" if self.task_data.get('repeats') != 'None' else ""
        repeat_lbl = Label(text=repeat_icon, size_hint_x=0.08, font_size='14sp', color=self.theme['ACCENT_COLOR'])

        edit_btn = Button(text='✏️', size_hint_x=0.1, background_color=self.theme['EDIT_COLOR'])
        edit_btn.bind(on_press=lambda x: self.edit_callback(self.task_data))
        delete_btn = Button(text='X', size_hint_x=0.1, background_color=self.theme['DELETE_COLOR'])
        delete_btn.bind(on_press=lambda x: self.delete_callback(self.task_data))

        top_row.add_widget(self.checkbox); top_row.add_widget(self.label)
        top_row.add_widget(priority_lbl); top_row.add_widget(repeat_lbl)
        top_row.add_widget(edit_btn); top_row.add_widget(delete_btn)

        # --- Row 2: Stage, Date, Category & Subtask Mini-Progress ---
        mid_row = BoxLayout(spacing=5, padding=[20, 0, 0, 0])
        
        stage_lbl = Label(text=f"🔄 {self.task_data['stage']}", size_hint_x=0.3, halign='left', valign='middle',
                          color=self.theme['ACCENT_COLOR'] if self.task_data['stage'] != 'Done' else self.theme['PROGRESS_FG'], font_size='12sp')
        stage_lbl.bind(size=stage_lbl.setter('text_size'))

        date_color = self.theme['TEXT_COLOR']; date_text = self.task_data.get('due_date', '')
        if self.task_data['completed'] and self.task_data.get('completed_date'):
            date_text = f"Done: {self.task_data['completed_date']}"; date_color = self.theme['COMPLETED_COLOR']
        elif not self.task_data['completed'] and date_text:
            try:
                due_dt = datetime.strptime(date_text, '%Y-%m-%d'); now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                if due_dt < now: date_text = f"{date_text} (OVERDUE)"; date_color = (1, 0.3, 0.3, 1)
                elif due_dt == now: date_text = f"{date_text} (TODAY)"; date_color = (1, 0.8, 0.2, 1)
            except ValueError: pass
        
        date_lbl = Label(text=date_text, halign='left', valign='middle', color=date_color, font_size='12sp', size_hint_x=0.4)
        date_lbl.bind(size=date_lbl.setter('text_size'))
        
        # Subtask Mini Progress
        subtask_text = ""; subtask_color = self.theme['TEXT_COLOR']
        subs = self.task_data.get('subtasks', [])
        if subs:
            done_subs = sum(1 for s in subs if s['done'])
            subtask_text = f"📋 {done_subs}/{len(subs)}"
            subtask_color = self.theme['PROGRESS_FG'] if done_subs == len(subs) else self.theme['ACCENT_COLOR']
            
        subtask_lbl = Label(text=subtask_text, halign='right', valign='middle', color=subtask_color, font_size='12sp', size_hint_x=0.3)
        subtask_lbl.bind(size=subtask_lbl.setter('text_size'))

        mid_row.add_widget(stage_lbl); mid_row.add_widget(date_lbl); mid_row.add_widget(subtask_lbl)

        # --- Row 3: Context & Tags ---
        bot_row = BoxLayout(spacing=5, padding=[20, 0, 0, 0])
        ctx_text = f"📍 {self.task_data['context']}" if self.task_data.get('context') else ""
        tags_text = f"🏷️ {self.task_data['tags']}" if self.task_data.get('tags') else ""
        ctx_lbl = Label(text=ctx_text, halign='left', valign='middle', color=(0.6, 0.8, 0.6, 1), font_size='12sp', size_hint_x=0.4)
        ctx_lbl.bind(size=ctx_lbl.setter('text_size'))
        tags_lbl = Label(text=tags_text, halign='left', valign='middle', color=(0.8, 0.5, 0.8, 1), font_size='12sp', size_hint_x=0.6)
        tags_lbl.bind(size=tags_lbl.setter('text_size'))
        bot_row.add_widget(ctx_lbl); bot_row.add_widget(tags_lbl)

        self.add_widget(top_row); self.add_widget(mid_row); self.add_widget(bot_row)
        
        # Expandable Subtask Area
        self.subtask_layout = BoxLayout(orientation='vertical', size_hint_y=None, spacing=2)
        if subs:
            expand_btn = Button(text="Toggle Subtasks", size_hint_y=None, height=25, font_size='11sp', background_color=self.theme['INPUT_BG'])
            expand_btn.bind(on_press=self.toggle_expand)
            self.add_widget(expand_btn)
            self.add_widget(self.subtask_layout)
            self.subtask_layout.height = 0 # Start collapsed

        self.height = 95

    def update_rect(self, instance, value): self.rect.pos = instance.pos; self.rect.size = instance.size

    def toggle_expand(self, instance):
        self.is_expanded = not self.is_expanded
        if self.is_expanded:
            self.render_subtasks()
        else:
            self.subtask_layout.clear_widgets()
            self.subtask_layout.height = 0
            self.height = 95

    def render_subtasks(self):
        self.subtask_layout.clear_widgets()
        subs = self.task_data.get('subtasks', [])
        for s in subs:
            row = SubtaskRow(s, self.update_subtask_progress, self.theme)
            self.subtask_layout.add_widget(row)
        self.subtask_layout.height = len(subs) * 30
        self.height = 95 + (len(subs) * 30) + 25

    def update_subtask_progress(self):
        self.toggle_callback(rebuild_ui=False) # Save data
        # Quick UI refresh of the summary text without rebuilding whole list
        # To keep it simple, we just trigger a full refresh. For 100s of tasks, optimize this.
        self.toggle_callback(rebuild_ui=True)

    def on_checkbox_active(self, instance, value):
        self.task_data['completed'] = value
        if value:
            self.task_data['completed_date'] = datetime.now().strftime('%Y-%m-%d')
            self.task_data['stage'] = 'Done'
            # Recurring Task Logic
            if self.task_data.get('repeats') != 'None':
                self.handle_recurring()
        else:
            self.task_data['completed_date'] = ""
            if self.task_data['stage'] == 'Done': self.task_data['stage'] = 'To Do'
        self.toggle_callback()

    def handle_recurring(self):
        new_task = self.task_data.copy()
        new_task['id'] = uuid.uuid4().hex[:8]
        new_task['completed'] = False
        new_task['completed_date'] = ""
        new_task['stage'] = 'To Do'
        # Reset subtasks for new instance
        new_task['subtasks'] = [{'text': s['text'], 'done': False} for s in self.task_data.get('subtasks', [])]

        old_date_str = self.task_data.get('due_date')
        if old_date_str:
            try:
                old_dt = datetime.strptime(old_date_str, '%Y-%m-%d')
                if self.task_data['repeats'] == 'Daily': new_dt = old_dt + timedelta(days=1)
                elif self.task_data['repeats'] == 'Weekly': new_dt = old_dt + timedelta(weeks=1)
                elif self.task_data['repeats'] == 'Monthly': new_dt = old_dt + timedelta(days=30) # Approx
                new_task['due_date'] = new_dt.strftime('%Y-%m-%d')
            except ValueError: pass
        
        # Add new task directly to app's task list via callback
        self.archive_callback('add_recurring', new_task)


class KanbanCard(BoxLayout):
    def __init__(self, task_data, edit_callback, theme, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.size_hint_y = None; self.height = 100; self.padding = [8, 6, 8, 6]
        self.task_data = task_data; self.theme = theme
        self.p_colors = PRIORITY_COLORS_DARK if theme['IS_DARK'] else PRIORITY_COLORS_LIGHT

        with self.canvas.before:
            Color(*self.theme['CARD_BG']); self.rect = Rectangle(size=self.size, pos=self.pos)
        self.bind(size=self.update_rect, pos=self.update_rect)

        top_row = BoxLayout(spacing=5)
        p_color = self.p_colors.get(self.task_data['priority'], self.theme['TEXT_COLOR'])
        repeat_icon = "🔄 " if self.task_data.get('repeats') != 'None' else ""
        top_row.add_widget(Label(text=f"{repeat_icon}[{self.task_data['priority']}]", size_hint_x=0.25, color=p_color, font_size='12sp', bold=True))
        title_lbl = Label(text=self.task_data['text'], halign='left', valign='middle', color=self.theme['TEXT_COLOR'], size_hint_x=0.55, font_size='14sp')
        title_lbl.bind(size=title_lbl.setter('text_size'))
        edit_btn = Button(text='✏️', size_hint_x=0.2, background_color=self.theme['EDIT_COLOR'])
        edit_btn.bind(on_press=lambda x: edit_callback(self.task_data))
        top_row.add_widget(title_lbl); top_row.add_widget(edit_btn)

        mid_row = BoxLayout(spacing=5)
        tags_text = f"🏷️ {self.task_data['tags']}" if self.task_data.get('tags') else ""
        mid_row.add_widget(Label(text=tags_text, halign='left', valign='middle', color=(0.8, 0.5, 0.8, 1), font_size='11sp'))
        
        # Subtasks in Kanban
        sub_text = ""; sub_color = self.theme['TEXT_COLOR']
        subs = self.task_data.get('subtasks', [])
        if subs:
            done_subs = sum(1 for s in subs if s['done']); sub_text = f"📋 {done_subs}/{len(subs)}"
            sub_color = self.theme['PROGRESS_FG'] if done_subs == len(subs) else self.theme['ACCENT_COLOR']
        mid_row.add_widget(Label(text=sub_text, halign='right', valign='middle', color=sub_color, font_size='11sp'))

        self.add_widget(top_row); self.add_widget(mid_row)

    def update_rect(self, instance, value): self.rect.pos = instance.pos; self.rect.size = instance.size


class TaskFormPopup(Popup):
    def __init__(self, save_callback, task_to_edit=None, theme=None, **kwargs):
        super().__init__(**kwargs)
        self.title = "Edit Task" if task_to_edit else "Add New Task"
        self.size_hint = (0.95, 0.95)
        self.background_color = theme['POPUP_BG']; self.title_color = theme['TEXT_COLOR']
        self.save_callback = save_callback; self.task_to_edit = task_to_edit; self.theme = theme

        main_layout = BoxLayout(orientation='vertical', spacing=8, padding=10)

        self.name_input = TextInput(hint_text='Task Name *', multiline=False, size_hint_y=0.08, background_color=theme['INPUT_BG'], foreground_color=theme['TEXT_COLOR'])
        self.desc_input = TextInput(hint_text='Description', multiline=True, size_hint_y=0.12, background_color=theme['INPUT_BG'], foreground_color=theme['TEXT_COLOR'])
        
        row1 = BoxLayout(spacing=5, size_hint_y=0.08)
        self.priority_spinner = Spinner(text='Priority', values=('High', 'Medium', 'Low'), background_color=theme['INPUT_BG'], color=theme['TEXT_COLOR'])
        self.stage_spinner = Spinner(text='Stage', values=STAGES, background_color=theme['INPUT_BG'], color=theme['TEXT_COLOR'])
        self.repeats_spinner = Spinner(text='Repeats', values=REPEATS, background_color=theme['INPUT_BG'], color=theme['TEXT_COLOR'])
        row1.add_widget(self.priority_spinner); row1.add_widget(self.stage_spinner); row1.add_widget(self.repeats_spinner)

        row2 = BoxLayout(spacing=5, size_hint_y=0.08)
        self.category_input = TextInput(hint_text='Project (e.g., Work)', multiline=False, background_color=theme['INPUT_BG'], foreground_color=theme['TEXT_COLOR'])
        self.context_input = TextInput(hint_text='Context (@Office)', multiline=False, background_color=theme['INPUT_BG'], foreground_color=theme['TEXT_COLOR'])
        row2.add_widget(self.category_input); row2.add_widget(self.context_input)

        row3 = BoxLayout(spacing=5, size_hint_y=0.08)
        self.tags_input = TextInput(hint_text='Tags (comma sep)', multiline=False, background_color=theme['INPUT_BG'], foreground_color=theme['TEXT_COLOR'])
        self.date_input = TextInput(hint_text='Due (YYYY-MM-DD)', multiline=False, background_color=theme['INPUT_BG'], foreground_color=theme['TEXT_COLOR'])
        row3.add_widget(self.tags_input); row3.add_widget(self.date_input)

        self.subtask_input = TextInput(hint_text='Subtasks (comma separated)', multiline=False, size_hint_y=0.08, background_color=theme['INPUT_BG'], foreground_color=theme['TEXT_COLOR'])

        save_btn = Button(text='Save Task', background_color=theme['ACCENT_COLOR'], size_hint_y=0.1)
        save_btn.bind(on_press=self.save_task)

        main_layout.add_widget(self.name_input); main_layout.add_widget(self.desc_input)
        main_layout.add_widget(row1); main_layout.add_widget(row2); main_layout.add_widget(row3)
        main_layout.add_widget(self.subtask_input)
        main_layout.add_widget(Widget(size_hint_y=0.04)); main_layout.add_widget(save_btn)

        if self.task_to_edit:
            self.name_input.text = self.task_to_edit['text']
            self.desc_input.text = self.task_to_edit.get('description', '')
            self.priority_spinner.text = self.task_to_edit['priority']
            self.stage_spinner.text = self.task_to_edit['stage']
            self.repeats_spinner.text = self.task_to_edit.get('repeats', 'None')
            self.category_input.text = self.task_to_edit['category']
            self.context_input.text = self.task_to_edit.get('context', '')
            self.tags_input.text = self.task_to_edit.get('tags', '')
            self.date_input.text = self.task_to_edit.get('due_date', '')
            # Convert subtask dicts back to comma string for editing
            subs = self.task_to_edit.get('subtasks', [])
            self.subtask_input.text = ", ".join([s['text'] for s in subs])

        self.content = main_layout

    def save_task(self, instance):
        name = self.name_input.text.strip()
        if not name: return
        
        priority = self.priority_spinner.text if self.priority_spinner.text != 'Priority' else 'Medium'
        stage = self.stage_spinner.text if self.stage_spinner.text != 'Stage' else 'To Do'
        repeats = self.repeats_spinner.text if self.repeats_spinner.text != 'Repeats' else 'None'
        category = self.category_input.text.strip() or 'General'
        context = self.context_input.text.strip()
        tags = self.tags_input.text.strip()
        due_date = self.date_input.text.strip()
        description = self.desc_input.text.strip()
        
        # Parse Subtasks
        subtask_str = self.subtask_input.text.strip()
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
                self.date_input.hint_text = "Invalid! Use YYYY-MM-DD"; self.date_input.text = ""; return

        if self.task_to_edit:
            self.save_callback(self.task_to_edit['id'], name, priority, stage, category, context, tags, due_date, description, repeats, subtasks)
        else:
            self.save_callback(None, name, priority, stage, category, context, tags, due_date, description, repeats, subtasks)
        self.dismiss()


class ArchivePopup(Popup):
    def __init__(self, archive_list, restore_callback, theme, **kwargs):
        super().__init__(**kwargs)
        self.title = "🗄️ Archive"
        self.size_hint = (0.9, 0.9)
        self.background_color = theme['POPUP_BG']; self.title_color = theme['TEXT_COLOR']
        layout = BoxLayout(orientation='vertical', spacing=10, padding=10)

        if not archive_list:
            layout.add_widget(Label(text="Archive is empty.", color=theme['TEXT_COLOR']))
        else:
            scroll = ScrollView()
            list_layout = BoxLayout(orientation='vertical', size_hint_y=None, spacing=5)
            list_layout.bind(minimum_height=list_layout.setter('height'))
            for t in archive_list:
                row = BoxLayout(size_hint_y=None, height=40, spacing=5)
                row.add_widget(Label(text=t['text'], halign='left', valign='middle', color=theme['COMPLETED_COLOR'], size_hint_x=0.7))
                restore_btn = Button(text='Restore', size_hint_x=0.3, background_color=theme['ACCENT_COLOR'])
                restore_btn.bind(on_press=lambda x, task=t: restore_callback(task))
                row.add_widget(restore_btn)
                list_layout.add_widget(row)
            scroll.add_widget(list_layout)
            layout.add_widget(scroll)

        close_btn = Button(text='Close', size_hint_y=0.1, background_color=theme['DELETE_COLOR'])
        close_btn.bind(on_press=self.dismiss)
        layout.add_widget(close_btn)
        self.content = layout


class ProgressBarWidget(Widget):
    def __init__(self, progress=0.0, theme=None, **kwargs):
        super().__init__(**kwargs)
        self.size_hint_y = None; self.height = 20; self.progress = progress; self.theme = theme
        self.bind(size=self.draw_bar, pos=self.draw_bar)

    def draw_bar(self, *args):
        self.canvas.clear()
        with self.canvas:
            Color(*self.theme['PROGRESS_BG']); Rectangle(pos=self.pos, size=self.size)
            Color(*self.theme['PROGRESS_FG']); Rectangle(pos=self.pos, size=(self.width * self.progress, self.height))


class TodoApp(App):
    def build(self):
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
        self.apply_theme()

        root = BoxLayout(orientation='vertical', padding=15, spacing=6)

        # 1. Header
        header = BoxLayout(size_hint_y=0.05)
        header.add_widget(Label(text="Ultimate Tasks", font_size='22sp', color=self.theme['ACCENT_COLOR'], halign='left', valign='middle'))
        header.bind(size=header.children[0].setter('text_size'))
        
        archive_btn = Button(text='🗄️', size_hint_x=0.1, background_color=self.theme['EDIT_COLOR'])
        archive_btn.bind(on_press=self.open_archive)
        view_btn = Button(text='🗂️', size_hint_x=0.1, background_color=self.theme['EDIT_COLOR'])
        view_btn.bind(on_press=self.toggle_view)
        theme_btn = Button(text='🌙', size_hint_x=0.1, background_color=self.theme['INPUT_BG'])
        theme_btn.bind(on_press=self.toggle_theme)
        export_btn = Button(text='📋', size_hint_x=0.1, background_color=self.theme['EDIT_COLOR'])
        export_btn.bind(on_press=self.export_tasks)

        header.add_widget(archive_btn); header.add_widget(view_btn)
        header.add_widget(theme_btn); header.add_widget(export_btn)
        root.add_widget(header)

        # 2. Quick Add Bar
        quick_add = BoxLayout(size_hint_y=0.06, spacing=5)
        self.quick_input = TextInput(hint_text='⚡ Quick Add (e.g., Task tomorrow high @Office)', multiline=False, background_color=self.theme['INPUT_BG'], foreground_color=self.theme['TEXT_COLOR'])
        self.quick_input.bind(on_text_validate=self.process_quick_add)
        add_btn = Button(text='+ Form', background_color=self.theme['ACCENT_COLOR'], size_hint_x=0.3)
        add_btn.bind(on_press=self.open_add_popup)
        quick_add.add_widget(self.quick_input); quick_add.add_widget(add_btn)
        root.add_widget(quick_add)

        # 3. Search & Sort
        search_sort = BoxLayout(size_hint_y=0.06, spacing=5)
        self.search_input = TextInput(hint_text='🔍 Search...', multiline=False, size_hint_x=0.6, background_color=self.theme['INPUT_BG'], foreground_color=self.theme['TEXT_COLOR'])
        self.search_input.bind(text=self.on_search)
        self.sort_spinner = Spinner(text='Sort: Default', values=('Sort: Default', 'Sort: Date', 'Sort: Priority', 'Sort: Name'), size_hint_x=0.4, background_color=self.theme['INPUT_BG'], color=self.theme['TEXT_COLOR'])
        self.sort_spinner.bind(text=self.on_sort_change)
        search_sort.add_widget(self.search_input); search_sort.add_widget(self.sort_spinner)
        root.add_widget(search_sort)

        # 4. Progress & Filters
        self.progress_bar = ProgressBarWidget(theme=self.theme)
        self.progress_label = Label(size_hint_y=0.03, font_size='12sp', color=self.theme['COMPLETED_COLOR'], halign='left', valign='middle')
        self.progress_label.bind(size=self.progress_label.setter('text_size'))
        root.add_widget(self.progress_bar); root.add_widget(self.progress_label)

        action_bar = BoxLayout(size_hint_y=0.06, spacing=10)
        self.cat_spinner = Spinner(text='All', values=('All',), size_hint_x=0.5, background_color=self.theme['INPUT_BG'], color=self.theme['TEXT_COLOR'])
        self.cat_spinner.bind(text=self.on_cat_filter_change)
        action_bar.add_widget(self.cat_spinner); action_bar.add_widget(Widget()) # Placeholder
        
        filter_bar = BoxLayout(size_hint_y=0.05, spacing=5)
        self.btn_all = Button(text='All', on_press=lambda x: self.set_status_filter('all'))
        self.btn_active = Button(text='Active', on_press=lambda x: self.set_status_filter('active'))
        self.btn_completed = Button(text='Done', on_press=lambda x: self.set_status_filter('completed'))
        archive_done_btn = Button(text='Archive Done', on_press=self.archive_completed, background_color=self.theme['DELETE_COLOR'])
        filter_bar.add_widget(self.btn_all); filter_bar.add_widget(self.btn_active)
        filter_bar.add_widget(self.btn_completed); filter_bar.add_widget(archive_done_btn)
        root.add_widget(action_bar); root.add_widget(filter_bar)

        # 5. View Container
        self.view_container = BoxLayout(orientation='vertical')
        root.add_widget(self.view_container)

        # 6. Footer
        footer = BoxLayout(size_hint_y=0.05)
        self.status_label = Label(halign='left', valign='middle', color=self.theme['COMPLETED_COLOR'])
        self.status_label.bind(size=self.status_label.setter('text_size'))
        self.undo_btn = Button(text='Undo', size_hint_x=0.3, background_color=(0.8, 0.5, 0.1, 1), opacity=0, disabled=True)
        self.undo_btn.bind(on_press=self.undo_delete)
        footer.add_widget(self.status_label); footer.add_widget(self.undo_btn)
        root.add_widget(footer)

        self.refresh_ui()
        return root

    # --- Core Logic ---
    def apply_theme(self): Window.clearcolor = self.theme['BG_COLOR']
    def toggle_theme(self, instance):
        self.theme = LIGHT_THEME if self.theme['IS_DARK'] else DARK_THEME
        self.apply_theme(); self.refresh_ui()

    def toggle_view(self, instance):
        self.current_view = 'board' if self.current_view == 'list' else 'list'
        self.refresh_ui()

    def load_data(self):
        # Tasks
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
        
        # Archive
        if os.path.exists(ARCHIVE_FILE):
            try:
                with open(ARCHIVE_FILE, 'r') as f: self.archive = json.load(f)
            except: self.archive = []
        else: self.archive = []

    def save_tasks(self):
        with open(DATA_FILE, 'w') as f: json.dump(self.tasks, f, indent=4)

    def save_archive(self):
        with open(ARCHIVE_FILE, 'w') as f: json.dump(self.archive, f, indent=4)

    # --- Natural Language Quick Add ---
    def process_quick_add(self, instance):
        text = instance.text.strip()
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
            self.save_tasks(); self.update_category_spinner(); self.refresh_ui()
        instance.text = ""

    def open_add_popup(self, instance):
        TaskFormPopup(save_callback=self.process_task_form, theme=self.theme).open()

    def open_edit_popup(self, task_data):
        TaskFormPopup(save_callback=self.process_task_form, task_to_edit=task_data, theme=self.theme).open()

    def open_archive(self, instance):
        ArchivePopup(self.archive, self.restore_from_archive, self.theme).open()

    def export_tasks(self, instance):
        md_text = "# 📋 Task Export\n\n"
        for t in self.tasks: md_text += f"- [{'x' if t['completed'] else ' '}] **{t['text']}** | Stage: {t['stage']}\n"
        Clipboard.copy(md_text); instance.text = "✅"
        Clock.schedule_once(lambda dt: setattr(instance, 'text', '📋'), 1.5)

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
        
        self.save_tasks(); self.update_category_spinner(); self.refresh_ui()

    # Callback for TaskItem actions
    def handle_task_action(self, action_type, task_data=None):
        if action_type == 'toggle':
            self.save_tasks(); self.refresh_ui()
        elif action_type == 'delete':
            if task_data in self.tasks:
                self.tasks.remove(task_data); self.deleted_buffer = task_data
                self.save_tasks(); self.update_category_spinner(); self.refresh_ui()
                self.undo_btn.opacity = 1; self.undo_btn.disabled = False
        elif action_type == 'add_recurring':
            # Insert the newly generated recurring task
            if task_data: self.tasks.append(task_data)
            self.save_tasks()

    def archive_completed(self, instance):
        # Move done tasks to archive
        done_tasks = [t for t in self.tasks if t['completed']]
        if done_tasks:
            self.archive.extend(done_tasks)
            self.tasks = [t for t in self.tasks if not t['completed']]
            self.save_tasks(); self.save_archive(); self.update_category_spinner(); self.refresh_ui()

    def restore_from_archive(self, task_data):
        if task_data in self.archive:
            self.archive.remove(task_data)
            task_data['completed'] = False; task_data['stage'] = 'To Do'; task_data['completed_date'] = ""
            self.tasks.append(task_data)
            self.save_tasks(); self.save_archive(); self.update_category_spinner(); self.refresh_ui()
            # Close popup manually by opening a new empty one (Kivy popup limitation workaround)
            self.open_archive(None)

    def undo_delete(self, instance):
        if self.deleted_buffer:
            self.tasks.append(self.deleted_buffer); self.deleted_buffer = None
            self.save_tasks(); self.update_category_spinner(); self.refresh_ui()
            self.undo_btn.opacity = 0; self.undo_btn.disabled = True

    def set_status_filter(self, filter_type): self.current_status_filter = filter_type; self.refresh_ui()
    def on_cat_filter_change(self, spinner, text): self.current_cat_filter = text; self.refresh_ui()
    def on_search(self, instance, text): self.search_query = text.strip().lower(); self.refresh_ui()
    def on_sort_change(self, spinner, text): self.current_sort = text.split(': ')[1]; self.refresh_ui()
    
    def update_category_spinner(self):
        cats = sorted(set(t['category'] for t in self.tasks))
        self.cat_spinner.values = ['All'] + cats

    def is_overdue(self, date_str):
        try: return datetime.strptime(date_str, '%Y-%m-%d') < datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        except: return False

    # --- Rendering ---
    def refresh_ui(self):
        self.view_container.clear_widgets()
        if self.current_view == 'list': self.render_list_view()
        else: self.render_kanban_view()
        self.update_bottom_bar()

    def render_list_view(self):
        scroll_view = ScrollView(size_hint=(1, 1))
        self.list_layout = BoxLayout(orientation='vertical', size_hint_y=None, spacing=5)
        self.list_layout.bind(minimum_height=self.list_layout.setter('height'))
        scroll_view.add_widget(self.list_layout)
        
        filtered_tasks = self.get_filtered_tasks()
        if not filtered_tasks:
            self.list_layout.add_widget(Label(text="No tasks found.", color=self.theme['COMPLETED_COLOR'], size_hint_y=None, height=50))
        for task in filtered_tasks:
            self.list_layout.add_widget(TaskItem(task, lambda rd=True: self.handle_task_action('toggle', rd), 
                                                 lambda t: self.handle_task_action('delete', t), 
                                                 self.open_edit_popup, self.handle_task_action, self.theme))
        self.view_container.add_widget(scroll_view)

    def render_kanban_view(self):
        scroll_view = ScrollView(size_hint=(1, 1), scroll_type=['content'], bar_width=dp(10))
        board_layout = BoxLayout(orientation='horizontal', size_hint_x=None, spacing=10)
        board_layout.bind(minimum_width=board_layout.setter('width'))
        
        filtered_tasks = self.get_filtered_tasks()

        for stage in STAGES:
            col_layout = BoxLayout(orientation='vertical', size_hint_x=None, width=dp(280), spacing=5, padding=[5,0,5,0])
            col_lbl = Label(text=stage, size_hint_y=None, height=dp(40), font_size='16sp', bold=True, color=self.theme['ACCENT_COLOR'])
            with col_lbl.canvas.before:
                Color(*self.theme['KANBAN_COL_BG']); col_lbl.rect = Rectangle(size=col_lbl.size, pos=col_lbl.pos)
            col_lbl.bind(size=lambda i, v: setattr(i.rect, 'size', v), pos=lambda i, v: setattr(i.rect, 'pos', v))
            col_layout.add_widget(col_lbl)
            
            col_scroll = ScrollView(size_hint=(1, 1))
            col_list = BoxLayout(orientation='vertical', size_hint_y=None, spacing=5)
            col_list.bind(minimum_height=col_list.setter('height'))
            
            stage_tasks = [t for t in filtered_tasks if t['stage'] == stage]
            if not stage_tasks: col_list.add_widget(Label(text="Empty", color=self.theme['COMPLETED_COLOR'], size_hint_y=None, height=30))
            else:
                for t in stage_tasks: col_list.add_widget(KanbanCard(t, self.open_edit_popup, self.theme))
            
            col_scroll.add_widget(col_list); col_layout.add_widget(col_scroll); board_layout.add_widget(col_layout)
        self.view_container.add_widget(scroll_view)

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
        total = len(self.tasks); comp = sum(1 for t in self.tasks if t['completed']); active_count = total - comp
        self.status_label.text = f"{active_count} task{'s' if active_count != 1 else ''} left"
        self.progress_bar.progress = comp / total if total > 0 else 0
        self.progress_bar.theme = self.theme; self.progress_bar.draw_bar()
        self.progress_label.text = f"{int(self.progress_bar.progress*100)}% Completed ({comp}/{total})"
        
        self.btn_all.background_color = self.theme['ACCENT_COLOR'] if self.current_status_filter == 'all' else self.theme['INPUT_BG']
        self.btn_active.background_color = self.theme['ACCENT_COLOR'] if self.current_status_filter == 'active' else self.theme['INPUT_BG']
        self.btn_completed.background_color = self.theme['ACCENT_COLOR'] if self.current_status_filter == 'completed' else self.theme['INPUT_BG']

if __name__ == '__main__':
    TodoApp().run()