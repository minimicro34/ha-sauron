"""Config flow and options flow for the SAURon integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import SauronApiClient, SauronApiError, SauronAuthError, SauronNoDataError
from .const import (
    CONF_CLIENT_ID,
    CONF_LOGIN,
    CONF_PASSWORD,
    CONF_SUBSCRIPTION_ID,
    DEFAULT_SCAN_INTERVAL_H,
    DEFAULT_STALE_DATA_THRESHOLD_H,
    DOMAIN,
    OPT_SCAN_INTERVAL_H,
    OPT_SCAN_INTERVAL_H_MAX,
    OPT_SCAN_INTERVAL_H_MIN,
    OPT_STALE_DATA_THRESHOLD_H,
    OPT_STALE_DATA_THRESHOLD_H_MAX,
    OPT_STALE_DATA_THRESHOLD_H_MIN,
)

if TYPE_CHECKING:
    import aiohttp
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

_STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_LOGIN): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


async def _probe_saur(session: aiohttp.ClientSession, login: str, password: str) -> tuple[str, str]:
    """Authenticate and discover (client_id, section_subscription_id)."""
    client = SauronApiClient(session, login, password)
    await client.async_authenticate()

    client_id = client.client_id or ""
    if not client_id:
        raise SauronApiError(0, "clientId missing from auth response")

    subscription_id = client.default_section_id or ""
    if subscription_id:
        _LOGGER.debug("SAURon: using defaultSectionId=%s from auth", subscription_id)
        return client_id, subscription_id

    _LOGGER.debug("SAURon: defaultSectionId absent, fetching website_areas")
    try:
        areas = await client.async_get_website_areas(client_id)
    except (SauronApiError, SauronNoDataError) as err:
        raise SauronApiError(0, f"Could not discover subscriptions: {err}") from err

    # Response nesting: clients -> customerAccounts -> sectionSubscriptions.
    for cli in areas.get("clients", []):
        for account in cli.get("customerAccounts", []):
            for sub in account.get("sectionSubscriptions", []):
                sid = str(sub.get("sectionSubscriptionId", ""))
                if sid:
                    _LOGGER.debug("SAURon: found sectionSubscriptionId=%s", sid)
                    return client_id, sid

    raise SauronApiError(0, "No sectionSubscriptionId found in website_areas response")


class SauronConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup flow for SAURon."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            login = user_input[CONF_LOGIN]
            password = user_input[CONF_PASSWORD]
            session = async_get_clientsession(self.hass)

            try:
                client_id, subscription_id = await _probe_saur(session, login, password)
            except SauronAuthError:
                errors["base"] = "invalid_auth"
            except SauronApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during SAUR probe")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(subscription_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"SAURon ({subscription_id})",
                    data={
                        CONF_LOGIN: login,
                        CONF_PASSWORD: password,
                        CONF_CLIENT_ID: client_id,
                        CONF_SUBSCRIPTION_ID: subscription_id,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Handle re-authentication when credentials become invalid."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            login = user_input[CONF_LOGIN]
            password = user_input[CONF_PASSWORD]
            session = async_get_clientsession(self.hass)

            try:
                client_id, subscription_id = await _probe_saur(session, login, password)
            except SauronAuthError:
                errors["base"] = "invalid_auth"
            except SauronApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during SAUR re-auth probe")
                errors["base"] = "unknown"
            else:
                if subscription_id != entry.data.get(CONF_SUBSCRIPTION_ID):
                    errors["base"] = "wrong_account"
                else:
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates={
                            CONF_LOGIN: login,
                            CONF_PASSWORD: password,
                            CONF_CLIENT_ID: client_id,
                        },
                    )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_STEP_USER_SCHEMA,
            errors=errors,
            description_placeholders={"subscription_id": entry.data.get(CONF_SUBSCRIPTION_ID, "")},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SauronOptionsFlow()


class SauronOptionsFlow(OptionsFlow):
    """Options flow for SAURon — polling interval and alert thresholds."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    OPT_SCAN_INTERVAL_H,
                    default=options.get(OPT_SCAN_INTERVAL_H, DEFAULT_SCAN_INTERVAL_H),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=OPT_SCAN_INTERVAL_H_MIN, max=OPT_SCAN_INTERVAL_H_MAX),
                ),
                vol.Optional(
                    OPT_STALE_DATA_THRESHOLD_H,
                    default=options.get(OPT_STALE_DATA_THRESHOLD_H, DEFAULT_STALE_DATA_THRESHOLD_H),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(
                        min=OPT_STALE_DATA_THRESHOLD_H_MIN,
                        max=OPT_STALE_DATA_THRESHOLD_H_MAX,
                    ),
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
