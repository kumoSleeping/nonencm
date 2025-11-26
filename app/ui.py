import time
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from noneprompt import ListPrompt, Choice, InputPrompt, CancelledError
from .core import music_manager
from .config import config_manager
from .utils import logger, save_qr_and_open

class UI:
    def run(self):
        output_dir = Path(config_manager.get('output_dir', 'downloads')).absolute()
        logger.success(f"Download Directory: {output_dir}")
        logger.info("Press <Ctrl+C> to go back or cancel operations.")
        from .__main__ import get_version
        logger.success(f"nonencm v{get_version()}")
        
        while True:
            try:
                choices = [
                    Choice("Search & Download", "search"),
                ]

                if not music_manager.is_logged_in:
                    choices.extend([
                        Choice("Login (QR Code) [Recommended]", "login_qr"),
                        Choice("Login (Phone)", "login_phone"),
                        Choice("Login (Anonymous)", "login_anon"),
                    ])
                else:
                    choices.append(Choice("Logout", "logout"))

                choices.extend([
                    Choice("Settings", "settings"),
                    Choice("Exit", "exit"),
                ])
                
                selection = ListPrompt("Main Menu", choices).prompt()
                
                if selection.data == "exit":
                    break
                elif selection.data == "search":
                    self.menu_search()
                elif selection.data == "login_phone":
                    self.menu_login_phone()
                elif selection.data == "login_qr":
                    self.menu_login_qr()
                elif selection.data == "login_anon":
                    self.menu_login_anon()
                elif selection.data == "logout":
                    self.menu_logout()
                elif selection.data == "settings":
                    self.menu_settings()
                    
            except CancelledError:
                break
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"UI Error: {e}")

    def parse_url(self, url: str):
        """Parse Netease Music URL."""
        if "music.163.com" not in url:
            return None, None
            
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        
        if "playlist" in url or "playlist" in params.get("id", [""])[0]:
            if "id" in params:
                return "playlist", params["id"][0]
        elif "song" in url:
             if "id" in params:
                return "song", params["id"][0]
        
        if "id" in params:
            if "/playlist" in parsed.path:
                return "playlist", params["id"][0]
            if "/song" in parsed.path:
                return "song", params["id"][0]
                
        return None, None

    def menu_search(self):
        while True:
            try:
                keyword = InputPrompt("Enter song name or URL:").prompt()
                
                type_, id_ = self.parse_url(keyword)
                
                if type_ == "playlist":
                    logger.info(f"Detected Playlist ID: {id_}")
                    tracks = music_manager.get_playlist_tracks(id_)
                    if not tracks:
                        logger.warning("No tracks found in playlist.")
                        continue
                        
                    print(f"Found {len(tracks)} tracks. Starting download...")
                    for track in tracks:
                        artists = ", ".join([ar["name"] for ar in track["ar"]])
                        music_manager.download_song(track["id"], track["name"], artists)
                    print("Playlist download complete.")
                    continue
                    
                elif type_ == "song":
                    logger.info(f"Detected Song ID: {id_}")
                    music_manager.download_song(id_, f"Song_{id_}", "Unknown")
                    continue

                songs = music_manager.search(keyword)
                if not songs:
                    print("No results found.")
                    continue
                
                song_choices = []
                for song in songs:
                    artists = ", ".join([ar["name"] for ar in song["ar"]])
                    name = song["name"]
                    song_choices.append(Choice(f"{name} - {artists}", data=song))
                
                song_choices.append(Choice("Back", "back"))
                
                selected_song = ListPrompt("Select song to download:", song_choices).prompt()
                
                if selected_song.data == "back":
                    continue
                
                song = selected_song.data
                artists = ", ".join([ar["name"] for ar in song["ar"]])
                music_manager.download_song(song["id"], song["name"], artists)
                
            except CancelledError:
                break

    def menu_login_phone(self):
        phone = InputPrompt("Phone Number:").prompt()
        password = InputPrompt("Password:").prompt()
        if music_manager.login_phone(phone, password):
            print("Login successful!")
        else:
            print("Login failed.")

    def menu_login_qr(self):
        print("Generating QR code...")
        unikey = music_manager.login_qr_get_key()
        url = f"https://music.163.com/login?codekey={unikey}"
        save_qr_and_open(url)
        
        while True:
            time.sleep(2)
            res = music_manager.login_qr_check(unikey)
            code = res.get("code")
            if code == 800:
                print("QR Code expired.")
                break
            elif code == 801:
                pass
            elif code == 802:
                print("Scanned, waiting for confirmation...")
            elif code == 803:
                print("Login successful!")
                music_manager.save_session()
                break

    def menu_login_anon(self):
        if music_manager.login_anonymous():
            print("Anonymous login successful!")
        else:
            print("Anonymous login failed.")

    def menu_logout(self):
        try:
            choices = [Choice("No", False), Choice("Yes", True)]
            if ListPrompt("Are you sure you want to logout?", choices).prompt().data:
                if music_manager.logout():
                    print("Logged out successfully.")
                else:
                    print("Logout failed.")
            else:
                print("Logout cancelled.")
        except CancelledError:
            print("Logout cancelled.")

    def menu_settings(self):
        while True:
            try:
                current_output = config_manager.get("output_dir", "downloads")
                current_quality = config_manager.get("quality", "standard")
                current_format = config_manager.get("preferred_format", "auto")
                current_template = config_manager.get("template", "{artist} - {title}")
                current_lyrics = config_manager.get("download_lyrics", False)
                
                current_use_api = config_manager.get("use_download_api", False)
                current_overwrite = config_manager.get("overwrite", False)
                
                choices = [
                    Choice(f"Output Directory: {current_output}", "output"),
                    Choice(f"Audio Quality: {current_quality}", "quality"),
                    Choice(f"Preferred Format: {current_format}", "format"),
                    Choice("Filename Template", "template"),
                    Choice(f"Download Lyrics: {'Yes' if current_lyrics else 'No'}", "lyrics"),
                    Choice(f"Use Download API: {'Yes' if current_use_api else 'No'}", "use_api"),
                    Choice(f"Overwrite Files: {'Yes' if current_overwrite else 'No'}", "overwrite"),
                    Choice("Back", "back")
                ]
                
                selection = ListPrompt("Settings", choices).prompt()
                
                if selection.data == "back":
                    break
                
                elif selection.data == "output":
                    try:
                        new_output = InputPrompt(f"Enter new output directory (current: {current_output}):").prompt()
                        if new_output:
                            config_manager.set("output_dir", new_output)
                    except CancelledError:
                        pass
                
                elif selection.data == "quality":
                    try:
                        q_choices = [
                            Choice("Standard (standard)", "standard"),
                            Choice("Higher (exhigh)", "exhigh"),
                            Choice("Lossless (lossless)", "lossless"),
                            Choice("Hi-Res (hires)", "hires"),
                        ]
                        q_sel = ListPrompt("Select Audio Quality:", q_choices).prompt()
                        config_manager.set("quality", q_sel.data)
                    except CancelledError:
                        pass
                    
                elif selection.data == "format":
                    try:
                        f_choices = [
                            Choice("Auto (auto)", "auto"),
                            Choice("MP3 (mp3)", "mp3"),
                            Choice("FLAC (flac)", "flac"),
                        ]
                        f_sel = ListPrompt("Select Preferred Format:", f_choices).prompt()
                        config_manager.set("preferred_format", f_sel.data)
                    except CancelledError:
                        pass

                elif selection.data == "template":
                    try:
                        print("Available variables: {title}, {artist}, {album}, {id}")
                        new_template = InputPrompt(f"Enter filename template (current: {current_template}):").prompt()
                        if new_template:
                            config_manager.set("template", new_template)
                    except CancelledError:
                        pass
                        
                elif selection.data == "lyrics":
                    try:
                        choices = [Choice("No", False), Choice("Yes", True)]
                        new_val = ListPrompt("Download lyrics?", choices).prompt().data
                        config_manager.set("download_lyrics", new_val)
                    except CancelledError:
                        pass

                elif selection.data == "use_api":
                    try:
                        choices = [Choice("No", False), Choice("Yes", True)]
                        new_val = ListPrompt("Use standard Download API?", choices).prompt().data
                        config_manager.set("use_download_api", new_val)
                    except CancelledError:
                        pass

                elif selection.data == "overwrite":
                    try:
                        choices = [Choice("No", False), Choice("Yes", True)]
                        new_val = ListPrompt("Overwrite existing files?", choices).prompt().data
                        config_manager.set("overwrite", new_val)
                    except CancelledError:
                        pass
                    
            except CancelledError:
                break

ui = UI()
