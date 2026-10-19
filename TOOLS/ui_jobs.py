"""Small background jobs shared by the desktop UI."""
from PyQt6.QtCore import QThread, pyqtSignal


class Job(QThread):
    result = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.result.emit(self.function())
        except Exception:
            # OAuth/provider errors may contain request or credential details.
            self.failed.emit('Connection failed. Check your connection, client_secret.json and Google authorization, then try again.')


class LinkJob(QThread):
    row_result = pyqtSignal(int, str, bool)

    def __init__(self, rows, auth_id, auth_secret, event_key, remember, parent=None):
        super().__init__(parent)
        self.rows, self.auth_id, self.auth_secret = rows, auth_id, auth_secret
        self.event_key, self.remember = event_key, remember

    def run(self):
        from TOOLS.manual_links import link_video
        for row, prepared in self.rows:
            try:
                result = link_video(self.auth_id, self.auth_secret, self.event_key, prepared, self.remember)
                self.row_result.emit(row, result, True)
            except (RuntimeError, ValueError) as error:
                self.row_result.emit(row, str(error), False)
            except Exception:
                self.row_result.emit(row, 'Local operation failed. Check the connection and file permissions, then retry.', False)
        self.auth_id = self.auth_secret = ''
