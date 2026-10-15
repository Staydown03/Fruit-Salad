import json
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QDialogButtonBox, QPushButton

"""

GUI for getting API credentials from user
    * FRC
    * Twitch
    * FTC

"""

class CredDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("API Credentials")
        self.setLayout(QVBoxLayout())
        
        self.FRC_username = QLineEdit()
        self.layout().addWidget(QLabel("FRC API Username:"))
        self.layout().addWidget(self.FRC_username)
        self.FRC_key = QLineEdit()
        self.layout().addWidget(QLabel("FRC API AuthorizationKey:"))
        self.layout().addWidget(self.FRC_key)

        self.Twitch_clientID = QLineEdit()
        self.layout().addWidget(QLabel("Twitch Client ID:"))
        self.layout().addWidget(self.Twitch_clientID)
        self.Twitch_clientSecret = QLineEdit()
        self.layout().addWidget(QLabel("Twitch Client Secret:"))
        self.layout().addWidget(self.Twitch_clientSecret)

        self.Youtube_API_Key = QLineEdit()
        self.layout().addWidget(QLabel("Youtube Data API Key:"))
        self.layout().addWidget(self.Youtube_API_Key)

        self.FTC_username = QLineEdit()
        self.layout().addWidget(QLabel("FTC API Username:"))
        self.layout().addWidget(self.FTC_username)
        self.FTC_key = QLineEdit()
        self.layout().addWidget(QLabel("FTC API AuthorizationKey:"))
        self.layout().addWidget(self.FTC_key)
        
        self.save_close_button = QPushButton("Save && Close")
        self.save_close_button.clicked.connect(self.save_and_close)
        self.layout().addWidget(self.save_close_button)
        
        self.load_credentials()

    def load_credentials(self):
        try:
            with open("CREDENTIALS", "r") as file:
                credentials = json.load(file)
                self.FRC_username.setText(credentials.get("FRC_username", ""))
                self.FRC_key.setText(credentials.get("FRC_key", ""))
                self.Twitch_clientID.setText(credentials.get("Twitch_clientID", ""))
                self.Twitch_clientSecret.setText(credentials.get("Twitch_clientSecret", ""))
                self.Youtube_API_Key.setText(credentials.get("Youtube_API_Key", ""))
                self.FTC_username.setText(credentials.get("FTC_username", ""))
                self.FTC_key.setText(credentials.get("FTC_key", ""))
        except FileNotFoundError:
            # No existing credentials file
            pass

    def save_and_close(self):
        FRC_username = self.FRC_username.text()
        FRC_key = self.FRC_key.text()
        Twitch_clientID = self.Twitch_clientID.text()
        Twitch_clientSecret = self.Twitch_clientSecret.text()
        Youtube_API_Key = self.Youtube_API_Key.text()
        FTC_username = self.FTC_username.text()
        FTC_key = self.FTC_key.text()
        
        with open("CREDENTIALS", "w") as file:
            json.dump({"FRC_username": FRC_username, "FRC_key": FRC_key, 
                       "Twitch_clientID": Twitch_clientID, "Twitch_clientSecret": Twitch_clientSecret, 
                       "Youtube_API_Key": Youtube_API_Key,
                       "FTC_username": FTC_username, "FTC_key": FTC_key}, file)

            
        self.accept()