"""Offline PyQt smoke check, run with .venv Python. No live service calls."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtTest import QTest
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget, QLineEdit, QComboBox, QPushButton
from TOOLS.Utilities import UtilitiesPage
from TOOLS import manual_links


def main():
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/arial.ttf')
    app.setFont(QFont('Arial', 10))
    original = os.getcwd()
    with tempfile.TemporaryDirectory() as folder:
        os.chdir(folder)
        try:
            Path('output').mkdir()
            Path('output/TEST_Q1_0900.mp4').write_bytes(b'synthetic')
            parent = QWidget()
            parent.program = QComboBox()
            parent.program.addItems(['FRC', 'FTC'])
            parent.TBA_eventCode = QLineEdit('2026test')
            parent.TBA_AuthID = QLineEdit('synthetic-id')
            parent.TBA_AuthSecret = QLineEdit('synthetic-secret')
            parent.event_code = QLineEdit('TEST')
            parent.startThreadButton = QPushButton()
            parent.startThreadButton.setEnabled(False)
            parent.load_config, parent.bake_config = QPushButton(), QPushButton()
            page = UtilitiesPage(parent)
            page.resize(1100, 650)
            page.show()
            page.paste.setPlainText('TEST_Q1_0900.mp4 https://youtu.be/AbC_def-123')
            page.import_rows()
            page.validate_rows()
            assert page.push_button.isEnabled()
            assert page.prepared[0][1]['match_key'] == 'qm1'
            assert page.prepared[0][1]['local_names'] == ['TEST_Q1_0900']
            with patch.object(manual_links, 'postTheBlueAlliance', return_value=SimpleNamespace(status_code=200, json=lambda: {'Success': 'Match videos successfully updated'})) as post, \
                 patch.object(manual_links.status, 'mark_manual_upload') as record:
                page.push()
                deadline = time.monotonic() + 5
                while page.busy() and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(0.01)
                app.processEvents()
                assert not page.busy(), 'Background linker did not finish'
                post.assert_called_once_with('synthetic-id', 'synthetic-secret', '2026test', {'qm1': 'AbC_def-123'})
                record.assert_called_once_with('TEST_Q1_0900', 'AbC_def-123', '2026test')
            assert page.table.item(0, 0).checkState() == Qt.CheckState.Unchecked
            assert 'Linked to TBA' in page.table.item(0, 3).text()
            assert not parent.startThreadButton.isEnabled(), 'Prior processing-button state was not restored'
            page.add_row('Q2', 'invalid')
            page.validate_rows()
            assert not page.push_button.isEnabled()
            assert '11-character' in page.table.item(1, 3).text()
            page.table.item(1, 2).setText('AbC_def-123')
            page.validate_rows()
            assert page.push_button.isEnabled()
            parent.thread_send = SimpleNamespace(is_alive=lambda: True)
            page.push()
            assert 'Restart FRUIT' in page.message.text()
            del parent.thread_send
            selection = UtilitiesPage(parent)
            selection.resize(1100, 800)
            for number in range(1, 6):
                selection.add_row(f'Q{number}', 'AbC_def-123', checked=False)
            selection.show()
            app.processEvents()
            def click_row(row, modifiers=Qt.KeyboardModifier.NoModifier, column=1):
                rect = selection.table.visualItemRect(selection.table.item(row, column))
                QTest.mouseClick(selection.table.viewport(), Qt.MouseButton.LeftButton, modifiers, rect.center())
                app.processEvents()
            click_row(0)
            click_row(3, Qt.KeyboardModifier.ShiftModifier)
            assert selection.selected_rows() == [0, 1, 2, 3], 'Shift-click did not select the full range'
            selection.check_selected_button.click()
            assert all(selection.table.item(row, 0).checkState() == Qt.CheckState.Checked for row in range(4))
            assert selection.table.item(4, 0).checkState() == Qt.CheckState.Unchecked
            click_row(4, Qt.KeyboardModifier.ControlModifier)
            assert selection.selected_rows() == [0, 1, 2, 3, 4], 'Ctrl-click did not extend the selection'
            click_row(1, Qt.KeyboardModifier.ControlModifier)
            assert selection.selected_rows() == [0, 2, 3, 4], 'Ctrl-click did not toggle a selected row'
            selection.remove_button.click()
            assert selection.table.rowCount() == 1
            assert selection.table.item(0, 1).text() == 'Q2', 'Removal deleted an unselected row'
            selection.add_row('Q6', 'AbC_def-123', checked=False)
            selection.add_row('Q7', 'AbC_def-123', checked=False)
            selection.select_all_button.click()
            assert selection.selected_rows() == [0, 1, 2]
            selection.check_selected_button.click()
            assert all(selection.table.item(row, 0).checkState() == Qt.CheckState.Checked for row in range(3))
            selection.uncheck_selected_button.click()
            assert all(selection.table.item(row, 0).checkState() == Qt.CheckState.Unchecked for row in range(3))
            selection.table.clearSelection()
            selection.table.setFocus()
            QTest.keyClick(selection.table, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
            assert selection.selected_rows() == [0, 1, 2], 'Ctrl+A did not select all table rows'
            selection.remove_button.click()
            assert selection.table.rowCount() == 0
            selection.add_row('Q8', 'AbC_def-123', checked=False)
            selection.add_row('Q9', 'AbC_def-123', checked=False)
            click_row(0, column=0)
            assert selection.selected_rows() == [0], 'Checkbox-column click did not select its row'
            assert selection.table.item(0, 0).checkState() == Qt.CheckState.Checked, 'Checkbox click did not toggle exactly once'
            selection.remove_button.click()
            assert selection.table.rowCount() == 1 and selection.table.item(0, 1).text() == 'Q9'
            selection.table.clearSelection()
            selection.remove_button.click()
            assert selection.table.rowCount() == 1 and 'Select rows to remove' in selection.message.text()
            selection.add_row('Q10', 'AbC_def-123', checked=False)
            selection.add_row('Q11', 'AbC_def-123', checked=False)
            click_row(0, column=0)
            click_row(2, Qt.KeyboardModifier.ShiftModifier, column=0)
            assert selection.selected_rows() == [0, 1, 2], 'Shift-click from checkbox did not preserve the range anchor'
            click_row(1, Qt.KeyboardModifier.ControlModifier, column=0)
            assert selection.selected_rows() == [0, 2], 'Ctrl-click from checkbox did not toggle row selection'
            selection.close()
            screenshot = Path(__file__).resolve().parents[1] / '.cache' / 'utilities-preview.png'
            screenshot.parent.mkdir(exist_ok=True)
            app.processEvents()
            page.grab().save(str(screenshot))
            page.close()
            parent.close()
            # Build the actual main window in the isolated folder. Its initial
            # credential/log files are synthetic; no event files are touched.
            import FRUIT
            window = FRUIT.MainWindow()
            assert window.tab.tabText(window.tab.count() - 1) == 'Utilities'
            assert window.tab.tabText(1) == 'Event information'
            assert window.tab.tabText(2) == 'YouTube settings'
            assert window.tab.tabText(5) == 'Video input'
            assert window.startThreadButton.text() == 'Make the Sauce'
            # Counter prefixes remain seven characters for the existing updater.
            from TOOLS.process_queue import incrementCountText
            window.status_built.setText('Built: 2')
            incrementCountText(window.status_built)
            assert window.status_built.text() == 'Built: 3'
            window.dropdownDataFrequency.setCurrentText('Live')
            window.dropdownInput.setCurrentText('Local File')
            config_path = Path('CONFIG')
            original_config = b'{"synthetic": "preserve existing config"}'
            config_path.write_bytes(original_config)
            previous_config = {'synthetic': 'previous in-memory config'}
            window.CONFIG = previous_config
            for missing in (None, '', str(Path(folder, 'missing-recording.mkv')), folder):
                window.videoFilepath = missing
                window.startThreadButton.setEnabled(True)
                with patch.object(FRUIT.QMessageBox, 'warning') as warning:
                    window.bake_config.click()
                    warning.assert_called_once()
                    assert 'Select an existing recording' in warning.call_args.args[2]
                assert not window.startThreadButton.isEnabled()
                assert config_path.read_bytes() == original_config
                assert window.CONFIG is previous_config
                assert window.tab.currentIndex() == 5
            selected = str(Path(folder, 'output', 'TEST_Q1_0900.mp4'))
            window.videoFilepath = selected
            with patch.object(FRUIT.QFileDialog, 'getOpenFileName', return_value=('', '')):
                window.getFileVideo(['mp4', 'mkv'], window.videoFile_button)
            assert window.videoFilepath == selected, 'Canceling selection cleared the previous recording'
            # Exercise the file-disappearing-between-check-and-getctime race.
            with patch.object(FRUIT.os.path, 'getctime', side_effect=FileNotFoundError()), \
                 patch.object(FRUIT.QMessageBox, 'warning') as warning:
                window.bake_config.click()
                warning.assert_called_once()
            assert not window.startThreadButton.isEnabled()
            assert config_path.read_bytes() == original_config

            with patch.object(FRUIT, 'authenticate_youtube', return_value=object()) as connect:
                window.handleYouTube()
                deadline = time.monotonic() + 5
                while window.youtube_job.isRunning() and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(0.01)
                app.processEvents()
                connect.assert_called_once_with(force_login=False)
                assert window.YouTube is not None
                assert window.youtube_switch.isEnabled()
            window.close()
        finally:
            os.chdir(original)
    print('Utilities UI passed: linking, guards, Shift/Ctrl ranges, Ctrl+A, select all, bulk check/uncheck and row removal.')


if __name__ == '__main__':
    main()
