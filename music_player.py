from kivy.config import Config
Config.set('input', 'mouse', 'mouse,multitouch_on_demand')

import os
import platform
import pathlib
import random
import json
import configparser
import sys
if sys.platform=="win32":
    import ctypes

from kivy.app import App
from kivy.properties import NumericProperty, StringProperty, ObjectProperty, ListProperty, DictProperty, BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.core.audio import SoundLoader
from kivy.clock import Clock
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider

from kivy.uix.settings import SettingsWithSpinner
from kivy.config import ConfigParser

from tinytag import TinyTag

class MusicPlayer(BoxLayout):
    INIT_POS_DUR = '0:00 / 0:00'
    INIT_SONG_TITLE = 'Click on Play or Select Song Title Above'
    INIT_MUSIC_SELECTION = 'A valid dance music directory is needed.  Click here or use Music Settings button'
    SONG_BTN_BCKGRD = (0.5,0.5,0.5,1)

    sound = ObjectProperty(None, allownone=True)
    music_file = StringProperty(None)
    position = NumericProperty(0)
    volume = NumericProperty(0.7)
    music_dir = StringProperty('')
    progress_max = NumericProperty(100)
    progress_value = NumericProperty(0)
    progress_text = StringProperty(INIT_POS_DUR)
    song_title = StringProperty(INIT_SONG_TITLE)
    play_single_song = BooleanProperty(False)


    practice_dances = DictProperty({
        "default": ['Waltz', 'Tango', 'VWSlow', 'VienneseWaltz', 'Foxtrot', 'QuickStep',
                    'WCS', 'Samba', 'ChaCha', 'Rumba', 'PasoDoble', 'JSlow', 'Jive'],
        "beginner": ["Waltz", "JSlow", "Jive", "Rumba", "Foxtrot", "ChaCha", "Tango"],
        "newcomer": ["Waltz", "JSlow", "Jive", "Rumba", "Foxtrot", "ChaCha", "Tango", 
                     "Samba", "QuickStep", "VWSlow", "VienneseWaltz", "WCS"],
        "LineDance": ["LineDance"],
        "misc": ["AmericanRumba", "ArgentineTango", "Bolero", "DiscoFox", "Hustle", "LindyHop", "Mambo", "Merengue", "NC2Step", "Polka", "Salsa"]
    })
      
    playlist = ListProperty([])
    playlist_idx = NumericProperty(0)
    dances = ListProperty([])
    practice_type = StringProperty('60min')
    num_selections = NumericProperty(2)
    song_max_playtime = 210  # music selections longer than 210 (3m30s) are faded out
    fade_time = 10 # 10s fade out
    
    settings_json = [
        {
            "type": "numeric",
            "title": "Volume",
            "desc": "Set the music volume; range is 0.0 to 1.0.",
            "section": "user",
            "key": "volume"
        },
        {
            "type": "path",
            "title": "Music Directory",
            "desc": "Set the music directory.  The directory must have sub-folders containing the music for each dance included in the playlist.  For example, musical selections for the Waltz will be randomly selected from the Waltz sub-folder.",
            "section": "user",
            "key": "music_dir"
        },
        {
            "type": "numeric",
            "title": "Max Playtime",
            "desc": "Set the maximum playtime for a song in seconds.  The music fades out and stops after the maximum playtime.",
            "section": "user",
            "key": "song_max_playtime"
        },
        {
            "type": "options",
            "title": "Practice Type",
            "desc": "Choose the practice type/length. Un-prefixed times are dances played in competition order.  The prefix B (for beginner) includes only beginner dances.  The prefixes B and NC (for newcomer) modify the order of dances.",
            "section": "user",
            "key": "practice_type",
            "options": ["60min","NC 60min","B 60min","90min", "NC 90min", "120min", "NC 120min","LineDance","Misc"]
        }
    ]

    script_path = os.path.dirname(os.path.abspath(__file__))

    current_button = None  # Track the currently playing song's button
    song_buttons = []  # Store the buttons for all songs

    def __init__(self, **kwargs):
        super(MusicPlayer, self).__init__(**kwargs)
        self.sound = None
        self.playing_position = 0
        self.total_time = 0
        self.schedule_interval = 0.1
        
        self.orientation = 'vertical'

        # Create ScrollView and GridLayout for playlist buttons
        self.scrollview = ScrollView(size_hint=(1, 1), size=(self.width, 400))
        self.button_grid = GridLayout(cols=1, size_hint_y=None)
        self.button_grid.bind(minimum_height=self.button_grid.setter('height'))
        self.scrollview.add_widget(self.button_grid)
        self.add_widget(self.scrollview)

        # Volume and control layout
        volume_and_controls = BoxLayout(orientation='horizontal', height="125dp", size_hint_y=None)

        # Volume Slider
        volume_layout = BoxLayout(orientation='horizontal', size_hint_x=0.20, padding=(10, 0))
        self.volume_slider = Slider(min=0.0, max=1.0, value=self.volume, orientation='vertical', size_hint_y=1, height=125, value_track = True, value_track_color=(0.3, 0.8, 0.3,1))
        self.volume_slider.bind(value=self.set_volume)
        self.volume_label = Label(text="Vol: " + str(int(100 * self.volume)) + "%", size_hint_x=1, width=30, color=(0.3, 0.8, 0.3, 1))
        volume_layout.add_widget(self.volume_label)
        volume_layout.add_widget(self.volume_slider)
        self.bind(volume=self.update_volume_label)

        # Controls (includes progress bar and control buttons)
        controls = BoxLayout(orientation='vertical', height="100dp", padding=2)

        # progress bar with song title and position in song
        self.song_title_label = Label(text=self.song_title, color=(0, 1, 0, 1))  # Green text
        self.bind(song_title=self.song_title_label.setter('text'))
        controls.add_widget(self.song_title_label)
        self.progress_bar = Slider(min=0, max=self.progress_max, value=self.progress_value, step=1,
                           cursor_size=(0, 0), value_track=True, value_track_width=4, size_hint_x=1,
                           value_track_color=(0.3, 0.8, 0.3, 1))
        self.bind(progress_max=self.progress_bar.setter('max'))
        self.bind(progress_value=self.progress_bar.setter('value'))
        self.progress_bar.bind(on_touch_up=self.on_slider_move)
        controls.add_widget(self.progress_bar)
        self.progress_label = Label(text=self.progress_text, color=(0, 1, 0, 1))
        self.bind(progress_text=self.progress_label.setter('text'))
        controls.add_widget(self.progress_label)

        # control: play, pause, etc.
        control_buttons = BoxLayout(size_hint_y=None, height=50)
        play_button = Button(text="Play", background_color=(0.2, 0.6, 0.8, 1), color=(1, 1, 1, 1))
        play_button.bind(on_press=self.play_sound)
        control_buttons.add_widget(play_button)

        pause_button = Button(text="Pause", background_color=(0.2, 0.6, 0.8, 1), color=(1, 1, 1, 1))
        pause_button.bind(on_press=self.pause_sound)
        control_buttons.add_widget(pause_button)

        stop_button = Button(text="Stop", background_color=(0.2, 0.6, 0.8, 1), color=(1, 1, 1, 1))
        stop_button.bind(on_press=self.stop_sound)
        control_buttons.add_widget(stop_button)

        restart_button = Button(text="Restart Song", background_color=(0.2, 0.6, 0.8, 1), color=(1, 1, 1, 1))
        restart_button.bind(on_press=self.restart_sound)
        control_buttons.add_widget(restart_button)
        
        playlist_button = Button(text="New Playlist", background_color=(0.2, 0.6, 0.8, 1), color=(1, 1, 1, 1))
        playlist_button.bind(on_press=lambda instance: self.update_playlist(self.music_dir))
        control_buttons.add_widget(playlist_button)

        settings_button = Button(text="Music Settings", background_color=(0.2, 0.6, 0.8, 1), color=(1, 1, 1, 1))
        settings_button.bind(on_press=lambda instance: App.get_running_app().open_settings())
        control_buttons.add_widget(settings_button)

        controls.add_widget(control_buttons)

        volume_and_controls.add_widget(volume_layout)
        volume_and_controls.add_widget(controls)

        self.add_widget(volume_and_controls)
        
        if not self.playlist and self.music_dir:
            self.update_playlist(self.music_dir)
                   
    def get_dances(self, list_name):
        try:
            return self.practice_dances[list_name]
        except KeyError:
            return self.practice_dances["default"]

    def play_sound(self, instance=None):
        
        # Check if there are songs in the playlist
        if self.playlist and self.playlist_idx < len(self.playlist):
            current_song_path = self.playlist[self.playlist_idx]

            # Check if the song file exists
            if not os.path.exists(current_song_path):
                # If the file does not exist, show an error message and skip to the next song
                self.show_error_popup(f"Song file not found: {current_song_path}")
                self.playlist_idx += 1  # Move to the next song
                if self.playlist_idx < len(self.playlist):
                    self.play_sound()  # Try playing the next song
                return
        
        # Load and play the song if the file exists
        if self.sound is None and self.playlist:
            self.sound = SoundLoader.load(self.playlist[self.playlist_idx])

        if self.sound:
            if self.sound.state == 'play':
                self.playing_position = self.sound.get_pos()
            if self.sound and self.sound.state != 'stop':
                self.sound.stop()
            self.sound.volume = self.volume

            Clock.unschedule(self.update_progress)
            if self.sound.length is not None and self.sound.length > 0:
                self.progress_max = round(self.sound.length)
            else:
                self.progress_max = round(self.song_duration(self.playlist[self.playlist_idx]))
                
            self.total_time = self.secs_to_time_str(time_sec=self.progress_max)
            self.song_title = self.song_label(self.playlist[self.playlist_idx])[:90]

            # Reset the previous button to default color (white)
            if hasattr(self, 'current_button') and self.current_button:
                self.current_button.background_color = (1, 1, 1, 1)

            # Get the current button and change its background color
            self.current_button = self.song_buttons[self.playlist_idx]
            self.current_button.background_color = (0, 1, 1, 1)  # Highlight the button (RGB with opacity)

            # Scroll so the current button is visible
            if self.playlist_idx < len(self.song_buttons)-2:
                self.scrollview.scroll_to(self.song_buttons[self.playlist_idx+2])
            elif self.playlist_idx < len(self.song_buttons)-1:
                self.scrollview.scroll_to(self.song_buttons[self.playlist_idx+1])

            Clock.schedule_interval(self.update_progress, self.schedule_interval)
            
            if platform.system() == 'Windows':
                self.sound.play()
                self.sound.seek(self.playing_position)
            else:    
                self.sound.seek(self.playing_position)
                self.sound.play()
        else:
            # If sound couldn't be loaded, show an error popup and skip to the next song
            self.show_error_popup(f"Could not load song: {self.playlist[self.playlist_idx]}")
            self.playlist_idx += 1
            if self.playlist_idx < len(self.playlist):
                self.play_sound()
            else:
                self.restart_playlist()            
           
    def pause_sound(self, instance=None):
        if self.sound and self.sound.state == 'play':
            self.playing_position = self.sound.get_pos()
            if self.sound:
                self.sound.stop()

    def stop_sound(self, instance=None):
        if self.sound:
            self.sound.stop()
            self.sound.unload()
            Clock.unschedule(self.update_progress)
            self.progress_value = 0
            self.playing_position = 0
            self.progress_text = self.INIT_POS_DUR
            self.sound = None

    def restart_sound(self, instance=None):
        if self.sound:
            self.sound.stop()
            self.playing_position = 0
            self.sound.play()

    def set_volume(self, slider, volume):
        self.volume= volume
        if self.sound:
            self.sound.volume = volume

    def update_volume_label(self, instance, value):
        self.volume_label.text = f"Vol: {int(value * 100)}%"
        
    def show_error_popup(self, message):
        # Create a label that supports text wrapping
        label = Label(text=message, 
                    text_size=(380, None),  # 380 is slightly smaller than the popup width
                    size_hint_y=None,
                    color=(1,1,1,1)) # white text

        # Set the label height based on the content to ensure it adjusts to long text
        label.bind(texture_size=label.setter('size'))

        # Create a "Close" button
        close_button = Button(text="Close", background_color=(0.7, 0.7, 0.7, 1), color=(0, 0, 0, 1))  # Gray button with black text
        
        # Create a layout to hold both the label and button
        layout = BoxLayout(orientation='vertical', padding=10, spacing=10)
        layout.add_widget(label)
        layout.add_widget(close_button)

        # Create the popup
        popup = Popup(title="Error", 
                    content=layout, 
                    size_hint=(None, None), 
                    size=(400, 200))
        
        # Bind the close button to dismiss the popup
        close_button.bind(on_press=popup.dismiss)

        # Open the popup
        popup.open()


    def on_slider_move(self, instance, touch):
        if self.sound and instance.collide_point(*touch.pos):
            self.playing_position = self.progress_bar.value
            self.sound.seek(self.playing_position)

    def update_progress(self, dt):
        if self.sound is not None and self.sound.state == 'play':         
            self.playing_position = self.sound.get_pos()
            self.progress_value = round(self.playing_position)
            current_time = self.secs_to_time_str(time_sec=self.playing_position)
            self.progress_text = f'{current_time} / {self.total_time}'
            if not self.play_single_song:
                if self.playing_position >= self.song_max_playtime and self.fade_time > 0:
                    self.sound.volume=self.sound.volume* (1 + self.schedule_interval*(self.song_max_playtime - self.playing_position) / self.fade_time)
                if self.playing_position >= self.progress_max - 1 or self.playing_position > self.song_max_playtime + self.fade_time:
                    self.sound.unload()
                    self.playlist_idx += 1
                    self.playing_position = 0
                    if self.playlist_idx < len(self.playlist):
                        #self.sound = SoundLoader.load(self.playlist[self.playlist_idx])
                        self.sound  = None
                        self.play_sound()
                    else:
                        self.restart_playlist()

    def on_song_button_press(self, index):
        if self.sound:
            self.sound.unload()
        self.playing_position = 0
        self.playlist_idx = index
        self.sound = None
        self.play_sound()

    def secs_to_time_str(self, time_sec):
        hours = int(time_sec // 3600)
        minutes = int((time_sec % 3600) // 60)
        seconds = int(time_sec % 60)
        return f'{hours:02d}:{minutes:02d}:{seconds:02d}' if hours > 0 else f'{minutes:02d}:{seconds:02d}'

    def restart_playlist(self, instance=None):
        if self.sound:
            self.sound.unload()
        Clock.unschedule(self.update_progress)
        self.progress_value = 0
        self.playing_position = 0
        self.progress_text = self.INIT_POS_DUR
        self.playlist_idx = 0
        self.song_title = self.INIT_SONG_TITLE
        for btn in self.song_buttons:
            btn.background_color = self.SONG_BTN_BCKGRD
        if hasattr(self, 'current_button') and self.current_button:
            #self.current_button.background_color = (1, 1, 1, 1)
            self.current_button = self.song_buttons[self.playlist_idx]
            self.current_button.background_color = (0, 1, 1, 1)
            self.scrollview.scroll_to(self.current_button)
        self.sound = None
        #self.sound = SoundLoader.load(self.playlist[0])
        
    def update_playlist(self, directory, instance=None):
        if self.sound:
            self.sound.unload()
        self.playlist = []
        for dance in self.dances:
            self.playlist.extend(self.get_songs(directory, dance, self.num_selections))
        #if self.playlist:
        self.playlist_idx = 0
        self.sound = None
        #self.sound = SoundLoader.load(self.playlist[0])
        self.display_playlist(self.playlist)
        self.restart_playlist()

    def display_playlist(self, playlist):
        self.button_grid.clear_widgets()
        self.song_buttons = []  # Clear the buttons list
        if len(self.playlist) == 0:
            btn = Button(text=self.INIT_MUSIC_SELECTION, size_hint_y=None, height=40,
                         background_color=(1, 0, 0, 1), color=(1, 1, 1, 1))
            btn.bind(on_press=lambda instance: App.get_running_app().open_settings())
            self.song_buttons.append(btn)  # Store the button in the list
            self.button_grid.add_widget(btn)
        else:
            for i in range(len(self.playlist)):
                btn = Button(text=self.song_label(self.playlist[i]), size_hint_y=None, height=40,
                            background_color=self.SONG_BTN_BCKGRD, color=(1, 1, 1, 1))  # Dark gray background, white text
                btn.bind(on_press=lambda instance, i=i: self.on_song_button_press(i))
                self.song_buttons.append(btn)  # Store the button in the list
                self.button_grid.add_widget(btn)

    def song_duration(self, selection):
        tag = TinyTag.get(selection)
        return tag.duration if tag.duration is not None else 300
    
    def song_label(self, selection) -> str:
        label = pathlib.Path(selection).stem
        tag = TinyTag.get(selection)
        
        if all([tag.title is None, tag.genre is None, tag.artist is None, tag.album is None]):
            return label
        title = tag.title if tag.title is not None else "Title Unspecified"
        genre = tag.genre if tag.genre is not None else "Genre Unspecified"
        artist = tag.artist if tag.artist is not None else "Artist Unspecified"
        album = tag.album if tag.album is not None else "Album Unspecified"
        
        return title + ' / ' + genre + ' / ' + artist + ' / ' + album

    def adjust_num_selections(self, dance, num_selections):
        if dance in ("PasoDoble") and num_selections == 1:
            num_selections = 0
        elif dance in ("PasoDoble") and num_selections in (2,3):
            num_selections = 1
        elif dance in ("PasoDoble") and num_selections > 3:
            num_selections = 2
        elif dance in ("VWSlow", "JSlow") and num_selections > 1:
            num_selections = 1
        elif dance in ('VienneseWaltz', 'Jive') and num_selections > 1:
            num_selections -= 1
        elif dance in ('WCS') and num_selections > 2:
            num_selections = 2
        elif dance in ('LineDance'):
            num_selections = 100 # include all the line dances
        return num_selections
        
    def get_songs(self, directory, dance, num_selections):
        music = []
        num_selections = self.adjust_num_selections(dance, num_selections)
        subdir = os.path.join(directory, dance)
        
        if os.path.exists(subdir):
            for root, dirs, files in os.walk(subdir):
                for file in files:
                    if file.endswith(('.mp3', '.ogg', '.m4a', '.flac', '.wav')):
                        music.append(os.path.join(root, file))
            
            if music:
                num = min(num_selections, len(music))
                if dance != 'LineDance':
                    selected_songs = random.sample(music, num)
                else:
                    selected_songs = sorted(music[:num+1])
                if os.path.isfile(os.path.join(self.script_path, 'announce', dance + '.ogg')):
                    selected_songs.insert(0, os.path.join(self.script_path, 'announce', dance + '.ogg'))
                else:
                    selected_songs.insert(0, os.path.join(self.script_path, 'announce', 'Generic.ogg'))
                return selected_songs
        
        return []

    def set_practice_type(self, spinner, text):
        self.play_single_song = False
        if text == '60min':
            self.dances = self.get_dances('default')
            self.num_selections = 2
        elif text == 'B 60min':
            self.dances = self.get_dances('beginner')
            self.num_selections = 2   
        elif text == 'NC 60min':
            self.dances = self.get_dances('newcomer')
            self.num_selections = 2       
        elif text == '90 min':
            self.dances = self.get_dances('default')
            self.num_selections = 3
        elif text == 'NC 90min':
            self.dances = self.get_dances('newcomer')
        elif text == '120min':
            self.dances = self.get_dances('default')
            self.num_selections = 4
        elif text == 'NC 120min':
            self.dances = self.get_dances('newcomer')
            self.num_selections = 4
        elif text == 'LineDance':
            self.play_single_song = True
            self.dances = self.get_dances('LineDance')
            self.num_selections = 100
        elif text == 'Misc':
            #self.play_single_song = True
            self.dances = self.get_dances('misc')
            self.num_selections = 100
        else:
            self.dances = self.get_dances('default')
            self.num_selections = 2
        self.stop_sound()
        self.update_playlist(self.music_dir)

class MusicApp(App):
    home_dir = os.getenv("USERPROFILE") or os.getenv("HOME") or str(pathlib.Path.home())
    default_music_dir = os.path.join(home_dir, "Music")
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config = ConfigParser()


    def build(self):
        self.settings_cls = SettingsWithSpinner
        self.root = MusicPlayer()
        return self.root

    def on_start(self):
        config = self.config
        user_section = 'user'
        if config.has_section(user_section):
            self.root.volume = config.getfloat(user_section, 'volume', fallback=0.7)
            self.root.music_dir = config.get(user_section, 'music_dir', fallback=self.default_music_dir)
            self.root.song_max_playtime = config.getint(user_section, 'song_max_playtime', fallback=210)
            self.root.practice_type = config.get(user_section, 'practice_type', fallback='60min')
        
        self.root.set_practice_type(None, self.root.practice_type)
        if sys.platform == "win32":
            Clock.schedule_once(self.close_console, 1)

    def close_console(self, dt):
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
        # The following code is a workaround for gstreamer starting very slowly because
        # of missing dlls.  Without it, there is a noticeable delay playing the first
        # selection in the playlist.  We can't fix that so deal with it during startup.
        self.root.sound = SoundLoader.load(self.root.playlist[self.root.playlist_idx])
        self.root.sound.play()
        self.root.sound.stop()

    def build_config(self, config):
        config.setdefaults('user', {
            'volume': 0.7,
            'music_dir': self.default_music_dir,
            'song_max_playtime': 210,
            'practice_type': '60min'
        })

    def build_settings(self, settings):
        settings.add_json_panel('Music Player Settings', self.config, data=json.dumps(self.root.settings_json))

    def on_config_change(self, config, section, key, value):
        if section == 'user':
            if key == 'volume':
                try:
                    volume_value = float(value)
                    self.root.volume = volume_value
                    self.root.set_volume(None,volume_value)
                    self.root.volume_slider.value = volume_value
                except ValueError:
                    print("Error: volume value is not a float")
            elif key == 'music_dir':
                self.root.music_dir = value
                self.root.update_playlist(value)
            elif key == 'song_max_playtime':
                self.root.song_max_playtime = int(value)
            elif key == 'practice_type':
                self.root.practice_type = value
                self.root.set_practice_type(None, value)
                     
if __name__ == '__main__':
    MusicApp().run()
