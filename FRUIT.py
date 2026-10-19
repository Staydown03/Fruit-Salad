# imports for GUI
from PyQt6.QtWidgets import (QApplication, QWidget,  QFormLayout, QGridLayout, QTabWidget, QPushButton, QLineEdit, QPlainTextEdit, QLabel, QFileDialog, QComboBox, QCheckBox, QHBoxLayout, QStackedWidget, QVBoxLayout, QCompleter, QMessageBox)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtGui import QPixmap, QColor, QIcon, QDesktopServices
from PyQt6.QtCore import QSize, QUrl, QTimer
from PyQt6.QtSvgWidgets import QSvgWidget

import random       # random thumbnail generation
import datetime     # str conversion and timeDelta
import pytz         # timezone handling
import os           # file IO
import json         # CONFIG handling
import sys          # packaged FRUIT.exe support
import shutil       # finding ffmpeg
import subprocess   # installing ffmpeg if missing

# as FRUIT.exe, work from the exe's folder (FRUIT uses relative paths like log/ and output/)
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

# a fresh install has no CREDENTIALS yet and TOOLS/FMS.py reads it on import; fill it in with the credentials button
if not os.path.exists('CREDENTIALS'):
    with open('CREDENTIALS', 'w') as file:
        json.dump({"FRC_username": "", "FRC_key": "", "Twitch_clientID": "", "Twitch_clientSecret": "",
                   "Youtube_API_Key": "", "FTC_username": "", "FTC_key": ""}, file)

# my functions, see python scripts in TOOLS
from TOOLS.FMS import getMatchesFromFMS
from TOOLS.FMS import rewrapMatches
from TOOLS.FMS import getEventInfoFromFMS
from TOOLS.timezones import convert_windows_to_iana
from TOOLS.YouTube import authenticate_youtube
from TOOLS.YouTube import downloadYouTubeClip
from TOOLS.thumbnails import generateThumbnail
from TOOLS.TBA import postTheBlueAlliance
from TOOLS.Twitch import covertID2Username
from TOOLS.YoutubeLivestream import getChannelIDFromHandle

# my pop-ups and other custom widgets
from TOOLS.QT_MatchForm import MatchModel
from TOOLS.QT_MatchForm import MatchForm
from TOOLS.CredentialsPopUp import CredDialog
from TOOLS.Utilities import UtilitiesPage
from TOOLS.ui_jobs import Job

# processes to run on queued threads
import threading
from TOOLS.process_queue import process_queue_seek
from TOOLS.process_queue import process_queue_build_live
from TOOLS.process_queue import process_queue_build_live_local
from TOOLS.process_queue import process_queue_build_static
from TOOLS.process_queue import process_queue_send
from TOOLS.ffmpegrecord import start_recording
from TOOLS.ffmpegrecord import stop_recording
from TOOLS import status
from TOOLS import review
import dashboard

# create directories/files if missing
os.makedirs('log/', exist_ok=True)
open('log/seek.txt', 'a+').close()
open('log/send.txt', 'a+').close()
os.makedirs('input/temp', exist_ok=True)
os.makedirs('output/thumbnails', exist_ok=True)

# translator for symbols
translateSymbol = {'M': 'Playoffs', 'P': 'Playoffs', 'Q': 'Quals', 'F': 'Finals'}

