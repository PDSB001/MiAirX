"""Xiaomi account authentication manager for MiAirX"""

import logging
import os
import re

import aiohttp
from miservice import MiAccount, MiIOService, MiNAService

from miairx.auth.cookie import mask_cookie_value, parse_cookie_string, validate_cookie_data
from miairx.auth.errors import CaptchaRequiredError, LoginError, TokenExpiredError
from miairx.config.models import AppConfig

log = logging.getLogger(__name__)


class AuthManager:
    """Manages Xiaomi account authentication and device services."""

    def __init__(self, config: AppConfig, session: aiohttp.ClientSession):
        self.config = config
        self.session = session
        self.account: MiAccount | None = None
        self.mina_service: MiNAService | None = None
        self.miio_service: MiIOService | None = None
        self._logged_in = False

    async def login(self) -> None:
        """Login to Xiaomi account and initialize services."""
        # Check if account is configured
        if not self.config.account and not self.config.cookie:
            log.warning("No Xiaomi account configured. Please configure account in Web UI or config file.")
            log.warning(f"Config file: {self.config.conf_path}/config.json")
            log.warning(f"Web UI: http://{self.config.hostname}:{self.config.web_port}")
            self._logged_in = False
            return
        
        os.makedirs(self.config.conf_path, exist_ok=True)

        token_store = self.config.mi_token_home

        # Parse cookie if provided
        token_data = {}
        if self.config.cookie:
            token_data = parse_cookie_string(self.config.cookie)

        # Create MiAccount
        if token_data.get("userId") and token_data.get("passToken"):
            # Cookie-based login
            self.account = MiAccount(
                self.session,
                "",  # Empty account
                "",  # Empty password
                token_store=token_store,
            )
            # Set token with all required fields
            self.account.token = {
                "userId": token_data["userId"],
                "passToken": token_data["passToken"],
                "deviceId": "miair_device",
                "ssecurity": "",
                "serviceToken": "",
            }
            log.info(f"Using cookie login for user {mask_cookie_value(token_data['userId'])}")
        else:
            # Account/password login
            self.account = MiAccount(
                self.session,
                self.config.account,
                self.config.password,
                token_store=token_store,
            )
            # Ensure token is not None
            if not hasattr(self.account, 'token') or self.account.token is None:
                self.account.token = {"deviceId": "miair_device"}

        # Perform login
        if token_data.get("userId") and token_data.get("passToken"):
            # Cookie login - skip actual login call
            self._logged_in = True
            log.info("Cookie login successful")
        else:
            try:
                await self.account.login("micoapi")
                self._logged_in = True
                log.info("Xiaomi account login successful")
            except Exception as e:
                self._logged_in = False
                # Ensure token is not None
                if not hasattr(self.account, 'token') or self.account.token is None:
                    self.account.token = {"deviceId": "miair_device"}
                
                err_msg = str(e)
                err_code = self._extract_error_code(err_msg)
                
                if err_code == "87001" or "captcha" in err_msg.lower():
                    log.error(
                        "Login requires captcha! Visit https://account.xiaomi.com to verify, "
                        "or use cookie-based login"
                    )
                elif err_code == "70016":
                    log.error(
                        "Login verification failed! Possible causes: wrong password, "
                        "2FA enabled, or human verification needed at https://www.mi.com. "
                        "Please configure account in Web UI or use cookie login."
                    )
                elif "userId" in err_msg:
                    log.error(
                        "Login failed (missing userId)! Account may need additional verification. "
                        "Try: 1) Login at https://account.xiaomi.com, 2) Use cookie login, "
                        "3) Disable proxy/VPN"
                    )
                else:
                    log.error(f"Login failed: {e}")
                
                log.warning("Service will continue without Xiaomi account. Configure account in Web UI.")
                return

        # Initialize services
        self.mina_service = MiNAService(self.account)
        self.miio_service = MiIOService(self.account)

    async def ensure_login(self) -> None:
        """Ensure we're logged in, login if needed."""
        if self.mina_service is None or not self._logged_in:
            await self.login()

    def invalidate_session(self) -> None:
        """Invalidate current session (for retry logic)."""
        self._logged_in = False
        log.info("Session invalidated, will re-login on next request")

    @staticmethod
    def _extract_error_code(err_msg: str) -> str:
        """Extract numeric error code from exception message."""
        m = re.search(r'\b(\d{4,6})\b', err_msg)
        return m.group(1) if m else ""

    async def get_device_list(self) -> list[dict]:
        """Get all devices under the account."""
        await self.ensure_login()
        if not self._logged_in:
            log.warning("Not logged in, cannot get device list")
            return []
        
        try:
            devices = await self.mina_service.device_list()
            return devices or []
        except Exception as e:
            log.warning(f"Failed to get device list: {e}")
            # Token might be expired
            if self.config.cookie:
                log.error(f"Cookie may be expired, please refresh: {e}")
                return []
            
            # Try to re-login
            self.invalidate_session()
            await self.login()
            if not self._logged_in:
                return []
            
            try:
                devices = await self.mina_service.device_list()
                return devices or []
            except Exception as e2:
                log.error(f"Still failed after re-login: {e2}")
                return []

    async def update_speakers_info(self) -> None:
        """Update speaker configuration with device info from cloud."""
        devices = await self.get_device_list()
        did_list = self.config.get_did_list()

        for device in devices:
            miot_did = device.get("miotDID", "")
            if miot_did in did_list:
                speaker = self.config.get_speaker(miot_did)
                speaker.device_id = device.get("deviceID", "")
                speaker.hardware = device.get("hardware", "")
                if not speaker.name:
                    speaker.name = device.get("name", "")
                speaker.ensure_udn()
                log.info(
                    f"Updated device info: {speaker.name} "
                    f"(did={miot_did}, device_id={speaker.device_id}, "
                    f"hardware={speaker.hardware})"
                )

    def is_logged_in(self) -> bool:
        """Check if we're logged in."""
        return self._logged_in

    async def close(self) -> None:
        """Close the authentication manager."""
        # Note: We don't close the session here as it's shared
        self.account = None
        self.mina_service = None
        self.miio_service = None
        self._logged_in = False
