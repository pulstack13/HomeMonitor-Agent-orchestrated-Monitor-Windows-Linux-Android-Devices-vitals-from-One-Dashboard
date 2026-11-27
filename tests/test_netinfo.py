from __future__ import annotations

import unittest
from unittest.mock import patch

from common.netinfo import (
    _windows,
    parse_default_route,
    parse_ip_addr,
    parse_ipconfig,
    parse_netsh,
    parse_nmcli,
    parse_proc_route,
    parse_wireless,
)

IP_ADDR = """\
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    inet 127.0.0.1/8 scope host lo
2: wlan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP group default qlen 1000
    inet 192.0.2.34/24 brd 192.0.2.255 scope global wlan0
"""

IP_ROUTE_ALL = """\
default via 192.0.2.1 dev wlan0  table wlan0  proto static
192.0.2.0/24 dev wlan0  table wlan0  proto static  scope link
default dev dummy0  table dummy0  proto static  scope link
"""

WIRELESS = """\
Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE
 face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22
 wlan0: 0000   14.  -50.  -64.       0      0      0      0      0        0
"""

NETSH = """\

Interface name : Wi-Fi
There are 1 interfaces on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6E AX211 160MHz
    State                  : connected
    SSID                   : Home Network
    BSSID                  : 00:11:22:33:44:55
    Signal                 : 87%
    Receive rate (Mbps)    : 144.4
    Transmit rate (Mbps)   : 144.4
"""

NETSH_DISCONNECTED = """\

There is 1 interface on the system:

    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6E AX211 160MHz
    State                  : disconnected
    SSID                   : Stale Network
    Signal                 : 84%
    Receive rate (Mbps)    : 650
"""

IPCONFIG = """\

Wireless LAN adapter Local Area Connection* 1:

   Media State . . . . . . . . . . . : Media disconnected

Wireless LAN adapter Wi-Fi:

   Default Gateway . . . . . . . . . : fe80::1%12
                                       192.0.2.1
   IPv4 Address. . . . . . . . . . . : 192.0.2.50(Preferred)
   DNS Servers . . . . . . . . . . . : 192.0.2.1
                                       1.1.1.1
"""

IPCONFIG_TETHER = """\

Ethernet adapter Ethernet 4:

   Description . . . . . . . . . . . : Apple Mobile Device Ethernet
   IPv4 Address. . . . . . . . . . . : 172.20.10.3(Preferred)
   Subnet Mask . . . . . . . . . . . : 255.255.255.240
   Default Gateway . . . . . . . . . : fe80::1%23
                                       172.20.10.1
   DNS Servers . . . . . . . . . . . : 172.20.10.1

Wireless LAN adapter Wi-Fi:

   Media State . . . . . . . . . . . : Media disconnected
"""

PROC_ROUTE = """\
Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
wlan0\t00000000\t010200C0\t0003\t0\t0\t0\t00000000\t0\t0\t0
"""


class NetInfoTests(unittest.TestCase):
    def test_parse_ip_addr_prefers_interface(self) -> None:
        self.assertEqual(parse_ip_addr(IP_ADDR, "wlan0"), ("wlan0", "192.0.2.34"))
        self.assertEqual(parse_ip_addr(IP_ADDR), ("wlan0", "192.0.2.34"))

    def test_default_route_from_android_policy_table(self) -> None:
        self.assertEqual(parse_default_route(IP_ROUTE_ALL), ("192.0.2.1", "wlan0"))

    def test_wireless_quality_and_rssi_modes(self) -> None:
        self.assertAlmostEqual(parse_wireless(WIRELESS, "wlan0") or 0, 20.0)
        self.assertAlmostEqual(
            parse_wireless(WIRELESS, "wlan0", prefer_level=True) or 0, 100.0
        )

    def test_netsh_parser(self) -> None:
        data = parse_netsh(NETSH)
        self.assertEqual(data["interface"], "Wi-Fi")
        self.assertEqual(data["state"], "connected")
        self.assertEqual(data["ssid"], "Home Network")
        self.assertEqual(data["signal_pct"], 87.0)
        self.assertEqual(data["link_mbps"], 144.4)

    def test_netsh_disconnected_drops_stale_wifi_details(self) -> None:
        data = parse_netsh(NETSH_DISCONNECTED)
        self.assertEqual(data["interface"], "Wi-Fi")
        self.assertEqual(data["state"], "disconnected")
        self.assertNotIn("ssid", data)
        self.assertNotIn("signal_pct", data)
        self.assertNotIn("link_mbps", data)

    def test_ipconfig_parser_keeps_continuation_lines(self) -> None:
        data = parse_ipconfig(IPCONFIG, "Wi-Fi")
        self.assertEqual(data["interface"], "Wi-Fi")
        self.assertEqual(data["ip"], "192.0.2.50")
        self.assertEqual(data["gateway"], "192.0.2.1")
        self.assertEqual(data["dns"], "192.0.2.1")

    def test_ipconfig_uses_active_adapter_when_wifi_disconnected(self) -> None:
        data = parse_ipconfig(IPCONFIG_TETHER, "Wi-Fi")
        self.assertEqual(data["interface"], "Ethernet 4")
        self.assertEqual(data["ip"], "172.20.10.3")
        self.assertEqual(data["gateway"], "172.20.10.1")
        self.assertEqual(data["dns"], "172.20.10.1")

    def test_windows_tether_does_not_merge_disconnected_wifi(self) -> None:
        def fake_run(args, timeout=3.0):  # noqa: ARG001
            if args[:2] == ["netsh", "wlan"]:
                return NETSH_DISCONNECTED
            if args[0] == "ipconfig":
                return IPCONFIG_TETHER
            return ""

        with patch("common.netinfo._run", side_effect=fake_run):
            data = _windows()
        self.assertEqual(data["interface"], "Ethernet 4")
        self.assertEqual(data["ip"], "172.20.10.3")
        self.assertEqual(data["gateway"], "172.20.10.1")
        self.assertNotIn("ssid", data)
        self.assertNotIn("signal_pct", data)
        self.assertNotIn("link_mbps", data)

    def test_windows_connected_wifi_still_reports_ssid(self) -> None:
        def fake_run(args, timeout=3.0):  # noqa: ARG001
            if args[:2] == ["netsh", "wlan"]:
                return NETSH
            if args[0] == "ipconfig":
                return IPCONFIG
            return ""

        with patch("common.netinfo._run", side_effect=fake_run):
            data = _windows()
        self.assertEqual(data["interface"], "Wi-Fi")
        self.assertEqual(data["ssid"], "Home Network")
        self.assertEqual(data["signal_pct"], 87.0)

    def test_nmcli_parser(self) -> None:
        data = parse_nmcli("yes:Home Network:81\nno:Other:20\n")
        self.assertEqual(data["ssid"], "Home Network")
        self.assertEqual(data["signal_pct"], 81.0)

    def test_proc_route_parser(self) -> None:
        self.assertEqual(parse_proc_route(PROC_ROUTE), ("192.0.2.1", "wlan0"))


if __name__ == "__main__":
    unittest.main()
