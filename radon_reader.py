#!/usr/bin/python
""" radon_reader.py: RadonEye RD200 (Bluetooth/BLE) Reader """

__progname__ = "RadonEye RD200 (Bluetooth/BLE) Reader"
__version__ = "0.3.6"
__author__ = "Carlos Andre"
__email__ = "candrecn at hotmail dot com"
__date__ = "2019-09-13"

import argparse
import struct
import time
import re
import json
from pprint import pprint
import paho.mqtt.client as mqtt

from bluepy import btle
from bluepy.btle import Scanner, DefaultDelegate

from time import sleep
from random import randint

parser = argparse.ArgumentParser(
    formatter_class=argparse.RawDescriptionHelpFormatter,
    description=__progname__)
parser.add_argument('-s',
                    '--scan',
                    action='store_true',
                    help='Scan for bluetooth devices',
                    required=False)
parser.add_argument('-a',
                    dest='address',
                    help='Bluetooth Address (AA:BB:CC:DD:EE:FF format)',
                    required=False)
parser.add_argument('-b',
                    '--becquerel',
                    action='store_true',
                    help='Display radon value in Becquerel (Bq/m^3) unit',
                    required=False)
parser.add_argument('-v',
                    '--verbose',
                    action='store_true',
                    help='Verbose mode',
                    required=False)
parser.add_argument(
    '--silent',
    action='store_true',
    help='Only output radon value (without unit and timestamp)',
    required=False)
parser.add_argument('-m',
                    '--mqtt',
                    action='store_true',
                    help='Enable send output to MQTT server',
                    required=False)
parser.add_argument('-ms',
                    dest='mqtt_srv',
                    help='MQTT server URL or IP address',
                    required=False)
parser.add_argument('-mp',
                    dest='mqtt_port',
                    help='MQTT server service port (Default: 1883)',
                    required=False,
                    default=1883)
parser.add_argument('-mu',
                    dest='mqtt_user',
                    help='MQTT server username',
                    required=False)
parser.add_argument('-mw',
                    dest='mqtt_pw',
                    help='MQTT server password',
                    required=False)
parser.add_argument(
    '-ma',
    dest='mqtt_ha',
    action='store_true',
    help='Enable Home Assistant MQTT output (Default: EmonCMS)',
    required=False)
args = parser.parse_args()


if args.address:
    args.address = args.address.upper()

    if not re.match("^([0-9A-F]{2}:){5}[0-9A-F]{2}$", args.address) or (
            args.mqtt and
            (args.mqtt_srv == None or args.mqtt_user == None or args.mqtt_pw == None)):
        parser.print_help()
        quit()


