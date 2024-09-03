import os
import pathlib
import random
import json

from kivy.app import App
from kivy.properties import NumericProperty, StringProperty, ObjectProperty, ListProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.core.audio import SoundLoader
from kivy.clock import Clock
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.slider import Slider
from kivy.core.window import Window
from kivy.uix.spinner import Spinner


class SoundPlayer:
    def __init__(self, music_file):
        self.sound = None
        self.music_file = music_file

    def load_sound(self):
        if not self.sound:
            self.sound = SoundLoader.load(self.music_file)

    def play(self):
        if not self.sound:
            self.load_sound()
        if self.sound:
            self.sound.play()

    def stop(self):
        if self.sound:
            self.sound.stop()

    def set_volume(self, volume):
        if self.sound:
            self.sound.volume = volume

    def seek(self, position):
        if self.sound:
            self.sound.seek(position)

class MyFileChooser(GridLayout):
    def __init__(self, music_player, popup, **kwargs):
        super().__init__(**kwargs)
        self.music_player = music_player
        self.popup = popup
        self.cols = 1
        self.file_chooser = FileChooserListView(path=os.path.expanduser("~"), dirselect=True)
        self.add_widget(self.file_chooser)

        button_layout = BoxLayout(size_hint_y=None, height=50)
        select_button = Button(text="Select Directory")
        select_button.bind(on_press=self.select_directory)
        button_layout.add_widget(select_button)

        cancel_button = Button(text="Cancel")
        cancel_button.bind(on_press=self.dismiss_popup)
        button_layout.add_widget(cancel_button)

        self.add_widget(button_layout)

    def select_directory(self, instance):
        selected = self.file_chooser.selection
        if selected:
            selected_dir = selected[0]
            if os.path.isdir(selected_dir):
                self.music_player.set_music_dir(selected_dir)
                self.music_player.update_playlist(selected_dir)
                self.dismiss_popup()

    def dismiss_popup(self, *args):
        self.popup.dismiss()

