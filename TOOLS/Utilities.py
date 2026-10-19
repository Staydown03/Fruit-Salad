"""Desktop utilities for videos already uploaded manually to YouTube."""
import re
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QPlainTextEdit, QCheckBox, QAbstractItemView)
from TOOLS.manual_links import local_matches, prepare_link
from TOOLS.ui_jobs import LinkJob


class MatchTable(QTableWidget):
    def mousePressEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and index.isValid() and index.column() == 0:
            # Qt's checkbox delegate consumes clicks before normal row selection.
            # Let the adjacent text cell handle native Shift/Ctrl selection, then
            # toggle the checkbox without losing that selection or its anchor.
            position = QPointF(self.visualRect(index.siblingAtColumn(1)).center())
            selection_event = QMouseEvent(event.type(), position, event.globalPosition(),
                                          event.button(), event.buttons(), event.modifiers())
            super().mousePressEvent(selection_event)
            item = self.item(index.row(), 0)
            item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                               else Qt.CheckState.Checked)
            event.accept()
            return
        super().mousePressEvent(event)


class UtilitiesPage(QWidget):
    def __init__(self, main):
        super().__init__(main)
        self.main, self.worker, self.prepared = main, None, []
        layout = QVBoxLayout(self)
        intro = QLabel('Link videos you already uploaded to YouTube. Enter your event credentials in The Blue Alliance tab first. '
                       'No YouTube login or API key is needed. Check the destination and mappings, then validate and publish.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.target = QLabel()
        layout.addWidget(self.target)
        self.table = MatchTable(0, 4)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        self.table.setHorizontalHeaderLabels(['Link', 'Match or local clip filename', 'YouTube URL or video ID', 'Result'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for column in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        controls = QHBoxLayout()
        self.load_button, self.add_button, self.remove_button = (QPushButton(t) for t in
            ('Load local matches', 'Add row', 'Remove selected rows'))
        for button in (self.load_button, self.add_button, self.remove_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        selection_controls = QHBoxLayout()
        self.select_all_button = QPushButton('Select all rows')
        self.check_selected_button = QPushButton('Check selected')
        self.uncheck_selected_button = QPushButton('Uncheck selected')
        for button in (self.select_all_button, self.check_selected_button, self.uncheck_selected_button):
            selection_controls.addWidget(button)
        layout.addLayout(selection_controls)
        selection_note = QLabel('Shift-click selects a range; Ctrl-click adds or removes rows; Ctrl+A selects all. '
                               'Use Check selected to include highlighted rows for linking. Double-click a cell to edit.')
        selection_note.setWordWrap(True)
        layout.addWidget(selection_note)
        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText('Optional batch paste: one match and YouTube URL per line\nQ1 https://youtu.be/VIDEO_ID\nP9 https://www.youtube.com/watch?v=VIDEO_ID\nUse a full local filename to distinguish replays.')
        self.paste.setMaximumHeight(85)
        layout.addWidget(self.paste)
        self.import_button = QPushButton('Add pasted mappings')
        layout.addWidget(self.import_button)
        self.remember = QCheckBox('Mark matching local clips as completed after TBA accepts the link (prevents duplicate uploads)')
        self.remember.setChecked(True)
        layout.addWidget(self.remember)
        actions = QHBoxLayout()
        self.validate_button = QPushButton('Validate checked mappings')
        self.push_button = QPushButton('Link checked videos to TBA')
        self.push_button.setEnabled(False)
        actions.addWidget(self.validate_button)
        actions.addWidget(self.push_button)
        layout.addLayout(actions)
        self.message = QLabel('Load local matches or add mappings. Publishing requires TBA event write keys.')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.load_button.clicked.connect(self.load_local)
        self.add_button.clicked.connect(lambda: self.add_row())
        self.remove_button.clicked.connect(self.remove_rows)
        self.select_all_button.clicked.connect(self.table.selectAll)
        self.check_selected_button.clicked.connect(lambda: self.check_selected(True))
        self.uncheck_selected_button.clicked.connect(lambda: self.check_selected(False))
        self.import_button.clicked.connect(self.import_rows)
        self.validate_button.clicked.connect(self.validate_rows)
        self.push_button.clicked.connect(self.push)
        self.table.itemChanged.connect(self.invalidate)
        self.remember.stateChanged.connect(self.invalidate)
        for field in (main.TBA_eventCode, main.TBA_AuthID, main.TBA_AuthSecret, main.event_code):
            field.textChanged.connect(self.invalidate)
        self.invalidate()

    def busy(self):
        return self.worker is not None and self.worker.isRunning()

    def invalidate(self, *args):
        self.prepared = []
        self.push_button.setEnabled(False)
        self.target.setText('Destination TBA event: ' + (self.main.TBA_eventCode.text().strip().lower() or '(not set)'))

    def add_row(self, match='', video='', checked=True):
        row = self.table.rowCount()
        self.table.insertRow(row)
        check = QTableWidgetItem()
        check.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        check.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        for column, item in enumerate((check, QTableWidgetItem(match), QTableWidgetItem(video), QTableWidgetItem(''))):
            if column == 3:
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, column, item)
        self.invalidate()

    def row_message(self, row, text):
        self.table.blockSignals(True)
        self.table.item(row, 3).setText(text)
        self.table.item(row, 3).setToolTip(text)
        self.table.blockSignals(False)

    def load_local(self):
        code = self.main.event_code.text().strip().upper()
        if not code:
            self.message.setText('Set the FIRST event code in Event information or load your CONFIG first.')
            return
        existing = {self.table.item(row, 1).text() for row in range(self.table.rowCount())}
        try:
            names = local_matches(code)
        except OSError:
            self.message.setText('Could not read the local output/log files. Check file permissions.')
            return
        for name in names:
            if name not in existing:
                self.add_row(name, checked=False)
        self.message.setText('Enter each video URL and check the rows to link. Full filenames distinguish separate match attempts.')

    def selected_rows(self):
        return sorted(index.row() for index in self.table.selectionModel().selectedRows())

    def remove_rows(self):
        rows = self.selected_rows()
        if not rows:
            self.message.setText('Select rows to remove. Click a row, Shift-click a range, or use Select all rows.')
            return
        for row in reversed(rows):
            self.table.removeRow(row)
        self.invalidate()
        self.message.setText(f'Removed {len(rows)} {"row" if len(rows) == 1 else "rows"} from this table. Local files and TBA links were not changed.')

    def check_selected(self, checked):
        rows = self.selected_rows()
        if not rows:
            self.message.setText('Select rows first, or use Select all rows.')
            return
        self.table.blockSignals(True)
        try:
            for row in rows:
                self.table.item(row, 0).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        finally:
            self.table.blockSignals(False)
        self.invalidate()
        self.message.setText(f'{"Checked" if checked else "Unchecked"} {len(rows)} selected {"row" if len(rows) == 1 else "rows"}. Validate checked mappings before linking.')

    def import_rows(self):
        parsed = []
        for line in self.paste.toPlainText().splitlines():
            if not line.strip():
                continue
            values = re.split(r'[\s,]+', line.strip(), maxsplit=1)
            if len(values) != 2:
                self.message.setText('Each pasted line needs a match followed by its YouTube URL or video ID.')
                return
            parsed.append(values)
        for match, video in parsed:
            self.add_row(match, video)
        self.paste.clear()

    def validate_rows(self):
        self.invalidate()
        if self.main.program.currentText() != 'FRC':
            self.message.setText('The Blue Alliance linking is available for FRC matches.')
            return
        if not re.fullmatch(r'[0-9]{4}[a-z0-9]+', self.main.TBA_eventCode.text().strip().lower()):
            self.message.setText('Set a valid TBA event key in The Blue Alliance tab.')
            return
        rows, seen, failed = [], set(), False
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() != Qt.CheckState.Checked:
                continue
            try:
                item = prepare_link(self.table.item(row, 1).text(), self.table.item(row, 2).text(),
                                    self.main.event_code.text().strip(), self.remember.isChecked())
                if item['match_key'] in seen:
                    raise ValueError('Duplicate TBA match in this batch; submit different attempts separately.')
                seen.add(item['match_key'])
                rows.append((row, item))
                self.row_message(row, 'Ready → ' + item['match_key'] + ('; local record will be updated' if item['local_names'] else '; TBA link only'))
            except (ValueError, OSError) as error:
                failed = True
                self.row_message(row, str(error) if isinstance(error, ValueError) else 'Could not read local match records.')
        self.prepared = rows if not failed else []
        self.push_button.setEnabled(bool(self.prepared))
        self.message.setText('Fix the marked rows before publishing.' if failed else
                             f'{len(rows)} {"mapping" if len(rows) == 1 else "mappings"} ready. Check the destination above, then press Link checked videos to TBA.')

    def push(self):
        if self.busy():
            return
        if any(getattr(self.main, name, None) is not None and getattr(self.main, name).is_alive()
               for name in ('thread_seek', 'thread_build', 'thread_send')):
            self.message.setText('Restart FRUIT and use Utilities before starting Make the Sauce, so active uploads cannot race manual links.')
            return
        self.validate_rows()
        if not self.prepared:
            return
        auth_id, secret = self.main.TBA_AuthID.text().strip(), self.main.TBA_AuthSecret.text().strip()
        if not auth_id or not secret:
            self.message.setText('Fill in the TBA Auth ID and Auth Secret in The Blue Alliance tab.')
            return
        self.worker = LinkJob(list(self.prepared), auth_id, secret,
                              self.main.TBA_eventCode.text().strip().lower(), self.remember.isChecked(), self)
        self.worker.row_result.connect(self.on_result)
        self.worker.finished.connect(self.on_finished)
        self.set_editable(False)
        self.message.setText('Linking checked videos to TBA…')
        self.worker.start()

    def set_editable(self, enabled):
        widgets = (self.table, self.paste, self.load_button, self.add_button, self.remove_button,
                   self.select_all_button, self.check_selected_button, self.uncheck_selected_button,
                   self.import_button, self.validate_button, self.remember, self.main.TBA_eventCode,
                   self.main.TBA_AuthID, self.main.TBA_AuthSecret, self.main.event_code, self.main.program,
                   self.main.load_config, self.main.bake_config, self.main.startThreadButton)
        if not enabled:
            self.previous_enabled = {widget: widget.isEnabled() for widget in widgets}
            for widget in widgets:
                widget.setEnabled(False)
        else:
            for widget in widgets:
                widget.setEnabled(self.previous_enabled.get(widget, True))
        self.push_button.setEnabled(False)

    def on_result(self, row, text, success):
        self.row_message(row, text)
        if success:
            self.table.blockSignals(True)
            self.table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
            self.table.blockSignals(False)

    def on_finished(self):
        self.set_editable(True)
        self.invalidate()
        self.message.setText('Finished. Confirmed rows are unchecked. TBA match pages can show cached results; reload with a fresh query string if links are not visible. Review failed rows before retrying.')
