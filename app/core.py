import os
import time
import re
import io
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional, Dict, List, Any
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pyncm
from pyncm import apis
from pyncm.apis import login, playlist, track
from mutagen import File as MutagenFile
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, USLT
from mutagen.mp3 import MP3
from mutagen.flac import FLAC, Picture
from PIL import Image, ImageDraw
Text2Image = None
_pil_utils_error = None
from .utils import logger
from .config import config_manager

class MusicManager:
    def __init__(self):
        self.session_file = Path("session.pyncm")
        self._is_logged_in_cache = False
        self._last_login_check = 0
        self.audio_exts = {".mp3", ".flac", ".m4a", ".wav", ".ogg", ".aac"}
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

    def _refresh_login_status(self, force: bool = False) -> bool:
        """Check login status from server with simple caching."""
        now = time.time()
        if not force and (now - self._last_login_check) < 60 and self._last_login_check != 0:
            return self._is_logged_in_cache
        try:
            status = login.LoginStatus()
            account = status.get("data", {}).get("account")
            profile = status.get("data", {}).get("profile")
            self._is_logged_in_cache = bool(account and account.get("id") and profile)
        except Exception:
            # Fall back to presence of session file if status check fails
            self._is_logged_in_cache = self.session_file.exists()
        self._last_login_check = now
        return self._is_logged_in_cache

    @property
    def is_logged_in(self) -> bool:
        """Check if user is logged in."""
        return self._refresh_login_status()

    def login_phone(self, phone: str, password: str) -> bool:
        """Login via phone and password."""
        try:
            res = login.LoginViaCellphone(phone=phone, password=password)
            if res.get("code") == 200:
                logger.info(f"Logged in as {pyncm.GetCurrentSession().nickname}")
                self.save_session()
                self._refresh_login_status(force=True)
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
            self._refresh_login_status(force=True)
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
            self._is_logged_in_cache = False
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

    def download_cover(self, url: str, quiet: bool = False) -> Optional[bytes]:
        """Download cover image."""
        log_error = logger.error if not quiet else lambda *a, **k: None
        try:
            r = pyncm.GetCurrentSession().get(url, timeout=20)
            if r.status_code == 200:
                return r.content
        except Exception as e:
            log_error(f"Failed to download cover: {e}")
        return None

    def download_lyrics(self, song_id: int, filepath: Path, quiet: bool = False):
        """Download and save lyrics."""
        log_info = logger.info if not quiet else lambda *a, **k: None
        log_error = logger.error if not quiet else lambda *a, **k: None
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
                log_info(f"Lyrics saved to {lrc_path}")
                
        except Exception as e:
            log_error(f"Failed to download lyrics: {e}")

    def embed_metadata(self, filepath: Path, song_info: Dict[str, Any], cover_data: Optional[bytes], quiet: bool = False):
        """Embed metadata and cover art."""
        log_error = logger.error if not quiet else lambda *a, **k: None
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
            log_error(f"Failed to embed metadata for {filepath}: {e}")

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

    def _extract_tags(self, audio_obj) -> Dict[str, str]:
        """Extract basic title/artist from mutagen object."""
        title = artist = album = None
        try:
            if audio_obj is None:
                return {"title": None, "artist": None, "album": None}
            if isinstance(audio_obj, MP3):
                title = getattr(audio_obj.tags.get("TIT2"), "text", [None])[0] if audio_obj.tags else None
                artist = getattr(audio_obj.tags.get("TPE1"), "text", [None])[0] if audio_obj.tags else None
                album = getattr(audio_obj.tags.get("TALB"), "text", [None])[0] if audio_obj.tags else None
            elif isinstance(audio_obj, FLAC):
                title = audio_obj.get("title", [None])[0]
                artist = audio_obj.get("artist", [None])[0]
                album = audio_obj.get("album", [None])[0]
            else:
                title = audio_obj.tags.get("title", [None])[0] if audio_obj.tags else None
                artist = audio_obj.tags.get("artist", [None])[0] if audio_obj.tags else None
                album = audio_obj.tags.get("album", [None])[0] if audio_obj.tags else None
        except Exception:
            pass
        return {"title": title, "artist": artist, "album": album}

    def _extract_cover_image(self, audio_obj) -> Optional[Image.Image]:
        """Extract embedded cover as a PIL Image."""
        try:
            if isinstance(audio_obj, MP3) and audio_obj.tags:
                for tag in audio_obj.tags.values():
                    if isinstance(tag, APIC):
                        return Image.open(io.BytesIO(tag.data)).convert("RGB")
            elif isinstance(audio_obj, FLAC):
                if audio_obj.pictures:
                    return Image.open(io.BytesIO(audio_obj.pictures[0].data)).convert("RGB")
        except Exception:
            return None
        return None

    def _inspect_file(self, file: Path, max_duration_sec: int, min_size_kb: int):
        try:
            if not file.exists() or not file.is_file():
                return None
            if file.suffix.lower() not in self.audio_exts:
                return None

            size_kb = file.stat().st_size / 1024
            audio_obj = MutagenFile(file)
            duration = getattr(audio_obj.info, "length", 0) if audio_obj and getattr(audio_obj, "info", None) else 0
            tags = self._extract_tags(audio_obj)

            too_short = duration is not None and duration <= max_duration_sec and duration > 0
            too_small = size_kb < min_size_kb

            if too_short or too_small:
                return {
                    "path": file,
                    "duration": duration,
                    "size_kb": size_kb,
                    "title": tags.get("title") or file.stem,
                    "artist": tags.get("artist"),
                    "album": tags.get("album"),
                    "max_duration_sec": max_duration_sec,
                    "min_size_kb": min_size_kb,
                }
        except Exception as e:
            logger.error(f"Failed to inspect {file}: {e}")
        return None

    def detect_failed_downloads(self, output_dir: Optional[Path] = None, files: Optional[List[Path]] = None, max_duration_sec: int = 31, min_size_kb: int = 100):
        """Return list of files that look like failed downloads (short or too small)."""
        failed = []
        targets: List[Path] = []

        if files:
            targets.extend(files)
        else:
            if output_dir is None:
                output_dir = Path(config_manager.get("output_dir", "downloads"))
            if not output_dir.exists():
                return failed
            targets.extend([p for p in output_dir.rglob("*") if p.is_file()])

        for file in targets:
            info = self._inspect_file(file, max_duration_sec, min_size_kb)
            if info:
                failed.append(info)

        return failed

    def _collect_local_tracks(self, output_dir: Path):
        tracks = []
        if not output_dir.exists():
            return tracks
        for file in sorted(output_dir.rglob("*")):
            if not file.is_file() or file.suffix.lower() not in self.audio_exts:
                continue
            try:
                audio_obj = MutagenFile(file)
                tags = self._extract_tags(audio_obj)
                cover_img = self._extract_cover_image(audio_obj)
                tracks.append({
                    "path": file,
                    "title": tags.get("title") or file.stem,
                    "artist": tags.get("artist") or "Unknown",
                    "album": tags.get("album"),
                    "cover": cover_img,
                })
            except Exception as e:
                logger.error(f"Failed to read tags for {file}: {e}")
                continue
        tracks.sort(key=lambda t: ((t.get("artist") or "").lower(), (t.get("title") or "").lower()))
        return tracks

    def _normalize_title(self, title: str) -> str:
        title = title.lower()
        # Remove bracketed content (ASCII + CJK variants)
        title = re.sub(r"[（([\{＜《『【〖［｛].*?[）)\]】}＞》』】〗］｝]", " ", title)
        # Replace separators with spaces
        title = re.sub(r"[-–—~〜·•・･⁓⎯_]+", " ", title)
        # Collapse multiple spaces
        title = re.sub(r"\s+", " ", title).strip()
        return title

    def _normalize_artist(self, artist: str) -> str:
        artist = artist.lower()
        artist = re.sub(r"[（([\{＜《『【〖［｛].*?[）)\]】}＞》』】〗］｝]", " ", artist)
        artist = re.sub(r"[\\/,&;，、·•・･⁓⎯]+", " ", artist)
        artist = re.sub(r"\s+", " ", artist).strip()
        return artist

    def _base_title(self, title: str) -> str:
        """Take the part before common separators/variants."""
        lowered = title.lower()
        base = re.split(r"[（([\{＜《『【〖［｛~～\-–—]", lowered, 1)[0]
        base = re.sub(r"\s+", " ", base).strip()
        return base

    def _tokens(self, text: str):
        return [t for t in re.split(r"[ \t/\\,&;，、·•・･⁓⎯\-]+", text) if len(t) >= 3]

    def detect_duplicate_tracks(self, output_dir: Optional[Path] = None, threshold: float = 0.8):
        """Find likely duplicate tracks; returns groups of similar tracks."""
        if output_dir is None:
            output_dir = Path(config_manager.get("output_dir", "downloads"))
        tracks = self._collect_local_tracks(output_dir)
        if not tracks:
            return []

        norms = [self._normalize_title(t["title"]) for t in tracks]
        bases = [self._base_title(t["title"]) for t in tracks]
        artists = [self._normalize_artist(t.get("artist") or "") for t in tracks]
        norm_tokens = [set(self._tokens(n)) for n in norms]

        n = len(tracks)
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            pa, pb = find(a), find(b)
            if pa != pb:
                parent[pb] = pa

        for i in range(n):
            for j in range(i + 1, n):
                if not norms[i] or not norms[j]:
                    continue
                # Skip if bases are too short to be meaningful
                if (bases[i] and len(bases[i]) < 3) or (bases[j] and len(bases[j]) < 3):
                    continue

                base_match = bases[i] and bases[j] and bases[i] == bases[j]
                if base_match:
                    # Require shared token to avoid empty matches
                    if norm_tokens[i] and norm_tokens[j] and norm_tokens[i] & norm_tokens[j]:
                        union(i, j)
                    continue

                # Same-artist similarity fallback
                if artists[i] and artists[i] == artists[j]:
                    ratio = SequenceMatcher(None, norms[i], norms[j]).ratio()
                    if ratio >= threshold:
                        union(i, j)

        comps: Dict[int, List[Dict[str, Any]]] = {}
        for idx, t in enumerate(tracks):
            root = find(idx)
            comps.setdefault(root, []).append(t)

        groups = []
        for comp in comps.values():
            if len(comp) <= 1:
                continue
            comp.sort(key=lambda t: ((t.get("artist") or "").lower(), (t.get("title") or "").lower()))
            groups.append({"normalized": comp[0].get("artist", ""), "tracks": comp})

        groups.sort(key=lambda g: (g["normalized"], g["tracks"][0].get("title", "")))
        return groups

    def _load_pil_utils(self):
        global Text2Image, _pil_utils_error
        if Text2Image is not None:
            return Text2Image
        try:
            from pil_utils import Text2Image as _t
            Text2Image = _t
            _pil_utils_error = None
        except Exception as e:
            _pil_utils_error = e
            Text2Image = None
        return Text2Image

    def has_pil_utils(self) -> bool:
        return self._load_pil_utils() is not None

    def generate_playlist_report(self, output_dir: Optional[Path] = None, filename: str = "All_List.jpg", title: str = "", description: str = ""):
        """Generate a collage/report of local tracks using pil-utils for text rendering."""
        if self._load_pil_utils() is None:
            if _pil_utils_error:
                err_msg = str(_pil_utils_error)
                if "typing_extensions" in err_msg:
                    logger.error("pil-utils dependency missing: typing_extensions. Install with 'pip install typing_extensions' or 'pip install nonencm[pil-utils]'.")
                else:
                    logger.error(f"pil-utils is unavailable: {_pil_utils_error}. Try reinstalling with 'pip install nonencm[pil-utils]'.")
            else:
                logger.error("pil-utils is unavailable. Install with 'pip install nonencm[pil-utils]'.")
            return None

        if output_dir is None:
            output_dir = Path(config_manager.get("output_dir", "downloads"))
        tracks = self._collect_local_tracks(output_dir)
        if not tracks:
            logger.warning("No tracks found to include in the report.")
            return None

        cover_size = 120
        row_height = 150
        margin = 46
        row_gap = 10
        width = 1280
        header_height = 140
        content_height = len(tracks) * row_height + max(0, len(tracks) - 1) * row_gap
        watermark_height = 50
        height = margin * 2 + header_height + content_height + watermark_height

        # Soft pink theme
        background = (247, 232, 238)
        card_outline = (221, 180, 193)
        card_fill = (255, 245, 249)
        header_bg = (255, 240, 246)
        primary_text = (92, 46, 68)
        secondary_text = (126, 82, 102)
        tertiary_text = (155, 115, 132)

        base = Image.new("RGB", (width, height), color=background)
        draw = ImageDraw.Draw(base)

        def render_text_image(text: str, size: int, color):
            try:
                return Text2Image.from_text(text, size, fill=color).to_image(bg_color=(0, 0, 0, 0))
            except TypeError:
                hex_color = "#{:02x}{:02x}{:02x}".format(*color)
                return Text2Image.from_text(f"[color={hex_color}]{text}[/color]", size).to_image(bg_color=(0, 0, 0, 0))

        def draw_text(x: int, y: int, text: str, size: int, color, target: Optional[Image.Image] = None, max_width: Optional[int] = None):
            if not text:
                return
            tgt = target if target is not None else base
            display_text = text
            img = render_text_image(display_text, size, color)
            if max_width is not None and img.size[0] > max_width:
                # truncate with ellipsis
                ellipsis = "..."
                lo, hi = 0, len(display_text)
                while lo < hi:
                    mid = (lo + hi) // 2
                    test = display_text[:mid] + ellipsis
                    test_img = render_text_image(test, size, color)
                    if test_img.size[0] <= max_width:
                        lo = mid + 1
                        img = test_img
                    else:
                        hi = mid
            tgt.paste(img, (x, y), img)

        # Header card
        header_rect = [margin, margin, width - margin, margin + header_height]
        draw.rounded_rectangle(header_rect, radius=18, fill=header_bg, outline=card_outline, width=1)

        header_title = title if title else "Playlist Report"
        header_desc = description if description else ""
        header_count = f"Tracks: {len(tracks)}"
        draw_text(margin + 28, margin + 18, header_title, 46, primary_text, max_width=width - margin * 2 - 60)
        if header_desc:
            draw_text(margin + 28, margin + 74, header_desc, 26, secondary_text, max_width=width - margin * 2 - 60)
            count_y = margin + 74 + 36
        else:
            count_y = margin + 70
        draw_text(margin + 28, count_y, header_count, 24, secondary_text)

        y = margin + header_height + row_gap
        for track in tracks:
            box_top = y
            box_bottom = y + row_height
            draw.rounded_rectangle([(margin, box_top), (width - margin, box_bottom)], radius=12, fill=card_fill, outline=card_outline, width=1)

            cover = track["cover"]
            if cover is not None:
                cover_resized = cover.resize((cover_size, cover_size))
            else:
                cover_resized = Image.new("RGB", (cover_size, cover_size), color=(236, 206, 219))
                cover_draw = ImageDraw.Draw(cover_resized)
                cover_draw.rounded_rectangle([6, 6, cover_size - 6, cover_size - 6], radius=14, outline=card_outline, width=2)
                draw_text(16, cover_size // 2 - 14, "No Cover", 20, secondary_text, target=cover_resized)

            base.paste(cover_resized, (margin + 14, y + 14))

            text_x = margin + cover_size + 32
            max_text_width = width - margin - text_x - 20
            draw_text(text_x, y + 16, track["title"], 32, primary_text, max_width=max_text_width)
            draw_text(text_x, y + 60, track["artist"], 24, secondary_text, max_width=max_text_width)
            if track.get("album"):
                draw_text(text_x, y + 92, track["album"], 22, tertiary_text, max_width=max_text_width)

            y += row_height + row_gap

        # Watermark
        watermark = "nonencm[pyncm] @2025 kumoSleeping"
        wm_img = render_text_image(watermark, 18, tertiary_text)
        wm_x = width - margin - wm_img.size[0]
        wm_y = height - margin - wm_img.size[1]
        base.paste(wm_img, (wm_x, wm_y), wm_img)

        output_path = output_dir / filename
        output_dir.mkdir(parents=True, exist_ok=True)
        base.save(output_path, format="JPEG", quality=92)
        logger.success(f"Playlist report generated: {output_path}")
        return output_path

    def export_playlist_table(self, output_dir: Optional[Path] = None, fmt: str = "csv"):
        """Export playlist info to csv/txt/markdown."""
        if output_dir is None:
            output_dir = Path(config_manager.get("output_dir", "downloads"))
        tracks = self._collect_local_tracks(output_dir)
        if not tracks:
            logger.warning("No tracks found to export.")
            return None

        fmt = fmt.lower()
        if fmt not in {"csv", "txt", "md", "markdown"}:
            logger.error(f"Unsupported export format: {fmt}")
            return None

        if fmt == "csv":
            filename = "All_List.csv"
        elif fmt == "txt":
            filename = "All_List.txt"
        else:
            filename = "All_List.md"

        output_path = output_dir / filename
        lines = []
        if fmt == "csv":
            lines.append("title,artist,album")
            for t in tracks:
                title = t["title"].replace('"', '""')
                artist = (t.get("artist") or "").replace('"', '""')
                album = (t.get("album") or "").replace('"', '""')
                lines.append(f'"{title}","{artist}","{album}"')
            lines.append('"nonencm[pyncm] @2025 kumoSleeping","",""')
        elif fmt == "txt":
            for t in tracks:
                album = t.get("album") or ""
                lines.append(f"{t['title']} - {t.get('artist') or 'Unknown'}" + (f" [{album}]" if album else ""))
            lines.append("nonencm[pyncm] @2025 kumoSleeping")
        else:  # markdown
            lines.append("| Watermark | Title | Artist | Album |")
            lines.append("| --- | --- | --- | --- |")
            lines.append(f"| nonencm[pyncm] @2025 kumoSleeping |  |  |  |")
            for t in tracks:
                album = t.get("album") or ""
                lines.append(f"|  | {t['title']} | {t.get('artist') or 'Unknown'} | {album} |")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        logger.success(f"Playlist exported to {output_path}")
        return output_path

    def download_song(self, song_id: int, song_name: str, artist_name: str, output_dir: Optional[Path] = None, quiet: bool = False, force_overwrite: Optional[bool] = None) -> Optional[Path]:
        """Download a song by ID."""
        log_info = logger.info if not quiet else lambda *a, **k: None
        log_warning = logger.warning if not quiet else lambda *a, **k: None
        log_error = logger.error if not quiet else lambda *a, **k: None
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
            effective_overwrite = overwrite if force_overwrite is None else force_overwrite

            # Adjust quality based on preferred format
            if preferred_format == "mp3":
                if quality in ["lossless", "hires"]:
                    log_info("Downgrading quality to exhigh for MP3 preference.")
                    quality = "exhigh"
            elif preferred_format == "flac":
                if quality in ["standard", "exhigh"]:
                    log_info("Upgrading quality to lossless for FLAC preference.")
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
                log_error(f"Failed to get audio URL for {song_name}")
                return None

            data = audio_res["data"][0]
            url = data["url"]
            if not url:
                log_warning(f"No download URL for {song_name} (VIP/Copyright?)")
                return None

            ext = data["type"]
            if not ext: ext = "mp3" # Default fallback
            
            filename = self.get_filename(template, song_info, ext)
            filepath = output_dir / filename

            if filepath.exists() and not effective_overwrite:
                log_info(f"File already exists: {filepath}")
                return filepath

            log_info(f"Downloading {filename} [{quality}]...")
            r = pyncm.GetCurrentSession().get(url, stream=True, timeout=60)
            with open(filepath, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024):
                    if chunk:
                        f.write(chunk)
            
            log_info(f"Downloaded to {filepath}")
            
            # Embed metadata
            if detail_res.get("code") == 200:
                cover_url = song_info["al"]["picUrl"]
                cover_data = self.download_cover(cover_url, quiet=quiet)
                self.embed_metadata(filepath, song_info, cover_data, quiet=quiet)
                log_info(f"Metadata embedded for {filename}")
            
            # Download lyrics
            if download_lrc:
                self.download_lyrics(song_id, filepath, quiet=quiet)

            return filepath

        except Exception as e:
            log_error(f"Download failed for {song_name}: {e}")
        return None
music_manager = MusicManager()
