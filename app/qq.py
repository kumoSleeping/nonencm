import asyncio
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from qqmusic_api import search as qq_search
from qqmusic_api import song as qq_song
from qqmusic_api import songlist as qq_songlist
from qqmusic_api.login import (
    LoginError,
    PhoneLoginEvents,
    QRCodeLoginEvents,
    QRLoginType,
    check_expired,
    check_qrcode,
    get_qrcode,
    phone_authorize,
    refresh_cookies,
    send_authcode,
)
from qqmusic_api.utils.credential import Credential
from qqmusic_api.utils.session import Session, set_session, clear_session

from .config import config_manager
from .utils import logger
from .utils.common import save_raw_qr
from .core import music_manager


class QQMusicManager:
    def __init__(self):
        self.session_file = Path("session.qqmusic.json")
        self._credential: Optional[Credential] = None
        self._is_logged_in_cache = False
        self._last_login_check = 0.0
        self.load_session()

    async def _with_session(self, coro, session: Optional[Session], owns_session: bool):
        """Run coroutine with provided or fresh Session bound to context."""
        sess = session or Session(credential=self._credential)
        set_session(sess)
        try:
            return await coro
        finally:
            try:
                if owns_session:
                    await sess.aclose()
            except Exception:
                pass
            clear_session()

    def _run_async(self, coro, session: Optional[Session] = None):
        """Run coroutine safely even if another loop exists, with optional shared session."""
        owns = session is None
        try:
            return asyncio.run(self._with_session(coro, session, owns))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(self._with_session(coro, session, owns))
                loop.run_until_complete(loop.shutdown_asyncgens())
                return result
            finally:
                try:
                    loop.close()
                except Exception:
                    pass
                asyncio.set_event_loop(None)

    def _run_coro_direct(self, coro):
        """Run coroutine without injecting session (for custom-managed flows)."""
        try:
            return asyncio.run(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(coro)
                loop.run_until_complete(loop.shutdown_asyncgens())
                return result
            finally:
                try:
                    loop.close()
                except Exception:
                    pass
                asyncio.set_event_loop(None)

    def load_session(self):
        """Load stored credential from disk."""
        if not self.session_file.exists():
            return
        try:
            data = json.loads(self.session_file.read_text(encoding="utf-8"))
            # Normalize legacy keys
            if "loginType" in data and "login_type" not in data:
                data["login_type"] = data.pop("loginType")
            if "encryptUin" in data and "encrypt_uin" not in data:
                data["encrypt_uin"] = data.pop("encryptUin")
            cred = Credential(**data)
            self._apply_credential(cred)
            logger.info("Loaded QQ Music session.")
        except Exception as e:
            logger.error(f"Failed to load QQ session: {e}")

    def save_session(self):
        """Persist credential to disk."""
        if not self._credential:
            return
        try:
            payload = self._credential.as_dict() if hasattr(self._credential, "as_dict") else self._credential.__dict__
            self.session_file.write_text(json.dumps(payload), encoding="utf-8")
            logger.info("Saved QQ Music session.")
        except Exception as e:
            logger.error(f"Failed to save QQ session: {e}")

    def _apply_credential(self, credential: Credential):
        self._credential = credential
        self._is_logged_in_cache = True
        self._last_login_check = time.time()

    def _refresh_login_status(self, force: bool = False) -> bool:
        now = time.time()
        if self._credential is None:
            self._is_logged_in_cache = False
            self._last_login_check = now
            return False
        if not force and (now - self._last_login_check) < 60 and self._last_login_check != 0:
            return self._is_logged_in_cache
        try:
            expired = self._run_async(check_expired(self._credential))
            if expired:
                refreshed = self._run_async(refresh_cookies(self._credential))
                self._is_logged_in_cache = bool(refreshed)
                if refreshed:
                    self._apply_credential(self._credential)
                    self.save_session()
            else:
                self._is_logged_in_cache = True
        except Exception:
            self._is_logged_in_cache = False
        self._last_login_check = time.time()
        return self._is_logged_in_cache

    @property
    def is_logged_in(self) -> bool:
        return self._refresh_login_status()

    def logout(self) -> bool:
        try:
            if self.session_file.exists():
                self.session_file.unlink()
            self._credential = None
            self._is_logged_in_cache = False
            self._last_login_check = 0.0
            self.session = Session()
            set_session(self.session)
            logger.info("Logged out of QQ Music.")
            return True
        except Exception as e:
            logger.error(f"QQ Music logout failed: {e}")
            return False

    def send_phone_code(self, phone: str, country_code: int = 86):
        """Send SMS code for phone login."""
        try:
            phone_num = int(phone)
        except ValueError:
            logger.error("Phone number must be numeric.")
            return None, None
        try:
            return self._run_async(send_authcode(phone_num, country_code))
        except LoginError as e:
            logger.error(f"Failed to send code: {e}")
        except Exception as e:
            logger.error(f"Unexpected error sending code: {e}")
        return None, None

    def login_phone(self, phone: str, auth_code: str, country_code: int = 86) -> bool:
        """Login via phone verification code."""
        try:
            phone_num = int(phone)
            code_num = int(auth_code)
        except ValueError:
            logger.error("Phone and auth code must be numeric.")
            return False
        try:
            credential = self._run_async(phone_authorize(phone_num, code_num, country_code))
            self._apply_credential(credential)
            self.save_session()
            logger.success(f"QQ Music login successful! MusicID: {credential.musicid}")
            return True
        except LoginError as e:
            logger.error(f"Login failed: {e}")
        except Exception as e:
            logger.error(f"Unexpected login error: {e}")
        return False

    def login_qr(self, login_type: QRLoginType = QRLoginType.QQ) -> bool:
        """Login via QR code (QQ or WeChat)."""
        async def flow():
            session = Session()
            set_session(session)
            try:
                qr = await get_qrcode(login_type)
                save_raw_qr(qr.data, filename="login_qr.png")
                while True:
                    await asyncio.sleep(2)
                    event, credential = await check_qrcode(qr)

                    if event == QRCodeLoginEvents.TIMEOUT:
                        logger.warning("QR code expired. Please retry.")
                        return False
                    if event == QRCodeLoginEvents.SCAN:
                        logger.info("QR scanned. Waiting for confirmation...")
                        continue
                    if event == QRCodeLoginEvents.CONF:
                        logger.info("Awaiting confirmation on your device...")
                        continue
                    if event == QRCodeLoginEvents.REFUSE:
                        logger.warning("Login refused on device.")
                        return False
                    if event == QRCodeLoginEvents.DONE and credential:
                        self._apply_credential(credential)
                        self.save_session()
                        logger.success(f"QQ Music login successful! MusicID: {credential.musicid}")
                        return True
            except LoginError as e:
                logger.error(f"QR login failed: {e}")
                return False
            except Exception as e:
                logger.error(f"Unexpected QR login error: {e}")
                return False
            finally:
                try:
                    await session.aclose()
                except Exception:
                    pass
                clear_session()

        return bool(self._run_coro_direct(flow()))

    def search(self, keyword: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search songs on QQ Music."""
        try:
            songs = self._run_async(
                qq_search.search_by_type(
                    keyword,
                    search_type=qq_search.SearchType.SONG,
                    num=limit,
                    page=1,
                    highlight=False,
                )
            )
        except Exception as e:
            logger.error(f"QQ search error: {e}")
            return []

        results = []
        for song in songs or []:
            title = song.get("name") or song.get("title") or song.get("songname") or "Unknown"
            mid = song.get("mid") or song.get("songmid") or str(song.get("id"))
            singers = [s.get("name") for s in song.get("singer", []) if s.get("name")]
            album = ""
            album_info = song.get("album")
            album_mid = None
            if isinstance(album_info, dict):
                album = album_info.get("name") or album_info.get("title") or ""
                album_mid = album_info.get("mid") or (album_info.get("pmid") or "").split("_")[0] or None
            media_mid = (song.get("file") or {}).get("media_mid") or mid
            vs = song.get("vs") or []
            results.append(
                {
                    "mid": mid,
                    "title": title,
                    "singers": singers,
                    "album": album,
                    "album_mid": album_mid,
                    "media_mid": media_mid,
                    "vs": vs,
                    "raw": song,
                }
            )
        return results

    def get_playlist_tracks(self, playlist_id: str) -> List[Dict[str, Any]]:
        """Fetch all tracks from a QQ Music playlist."""
        try:
            tracks = self._run_async(qq_songlist.get_songlist(int(playlist_id)))
        except Exception as e:
            logger.error(f"Failed to fetch Q playlist {playlist_id}: {e}")
            return []

        results = []
        for track in tracks or []:
            mid = track.get("mid") or track.get("songmid") or track.get("id")
            if not mid:
                continue
            title = track.get("name") or track.get("title") or track.get("songname") or "Unknown"
            singers = [s.get("name") for s in track.get("singer", []) if s.get("name")]
            album = ""
            album_mid = None
            album_info = track.get("album")
            if isinstance(album_info, dict):
                album = album_info.get("name") or album_info.get("title") or ""
                album_mid = album_info.get("mid") or (album_info.get("pmid") or "").split("_")[0] or None
            media_mid = (track.get("file") or {}).get("media_mid") or mid
            vs = track.get("vs") or []
            results.append(
                {
                    "mid": str(mid),
                    "title": title,
                    "singers": singers,
                    "album": album,
                    "album_mid": album_mid,
                    "media_mid": media_mid,
                    "vs": vs,
                }
            )
        return results

    def get_song_detail(self, song_mid: str) -> Optional[Dict[str, Any]]:
        """Fetch song detail by mid to enrich metadata/cover."""
        try:
            data = self._run_async(qq_song.query_song([song_mid]))
        except Exception as e:
            logger.error(f"Failed to query Q song detail for {song_mid}: {e}")
            return None
        if not data:
            return None
        info = data[0]
        title = info.get("name") or info.get("title") or "Unknown"
        singers = [s.get("name") for s in info.get("singer", []) if s.get("name")]
        album_info = info.get("album") or {}
        album = album_info.get("name") or album_info.get("title") or ""
        album_mid = album_info.get("mid") or (album_info.get("pmid") or "").split("_")[0] or ""
        media_mid = (info.get("file") or {}).get("media_mid") or song_mid
        vs = info.get("vs") or []
        return {
            "mid": song_mid,
            "title": title,
            "singers": singers,
            "album": album,
            "album_mid": album_mid,
            "media_mid": media_mid,
            "vs": vs,
        }

    def _qq_file_type(self):
        """Resolve preferred QQ file type."""
        prefer = config_manager.get("qq_file_type", "mp3_320")
        mapping = {
            "mp3_128": qq_song.SongFileType.MP3_128,
            "mp3_320": qq_song.SongFileType.MP3_320,
            "flac": qq_song.SongFileType.FLAC,
        }
        return mapping.get(prefer, qq_song.SongFileType.MP3_320)

    def download_song(
        self,
        song_mid: str,
        song_name: str,
        artists: str,
        album: str = "",
        album_mid: str = "",
        media_mid: str = "",
        vs: Optional[List[str]] = None,
        *,
        quiet: bool = False,
        force_overwrite: Optional[bool] = None,
    ) -> Optional[Path]:
        """Download a QQ Music song by mid."""
        log_info = logger.info if not quiet else (lambda *a, **k: None)
        log_error = logger.error if not quiet else (lambda *a, **k: None)

        output_dir = Path(config_manager.get("output_dir", "downloads"))
        output_dir.mkdir(parents=True, exist_ok=True)

        file_type = self._qq_file_type()
        ext = file_type.e.lstrip(".")

        song_info = {
            "name": song_name,
            "ar": [{"name": a.strip()} for a in artists.split(",") if a.strip()],
            "al": {"name": album or ""},
            "id": song_mid,
        }
        template = config_manager.get("template", "{title} - {artist}")
        filename = music_manager.get_filename(template, song_info, ext)
        filepath = output_dir / filename

        if force_overwrite is None:
            force_overwrite = config_manager.get("overwrite", False)

        if filepath.exists() and not force_overwrite:
            log_info(f"File exists, skipping: {filepath}")
            return filepath

        try:
            vs_list = vs or []
            media = media_mid or song_mid
            candidates = [song_mid, media] + vs_list

            url = self._get_download_url(candidates, file_type, vs_list)

            # Fallback: fetch detail if missing URLs
            if not url:
                detail = self.get_song_detail(song_mid)
                if detail:
                    media = detail.get("media_mid") or media
                    vs_list = detail.get("vs") or vs_list
                    if not album_mid:
                        album_mid = detail.get("album_mid") or album_mid
                    # Enrich tags if missing
                    if not album:
                        album = detail.get("album") or album
                        song_info["al"]["name"] = album
                    if not artists:
                        artists = ", ".join(detail.get("singers") or [])
                        song_info["ar"] = [{"name": a.strip()} for a in artists.split(",") if a.strip()]
                    if detail.get("title"):
                        song_info["name"] = detail["title"]
                    candidates = [song_mid, media] + vs_list
                    url = self._get_download_url(candidates, file_type, vs_list)

            if not url:
                log_error("No download URL returned.")
                return None

            with httpx.Client(timeout=30) as client:
                cover_data = self._fetch_cover(client, album_mid)
                with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with open(filepath, "wb") as f:
                        for chunk in resp.iter_bytes(8192):
                            if chunk:
                                f.write(chunk)
            try:
                music_manager.embed_metadata(filepath, song_info, cover_data=cover_data, quiet=True)
            except Exception:
                pass
            log_info(f"Downloaded: {filepath}")
            return filepath
        except Exception as e:
            log_error(f"Failed to download {song_name}: {e}")
            return None

    def _get_download_url(
        self,
        mids: List[str],
        file_type: qq_song.SongFileType,
        vs: List[str],
    ) -> Optional[str]:
        """Get download URL with fallbacks across multiple mids."""
        candidates = []
        seen = set()
        for m in mids:
            if m and m not in seen:
                candidates.append(m)
                seen.add(m)

        # Preferred quality
        for mid in candidates:
            try:
                url_map = self._run_async(
                    qq_song.get_song_urls([mid], file_type=file_type, credential=self._credential)
                )
                url = url_map.get(mid)
                if isinstance(url, tuple):
                    url = url[0]
                if url:
                    return url
            except Exception as e:
                logger.error(f"Primary download URL fetch failed for {mid}: {e}")

        # Fallback to MP3_128
        if file_type != qq_song.SongFileType.MP3_128:
            for mid in candidates:
                try:
                    url_map = self._run_async(
                        qq_song.get_song_urls([mid], file_type=qq_song.SongFileType.MP3_128, credential=self._credential)
                    )
                    url = url_map.get(mid)
                    if isinstance(url, tuple):
                        url = url[0]
                    if url:
                        return url
                except Exception as e:
                    logger.error(f"MP3_128 fallback failed for {mid}: {e}")

        # Try preview URL as last resort
        if candidates:
            try:
                # Use provided vs first; otherwise fall back to empty string
                vs_val = vs[0] if vs else ""
                url = self._run_async(qq_song.get_try_url(candidates[0], vs_val))
                if isinstance(url, dict):
                    url = next(iter(url.values()), "")
                return url or None
            except Exception as e:
                logger.error(f"Preview URL fetch failed: {e}")

        return None

    def _fetch_cover(self, client: httpx.Client, album_mid: Optional[str]) -> Optional[bytes]:
        """Fetch album cover using album mid if available."""
        if not album_mid:
            return None
        url = f"https://y.qq.com/music/photo_new/T002R300x300M000{album_mid}.jpg?max_age=2592000"
        try:
            resp = client.get(url, timeout=10)
            resp.raise_for_status()
            return resp.content
        except Exception:
            return None


qq_music_manager = QQMusicManager()