def GetRadonValue():
    if args.verbose and not args.silent:
        print("Connecting...")
    DevBT = btle.Peripheral(args.address, btle.ADDR_TYPE_RANDOM)
    RadonEye = btle.UUID("00001523-1212-efde-1523-785feabcd123")
    if args.verbose and not args.silent:
        print("DEBUG: DevBT.getServices()")
        pprint(DevBT.getServices())
    RadonEyeService = DevBT.getServiceByUUID(RadonEye)
    if args.verbose and not args.silent:
        print("DEBUG: RadonEyeService")
        pprint(RadonEyeService)
        for c in RadonEyeService.getCharacteristics():
            pprint(c.uuid.getCommonName())
            pprint(c.read())

    # Write 0x50 to 00001524-1212-efde-1523-785feabcd123
    if args.verbose and not args.silent:
        print("Writing...")
    uuidWrite = btle.UUID("00001524-1212-efde-1523-785feabcd123")
    RadonEyeWrite = RadonEyeService.getCharacteristics(uuidWrite)[0]
    if args.verbose and not args.silent:
        print("DEBUG: RadonEyeWrite")
        pprint(RadonEyeWrite)
        pprint(RadonEyeWrite.uuid.getCommonName())
        pprint(RadonEyeWrite.read())
    RadonEyeWrite.write(bytes(80))

    # Read from 3rd to 6th byte of 00001525-1212-efde-1523-785feabcd123
    if args.verbose and not args.silent:
        print("Reading...")
    uuidRead = btle.UUID("00001525-1212-efde-1523-785feabcd123")
    RadonEyeValue = RadonEyeService.getCharacteristics(uuidRead)[0]
    if args.verbose and not args.silent:
        print("DEBUG: RadonEyeValue")
        pprint(RadonEyeValue)
    RadonValue = RadonEyeValue.read()
    if args.verbose and not args.silent:
        print("DEBUG: RadonValue")
        pprint(RadonValue)
    RadonValue = struct.unpack('<f', RadonValue[2:6])[0]

    DevBT.disconnect()

    # Raise exception (will try get Radon value from RadonEye again) if received a very high radon value.
    # Maybe a bug on RD200 or Python BLE Lib?!
    if RadonValue > 1000:
        raise Exception("Strangely high radon value. Debugging needed.")

    if args.becquerel:
        Unit = "Bq/m^3"
        RadonValue = (RadonValue * 37)
    else:
        Unit = "pCi/L"

    if args.silent:
        print("%0.2f" % (RadonValue))
    else:
        print("%s - %s - Radon Value: %0.2f %s" %
              (time.strftime("%Y-%m-%d [%H:%M:%S]"), args.address, RadonValue,
               Unit))

    if args.mqtt:
        if args.verbose and not args.silent:
            print("Sending to MQTT...")
            if args.mqtt_ha:
                mqtt_out = "Home Assistant"
            else:
                mqtt_out = "EmonCMS"
            print(
                "MQTT Server: %s | Port: %s | Username: %s | Password: %s | Output: %s"
                % (args.mqtt_srv, args.mqtt_port, args.mqtt_user, args.mqtt_pw,
                   mqtt_out))

        # REKey = Last 3 bluetooth address octets (Register/Identify multiple RadonEyes).
        # Sample: D7-21-A0
        REkey = args.address[9:].replace(":", "-")

        clientMQTT = mqtt.Client("RadonEye_%s" % randint(1000, 9999))
        clientMQTT.username_pw_set(args.mqtt_user, args.mqtt_pw)
        clientMQTT.connect(args.mqtt_srv, args.mqtt_port)

        if args.mqtt_ha:
            ha_var = json.dumps({"radonvalue": "%0.2f" % (RadonValue)})
            clientMQTT.publish("environment/RADONEYE/" + REkey, ha_var, qos=1)
        else:
            clientMQTT.publish("emon/RADONEYE/" + REkey, RadonValue, qos=1)

        if args.verbose and not args.silent:
            print("OK")
        sleep(1)
        clientMQTT.disconnect()


class ScanDelegate(DefaultDelegate):
    def __init__(self):
        DefaultDelegate.__init__(self)

    def handleDiscovery(self, dev, isNewDev, isNewData):
        if isNewDev:
            print("Discovered device", dev.addr)
        elif isNewData:
            print("Received new data from", dev.addr)


try:
    if args.scan:
        scanner = Scanner().withDelegate(ScanDelegate())
        devices = scanner.scan(10.0)

        for dev in devices:
            print("Device %s (%s), RSSI=%d dB" % (dev.addr, dev.addrType, dev.rssi) )
            for (adtype, desc, value) in dev.getScanData():
                print("  %s = %s" % (desc, value) )
        #
    else:
        GetRadonValue()
except Exception as e:
    if args.verbose and not args.silent:
        print(e)

    for i in range(1, 4):
        if args.verbose and not args.silent:
            print(f"\nAttempt #{i}")
        try:
            if args.verbose and not args.silent and i > 1:
                print("trying again (%s)..." % i)
            sleep(5)
            GetRadonValue()
        except Exception as e:
            print(f"Attemp {i} Failed with error: {e}")
            if i < 3:
                continue
        break
