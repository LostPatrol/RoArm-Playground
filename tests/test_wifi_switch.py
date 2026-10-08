"""USB switch protocol/resource tests with temporary sysfs and mocked libusb only."""
from contextlib import redirect_stdout
import ctypes as ct
import importlib.util
import io
from pathlib import Path
import struct
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, call, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("wifi_switch", ROOT / "rk3588/switch_wifi_usb.py")
wifi_switch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wifi_switch)


class FakeUsb:
    """Represent three devices; only bus 2/address 5 is the requested adapter."""

    def __init__(self, packets=None, active=1):
        self.library = Mock()
        self.addresses = {10: (2, 6), 20: (2, 5), 30: (3, 5)}
        self.devices = (ct.c_void_p * 3)(10, 20, 30)
        self.packets = list(packets if packets is not None else [(0, 18), (0, 13), (0, 13), (-7, 0)])
        lib = self.library
        lib.libusb_init.side_effect = self.initialize
        lib.libusb_get_device_list.side_effect = self.enumerate
        lib.libusb_get_bus_number.side_effect = lambda device: self.addresses[device][0]
        lib.libusb_get_device_address.side_effect = lambda device: self.addresses[device][1]
        lib.libusb_open.side_effect = self.open
        lib.libusb_kernel_driver_active.return_value = active
        lib.libusb_detach_kernel_driver.return_value = 0
        lib.libusb_claim_interface.return_value = 0
        lib.libusb_bulk_transfer.side_effect = self.bulk
        lib.libusb_release_interface.return_value = 0

    @staticmethod
    def initialize(context):
        ct.cast(context, ct.POINTER(ct.c_void_p))[0] = ct.c_void_p(100)
        return 0

    def enumerate(self, context, output):
        ct.cast(output, ct.POINTER(ct.POINTER(ct.c_void_p)))[0] = ct.cast(
            self.devices, ct.POINTER(ct.c_void_p))
        return len(self.devices)

    @staticmethod
    def open(device, output):
        ct.cast(output, ct.POINTER(ct.c_void_p))[0] = ct.c_void_p(200)
        return 0

    def bulk(self, handle, endpoint, buffer, capacity, actual, timeout):
        status, size = self.packets.pop(0)
        ct.cast(actual, ct.POINTER(ct.c_int))[0] = size
        return status