class MusicPlayer(BoxLayout):
    INIT_POS_DUR = '0:00 / 0:00'
    INIT_SONG_TITLE = 'Click on Play or Select Song Title Above'
    vol = NumericProperty(1.0)
    music_dir = StringProperty()
    sound_player = ObjectProperty(None)
    progress_max = NumericProperty(100)
    progress_value = NumericProperty(0)
    progress_text = StringProperty(INIT_POS_DUR)
    song_title = StringProperty(INIT_SONG_TITLE)
    dances = ListProperty(['Waltz', 'Tango', 'VWSlow', 'VienneseWaltz', 'Foxtrot', 'Quickstep',
                           'WCS', 'Samba', 'ChaCha', 'Rumba', 'PasoDoble', 'JSlow', 'Jive'])
    playlist = ListProperty([])
    playlist_idx = 0
    num_selections = NumericProperty(2)
    song_max_playtime = 210  # music selections longer than 3m30s are faded out
    fade_time = 10 # 10s fade out

    script_path = os.path.dirname(os.path.abspath(__file__))

    def __init__(self, **kwargs):
        super(MusicPlayer, self).__init__(**kwargs)
        self.sound_player = None
        self.playing_position = 0
        self.load_config('config.json')

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
        self.vol_slider = Slider(min=0.0, max=1.0, value=self.vol, orientation='vertical', size_hint_y=1, height=125)
        self.vol_slider.bind(value=self.set_volume)
        self.volume_label = Label(text="Vol:" + str(int(100 * self.vol)), size_hint_x=1, width=30)
        volume_layout.add_widget(self.volume_label)
        volume_layout.add_widget(self.vol_slider)
        self.bind(vol=self.update_volume_label)

        # Controls (includes progress bar and control buttons)
        controls = BoxLayout(orientation='vertical', height="100dp", padding=2)

        # progress bar with song title and position in song
        self.song_title_label = Label(text=self.song_title)
        self.bind(song_title=self.song_title_label.setter('text'))
        controls.add_widget(self.song_title_label)
        self.progress_bar = Slider(min=0, max=self.progress_max, value=self.progress_value, step=1,
                                   cursor_size=(0, 0), value_track=True, value_track_width=4, size_hint_x=1)
        self.bind(progress_max=self.progress_bar.setter('max'))
        self.bind(progress_value=self.progress_bar.setter('value'))
        self.progress_bar.bind(on_touch_up=self.on_slider_move)
        controls.add_widget(self.progress_bar)
        self.progress_label = Label(text=self.progress_text)
        self.bind(progress_text=self.progress_label.setter('text'))
        controls.add_widget(self.progress_label)

        # control: play, pause, etc.
        control_buttons = BoxLayout(size_hint_y=None, height=50)
        play_button = Button(text="Play")
        play_button.bind(on_press=self.play_sound)
        control_buttons.add_widget(play_button)

        pause_button = Button(text="Pause")
        pause_button.bind(on_press=self.pause_sound)
        control_buttons.add_widget(pause_button)

        stop_button = Button(text="Stop")
        stop_button.bind(on_press=self.stop_sound)
        control_buttons.add_widget(stop_button)

        restart_button = Button(text="Restart")
        restart_button.bind(on_press=self.restart_sound)
        control_buttons.add_widget(restart_button)

        practice_length_button = Spinner(text='S30 L30', values=('S30 L30','S45 L45','S60 L60'),size_hint=(None,None), size_hint_y=1)
        practice_length_button.bind(text=self.practice_length)
        control_buttons.add_widget(practice_length_button)

        select_music_button = Button(text="Select Music")
        select_music_button.bind(on_press=self.open_file_manager)
        control_buttons.add_widget(select_music_button)

        controls.add_widget(control_buttons)

        volume_and_controls.add_widget(volume_layout)
        volume_and_controls.add_widget(controls)

        self.add_widget(volume_and_controls)

        if not self.playlist and self.music_dir:
            self.update_playlist(self.music_dir)

    def load_config(self, filename):
        if os.path.isfile(filename):
            with open(filename, 'r') as f:
                config_data = json.load(f)
                self.vol = config_data.get('volume', 1.0)
                self.set_music_dir(config_data.get("music_dir", 'Music'))
                #self.music_dir = config_data.get('music_dir', 'Music')

    def set_music_dir(self,dir_name):
        self.music_dir = dir_name

    def play_sound(self, instance=None):
        if not self.sound_player and self.playlist:
            self.sound_player = SoundPlayer(self.playlist[0])
        if self.sound_player:
            self.sound_player.play()

            self.sound_player.set_volume(self.vol)

            # Set progress_max to the length of the song
            if self.sound_player.sound:
                self.progress_max = round(self.sound_player.sound.length)
                self.total_time = self.secs_to_time_str(time_sec=self.progress_max)

            if self.playing_position == 0:
                Clock.unschedule(self.update_progress)
            Clock.schedule_interval(self.update_progress, 0.1)
            self.song_title = pathlib.Path(self.playlist[self.playlist_idx]).stem  # Update the song title here
            self.sound_player.seek(self.playing_position)

    def pause_sound(self, instance=None):
        if self.sound_player and self.sound_player.sound and self.sound_player.sound.state == 'play':
            self.playing_position = self.sound_player.sound.get_pos()
            self.sound_player.sound.stop()

    def stop_sound(self, instance=None):
        if self.sound_player:
            self.sound_player.stop()
            Clock.unschedule(self.update_progress)
            self.progress_value = 0
            self.playing_position = 0
            self.progress_text = self.INIT_POS_DUR


    def restart_sound(self, instance=None):
        if self.sound_player:
            self.sound_player.stop()
            self.playing_position = 0
            self.sound_player.play()

    def set_volume(self, slider, volume):
        self.vol = volume
        if self.sound_player:
            self.sound_player.set_volume(volume)

    def update_volume_label(self, instance, value):
        """Update the volume label text when self.vol changes."""
        self.volume_label.text = f"Vol: {int(value * 100)}"

    def on_slider_move(self, instance, touch):
        if self.sound_player and instance.collide_point(*touch.pos):
            self.playing_position = self.progress_bar.value
            self.sound_player.seek(self.playing_position)

    def update_progress(self, dt):
        if self.sound_player and self.sound_player.sound and self.sound_player.sound.state == 'play':         
                self.playing_position = self.sound_player.sound.get_pos()
                self.progress_value = round(self.playing_position)
                current_time = self.secs_to_time_str(time_sec=self.playing_position)
                self.progress_text = f'{current_time} / {self.total_time}'
                if self.playing_position >= self.song_max_playtime:
                    self.sound_player.set_volume(self.vol * (1 + (self.song_max_playtime - self.playing_position) / self.fade_time))
                if self.playing_position >= self.progress_max - 1 or self.playing_position > self.song_max_playtime + self.fade_time:
                    self.sound_player.sound.unload()
                    self.playlist_idx += 1
                    if self.playlist_idx < len(self.playlist):
                        self.sound_player = SoundPlayer(self.playlist[self.playlist_idx])
                        self.play_sound()
                        self.sound_player.set_volume(self.vol)
                    else:
                        self.restart_playlist()

    def on_song_button_press(self, index):
        if self.sound_player.sound:
            self.sound_player.sound.unload()
        self.playlist_idx = index
        self.sound_player = SoundPlayer(self.playlist[self.playlist_idx])
        self.play_sound()

    def secs_to_time_str(self, time_sec):
        hours = int(time_sec // 3600)
        minutes = int((time_sec % 3600) // 60)
        seconds = int(time_sec % 60)
        return f'{hours:02d}:{minutes:02d}:{seconds:02d}' if hours > 0 else f'{minutes:02d}:{seconds:02d}'

    def select_music_file(self, path, filename):
        if filename:
            self.sound_player = SoundPlayer(filename[0])

    def open_file_manager(self, instance):
        popup = Popup(title="Select Music Folder", size_hint=(0.9, 0.9))
        content = MyFileChooser(music_player=self, popup=popup)
        popup.content = content
        popup.open()

    def restart_playlist(self, instance=None):
        if self.sound_player and self.sound_player.sound:
            self.sound_player.sound.unload()
        Clock.unschedule(self.update_progress)
        self.progress_value = 0
        self.progress_text = self.INIT_POS_DUR
        self.playlist_idx = 0
        self.song_title = self.INIT_SONG_TITLE
        self.sound_player = SoundPlayer(self.playlist[0])
        
    def update_playlist(self, directory, instance=None):
        self.playlist = []
        for dance in self.dances:
            self.playlist.extend(self.get_songs(directory, dance, self.num_selections))
        if self.playlist:
            self.sound_player = SoundPlayer(self.playlist[0])
            self.display_playlist(self.playlist)
            self.restart_playlist()

    def display_playlist(self, playlist):
        self.button_grid.clear_widgets()
        for i in range(len(self.playlist)):
            btn = Button(text=pathlib.Path(self.playlist[i]).stem, size_hint_y=None, height=40)
            btn.bind(on_press=lambda instance, i=i: self.on_song_button_press(i))
            self.button_grid.add_widget(btn)

    def adjust_num_selections(self, dance, num_selections):
        if dance in ("PasoDoble") and num_selections == 1:
            num_selections = 0
        elif dance in ("PasoDoble") and num_selections == 2:
            num_selections = 1
        elif dance in ("PasoDoble") and num_selections > 1:
            num_selections = 2
        elif dance in ("VWSlow", "JSlow") and num_selections > 1:
            num_selections = 1
        elif dance in ('VienneseWaltz', 'Jive') and num_selections > 1:
            num_selections -= 1
        elif dance in ('WCS') and num_selections > 2:
            num_selections = 2
        return num_selections
        
    def get_songs(self, directory, dance, num_selections):
        music = []
        num = 0
        num_selections = self.adjust_num_selections(dance, num_selections)
        subdir = os.path.join(directory, dance)
        if os.path.exists(subdir):
            for root, dirs, files in os.walk(subdir):
                for file in files:
                    if file.endswith(('.mp3', '.wav', '.ogg')):
                        music.append(os.path.join(root, file))
            if music:
                random.shuffle(music)
                num = min(num_selections, len(music))
                music.insert(0, os.path.join(self.script_path, 'announce', dance + '.ogg'))
        return music[:num+1]

    def practice_length(self, spinner, text):
        if text == 'S30 L30':
            self.num_selections = 2
        elif text == 'S45 S45':
            self.num_selections = 3
        elif text == 'S60 L60':
            self.num_selections = 4
        self.stop_sound()
        self.update_playlist(self.music_dir)


class MusicApp(App):
    def build(self):
        return MusicPlayer()

if __name__ == '__main__':
    MusicApp().run()
