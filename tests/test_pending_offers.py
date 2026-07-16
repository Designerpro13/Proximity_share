"""
Tests for the manual file accept/reject mechanism (Task 5).

Tests the pending offers logic in TransferProtocol without requiring
a full network setup — validates the accept/reject/timeout behavior.
"""

import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src to path for bare module imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# Mock kivy before importing our modules
sys.modules["kivy"] = MagicMock()
sys.modules["kivy.app"] = MagicMock()
sys.modules["kivy.clock"] = MagicMock()
sys.modules["kivy.logger"] = MagicMock()
sys.modules["kivy.uix"] = MagicMock()
sys.modules["kivy.uix.boxlayout"] = MagicMock()
sys.modules["kivy.uix.button"] = MagicMock()
sys.modules["kivy.uix.label"] = MagicMock()
sys.modules["kivy.uix.scrollview"] = MagicMock()
sys.modules["kivy.uix.gridlayout"] = MagicMock()

# Mock plyer
sys.modules["plyer"] = MagicMock()

# Mock security module
sys.modules["security"] = MagicMock()
sys.modules["security.encryption"] = MagicMock()

# Mock transfer.container
sys.modules["transfer"] = MagicMock()
sys.modules["transfer.container"] = MagicMock()

from unittest.mock import patch

import pytest


class TestPendingOffers:
    """Tests for TransferProtocol pending offer management."""

    def _make_protocol(self):
        """Create a TransferProtocol with mocked Config."""
        with patch("utils.config.Config") as MockConfig:
            mock_config = MockConfig.return_value
            mock_config.get_port.return_value = 8888
            mock_config.get_device_name.return_value = "test-device"
            mock_config.get_shared_secret.return_value = ""
            mock_config.is_auto_accept_enabled.return_value = False
            mock_config.get_shared_folder.return_value = "/tmp"
            mock_config.get_connection_timeout.return_value = 10

            # Import here after mocks are set up
            from transfer.protocol import TransferProtocol
            protocol = TransferProtocol(mock_config)
            return protocol

    def test_accept_offer_sets_accepted_and_event(self):
        """accept_offer sets accepted=True and triggers the event."""
        protocol = self._make_protocol()

        event = threading.Event()
        protocol._pending_offers["test-id"] = {
            "event": event,
            "accepted": False,
            "filename": "test.txt",
            "size": 1024,
        }

        protocol.accept_offer("test-id")

        assert protocol._pending_offers["test-id"]["accepted"] is True
        assert event.is_set()

    def test_reject_offer_sets_rejected_and_event(self):
        """reject_offer sets accepted=False and triggers the event."""
        protocol = self._make_protocol()

        event = threading.Event()
        protocol._pending_offers["test-id"] = {
            "event": event,
            "accepted": False,
            "filename": "test.txt",
            "size": 1024,
        }

        protocol.reject_offer("test-id")

        assert protocol._pending_offers["test-id"]["accepted"] is False
        assert event.is_set()

    def test_accept_offer_nonexistent_id_does_nothing(self):
        """accept_offer with unknown ID doesn't raise."""
        protocol = self._make_protocol()
        protocol.accept_offer("nonexistent-id")  # Should not raise

    def test_reject_offer_nonexistent_id_does_nothing(self):
        """reject_offer with unknown ID doesn't raise."""
        protocol = self._make_protocol()
        protocol.reject_offer("nonexistent-id")  # Should not raise

    def test_on_file_offer_callback_is_initialized_none(self):
        """on_file_offer callback starts as None."""
        protocol = self._make_protocol()
        assert protocol.on_file_offer is None

    def test_pending_offers_dict_initialized_empty(self):
        """_pending_offers starts as empty dict."""
        protocol = self._make_protocol()
        assert protocol._pending_offers == {}

    def test_accept_offer_event_wakes_waiting_thread(self):
        """Simulates the _handle_client wait pattern — accept wakes the thread."""
        protocol = self._make_protocol()

        event = threading.Event()
        protocol._pending_offers["offer-abc"] = {
            "event": event,
            "accepted": False,
            "filename": "photo.jpg",
            "size": 2048,
        }

        result = {"decided": False, "accepted": False}

        def waiter():
            decided = event.wait(timeout=5.0)
            result["decided"] = decided
            result["accepted"] = protocol._pending_offers.get("offer-abc", {}).get("accepted", False)

        t = threading.Thread(target=waiter)
        t.start()

        time.sleep(0.1)  # Let waiter start blocking
        protocol.accept_offer("offer-abc")
        t.join(timeout=2.0)

        assert result["decided"] is True
        assert result["accepted"] is True

    def test_reject_offer_event_wakes_waiting_thread(self):
        """Simulates the _handle_client wait pattern — reject wakes the thread."""
        protocol = self._make_protocol()

        event = threading.Event()
        protocol._pending_offers["offer-xyz"] = {
            "event": event,
            "accepted": False,
            "filename": "doc.pdf",
            "size": 4096,
        }

        result = {"decided": False, "accepted": False}

        def waiter():
            decided = event.wait(timeout=5.0)
            result["decided"] = decided
            result["accepted"] = protocol._pending_offers.get("offer-xyz", {}).get("accepted", False)

        t = threading.Thread(target=waiter)
        t.start()

        time.sleep(0.1)
        protocol.reject_offer("offer-xyz")
        t.join(timeout=2.0)

        assert result["decided"] is True
        assert result["accepted"] is False


class TestTransferManagerPassthrough:
    """Tests that TransferManager correctly passes through offer methods."""

    def test_accept_offer_calls_protocol(self):
        """TransferManager.accept_offer delegates to protocol."""
        with patch("utils.config.Config") as MockConfig:
            mock_config = MockConfig.return_value
            mock_config.get_port.return_value = 8888
            mock_config.get_device_name.return_value = "test"
            mock_config.get_shared_secret.return_value = ""
            mock_config.is_auto_accept_enabled.return_value = False
            mock_config.get_shared_folder.return_value = "/tmp"
            mock_config.get_connection_timeout.return_value = 10
            mock_config.get_retry_base_delay.return_value = 30
            mock_config.get_max_retry_delay.return_value = 1800
            mock_config.get_max_retries.return_value = 10

            from transfer.manager import TransferManager
            manager = TransferManager(mock_config)
            manager._protocol.accept_offer = MagicMock()

            manager.accept_offer("offer-123")
            manager._protocol.accept_offer.assert_called_once_with("offer-123")

    def test_reject_offer_calls_protocol(self):
        """TransferManager.reject_offer delegates to protocol."""
        with patch("utils.config.Config") as MockConfig:
            mock_config = MockConfig.return_value
            mock_config.get_port.return_value = 8888
            mock_config.get_device_name.return_value = "test"
            mock_config.get_shared_secret.return_value = ""
            mock_config.is_auto_accept_enabled.return_value = False
            mock_config.get_shared_folder.return_value = "/tmp"
            mock_config.get_connection_timeout.return_value = 10
            mock_config.get_retry_base_delay.return_value = 30
            mock_config.get_max_retry_delay.return_value = 1800
            mock_config.get_max_retries.return_value = 10

            from transfer.manager import TransferManager
            manager = TransferManager(mock_config)
            manager._protocol.reject_offer = MagicMock()

            manager.reject_offer("offer-456")
            manager._protocol.reject_offer.assert_called_once_with("offer-456")
