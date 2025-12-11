import time
import re
import threading
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
                    Choice("Detection", "detection"),
                    Choice("Export", "export"),
                ]

                if not music_manager.is_logged_in:
                    logger.warning("You are not logged in. The song download may be incomplete.")
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
                elif selection.data == "detection":
                    self.menu_detection()
                elif selection.data == "export":
                    self.menu_export()
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
        # Handle fragment-style links like https://music.163.com/#/playlist?id=XXXX
        frag_path = parsed.fragment
        frag_params = {}
        if frag_path:
            if "?" in frag_path:
                frag_path_part, frag_query = frag_path.split("?", 1)
                frag_params = parse_qs(frag_query)
            else:
                frag_path_part = frag_path
            # Merge fragment-derived params if present
            if "id" in frag_params and "id" not in params:
                params["id"] = frag_params["id"]
            # If the fragment path explicitly contains playlist/song, reflect that
            if not parsed.path or parsed.path == "/":
                parsed = parsed._replace(path=frag_path_part if frag_path_part.startswith("/") else f"/{frag_path_part}")
        
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

        # Fallback: regex for playlist/song id in any part of the URL
        match = re.search(r"(playlist|song)[^\\d]*(\\d+)", url)
        if match:
            return match.group(1), match.group(2)
                
        return None, None

    def _split_keywords(self, text: str):
        """Split multiline input into cleaned keywords."""
        if not text:
            return []
        keywords = []
        for line in text.replace("\r\n", "\n").split("\n"):
            cleaned = line.strip().strip("'\"")
            if cleaned:
                keywords.append(cleaned)
        return keywords

    def _select_song_from_results(self, songs, title: str, back_label: str):
        song_choices = []
        for song in songs:
            artists = ", ".join([ar["name"] for ar in song["ar"]])
            name = song["name"]
            song_choices.append(Choice(f"{name} - {artists}", data=song))

        song_choices.append(Choice(back_label, None))
        selected_song = ListPrompt(title, song_choices).prompt()
        return selected_song.data

    def _start_download(self, song, background: bool = False, force_overwrite: bool = None, quiet: bool = False):
        artists = ", ".join([ar["name"] for ar in song["ar"]])
        if background:
            t = threading.Thread(
                target=music_manager.download_song,
                args=(song["id"], song["name"], artists),
                kwargs={"quiet": True, "force_overwrite": force_overwrite},
                daemon=True,
            )
            t.start()
            return t
        else:
            return music_manager.download_song(
                song["id"],
                song["name"],
                artists,
                quiet=quiet,
                force_overwrite=force_overwrite,
            )

    def _handle_direct_url(self, keyword: str) -> bool:
        type_, id_ = self.parse_url(keyword)

        if type_ == "playlist":
            logger.info(f"Detected Playlist ID: {id_}")
            tracks = music_manager.get_playlist_tracks(id_)
            if not tracks:
                logger.warning("No tracks found in playlist.")
                return True

            print(f"Found {len(tracks)} tracks. Starting download...")
            for track in tracks:
                artists = ", ".join([ar["name"] for ar in track["ar"]])
                music_manager.download_song(track["id"], track["name"], artists)
            print("Playlist download complete.")
            self._auto_check_failed()
            return True

        elif type_ == "song":
            logger.info(f"Detected Song ID: {id_}")
            path = music_manager.download_song(id_, f"Song_{id_}", "Unknown")
            if path:
                self._auto_check_failed(files=[path])
            return True

        return False

    def _handle_single_keyword(self, keyword: str, back_label: str = "Back", background: bool = False, force_overwrite: bool = None, quiet: bool = False):
        songs = music_manager.search(keyword)
        if not songs:
            print("No results found.")
            return

        song = self._select_song_from_results(songs, "Select song to download:", back_label)
        if song is None:
            return

        filepath = self._start_download(song, background=background, force_overwrite=force_overwrite, quiet=quiet)
        if not background and filepath:
            self._auto_check_failed(files=[filepath])
        return filepath

    def _handle_batch_keywords(self, keywords):
        total = len(keywords)
        logger.info(f"Detected multiple lines ({total}). Processing batch search...")
        cancelled = False
        threads = []
        for idx, keyword in enumerate(keywords, 1):
            try:
                logger.info(f"[{idx}/{total}] Searching for: {keyword}")
                if self._handle_direct_url(keyword):
                    continue
                songs = music_manager.search(keyword)
                if not songs:
                    logger.warning(f"No results found for '{keyword}'. Skipping.")
                    continue

                song = self._select_song_from_results(
                    songs,
                    f"Select match for: {keyword}",
                    back_label="Skip"
                )

                if song is None:
                    logger.info(f"Skipped '{keyword}'.")
                    continue

                t = self._start_download(song, background=True)
                if isinstance(t, threading.Thread):
                    threads.append(t)

            except CancelledError:
                logger.warning("Batch search cancelled by user.")
                cancelled = True
                break
        if cancelled:
            return
        for t in threads:
            t.join()
        # Run a post-batch integrity check after all threads finish.
        self._auto_check_failed()

    def _format_fail_reason(self, info: dict) -> str:
        reasons = []
        if info.get("duration") and info["duration"] <= info.get("max_duration_sec", 30):
            reasons.append(f"duration {info['duration']:.1f}s")
        if info.get("size_kb", 0) < info.get("min_size_kb", 100):
            reasons.append(f"size {int(info['size_kb'])}KB")
        return "; ".join(reasons) if reasons else "unknown issue"

    def _perform_failed_check(self, silent_if_clean: bool = False, files=None):
        output_dir = Path(config_manager.get("output_dir", "downloads"))
        if not silent_if_clean:
            logger.info(f"Checking downloads in: {output_dir}")
        failed = music_manager.detect_failed_downloads(output_dir, files=files)
        if not failed:
            if not silent_if_clean:
                logger.success("No failed downloads detected.")
            return False
        if silent_if_clean:
            logger.warning(f"Detected {len(failed)} possible failed downloads. Review?")

        if not music_manager.is_logged_in:
            logger.warning("You are not logged in. Re-downloading may fail; please login to fix.")

        confirm = ListPrompt(
            f"Detected {len(failed)} possible failed downloads. Re-download all?",
            [Choice("Yes", True), Choice("No", False)],
        ).prompt().data
        if confirm:
            for info in failed:
                self._redownload_failed(info)

        return True

    def _auto_check_failed(self, allow_second_cancel: bool = False, files=None):
        try:
            self._perform_failed_check(silent_if_clean=True, files=files)
        except CancelledError:
            if allow_second_cancel:
                logger.info("Integrity check cancelled.")
                return
            raise

    def _redownload_failed(self, info: dict):
        title = info.get("title") or info["path"].stem
        artist = info.get("artist")
        keyword_parts = [title]
        if artist:
            keyword_parts.append(artist)
        keyword = " ".join([p for p in keyword_parts if p]).strip()
        logger.info(f"Re-downloading: {keyword} (will overwrite existing file)")
        self._handle_single_keyword(
            keyword,
            back_label="Skip",
            background=True,
            force_overwrite=True,
            quiet=True,
        )

    def menu_check_failed(self):
        try:
            self._perform_failed_check(silent_if_clean=False)

        except CancelledError:
            logger.info("Check cancelled.")

    def menu_check_duplicates(self):
        try:
            output_dir = Path(config_manager.get("output_dir", "downloads"))
            duplicates = music_manager.detect_duplicate_tracks(output_dir)
            if not duplicates:
                logger.success("No potential duplicates found.")
                return

            for dup in duplicates:
                tracks = dup["tracks"]
                title_preview = tracks[0]["title"]
                prompt_title = f"Detected possible duplicates: {title_preview}\nChoose one to keep (default Skip)."
                choices = [Choice(f"{idx+1}) {t['title']} - {t.get('artist') or 'Unknown'}", idx) for idx, t in enumerate(tracks)]
                choices.append(Choice("Skip", "skip"))
                choices.append(Choice("Stop", "stop"))

                selection = ListPrompt(prompt_title, choices).prompt().data
                if selection == "stop":
                    break
                if selection == "skip":
                    continue

                # Delete all except selected
                keep_idx = selection
                for idx, t in enumerate(tracks):
                    if idx == keep_idx:
                        continue
                    path = t.get("path")
                    if path and path.exists():
                        try:
                            path.unlink()
                            logger.warning(f"Deleted {path}")
                        except Exception as e:
                            logger.error(f"Failed to delete {path}: {e}")

        except CancelledError:
            logger.info("Duplicate check cancelled.")

    def menu_detection(self):
        try:
            choices = [
                Choice("Check Failed Downloads", "failed"),
                Choice("Check Possible Duplicates", "dups"),
                Choice("Back", "back"),
            ]
            selection = ListPrompt("Detection", choices).prompt()
            if selection.data == "failed":
                self.menu_check_failed()
            elif selection.data == "dups":
                self.menu_check_duplicates()
        except CancelledError:
            logger.info("Detection cancelled.")

    def menu_export_report(self):
        output_dir = Path(config_manager.get("output_dir", "downloads"))
        if not music_manager.has_pil_utils():
            from app.core import _pil_utils_error
            if _pil_utils_error:
                if "typing_extensions" in str(_pil_utils_error):
                    logger.error("pil-utils dependency missing: typing_extensions. Install with: pip install typing_extensions")
                else:
                    logger.error(f"pil-utils unavailable: {_pil_utils_error}. Try reinstalling with: pip install 'nonencm[pil-utils]'")
            else:
                logger.error("pil-utils not installed. Install with: pip install 'nonencm[pil-utils]'")
            return
        title = InputPrompt("Report Title (optional):").prompt()
        description = InputPrompt("Report Description (optional):").prompt()
        path = music_manager.generate_playlist_report(
            output_dir=output_dir,
            title=title.strip() if title else "",
            description=description.strip() if description else "",
        )
        if path:
            logger.success(f"Report saved to {path}")

    def menu_export_table(self, fmt: str):
        output_dir = Path(config_manager.get("output_dir", "downloads"))
        path = music_manager.export_playlist_table(output_dir=output_dir, fmt=fmt)
        if path:
            logger.success(f"Exported to {path}")

    def menu_export(self):
        try:
            choices = [
                Choice("Image Report (JPG)", "image"),
                Choice("CSV", "csv"),
                Choice("TXT", "txt"),
                Choice("Markdown", "md"),
                Choice("Back", "back"),
            ]
            selection = ListPrompt("Export", choices).prompt()
            if selection.data == "image":
                self.menu_export_report()
            elif selection.data == "csv":
                self.menu_export_table("csv")
            elif selection.data == "txt":
                self.menu_export_table("txt")
            elif selection.data == "md":
                self.menu_export_table("md")
        except CancelledError:
            logger.info("Export cancelled.")

    def menu_search(self):
        while True:
            try:
                keyword_input = InputPrompt("Enter song name or URL:").prompt()
                keywords = self._split_keywords(keyword_input)

                if not keywords:
                    continue

                if len(keywords) > 1:
                    self._handle_batch_keywords(keywords)
                    continue

                keyword = keywords[0]

                if self._handle_direct_url(keyword):
                    continue

                self._handle_single_keyword(keyword)

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
                current_template = config_manager.get("template", "{title} - {artist}")
                current_lyrics = config_manager.get("download_lyrics", False)
                
                current_use_api = config_manager.get("use_download_api", False)
                current_overwrite = config_manager.get("overwrite", False)
                
                choices = [
                    Choice(f"Output Directory: {current_output}", "output"),
                    Choice(f"Audio Quality: {current_quality}", "quality"),
                    Choice(f"Preferred Format: {current_format}", "format"),
                    Choice(f"Filename Template: {current_template}", "template"),
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
                            new_output = new_output.strip("'\"")
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
