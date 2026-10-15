from PyQt6.QtWidgets import QWidget, QFormLayout, QComboBox, QLineEdit
from PyQt6.QtGui import QRegularExpressionValidator, QIntValidator
from PyQt6.QtCore import QRegularExpression, QObject, pyqtSignal

class MatchModel(QObject):
    """
    Shared data model that holds match information.
    All pages/widgets bind to this model so they stay synchronized.
    """

    # Signals emitted whenever a field changes.
    matchTypeChanged = pyqtSignal(str)
    matchNumberChanged = pyqtSignal(str)
    timestampChanged = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        # Internal storage for the three shared values.
        self._match_type = "Q"
        self._match_number = ""
        self._timestamp = ""

    # --- Match Type ---
    def setMatchType(self, value: str):
        """
        Update the match type and notify all listeners.
        Only emits when the value actually changes.
        """
        if value != self._match_type:
            self._match_type = value
            self.matchTypeChanged.emit(value)

    def matchType(self) -> str:
        """Return the current match type."""
        return self._match_type[0] if self._match_type else ""  # Return only the first character (Q, P, F)

    # --- Match Number ---
    def setMatchNumber(self, value: str):
        if value != self._match_number:
            self._match_number = value
            self.matchNumberChanged.emit(value)

    def matchNumber(self) -> str:
        return self._match_number

    # --- Timestamp ---
    def setTimestamp(self, value: str):
        if value != self._timestamp:
            self._timestamp = value
            self.timestampChanged.emit(value)

    def timestamp(self) -> str:
        return self._timestamp


class MatchForm(QWidget):
    """
    A form containing three fields:
    - Match Type (QComboBox)
    - Match Number (QLineEdit)
    - Timestamp (QLineEdit, validated as mm:ss or mm:ss.xxx)

    Each instance binds to the same MatchModel so all pages stay in sync.
    """

    def __init__(self, model: MatchModel):
        super().__init__()
        self.model = model

        layout = QFormLayout(self)

        # --- Match Type ComboBox ---
        self.match_type = QComboBox()
        self.match_type.addItems(["Q = Quals", "P = Playoffs", "F = Finals"])
        layout.addRow("First Match Type:", self.match_type)

        self.match_type.currentTextChanged.connect(self.model.setMatchType)
        self.model.matchTypeChanged.connect(self.match_type.setCurrentText)

        if self.model.matchType():
            self.match_type.setCurrentText(self.model.matchType())

        # --- Match Number LineEdit ---
        self.match_number_ref = QLineEdit()
        layout.addRow("First Match Number:", self.match_number_ref)

        # Validator: positive integers only
        int_validator = QIntValidator(1, 9999)
        self.match_number_ref.setValidator(int_validator)

        self.match_number_ref.textChanged.connect(self.model.setMatchNumber)
        self.model.matchNumberChanged.connect(self.match_number_ref.setText)
        self.match_number_ref.setText(self.model.matchNumber())

        # --- Timestamp LineEdit with float-second validation ---
        self.timestamp_input = QLineEdit()
        layout.addRow("Enter timestamp (mm:ss):", self.timestamp_input)

        # Regex: mm:ss or mm:ss.xxx where seconds allow decimals
        timestamp_regex = QRegularExpression(r"^[0-9]{1,2}:[0-5][0-9](\.[0-9]+)?$")
        timestamp_validator = QRegularExpressionValidator(timestamp_regex)

        # Apply validator
        self.timestamp_input.setValidator(timestamp_validator)

        # User → Model
        self.timestamp_input.textChanged.connect(self.model.setTimestamp)

        # Model → Widget
        self.model.timestampChanged.connect(self.timestamp_input.setText)

        # Initial sync
        self.timestamp_input.setText(self.model.timestamp())

from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel

class MainWindow(QMainWindow):
    """
    Larger application window that embeds the MatchForm widget.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Match Entry System")

        # Create the main container widget
        container = QWidget()
        layout = QVBoxLayout(container)

        # Add your MatchForm into the main window
        self.model = MatchModel()
        self.form = MatchForm(self.model)
        layout.addWidget(self.form)

        # Example: a button that reads data from the model
        read_button = QPushButton("Print Match Data")
        read_button.clicked.connect(self.print_data)
        layout.addWidget(read_button)

        # Example: a label that shows model data
        self.output_label = QLabel("Model output will appear here.")
        layout.addWidget(self.output_label)

        # Set the central widget of the main window
        self.setCentralWidget(container)

    def print_data(self):
        """
        Demonstrates how to retrieve synchronized data from the model.
        """
        match_type = self.model.matchType()
        match_number = self.model.matchNumber()
        timestamp = self.model.timestamp()

        text = (
            f"Match Type: {match_type}\n"
            f"Match Number: {match_number}\n"
            f"Timestamp: {timestamp}"
        )

        # Show in label
        self.output_label.setText(text)

        # Also print to console
        print(text)


if __name__ == "__main__":
    app = QApplication([])
    window = MainWindow()
    window.show()
    app.exec()