class WifiSwitchTests(unittest.TestCase):
    def managed(self, context):
        """Register context cleanup without requiring Python 3.11 TestCase.enterContext."""
        value = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        return value

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.sysfs = Path(self.temporary.name)
        self.port = "2-1.1"
        self.device = self.sysfs / self.port
        self.device.mkdir()
        for field, value in {"idVendor": "0bda", "idProduct": "1a2b",
                             "busnum": "002", "devnum": "005"}.items():
            (self.device / field).write_text(value + "\n")
        self.usb = FakeUsb()
        self.loader = self.managed(patch.object(wifi_switch.ct, "CDLL", return_value=self.usb.library))
        # Any unanticipated subprocess is intercepted, so no test can touch USB or load a module.
        self.command = self.managed(patch.object(wifi_switch.subprocess, "run"))
        self.managed(redirect_stdout(io.StringIO()))

    def assert_cleanup(self, claimed=True, opened=True, listed=True):
        lib = self.usb.library
        if claimed:
            lib.libusb_release_interface.assert_called_once()
            self.assertEqual(lib.libusb_release_interface.call_args.args[1], 0)
        else:
            lib.libusb_release_interface.assert_not_called()
        if opened:
            lib.libusb_close.assert_called_once()
        else:
            lib.libusb_close.assert_not_called()
        if listed:
            lib.libusb_free_device_list.assert_called_once()
            self.assertEqual(lib.libusb_free_device_list.call_args.args[1], 1)
        else:
            lib.libusb_free_device_list.assert_not_called()
        lib.libusb_exit.assert_called_once()
        cleanup = [c[0] for c in lib.mock_calls if c[0] in {
            "libusb_release_interface", "libusb_close", "libusb_free_device_list", "libusb_exit"}]
        expected = (["libusb_release_interface"] if claimed else [])
        expected += (["libusb_close"] if opened else [])
        expected += (["libusb_free_device_list"] if listed else []) + ["libusb_exit"]
        self.assertEqual(cleanup, expected)

    def test_invalid_port_never_opens_usb_or_sends_command(self):
        for port in ("../2-1", "2-1:1.0", "2-1;reboot", "2", "", "/2-1"):
            with self.subTest(port=port), self.assertRaises(ValueError):
                wifi_switch.switch_wifi(port, self.sysfs)
        self.loader.assert_not_called()
        self.command.assert_not_called()

    def test_other_identity_and_absent_port_are_untouched(self):
        for vendor, product in (("1bcf", "28c4"), ("05e3", "0610"), ("ffff", "1a2b"), ("0bda", "1234")):
            (self.device / "idVendor").write_text(vendor)
            (self.device / "idProduct").write_text(product)
            with self.subTest(vendor=vendor, product=product), self.assertRaises(RuntimeError):
                wifi_switch.switch_wifi(self.port, self.sysfs)
        with self.assertRaises(RuntimeError):
            wifi_switch.switch_wifi("2-1.9", self.sysfs)
        self.loader.assert_not_called()
        self.command.assert_not_called()

    def test_wireless_device_needs_no_eject(self):
        (self.device / "idProduct").write_text("c812")
        wifi_switch.switch_wifi(self.port, self.sysfs)
        self.loader.assert_not_called()
        self.command.assert_not_called()

    def test_standard_eject_cbw_and_exact_bus_address(self):
        def switched(arguments, **kwargs):
            if arguments[0] == "usb_modeswitch":
                (self.device / "idProduct").write_text("c812")
                return subprocess.CompletedProcess(arguments, 1)
            return subprocess.CompletedProcess(arguments, 0)
        self.command.side_effect = switched
        wifi_switch.switch_wifi(self.port, self.sysfs)
        command = self.command.call_args_list[0].args[0]
        self.assertEqual(command[0], "usb_modeswitch")
        self.assertNotIn("-K", command)
        self.assertEqual(command[command.index("-v") + 1], "0bda")
        self.assertEqual(command[command.index("-p") + 1], "1a2b")
        self.assertEqual(command[command.index("-b") + 1], "002")
        self.assertEqual(command[command.index("-g") + 1], "005")
        packet = bytes.fromhex(command[command.index("-M") + 1])
        # Parse the transmitted bytes independently of the source constant's spelling.
        self.assertEqual(len(packet), 31)
        signature, tag, transfer, flags, lun, command_length = struct.unpack("<4sIIBBB", packet[:15])
        self.assertEqual(signature, b"USBC")
        self.assertEqual(tag, 0x21436597)
        self.assertEqual((transfer, flags, lun, command_length), (0, 0, 0, 6))
        self.assertEqual(packet[15:21], bytes((0x1b, 0, 0, 0, 2, 0)))
        self.assertEqual(packet[21:], bytes(10))
        self.assertEqual(self.command.call_args_list[0].kwargs, {"timeout": 15})
        self.assertEqual(self.command.call_args_list[1], call(["modprobe", "rtw_8822cu"], check=True, timeout=3))
        # modeswitch returned 1, but real c812 appearance is the authoritative success.
        self.assertEqual(self.command.call_count, 2)
        self.assert_cleanup()

    def test_modeswitch_zero_without_c812_is_failure(self):
        self.command.return_value = subprocess.CompletedProcess([], 0)
        with patch.object(wifi_switch.time, "monotonic", side_effect=[0, 0, 9]), \
             patch.object(wifi_switch.time, "sleep"), self.assertRaisesRegex(RuntimeError, "did not enter wireless"):
            wifi_switch.switch_wifi(self.port, self.sysfs)
        self.assertEqual(self.command.call_count, 1)
        self.assertEqual(self.command.call_args.args[0][0], "usb_modeswitch")
        self.assert_cleanup()

    def test_drain_three_old_packets_then_empty_timeout(self):
        wifi_switch.drain_storage_replies(self.device)
        lib = self.usb.library
        self.loader.assert_called_once_with("libusb-1.0.so.0")
        self.assertEqual(lib.libusb_open.call_args.args[0], 20)
        lib.libusb_detach_kernel_driver.assert_called_once()
        lib.libusb_claim_interface.assert_called_once()
        names = [c[0] for c in lib.mock_calls]
        self.assertLess(names.index("libusb_detach_kernel_driver"), names.index("libusb_claim_interface"))
        self.assertEqual(lib.libusb_bulk_transfer.call_count, 4)
        actual_lengths = []
        for attempt in lib.libusb_bulk_transfer.call_args_list:
            handle, endpoint, buffer, capacity, actual, timeout = attempt.args
            self.assertEqual((handle.value, endpoint, capacity, timeout), (200, 0x8a, 512, 1000))
            actual_lengths.append(ct.cast(actual, ct.POINTER(ct.c_int)).contents.value)
        self.assertEqual(actual_lengths, [18, 13, 13, 0])
        self.assertEqual(self.usb.packets, [])
        self.assert_cleanup()
        self.command.assert_not_called()

    def test_no_bound_driver_still_claims_and_releases(self):
        self.usb.library.libusb_kernel_driver_active.return_value = 0
        wifi_switch.drain_storage_replies(self.device)
        self.usb.library.libusb_detach_kernel_driver.assert_not_called()
        self.usb.library.libusb_claim_interface.assert_called_once()
        self.assert_cleanup()

    def test_partial_timeout_refuses_eject_and_cleans_up(self):
        self.usb.packets = [(-7, 13)]
        with self.assertRaisesRegex(RuntimeError, "Partial packet"):
            wifi_switch.switch_wifi(self.port, self.sysfs)
        self.assert_cleanup()
        self.command.assert_not_called()

    def test_eight_unfinished_packets_refuse_eject_and_cleanup(self):
        self.usb.packets = [(0, 13)] * 8 + [(-7, 0)]
        with self.assertRaisesRegex(RuntimeError, "exceeded eight packets"):
            wifi_switch.switch_wifi(self.port, self.sysfs)
        self.assertEqual(self.usb.library.libusb_bulk_transfer.call_count, 8)
        self.assertEqual(self.usb.packets, [(-7, 0)])
        self.assert_cleanup()
        self.command.assert_not_called()

    def test_enumeration_failure_cleans_context_without_eject(self):
        self.usb.library.libusb_get_device_list.side_effect = None
        self.usb.library.libusb_get_device_list.return_value = -1
        with self.assertRaisesRegex(RuntimeError, "enumerate failed"):
            wifi_switch.switch_wifi(self.port, self.sysfs)
        self.assert_cleanup(claimed=False, opened=False, listed=False)
        self.command.assert_not_called()

    def test_wrong_bus_address_and_changed_identity_never_open_usb(self):
        for change in ("wrong_bus", "changed_vendor"):
            with self.subTest(change=change):
                self.usb = FakeUsb()
                self.loader.return_value = self.usb.library
                (self.device / "idVendor").write_text("0bda")
                if change == "wrong_bus":
                    (self.device / "busnum").write_text("004")
                else:
                    (self.device / "busnum").write_text("002")
                    enumerate_devices = self.usb.enumerate
                    def replaced(context, output):
                        result = enumerate_devices(context, output)
                        (self.device / "idVendor").write_text("ffff")
                        return result
                    self.usb.library.libusb_get_device_list.side_effect = replaced
                with self.assertRaisesRegex(RuntimeError, "Target adapter changed"):
                    wifi_switch.switch_wifi(self.port, self.sysfs)
                self.usb.library.libusb_open.assert_not_called()
                self.assert_cleanup(claimed=False, opened=False)
                self.command.assert_not_called()

    def test_usb_stage_failures_cleanup_only_acquired_resources(self):
        for stage, claimed, opened in (("open", False, False), ("kernel_driver_active", False, True),
                                       ("detach_kernel_driver", False, True), ("claim_interface", False, True),
                                       ("bulk_transfer", True, True)):
            with self.subTest(stage=stage):
                self.usb = FakeUsb()
                self.loader.return_value = self.usb.library
                failed = getattr(self.usb.library, "libusb_" + stage)
                failed.side_effect = None
                failed.return_value = -8
                with self.assertRaisesRegex(RuntimeError, "libusb -8"):
                    wifi_switch.switch_wifi(self.port, self.sysfs)
                self.assert_cleanup(claimed=claimed, opened=opened)
                self.command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
