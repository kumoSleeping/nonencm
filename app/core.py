import os
import time
import re
from pathlib import Path
from typing import Optional, Dict, List, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pyncm
from pyncm import apis
from pyncm.apis import login, playlist, track
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, USLT
from mutagen.mp3 import MP3
from mutagen.flac import FLAC, Picture
from .utils import logger
from .config import config_manager

class MusicManager:
    def __init__(self):
        self.session_file = Path("session.pyncm")
        self.load_session()
        self.configure_session()

    def configure_session(self):
        """Configure session with retries."""
        retry = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        sess = pyncm.GetCurrentSession()
        sess.mount("http://", adapter)
        sess.mount("https://", adapter)

    def load_session(self):
        """Load session from file if exists."""
        if self.session_file.exists():
            try:
                with open(self.session_file, "r") as f:
                    dump = f.read()
                pyncm.SetCurrentSession(pyncm.LoadSessionFromString(dump))
                logger.info("Session loaded.")
            except Exception as e:
                logger.error(f"Failed to load session: {e}")
            finally:
                self.configure_session()

    def save_session(self):
        """Save current session to file."""
        try:
            dump = pyncm.DumpSessionAsString(pyncm.GetCurrentSession())
            with open(self.session_file, "w") as f:
                f.write(dump)
            logger.info("Session saved.")
        except Exception as e:
            logger.error(f"Failed to save session: {e}")

    @property
    def is_logged_in(self) -> bool:
        """Check if user is logged in."""
        return self.session_file.exists()

    def login_phone(self, phone: str, password: str) -> bool:
        """Login via phone and password."""
        try:
            res = login.LoginViaCellphone(phone=phone, password=password)
            if res.get("code") == 200:
                logger.info(f"Logged in as {pyncm.GetCurrentSession().nickname}")
                self.save_session()
                return True
            else:
                logger.error(f"Login failed: {res}")
                return False
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

    def login_anonymous(self) -> bool:
        """Login anonymously."""
        try:
            login.LoginViaAnonymousAccount()
            logger.info("Logged in anonymously.")
            self.save_session()
            return True
        except Exception as e:
            logger.error(f"Anonymous login failed: {e}")
            return False

    def logout(self) -> bool:
        """Logout by removing session file."""
        try:
            if self.session_file.exists():
                self.session_file.unlink()
            # Reset session
            pyncm.SetCurrentSession(pyncm.Session())
            self.configure_session() # Re-configure retries
            logger.info("Logged out.")
            return True
        except Exception as e:
            logger.error(f"Logout error: {e}")
            return False

    def login_qr_get_key(self) -> str:
        """Get QR code unikey."""
        res = login.LoginQrcodeUnikey(dtype=1)
        return res["unikey"]

    def login_qr_check(self, unikey: str) -> Dict[str, Any]:
        """Check QR code status."""
        return login.LoginQrcodeCheck(unikey)

    def search(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for songs."""
        try:
            res = apis.cloudsearch.GetSearchResult(keyword=keyword, limit=limit, stype=1)
            if res.get("code") == 200 and "songs" in res.get("result", {}):
                return res["result"]["songs"]
            return []
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    def get_playlist_tracks(self, playlist_id: str) -> List[Dict[str, Any]]:
        """Get all tracks from a playlist."""
        try:
            res = playlist.GetPlaylistAllTracks(playlist_id)
            if "songs" in res:
                return res["songs"]
            return []
        except Exception as e:
            logger.error(f"Failed to get playlist tracks: {e}")
            return []

    def download_cover(self, url: str) -> Optional[bytes]:
        """Download cover image."""
        try:
            r = pyncm.GetCurrentSession().get(url, timeout=20)
            if r.status_code == 200:
                return r.content
        except Exception as e:
            logger.error(f"Failed to download cover: {e}")
        return None

    def download_lyrics(self, song_id: int, filepath: Path):
        """Download and save lyrics."""
        try:
            res = track.GetTrackLyrics(song_id)
            if res.get("code") != 200:
                return

            lrc_content = ""
            if "lrc" in res and "lyric" in res["lrc"]:
                lrc_content += res["lrc"]["lyric"]
            
            # Append translation if available and configured?
            # For now just standard lrc
            
            if lrc_content:
                lrc_path = filepath.with_suffix(".lrc")
                with open(lrc_path, "w", encoding="utf-8") as f:
                    f.write(lrc_content)
                logger.info(f"Lyrics saved to {lrc_path}")
                
        except Exception as e:
            logger.error(f"Failed to download lyrics: {e}")

    def embed_metadata(self, filepath: Path, song_info: Dict[str, Any], cover_data: Optional[bytes]):
        """Embed metadata and cover art."""
        try:
            ext = filepath.suffix.lower()
            if ext == ".mp3":
                try:
                    audio = MP3(filepath, ID3=ID3)
                except Exception:
                    audio = MP3(filepath)
                    audio.add_tags()
                
                if audio.tags is None:
                    audio.add_tags()
                
                # Basic tags
                audio.tags.add(TIT2(encoding=3, text=song_info["name"]))
                audio.tags.add(TPE1(encoding=3, text=[ar["name"] for ar in song_info["ar"]]))
                audio.tags.add(TALB(encoding=3, text=song_info["al"]["name"]))

                # Cover art
                if cover_data:
                    audio.tags.add(
                        APIC(
                            encoding=3,
                            mime='image/jpeg',
                            type=3,
                            desc=u'Cover',
                            data=cover_data
                        )
                    )
                audio.save()
            
            elif ext == ".flac":
                audio = FLAC(filepath)
                audio["title"] = song_info["name"]
                audio["artist"] = [ar["name"] for ar in song_info["ar"]]
                audio["album"] = song_info["al"]["name"]
                
                if cover_data:
                    pic = Picture()
                    pic.type = 3
                    pic.mime = 'image/jpeg'
                    pic.desc = 'Cover'
                    pic.data = cover_data
                    audio.add_picture(pic)
                audio.save()
                
        except Exception as e:
            logger.error(f"Failed to embed metadata for {filepath}: {e}")

    def get_filename(self, template: str, song_info: Dict[str, Any], ext: str) -> str:
        """Generate filename based on template."""
        try:
            # Prepare template variables
            artists = ", ".join([ar["name"] for ar in song_info["ar"]])
            title = song_info["name"]
            album = song_info["al"]["name"]
            track_no = song_info.get("no", "")
            year = "" # Need to parse publishTime if needed
            id_ = song_info["id"]
            
            # Safe filename
            safe_title = re.sub(r'[\\/*?:"<>|]', "", title)
            safe_artists = re.sub(r'[\\/*?:"<>|]', "", artists)
            safe_album = re.sub(r'[\\/*?:"<>|]', "", album)
            
            filename = template.format(
                title=safe_title,
                artist=safe_artists,
                artists=safe_artists,
                album=safe_album,
                track=safe_title, # pyncm help says track - artists equivalent to title? usually track is number.
                # Let's stick to standard keys
                id=id_
            )
            return f"{filename}.{ext}"
        except Exception:
            # Fallback
            return f"{safe_title} - {safe_artists}.{ext}"

    def download_song(self, song_id: int, song_name: str, artist_name: str, output_dir: Optional[Path] = None):
        """Download a song by ID."""
        if output_dir is None:
            output_dir = Path(config_manager.get("output_dir", "downloads"))
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # Get configuration
            quality = config_manager.get("quality", "exhigh")
            preferred_format = config_manager.get("preferred_format", "auto")
            template = config_manager.get("template", "{title} - {artist}")
            download_lrc = config_manager.get("download_lyrics", False)
            use_download_api = config_manager.get("use_download_api", False)
            overwrite = config_manager.get("overwrite", False)

            # Adjust quality based on preferred format
            if preferred_format == "mp3":
                if quality in ["lossless", "hires"]:
                    logger.info("Downgrading quality to exhigh for MP3 preference.")
                    quality = "exhigh"
            elif preferred_format == "flac":
                if quality in ["standard", "exhigh"]:
                    logger.info("Upgrading quality to lossless for FLAC preference.")
                    quality = "lossless"

            # Get song info first to determine filename
            detail_res = track.GetTrackDetail(song_id)
            if detail_res.get("code") == 200 and "songs" in detail_res:
                song_info = detail_res["songs"][0]
            else:
                # Mock info if fail
                song_info = {"name": song_name, "ar": [{"name": artist_name}], "al": {"name": "Unknown"}, "id": song_id}

            # We need extension to check existence, but we don't know it yet without audio url...
            # Actually we can guess or just get audio url first.
            # But wait, if we get audio url, we might be "using" the API.
            # However, standard flow is get audio -> get ext -> check file.
            
            # Get audio URL
            if use_download_api:
                audio_res = track.GetTrackAudio(song_id)
            else:
                audio_res = track.GetTrackAudioV1(song_id, level=quality)
            
            if audio_res["code"] != 200 or not audio_res["data"]:
                # Fallback if V1 failed and we didn't force download api
                if not use_download_api:
                    audio_res = track.GetTrackAudio(song_id)
            
            if audio_res["code"] != 200 or not audio_res["data"]:
                logger.error(f"Failed to get audio URL for {song_name}")
                return

            data = audio_res["data"][0]
            url = data["url"]
            if not url:
                logger.warning(f"No download URL for {song_name} (VIP/Copyright?)")
                return

            ext = data["type"]
            if not ext: ext = "mp3" # Default fallback
            
            filename = self.get_filename(template, song_info, ext)
            filepath = output_dir / filename

            if filepath.exists() and not overwrite:
                logger.info(f"File already exists: {filepath}")
                return

            logger.info(f"Downloading {filename} [{quality}]...")
            r = pyncm.GetCurrentSession().get(url, stream=True, timeout=60)
            with open(filepath, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
            
            logger.info(f"Downloaded to {filepath}")
            
            # Embed metadata
            if detail_res.get("code") == 200:
                cover_url = song_info["al"]["picUrl"]
                cover_data = self.download_cover(cover_url)
                self.embed_metadata(filepath, song_info, cover_data)
                logger.info(f"Metadata embedded for {filename}")
            
            # Download lyrics
            if download_lrc:
                self.download_lyrics(song_id, filepath)

        except Exception as e:
            logger.error(f"Download failed for {song_name}: {e}")

music_manager = MusicManager()