class MainWindow(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #prepare optional arguments
        self.logoSponsorFilepath = None
        self.videoFilepath = None
        self.twitchUserID = None
        self.youtubeUserID = None
        self.YouTube = None
        self.youtube_job = None
        self.matchModel = MatchModel()
        self.stop_event = threading.Event()

        '''
        set window title, icon, size and layout
        '''
        self.setWindowTitle('FRUIT by Bryce Castle')
        self.setWindowIcon(QIcon('./images/icon_FRUIT.ico'))
        self.setGeometry(200, 200, 800, 400)
        main_layout = QGridLayout(self)
        self.setLayout(main_layout)
        self.tab = QTabWidget(self)

        '''
        WELCOME PAGE
         - information on how to use tool
         - mostly text
        '''
        bodyText = ("<ol style='font-size: 16px !important;'>"
                    "<li>Enter the season and event code in <b>Event information</b>, then load the event data from FIRST.</li>"
                    "<li>Connect your channel in <b>YouTube settings</b> and enter the upload details.</li>"
                    "<li>Choose a sponsor logo or event details in <b>Thumbnail settings</b>, then generate a test thumbnail.</li>"
                    "<li>Review <b>Match timing</b>. All values are in seconds.</li>"
                    "<li>Select the recording source in <b>Video input</b>.</li>"
                    "<li>Enter optional event write credentials in <b>The Blue Alliance</b> to link uploaded videos.</li>"
                    "<li>Use <b>Bake CONFIG</b> to save the configuration, then <b>Make the Sauce</b> to start processing.</li>"
                    "<li>Use <b>Utilities</b> to link videos you have already uploaded manually.</li></ol>")

        page_welcome = QWidget(self)
        layout = QFormLayout()
        page_welcome.setLayout(layout)
        layout.addRow(QLabel("<h1>FIRST Robotics Uploader from an Indiana Teammate</h1>\n<i>Complete the required tabs before starting. Yellow tabs are optional.</i>"))
        layout.addRow(QLabel(bodyText))
        # set/check credentials via dialog pop-up window
        self.credentialsButton = QPushButton("API credentials", self)
        self.credentialsButton.clicked.connect(lambda: CredDialog(self).exec())
        layout.addRow(self.credentialsButton)

        '''
        EVENT PAGE
         - Program (FRC/FTC)
         - Season Year
         - Event Code
         - Event Name & Timezone
         - Pull from FMS
        '''
        page_event = QWidget(self)
        layout = QFormLayout()
        page_event.setLayout(layout)
        # select program (FRC/FTC)
        self.program = QComboBox(); self.program.addItems(["FRC", "FTC"])
        layout.addRow(QLabel("Program:"), self.program)
        # Event (Season) Year
        self.season_year = QComboBox(); self.season_year.addItems(["2026", "2025", "2024"])
        layout.addRow(QLabel('Season year:'), self.season_year)
        # Event Code
        self.event_code = QLineEdit(self);
        layout.addRow(QLabel('Event code:'), self.event_code)
        # FMS pull button
        self.textFMS = QLabel('<font color="red">Event data not loaded</font>')
        self.button_FMS = QPushButton('Load event data')
        self.button_FMS.clicked.connect(lambda: self.handleFMS(self.season_year.currentText(), self.event_code.text().upper()))
        layout.addRow(self.button_FMS, self.textFMS)
        # Event Name
        self.event_name = QLineEdit(self);
        layout.addRow(QLabel('Event name:'), self.event_name)
        # Event Timezone
        self.event_timezone = QComboBox(); self.event_timezone.setEditable(True)
        completerTimezone = QCompleter(pytz.all_timezones); self.event_timezone.setCompleter(completerTimezone)
        layout.addRow(QLabel('Event time zone:'), self.event_timezone)
        
        '''
        YOUTUBE PAGE
         - YouTube Authentication
         - YouTube video description, tags, playlist
        '''
        page_YouTube = QWidget(self)
        layout = QFormLayout()
        page_YouTube.setLayout(layout)
        layout.addRow(QLabel('<b>Connect the YouTube channel you want to upload to and grant the requested video permissions.</b>'))
        # Authentication
        self.textYouTube = QLabel('<font color="red">YouTube not connected</font>')
        self.button_FMS = QPushButton('Connect to YouTube')
        self.button_FMS.clicked.connect(self.handleYouTube)
        layout.addRow(self.button_FMS, self.textYouTube)
        self.youtube_switch = QPushButton('Use another Google account')
        self.youtube_switch.clicked.connect(lambda: self.handleYouTube(force_login=True))
        layout.addRow(self.youtube_switch)
        saved_login_note = QLabel('Sign-in is saved locally on this computer and refreshed when possible. '
                                 'Google may still require occasional sign-in. An API key cannot authorize uploads.')
        saved_login_note.setWordWrap(True)
        layout.addRow(saved_login_note)
        # Playlist
        self.video_playlist = QLineEdit("https://www.youtube.com/playlist?list=")
        layout.addRow('Playlist URL (optional):', self.video_playlist)
        # Description
        self.video_description = QPlainTextEdit("Footage of this event is courtesy of FIRST Indiana Robotics.\n\nFollow us:\nhttps://twitch.tv/firstinrobotics\nhttps://www.facebook.com/FIRSTINRobotics/\nhttps://www.instagram.com/firstinrobotics/\nhttps://www.linkedin.com/company/first-in-robotics/\n\nEvent pictures: https://www.flickr.com/photos/indianafirst/albums/\n\nFor more information and future event schedules, visit our website: https://www.firstindianarobotics.org")
        layout.addRow('Description:', self.video_description)
        # Tags
        self.video_tags = QLineEdit('FIRST Indiana Robotics, FIN')
        layout.addRow(QLabel('Tags (comma-separated):'), self.video_tags)
        layout.addRow(QLabel('<i>FRUIT automatically adds the year, event code, and program (FRC or FTC).</i>'))
        
        '''
        THUMBNAIL PAGE
         - Sponsor Image
         - Verbose event details
         - Random thumbnail generator
        '''
        page_thumbnail = QWidget(self)
        layout = QFormLayout()
        page_thumbnail.setLayout(layout)
        layout.addRow(QLabel('<b>Choose a sponsor logo or enter event details for the YouTube thumbnail.</b>'))
        # Sponsor Image
        self.img_EventSponsor = QPushButton('Select file')
        self.img_EventSponsor.clicked.connect(lambda: self.getFileSponsorImage(self.img_EventSponsor))
        layout.addRow('Sponsor logo:', self.img_EventSponsor)
        # Verbose event details
        layout.addRow(QLabel('⸻ or ⸻'))
        self.eventBuilding = QLineEdit(self);  layout.addRow('Building:', self.eventBuilding)
        self.eventCity = QLineEdit(self);  layout.addRow('City:', self.eventCity)
        self.eventDates = QLineEdit(self);  layout.addRow('Dates:', self.eventDates)
        # Force text details over sponsor logo
        self.thumbnail_force = QCheckBox('Use event details instead of the sponsor logo')
        layout.addRow(self.thumbnail_force)
        # Test thumbnail using random generator
        self.image_thumbnail = QLabel('<font color="red">Test thumbnail not generated</font>')
        self.button_thumbnail = QPushButton('Generate test thumbnail')
        self.button_thumbnail.clicked.connect(lambda: self.handleThumbnail([self.eventBuilding.text(), self.eventCity.text(), self.eventDates.text()], self.image_thumbnail, self.thumbnail_force.isChecked()))
        layout.addRow(self.button_thumbnail, self.image_thumbnail)

        '''
        TIMINGS PAGE
         - seconds before match starts (to hear MC countdown)
         - match duration (auto + buzzer + teleop)
         - seconds to show after end of game
         - seconds to wait after post (reval animation)
         - seconds to show score
        '''
        page_timings = QWidget(self)
        layout = QFormLayout()
        page_timings.setLayout(layout)
        layout.addRow(QLabel('<b>Choose the match and score segments to include in each video.</b><br><i>Enter times in seconds. Decimal values are supported.</i>'))
        #2024 FRC values: [3, 155, 5, -7.25, 16.67]
        #2025 FRC values: [6, 155, 8, -8.06, 33]
        self.season_secondsBefore = QLineEdit(str(3.94)); layout.addRow('Before match start:', self.season_secondsBefore)
        self.season_matchDuration = QLineEdit(str(20+5+140)); layout.addRow('Match duration:', self.season_matchDuration)
        self.season_secondsAfterEnd = QLineEdit(str(3+2)); layout.addRow('After match end:', self.season_secondsAfterEnd)
        self.season_secondsBeforePost = QLineEdit(str(-5.8)); layout.addRow('Before score posting:', self.season_secondsBeforePost)
        self.season_secondsAfterPost = QLineEdit(str(20+5.8)); layout.addRow('After score posting:', self.season_secondsAfterPost)
        layout.addRow(QLabel('<i>The final video combines the match segment and the score segment.</i>'))
        svg_widget = QSvgWidget('./images/matchTrimDiagram.svg')
        svg_widget.setFixedSize(QSize(600, 150))
        layout.addRow(svg_widget)

        '''
        VIDEO INPUT
         - select video input (live/static)
         - provide reference match (# and time)
         - watch 4 seconds of clip
        '''
        page_video = QWidget(self)
        layout = QFormLayout()
        page_video.setLayout(layout)

        # Dropdown to switch views
        self.dropdownDataFrequency = QComboBox()
        self.dropdownInput = QComboBox()
        self.dropdownBuildMethod = QComboBox()
        self.stacked_widget = QStackedWidget()
        self.dropdownDataFrequency.addItems(["Live", "Static"])
        page_map = {
            ("Live", "Twitch"): 1,
            ("Live", "YouTube (experimental)"): 3,
            ("Live", "Local File"): 5,
            ("Static", "Twitch"): 1,
            ("Static", "YouTube (experimental)"): 4,
            ("Static", "Local File"): 2}
        frequencySourceOptions = {freq: [k2 for k1, k2 in page_map if k1 == freq] for freq in {freq for freq, _ in page_map}}
        def update_page():
            page = page_map.get((self.dropdownDataFrequency.currentText(), self.dropdownInput.currentText()))
            self.stacked_widget.setCurrentIndex(page-1) if page else None
        def update_dropdown():
            self.dropdownInput.clear()
            self.dropdownInput.addItems(frequencySourceOptions.get(self.dropdownDataFrequency.currentText(), []))
            update_page()
        update_dropdown()
        self.dropdownDataFrequency.currentTextChanged.connect(update_dropdown)
        self.dropdownInput.currentTextChanged.connect(update_page)
        self.dropdownBuildMethod.addItems(["ffmpeg", "moviepy"])
        self.adaptiveSyncCheckbox = QCheckBox('Adaptive audio timestamp sync')
        self.adaptiveSyncCheckbox.setChecked(True)
        layout.addRow('Recording mode:', self.dropdownDataFrequency)
        layout.addRow('Video source:', self.dropdownInput)
        layout.addRow('Build method:', self.dropdownBuildMethod)
        layout.addRow(self.adaptiveSyncCheckbox)
        layout.addRow(self.stacked_widget)

        # Video Input 1: Twitch Livestream
        video_input_Twitch = QFormLayout()
        self.twitchUser = QLineEdit('firstinrobotics'); video_input_Twitch.addRow('Twitch username:', self.twitchUser)
        self.twitch_button = QPushButton("Test Twitch connection")
        self.twitch_button.setStyleSheet('color: red')
        self.twitch_button.clicked.connect(self.test_twitch)
        video_input_Twitch.addRow(self.twitch_button)
        self.streamDelay = QLineEdit("4")
        video_input_Twitch.addRow("Stream delay (seconds):", self.streamDelay)

        Twitch_widget = QWidget()
        Twitch_widget.setLayout(video_input_Twitch)
        self.stacked_widget.addWidget(Twitch_widget)

        # Video Input 2: Static Local File
        video_input_File = QFormLayout()
        self.videoFile_button = QPushButton("Select file")
        self.videoFile_button.clicked.connect(lambda: self.getFileVideo(['mp4', 'mkv'], self.videoFile_button))
        video_input_File.addRow('Video file:', self.videoFile_button)
        # reference match details
        self.matchFormLocal = MatchForm(self.matchModel)
        video_input_File.addRow(self.matchFormLocal)
        # Create a video widget and add it to the layout
        self.video_widget = QVideoWidget()
        self.video_widget.setMinimumSize(480, 270)
        self.play_button = QPushButton("Preview 4 seconds")
        self.play_button.setStyleSheet('color: red')
        self.play_button.clicked.connect(lambda: self.play_video(self.media_player, self.videoFilepath, self.matchModel.timestamp()))
        video_input_File.addRow(self.play_button, self.video_widget)
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)
        file_widget = QWidget()
        file_widget.setLayout(video_input_File)
        self.stacked_widget.addWidget(file_widget)

        # Video Input 3: YouTube Livestream
        video_input_YouTube_Live = QFormLayout()
        self.youtubeUser = QLineEdit("FIRSTINRobotics"); video_input_YouTube_Live.addRow("YouTube username:", self.youtubeUser)
        # gets channel ID from username
        self.youtube_button = QPushButton("Test YouTube livestream connection")
        video_input_YouTube_Live.addRow(self.youtube_button)
        self.youtube_button.setStyleSheet("color: red")
        self.youtube_button.clicked.connect(self.get_yt_channel_ID)
        self.record_button = QPushButton(
            "Start recording YouTube livestream"
        )
        video_input_YouTube_Live.addRow(self.record_button)
        self.record_button.setStyleSheet("color: red")
        self.record_button.clicked.connect(lambda: start_recording(self.youtubeUserID))
        self.record_button.clicked.connect(self.recording_button)
        self.stop_button = QPushButton("Stop recording YouTube livestream")
        video_input_YouTube_Live.addRow(self.stop_button)
        self.stop_button.setStyleSheet("color: red")
        self.stop_button.clicked.connect(stop_recording)
        YouTube_widget = QWidget()
        YouTube_widget.setLayout(video_input_YouTube_Live)
        self.stacked_widget.addWidget(YouTube_widget)

        # Video Input 4: YouTube Video (Recording)
        video_input_YouTube_static = QFormLayout()
        video_input_YouTube_static.addRow(QLabel("YouTube downloads may be limited to 360p resolution."))
        self.youtubeURL = QLineEdit("https://www.youtube.com/watch?v="); video_input_YouTube_static.addRow("YouTube URL:", self.youtubeURL)
        self.matchFormYouTube = MatchForm(self.matchModel)
        video_input_YouTube_static.addRow(self.matchFormYouTube)
        YouTube_static_widget = QWidget()
        YouTube_static_widget.setLayout(video_input_YouTube_static)
        self.stacked_widget.addWidget(YouTube_static_widget)
        # Create a video widget and add it to the layout
        self.video_clip_widget = QVideoWidget()
        self.video_clip_widget.setMinimumSize(480, 270)
        self.clip_button = QPushButton("Download 4-second preview")
        self.clip_button.setStyleSheet('color: red')
        self.clip_button.clicked.connect(self.clip_video)
        video_input_YouTube_static.addRow(self.clip_button, self.video_clip_widget)
        self.media_clip_player = QMediaPlayer()
        self.audio_clip_output = QAudioOutput()
        self.media_clip_player.setAudioOutput(self.audio_clip_output)
        self.media_clip_player.setVideoOutput(self.video_clip_widget)

        # Video Input 5: Live Local File
        mkv_input_File = QFormLayout()
        self.mkvFile_button = QPushButton("Select file")
        self.mkvFile_button.clicked.connect(lambda: self.getFileVideo(['mkv'], self.mkvFile_button, True))
        mkv_input_File.addRow(self.mkvFile_button)
        mkv_file_widget = QWidget()
        mkv_file_widget.setLayout(mkv_input_File)
        self.stacked_widget.addWidget(mkv_file_widget)

        '''
        TBA PAGE
         - Season Year
         - Event Code & Name
         - Pull from FMS
        '''
        page_TBA = QWidget(self)
        layout = QFormLayout()
        page_TBA.setLayout(layout)

        self.TBA_eventCode = QLineEdit(); layout.addRow(QLabel('TBA event key:'), self.TBA_eventCode)
        self.TBA_AuthID = QLineEdit(); layout.addRow(QLabel('TBA Auth ID:'), self.TBA_AuthID)
        self.TBA_AuthSecret = QLineEdit(); self.TBA_AuthSecret.setEchoMode(QLineEdit.EchoMode.Password); layout.addRow(QLabel('TBA Auth Secret:'), self.TBA_AuthSecret)
        
        # FMS pull button
        self.button_TBA = QPushButton("Verify TBA"); self.button_TBA.setStyleSheet('color: red')
        self.button_TBA.clicked.connect(lambda: self.handleTBA(self.TBA_AuthID.text(), self.TBA_AuthSecret.text(), self.TBA_eventCode.text()))
        layout.addRow(self.button_TBA)

        '''
        add all tabs to window
        '''
        self.tab.addTab(page_welcome, 'Welcome')
        self.tab.addTab(page_event, 'Event information')
        self.tab.addTab(page_YouTube, 'YouTube settings')
        self.tab.addTab(page_thumbnail, 'Thumbnail settings')
        self.tab.addTab(page_timings, 'Match timing')
        self.tab.addTab(page_video, 'Video input')
        self.tab.addTab(page_TBA, 'The Blue Alliance')
        self.utilities = UtilitiesPage(self)
        self.tab.addTab(self.utilities, 'Utilities')
        # set tab colors
        self.tab.tabBar().setTabTextColor(1, QColor('red'))
        self.tab.tabBar().setTabTextColor(2, QColor('yellow'))
        self.tab.tabBar().setTabTextColor(3, QColor('red'))
        self.tab.tabBar().setTabTextColor(4, QColor('green'))
        self.tab.tabBar().setTabTextColor(5, QColor('red'))
        self.tab.tabBar().setTabTextColor(6, QColor('yellow'))
        main_layout.addWidget(self.tab)

        '''
        Bake CONFIG button
        '''
        config_container = QWidget()
        config_layout = QHBoxLayout(config_container)
        self.load_config = QPushButton('Load CONFIG')
        self.load_config.clicked.connect(lambda: self.loadCONFIG(self.load_config))
        config_layout.addWidget(self.load_config)
        self.bake_config = QPushButton('Bake CONFIG')
        self.bake_config.clicked.connect(lambda: self.bakeCONFIG(self.bake_config))
        config_layout.addWidget(self.bake_config)
        main_layout.addWidget(config_container)

        self.startThreadButton = QPushButton('Make the Sauce')
        self.startThreadButton.clicked.connect(self.start_sauce_thread)
        self.startThreadButton.setEnabled(False) # Disabled by default until CONFIG is baked
        main_layout.addWidget(self.startThreadButton)

        '''
        Clip confirmation switch, dashboard
        '''
        review_container = QWidget()
        review_layout = QHBoxLayout(review_container)
        self.reviewCheckbox = QCheckBox('Confirm each clip before upload (on the dashboard)')
        self.reviewCheckbox.setChecked(review.enabled())
        self.reviewCheckbox.toggled.connect(review.set_enabled)
        review_layout.addWidget(self.reviewCheckbox)
        self.dashboard_button = QPushButton('Open dashboard')
        self.dashboard_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f'http://localhost:{dashboard.PORT}')))
        review_layout.addWidget(self.dashboard_button)
        main_layout.addWidget(review_container)
        # the switch can also be flipped on the dashboard; keep the checkbox in step with it
        self.review_timer = QTimer(self)
        self.review_timer.timeout.connect(self.sync_review_checkbox)
        self.review_timer.start(2000)

        '''
        Status Bar (SEEN, BUILT, SENT)
        '''
        status_container = QWidget()
        status_layout = QHBoxLayout(status_container)
        
        self.status_seen = QLabel(" Seen: X")
        self.status_built = QLabel("Built: X")
        self.status_sent = QLabel(" Sent: X")
        
        status_layout.addWidget(self.status_seen)
        status_layout.addWidget(self.status_built)
        status_layout.addWidget(self.status_sent)

        main_layout.addWidget(status_container)

        self.show()
    
    def start_sauce_thread(self):
        if self.utilities.busy() or (self.youtube_job is not None and self.youtube_job.isRunning()):
            QMessageBox.information(self, 'Operation in progress', 'Wait for TBA linking or YouTube sign-in to finish before starting processing.')
            return
        # disable the button to prevent double-click
        self.startThreadButton.setEnabled(False)

        # Bake CONFIG re-enables this button; a second set of threads would build two clips at once
        # into the same input/temp files and corrupt them. Restart FRUIT to apply new settings instead.
        if getattr(self, 'thread_build', None) is not None and self.thread_build.is_alive():
            self.startThreadButton.setText('Processing is active; restart FRUIT to apply changes')
            print('Make the Sauce is already running; ignoring second click. Restart FRUIT to apply a new CONFIG.')
            return

        # clear the stop event
        self.stop_event.clear()

        # Clear and entries in send log file that were not finished
        with open('log/send.txt', 'r') as source_file:
            data = source_file.readlines()
        with open('log/seek.txt', 'w') as destination_file:
            destination_file.writelines(data)
        
        # Count finished matches
        count_finished = sum(1 for line in data if line.startswith(self.CONFIG['event']['code'].upper()))

        self.status_seen.setText(f" Seen: {count_finished}")
        self.status_built.setText(f"Built: {count_finished}")
        self.status_sent.setText(f" Sent: {count_finished}")

        # load API credentials
        with open("CREDENTIALS", "r") as file:
            CREDENTIALS = json.load(file)

        # Create threads for each queue
        self.thread_seek = threading.Thread(target=process_queue_seek, args=(self.CONFIG, self.stop_event, self.status_seen, CREDENTIALS))
        if self.CONFIG['video']['type'] == 'twitch':
            self.thread_build = threading.Thread(target=process_queue_build_live, args=(self.CONFIG, self.stop_event, self.status_built, CREDENTIALS))
        elif self.CONFIG['video']['type'] == 'local_live':
            self.thread_build = threading.Thread(target=process_queue_build_live_local, args=(self.CONFIG, self.stop_event, self.status_built, CREDENTIALS))
        elif self.CONFIG['video']['type'] == 'youtube_live':
            raise NotImplementedError("TODO: finish YouTube Livestream pipeline")
        elif self.CONFIG['video']['type'] in ['local', 'youtube_video']:
            self.thread_build = threading.Thread(target=process_queue_build_static, args=(self.CONFIG, self.stop_event, self.status_built, self.matches))
        self.thread_send = threading.Thread(target=process_queue_send, args=(self.CONFIG, self.stop_event, self.status_sent, self.YouTube))

        # Start the threads
        self.thread_seek.start()
        self.thread_build.start()
        self.thread_send.start()
        status.set_running(True)

    def sync_review_checkbox(self):
        on = review.enabled()
        if self.reviewCheckbox.isChecked() != on:
            self.reviewCheckbox.blockSignals(True)
            self.reviewCheckbox.setChecked(on)
            self.reviewCheckbox.blockSignals(False)

    def on_sauce_made(self, result):
        self.startThreadButton.setText(f"{result} {'match' if result == 1 else 'matches'} processed")
        self.startThreadButton.setEnabled(True)
    
    def play_video(self, player, source:str, timestamp:str, duration:float=4.0):
        """
        Play a video from a given source (file path) starting from a specific timestamp for a specified duration.

        Args:
            source (str): The file path of the video to be played.
            timestamp (str): The timestamp in the format "mm:ss" or "mm:ss.xxx" from which to start playing the video.
            duration (float): The duration in seconds for which the video should be played. Default is 4.0 seconds.
        """

        # Get the timestamp from the input field and convert it to milliseconds
        playMin, playSec = map(float, timestamp.split(':'))
        playMs = int((playMin * 60 + playSec) * 1000)
        def whenMediaReady(status):
            if status == QMediaPlayer.MediaStatus.LoadedMedia:
                player.setPosition(playMs)
                player.play()
                # Disconnect source after playing
                player.mediaStatusChanged.disconnect(whenMediaReady)
        
        # Play video when it is ready
        player.mediaStatusChanged.connect(whenMediaReady)

        # Set video source (and play)
        player.setSource(QUrl.fromLocalFile(source))

        def pause_and_release():
            player.pause()
            player.setSource(QUrl())   # release file

        # Pause the video after the specified duration
        QTimer.singleShot(int(duration * 1000), pause_and_release)
        self.tab.tabBar().setTabTextColor(5, QColor('green'))
        self.play_button.setStyleSheet('color: green')
    
    def getFileVideo(self, types, buttonBind, changeTabColor=False):
        if not(types):
            raise ValueError("types list cannot be empty")
        response = QFileDialog.getOpenFileName(
            parent=self,
            caption='Select a file',
            directory=os.getcwd(),
            filter=f'Video file (*.{" *.".join(types)})'
        )
        
        if not response[0]:
            return  # Canceling the picker must not clear an existing selection.
        self.videoFilepath = response[0]
        
        buttonBind.setText('📁'+response[0].split('/')[-1])

        if changeTabColor:
            self.tab.tabBar().setTabTextColor(5, QColor('green'))
    
    def clip_video(self):
        self.clip_button.setText('Downloading preview…')
        self.clip_button.setStyleSheet('color: teal'); self.clip_button.repaint();
        timestamp = self.matchModel.timestamp()
        self.match_timeMin, self.match_timeSec = map(float, timestamp.split(':'))
        timestamp_start = str(datetime.timedelta(minutes=int(self.match_timeMin), seconds=int(self.match_timeSec)))
        timestamp_end = str(datetime.timedelta(minutes=int(self.match_timeMin), seconds=int(self.match_timeSec)+5)) # 5 seconds of clip
        downloadYouTubeClip(self.youtubeURL.text(), timestamp_start, timestamp_end, 'input/temp/clip.mp4')
        self.clip_button.setText('Download 4-second preview')
        self.clip_button.setStyleSheet('color: green'); self.clip_button.repaint();
        self.play_video(self.media_clip_player, 'input/temp/clip.mp4', "00:"+ str(self.match_timeSec-int(self.match_timeSec)), duration=4.0)
    
    def getFileSponsorImage(self, button):
        response = QFileDialog.getOpenFileName(
            parent=self,
            caption='Select a file',
            directory=os.getcwd(),
            filter='Image File (*.png *.jpg)'
        )

        self.logoSponsorFilepath = response[0]

        button.setText('📁'+response[0].split('/')[-1])
    
    def handleFMS(self, year, eventCode):
        self.textFMS.setText('<font color="aqua">Loading event data from FIRST…</font>')
        self.textFMS.repaint()

        with open("CREDENTIALS", "r") as file:
            CREDENTIALS = json.load(file) # contains API credentials
        
        try:
            if self.program.currentText() == 'FRC':
                matchesRaw = getMatchesFromFMS(year, eventCode, self.program.currentText(), CREDENTIALS['FRC_username'], CREDENTIALS['FRC_key'])
                eventInfo = getEventInfoFromFMS(year, eventCode, self.program.currentText(), CREDENTIALS['FRC_username'], CREDENTIALS['FRC_key'])
                eventInfo['timezone'] = convert_windows_to_iana(eventInfo['timezone'])
            elif self.program.currentText() == 'FTC':
                matchesRaw = getMatchesFromFMS(year, eventCode, self.program.currentText(), CREDENTIALS['FTC_username'], CREDENTIALS['FTC_key'])
                eventInfo = getEventInfoFromFMS(year, eventCode, self.program.currentText(), CREDENTIALS['FTC_username'], CREDENTIALS['FTC_key'])
                eventInfo['timezone'] = convert_windows_to_iana(eventInfo['timezone'])
            
            self.matches = rewrapMatches(matchesRaw, self.program.currentText(), eventInfo['timezone'])
            
            # Report success of FMS pull
            if len(self.matches) != 0:
                self.textFMS.setText('<font color="green">'+str(len(self.matches))+(' match found for ' if len(self.matches) == 1 else ' matches found for ')+eventCode+'.</font>')
            else:
                self.textFMS.setText('<font color="yellow">No matches are available for '+eventCode+'. If the event has started, check the event code.</font>')
            
            # Update status bar counters
            self.status_seen.setText(f" Seen: {len(self.matches)}")
            with open('log/send.txt', 'r') as file:
                eventMatchesSent = len([line.strip() for line in file if line.startswith(eventCode.upper())])
            self.status_built.setText(f"Built: {eventMatchesSent}")
            self.status_sent.setText(f" Sent: {eventMatchesSent}")

            # Update event fields if empty
            if self.event_name.text() == '':
                self.event_name.setText(eventInfo['name'])
            if self.event_timezone.currentText() == '':
                self.event_timezone.setCurrentText(eventInfo['timezone'])
            if self.eventBuilding.text() == '':
                self.eventBuilding.setText(eventInfo['venue'])
            if self.eventCity.text() == '':
                self.eventCity.setText(eventInfo['city']+', '+eventInfo['stateprov'])
            if self.eventDates.text() == '':
                startDate = datetime.datetime.fromisoformat(eventInfo['dateStart']).date()
                endDate = datetime.datetime.fromisoformat(eventInfo['dateEnd']).date()
                if startDate == endDate:
                    self.eventDates.setText(startDate.strftime("%m/%d/%Y"))
                else:
                    self.eventDates.setText(f'{startDate.month}/{startDate.day}-{endDate.day}/{endDate.year}')

            self.tab.tabBar().setTabTextColor(1, QColor('green'))
        except json.JSONDecodeError:
            self.textFMS.setText('<font color="red">Could not load the event. Check the season, event code, and credentials.</font>')
            self.tab.tabBar().setTabTextColor(1, QColor('red'))
    
    def test_twitch(self):
        
        self.twitch_button.setText('Looking up the Twitch channel…')
        self.twitch_button.setStyleSheet("color: aqua;")
        self.twitch_button.repaint()

        with open("CREDENTIALS", "r") as file:
            CREDENTIALS = json.load(file) # contains API credentials
        
        try:
            self.twitchUserID = covertID2Username(CREDENTIALS['Twitch_clientID'], CREDENTIALS['Twitch_clientSecret'], self.twitchUser.text())
            self.twitch_button.setText('Channel found. ID: '+ self.twitchUserID)
            self.twitch_button.setStyleSheet("color: green;")
            self.tab.tabBar().setTabTextColor(5, QColor('green'))
        except IndexError:
            self.twitch_button.setText("Twitch channel not found")
            self.twitch_button.setStyleSheet("color: red;")
            self.tab.tabBar().setTabTextColor(5, QColor('red'))

    def get_yt_channel_ID(self):
        self.youtube_button.setText("Looking up the YouTube channel…")
        self.youtube_button.setStyleSheet("color: aqua;")
        self.youtube_button.repaint()
        with open("CREDENTIALS", "r") as file:
            CREDENTIALS = json.load(file)  # contains API credentials
        try:
            self.youtubeUserID = getChannelIDFromHandle(self.youtubeUser.text())
            self.youtube_button.setText("YouTube channel found")
            self.youtube_button.setStyleSheet("color: green")
            self.tab.tabBar().setTabTextColor(5, QColor("green"))
        except IndexError:
            self.youtube_button.setText("YouTube channel not found")
            self.youtube_button.setStyleSheet("color: red")

    def recording_button(self):
        self.record_button.setText("Waiting for or recording the livestream. Recordings are saved in TOOLS/recordings/.")
        self.record_button.setStyleSheet("color: aqua;")
        self.youtube_button.repaint()

    def handleTBA(self, TBA_Auth_Id, TBA_Auth_Secret, TBA_eventKey):
        self.button_TBA.setText('Verifying TBA credentials…')
        self.button_TBA.setStyleSheet('color: aqua')
        self.button_TBA.repaint()

        response = postTheBlueAlliance(TBA_Auth_Id, TBA_Auth_Secret, TBA_eventKey)

        if response.status_code == 200:
            self.button_TBA.setText('TBA credentials verified')
            self.button_TBA.setStyleSheet('color: green')
            self.button_TBA.repaint()
            self.tab.tabBar().setTabTextColor(6, QColor('green'))
        else:
            self.button_TBA.setText('Could not verify TBA credentials')
            self.button_TBA.setStyleSheet('color: red')
            self.button_TBA.repaint()
    
    def handleYouTube(self, checked=False, force_login=False):
        if self.youtube_job is not None and self.youtube_job.isRunning():
            return
        if any(getattr(self, name, None) is not None and getattr(self, name).is_alive()
               for name in ('thread_seek', 'thread_build', 'thread_send')):
            QMessageBox.information(self, 'Processing is active', 'Restart FRUIT before reconnecting or changing the upload account.')
            return
        self.textYouTube.setText('Connecting with saved sign-in, or opening your browser if needed…')
        self.button_FMS.setEnabled(False)
        self.youtube_switch.setEnabled(False)
        self.youtube_job = Job(lambda: authenticate_youtube(force_login=force_login), self)
        self.youtube_job.result.connect(self.youtube_connected)
        self.youtube_job.failed.connect(self.youtube_failed)
        self.youtube_job.finished.connect(self.youtube_finished)
        self.youtube_job.start()

    def youtube_connected(self, session):
        self.YouTube = session
        self.textYouTube.setText('<font color="green">YouTube connected; sign-in saved locally.</font>')
        self.tab.tabBar().setTabTextColor(2, QColor('green'))

    def youtube_failed(self, message):
        self.textYouTube.setText('Could not connect. Saved sign-in was preserved; check the connection and OAuth client settings.')
        QMessageBox.warning(self, 'YouTube connection', message)

    def youtube_finished(self):
        self.button_FMS.setEnabled(True)
        self.youtube_switch.setEnabled(True)

    def closeEvent(self, event):
        if self.utilities.busy() or (self.youtube_job is not None and self.youtube_job.isRunning()):
            QMessageBox.information(self, 'Operation in progress', 'Wait for TBA linking or browser sign-in to finish before closing FRUIT.')
            event.ignore()
            return
        super().closeEvent(event)

    def handleThumbnail(self, data, image, forceText = False):
        image.setText('<font color="aqua">Generating thumbnail…</font>')
        image.repaint()

        typMatchNumb = {'Q':70, 'P':13, 'F':3}
        matchType = random.choices(['Q', 'P', 'F'], [0.8, 0.15, 0.05])[0]
        matchNum = random.randint(1, typMatchNumb[matchType])

        teams = [random.randint(1, 11000) for x in range(6)]
        matchInfo = {'id': matchType+str(matchNum), 'start':datetime.datetime.now(), 'post': datetime.datetime.now()+datetime.timedelta(seconds=155), 'teamsRed': teams[0:3], 'teamsBlue' : teams[3:6]}

        eventDetails = data[0]+"\n"+data[1]+"\n"+data[2]

        if self.program.currentText() == 'FRC':
            programImagePath = './images/FIRSTRobotics_IconVert_RGB.png'
        elif self.program.currentText() == 'FTC':
            programImagePath = './images/FIRSTTech_IconVert_RGB.png'

        if forceText:
            generateThumbnail(matchInfo, programImagePath, eventDetails, None, './images/trial')
        elif self.logoSponsorFilepath != None:
            generateThumbnail(matchInfo, programImagePath, None, self.logoSponsorFilepath, './images/trial')
        else:
            generateThumbnail(matchInfo, programImagePath, eventDetails, None, './images/trial')
        
        image.setPixmap(QPixmap('./images/trial.png').scaled(QSize(424, 240)))
        self.tab.tabBar().setTabTextColor(3, QColor('green'))
    
    def bakeCONFIG(self, button):
        # Validate local input before reading its timestamps or touching CONFIG.
        if self.dropdownInput.currentText() == 'Local File':
            if not self.videoFilepath or not os.path.isfile(self.videoFilepath):
                button.setStyleSheet('color: red')
                button.setText('Bake CONFIG: select a video file')
                self.startThreadButton.setEnabled(False)
                self.tab.setCurrentIndex(5)  # Video Input
                QMessageBox.warning(self, 'Recording required',
                    'Select an existing recording in Video input before baking CONFIG. '
                    'If a file was previously selected, it may have been moved or deleted.')
                return
        try:

            original_text = button.text()
            original_style = button.styleSheet()

            # Sets text and color back to default so users know config can be baked again without restarting program
            QTimer.singleShot(
                2000,
                lambda: (
                    button.setStyleSheet(original_style),
                    button.setText(original_text),
                ),
            )

            CONFIG = {
                'program' : self.program.currentText(),
                'event' : {
                    'code' : self.event_code.text().upper(),
                    'name' : self.event_name.text(),
                    'timezone' : self.event_timezone.currentText(),
                    'details' : self.eventBuilding.text()+'\n'+self.eventCity.text()+'\n'+self.eventDates.text(),
                    'logoSponsor' : self.logoSponsorFilepath,
                    'forceDetails' : bool(self.thumbnail_force.isChecked())
                },
                'season' : {
                    'year' : int(self.season_year.currentText()),
                    'secondsBeforeStart' : float(self.season_secondsBefore.text()),
                    'secondsOfMatch' : float(self.season_matchDuration.text()), #auto + bell (~5) + teleop
                    'secondsAfterEnd' : float(self.season_secondsAfterEnd.text()),
                    'secondsBeforePost' : float(self.season_secondsBeforePost.text()),
                    'secondsAfterPost' : float(self.season_secondsAfterPost.text())
                },
                'YouTube' : {
                    'description' : self.video_description.toPlainText(),
                    'tags' : self.video_tags.text(),
                    'playlist' : self.video_playlist.text().split('?list=')[-1]
                },
                'TBA' : {
                    'Auth_Id' : self.TBA_AuthID.text(),
                    'Auth_Secret': self.TBA_AuthSecret.text(),
                    'eventKey': self.TBA_eventCode.text()
                }
            }

            CONFIG['buildMethod'] = self.dropdownBuildMethod.currentText()

            CONFIG['dataFrequency'] = self.dropdownDataFrequency.currentText()

            if 'twitch' in self.dropdownInput.currentText().lower():
                CONFIG['video'] = {'type': 'twitch',
                                   'twitchUsername' : self.twitchUser.text(),
                                   'twitchUserID' : self.twitchUserID, 
                                   'streamDelay' : float(self.streamDelay.text()),
                                   'filePath' : 'input/temp/twitchClip.mp4'}
            elif 'youtube' in self.dropdownInput.currentText().lower():
                if self.dropdownDataFrequency.currentText() == 'Live':
                    CONFIG['video'] = {'type': 'youtube_live',
                                       'youtubeUsername' : self.youtubeUser.text(),
                                       'youtubeUserID' : self.youtubeUserID, 
                                       'streamDelay' : float(self.streamDelay.text()),
                                       'filePath' : 'input/temp/youtubeClip.mp4',
                                       'recordingStartTime': 'TODO: add start time feature'}
                elif self.dropdownDataFrequency.currentText() == 'Static':
                    CONFIG['video'] = {'type': 'youtube_video',
                                       'URL' : self.youtubeURL.text(),
                                       'matchID' : self.matchModel.matchType() + str(self.matchModel.matchNumber()),
                                       'matchTime' : (self.match_timeMin, self.match_timeSec)}
            elif (self.dropdownDataFrequency.currentText() == 'Static') and (self.dropdownInput.currentText() == "Local File"):
                CONFIG['video'] = {'type': 'local',
                                   'filePath' : self.videoFilepath,
                                   'matchID' : self.matchModel.matchType() + str(self.matchModel.matchNumber()),
                                   'matchTime' : tuple(map(float, self.matchModel.timestamp().split(':')))}
            elif (self.dropdownDataFrequency.currentText() == 'Live') and (self.dropdownInput.currentText() == "Local File"):
                CONFIG['video'] = {'type': 'local_live',
                                   'filePath' : self.videoFilepath,
                                   'streamDelay' : 0.868,
                                   'recordingStartTime': str(datetime.datetime.fromtimestamp(os.path.getctime(self.videoFilepath)).astimezone())}
            
            CONFIG['video']['adaptiveSyncDelay'] = bool(self.adaptiveSyncCheckbox.isChecked())
            
            self.CONFIG = CONFIG

            self.startThreadButton.setEnabled(True)

            with open("CONFIG", "w") as file:
                json.dump(CONFIG, file, indent=2)
            button.setStyleSheet('color: green')
            button.setText('Configuration saved')
        
        except (AttributeError, TypeError, ValueError, OSError):
            button.setStyleSheet('color: red')
            button.setText('Configuration not saved')
            self.startThreadButton.setEnabled(False)
            QMessageBox.warning(self, 'Could not bake CONFIG',
                'Check that the selected recording is still available, timing values are valid numbers, '
                'and FRUIT can write to its folder. CONFIG was not successfully baked.')
    
    def loadCONFIG(self, button):
        response = QFileDialog.getOpenFileName(
            parent=self,
            caption='Select a file',
            directory=os.getcwd(),
            filter='CONFIG File (*CONFIG)'
        )

        if response[0]!='':
            button.setText('📁'+response[0].split('/')[-1])
            
            with open(response[0], "r") as file:
                # a broken CONFIG (e.g. a hand-edited path with backslashes) used to crash the whole app
                try:
                    CONFIG = json.load(file)
                except json.JSONDecodeError as error:
                    print(f'Could not load {response[0]}: {error}')
                    button.setText('Load CONFIG: invalid file')
                    return

                self.program.setCurrentText(CONFIG['program'])

                self.event_code.setText(CONFIG['event']['code'])
                self.event_name.setText(CONFIG['event']['name'])
                self.event_timezone.setCurrentText(CONFIG['event']['timezone'])
                eventDetails = CONFIG['event']['details'].split('\n')
                self.eventBuilding.setText(eventDetails[0])
                self.eventCity.setText(eventDetails[1])
                self.eventDates.setText(eventDetails[2])
                self.logoSponsorFilepath = CONFIG['event']['logoSponsor']
                if self.logoSponsorFilepath != None:
                    self.img_EventSponsor.setText('📁'+self.logoSponsorFilepath.split('/')[-1])
                self.thumbnail_force.setChecked(CONFIG['event']['forceDetails'])

                self.season_year.setCurrentText(str(CONFIG['season']['year']))
                self.season_secondsBefore.setText(str(CONFIG['season']['secondsBeforeStart']))
                self.season_matchDuration.setText(str(CONFIG['season']['secondsOfMatch']))
                self.season_secondsAfterEnd.setText(str(CONFIG['season']['secondsAfterEnd']))
                self.season_secondsBeforePost.setText(str(CONFIG['season']['secondsBeforePost']))
                self.season_secondsAfterPost.setText(str(CONFIG['season']['secondsAfterPost']))

                self.video_description.setPlainText(CONFIG['YouTube']['description'])
                self.video_tags.setText(CONFIG['YouTube']['tags'])
                self.video_playlist.setText('https://www.youtube.com/playlist?list='+CONFIG['YouTube']['playlist'])

                self.TBA_AuthID.setText(CONFIG['TBA']['Auth_Id'])
                self.TBA_AuthSecret.setText(CONFIG['TBA']['Auth_Secret'])
                self.TBA_eventCode.setText(CONFIG['TBA']['eventKey'])

                self.dropdownBuildMethod.setCurrentText(CONFIG['buildMethod'])
                self.dropdownDataFrequency.setCurrentText(CONFIG['dataFrequency'])
                self.adaptiveSyncCheckbox.setChecked(CONFIG['video']['adaptiveSyncDelay'])
                
                if CONFIG['video']['type'] == 'local':
                    self.videoFilepath = CONFIG['video']['filePath']
                    if CONFIG['video']['filePath'] != None:
                        self.videoFile_button.setText('📁'+CONFIG['video']['filePath'].split('/')[-1])
                        self.media_player.setSource(QUrl.fromLocalFile(CONFIG['video']['filePath']))
                    self.matchModel.setMatchType({'Q':"Q = Quals", 'P':"P = Playoffs", 'F':"F = Finals"}[CONFIG['video']['matchID'][0]])
                    self.matchModel.setMatchNumber(CONFIG['video']['matchID'][1:])
                    self.matchModel.setTimestamp(f'{int(CONFIG["video"]["matchTime"][0])}:{CONFIG["video"]["matchTime"][1]}')
                    self.dropdownInput.setCurrentText("Local File")
                elif CONFIG['video']['type'] == 'local_live':
                    self.videoFilepath = CONFIG['video']['filePath']
                    if CONFIG['video']['filePath'] != None:
                        self.mkvFile_button.setText('📁'+CONFIG['video']['filePath'].split('/')[-1])
                    self.dropdownInput.setCurrentText("Local File")
                    self.tab.tabBar().setTabTextColor(5, QColor('green'))
                elif CONFIG['video']['type'] == 'twitch':
                    self.streamDelay.setText(str(CONFIG['video']['streamDelay']))
                    self.twitchUser.setText(CONFIG['video']['twitchUsername'])
                    self.dropdownInput.setCurrentText("Twitch")
                    if CONFIG['video']['twitchUserID'] is not None:
                        self.twitchUserID = CONFIG['video']['twitchUserID']
                elif CONFIG['video']['type'] == 'youtube_live':
                    self.streamDelay.setText(str(CONFIG['video']['streamDelay']))
                    self.youtubeUser.setText(CONFIG['video']['youtubeUsername'])
                    self.youtubeUserID = CONFIG['video']['youtubeUserID']
                    self.dropdownInput.setCurrentText("YouTube (experimental)")
                elif CONFIG['video']['type'] == 'youtube_video':
                    self.youtubeURL.setText(CONFIG['video']['URL'])
                    self.matchModel.setMatchType({'Q':"Q = Quals", 'P':"P = Playoffs", 'F':"F = Finals"}[CONFIG['video']['matchID'][0]])
                    self.matchModel.setMatchNumber(CONFIG['video']['matchID'][1:])
                    self.matchModel.setTimestamp(f'{int(CONFIG["video"]["matchTime"][0])}:{CONFIG["video"]["matchTime"][1]}')
                    self.dropdownInput.setCurrentText("YouTube (experimental)")
        else:
            print('No CONFIG selected!')

import sys
if __name__ == '__main__':
    status.set_running(False)
    if dashboard.start():
        print(f'Dashboard: http://localhost:{dashboard.PORT}')
    else:
        print('Dashboard could not start: ports 8765-8774 are all in use')
    app = QApplication(sys.argv)
    # ffmpeg is the only thing FRUIT needs from outside; use the one already on this PC, only offer to install it if missing
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        answer = QMessageBox.question(None, 'FFmpeg not found', 'FRUIT needs ffmpeg to cut match videos, and it was not found on this PC.\n\n'
                                      'Install it now with winget? Restart FRUIT once the install finishes.')
        if answer == QMessageBox.StandardButton.Yes:
            subprocess.Popen(['cmd', '/c', 'winget install --id Gyan.FFmpeg -e & echo. & echo Done - restart FRUIT. & pause'],
                             creationflags=subprocess.CREATE_NEW_CONSOLE)
    window = MainWindow()
    sys.exit(app.exec())