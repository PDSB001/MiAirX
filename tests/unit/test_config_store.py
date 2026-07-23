"""Unit tests for configuration store"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from miairx.config.models import AppConfig
from miairx.config.store import ConfigStore


@pytest.fixture
def temp_dir():
    """Create temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def config_store(temp_dir):
    """Create config store with temporary directory."""
    return ConfigStore(conf_path=temp_dir)


def test_load_nonexistent(config_store):
    """Test loading from non-existent file."""
    config = config_store.load()
    
    assert config.account == ""
    assert config.dlna_port == 8200


def test_save_and_load(config_store, temp_dir):
    """Test saving and loading configuration."""
    config = AppConfig(
        account="test_user",
        password="test_pass",
        dlna_port=9000,
    )
    
    config_store.save_sync(config)
    
    # Verify file exists
    config_file = Path(temp_dir) / "config.json"
    assert config_file.exists()
    
    # Load and verify
    loaded = config_store.load()
    assert loaded.account == "test_user"
    assert loaded.password == "test_pass"
    assert loaded.dlna_port == 9000


def test_save_atomic(config_store, temp_dir):
    """Test atomic save (no corruption on failure)."""
    config = AppConfig(account="test_user")
    
    # Save once
    config_store.save_sync(config)
    
    # Verify no temp file remains
    config_file = Path(temp_dir) / "config.json"
    tmp_file = Path(temp_dir) / "config.tmp"
    assert config_file.exists()
    assert not tmp_file.exists()


def test_load_with_speakers(config_store, temp_dir):
    """Test loading configuration with speakers."""
    config_data = {
        "account": "test_user",
        "speakers": {
            "123": {
                "did": "123",
                "name": "Speaker 1",
                "enabled": True,
            },
            "456": {
                "did": "456",
                "name": "Speaker 2",
                "enabled": False,
            },
        },
    }
    
    config_file = Path(temp_dir) / "config.json"
    with open(config_file, "w") as f:
        json.dump(config_data, f)
    
    loaded = config_store.load()
    
    assert "123" in loaded.speakers
    assert "456" in loaded.speakers
    assert loaded.speakers["123"].name == "Speaker 1"
    assert loaded.speakers["456"].enabled is False
