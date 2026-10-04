"""Setting up the integration must never modify the Home Assistant
installation it runs in. It is installed on people's own instances, where
deleting `cloud` breaks `default_config` and replacing `frontend` leaves the
owner without a UI (see the module docstring in custom_components/willo).

Watches every rmtree and file write during a real async_setup_entry and fails
if any of them touches the installed `homeassistant` package.
"""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.willo.const import CONF_HOME_ID, CONF_SECRET, DOMAIN


def _ha_package_roots() -> list[Path]:
    spec = importlib.util.find_spec("homeassistant")
    assert spec is not None and spec.submodule_search_locations
    return [Path(root).resolve() for root in spec.submodule_search_locations]


def _inside_ha_package(path: object) -> bool:
    resolved = Path(str(path)).resolve()
    return any(resolved.is_relative_to(root) for root in _ha_package_roots())


async def test_setup_never_deletes_or_writes_inside_the_ha_package(hass: HomeAssistant) -> None:
    touched: list[str] = []
    real_rmtree = shutil.rmtree
    real_write_text = Path.write_text

    def watching_rmtree(path, *args, **kwargs):
        if _inside_ha_package(path):
            touched.append(f"rmtree {path}")
            return None
        return real_rmtree(path, *args, **kwargs)

    def watching_write_text(self, *args, **kwargs):
        if _inside_ha_package(self):
            touched.append(f"write_text {self}")
            return 0
        return real_write_text(self, *args, **kwargs)

    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOME_ID: "home-1", CONF_SECRET: "s3cret"})
    entry.add_to_hass(hass)
    with (
        patch("shutil.rmtree", new=watching_rmtree),
        patch.object(Path, "write_text", new=watching_write_text),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert touched == []
