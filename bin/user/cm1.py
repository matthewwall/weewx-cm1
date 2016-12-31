#!/usr/bin/env python
# Copyright 2016 Matthew Wall, all rights reserved

"""Driver for collecting data from Dyacon weather station using the CM1
weather tation control module.

Thanks to Eugene at Dyacon for full support in the development of this driver.

This implementation uses the Modbus-RTU interface described in the Dyacon
reference 57-6032-DOC-Manual-CM-1.pdf (2014).

This driver requires the minimalmodbus python module, which in turn depends on
the pyserial (pure python) module.

pip install minimalmodbus

The CM1 has two communication interfaces: a USB port for configuration, and
a RS-485 slave for reading data (Modbus-RTU over RS-485).

The CM1 has a data logger with capacity of 49,152 records, with logging
intervals of 1, 2, 5, 10, 15, 20, 30, and 60 minutes.
"""

import calendar
import minimalmodbus
import syslog
import time

import weewx
import weewx.drivers


DRIVER_NAME = 'CM1'
DRIVER_VERSION = '0.1'


def logmsg(dst, msg):
    syslog.syslog(dst, 'CM1: %s' % msg)

def logdbg(msg):
    logmsg(syslog.LOG_DEBUG, msg)

def loginf(msg):
    logmsg(syslog.LOG_INFO, msg)

def logcrt(msg):
    logmsg(syslog.LOG_CRIT, msg)

def logerr(msg):
    logmsg(syslog.LOG_ERR, msg)


def loader(config_dict, engine):
    return CM1(**config_dict[DRIVER_NAME])

def confeditor_loader():
    return CM1ConfEditor()


class CM1ConfEditor(weewx.drivers.AbstractConfEditor):
    @property
    def default_stanza(self):
        return """
[CM1]
    # This section is for the Dyacon MS-1xx weather stations.

    # Which model of weather station is this
    model = MS-120

    # RS485 (modbus) serial port
    port = /dev/ttyUSB0

    # How often to poll the device, in seconds
    poll_interval = 10

    # The driver to use
    driver = user.cm1
"""


class CM1Driver(weewx.drivers.AbstractDevice):
    # mapping from hardware names to database schema names
    DEFAULT_MAP = {
        'outTemp': 'temperature_outside',
        'inTemp': 'temperature_inside',
        'outHumidity': 'humidity',
        'pressure': 'pressure',
        'windSpeed': 'wind_speed',
        'windDir': 'wind_dir',
        'windGust': 'gust_speed',
        'windGustDir': 'gust_dir',
        'rain': 'precipitation',
        'radiation': 'solar_radiation'}

    def __init__(self, **stn_dict):
        self.model = stn_dict.get('model', 'MS-120')
        loginf("model is %s" % self.model)
        port = stn_dict.get('port', CM1Station.DEFAULT_PORT)
        loginf("port is %s" % port)
        address = int(stn_dict.get('address', CM1Station.DEFAULT_ADDRESS))
        loginf("address is %s" % address)
        baud_rate = int(stn_dict.get('baud_rate', CM1Station.DEFAULT_BAUD))
        loginf("baud_rate is %s" % baud_rate)
        self.poll_interval = int(stn_dict.get('poll_interval', 10))
        loginf("poll interval is %s" % self.poll_interval)
        self.sensor_map = stn_dict.get('sensor_map', CM1Driver.DEFAULT_MAP)
        self.max_tries = int(stn_dict.get('max_tries', 3))
        self.retry_wait = int(stn_dict.get('retry_wait', 5))
        self.station = CM1Station(port, address, baud_rate)
        params = self.station.get_system_parameters()
        for x in CM1Station.SYSTEM_PARAMETERS:
            loginf("%s: %s" % (x, params[x]))

    @property
    def hardware_name(self):
        return self.model

    def openPort(self):
        pass

    def closePort(self):
        self.station = None

    def genLoopPackets(self):
        ntries = 0
        while ntries < self.max_tries:
            ntries += 1
            try:
                data = self.station.get_current()
                logdbg("raw data: %s" % data)
                ntries = 0
                packet = dict()
                packet['dateTime'] = int(time.time() + 0.5)
                packet['usUnits'] = weewx.METRICWX
                for k in self.sensor_map:
                    if self.sensor_map[k] in pkt:
                        packet[k] = pkt[self.sensor_map[k]]
                yield packet
                if self.poll_interval:
                    time.sleep(self.poll_interval)
            except (IOError, ValueError), e:
                loginf("failed attempt %s of %s: %s" %
                       (ntries, self.max_tries, e))
                time.sleep(self.retry_wait)
        else:
            raise WeeWxIOError("max tries %s exceeded" % self.max_tries)


class CM1Station(minimalmodbus.Instrument):
    DEFAULT_PORT = '/dev/ttyUSB0'
    DEFAULT_ADDRESS = 1
    DEFAULT_BAUD_RATE = 19200

    SYSTEM_PARAMETERS = [
        'product_id', 'firmware_version', 'serial_number', 'epoch',
        'battery_voltage', 'solar_charge_voltage', 'charger_status']

    SENSORS = {
        'wind_status': ('register', 200), # -1 to 15; -1=none
        'wind_speed': ('register', 201, 0.1), # 0-500 m/s
        'wind_dir': ('register', 202, 0.1), # 0-3599
        'wind_speed_2min': ('register', 203, 0.1), # 0-500 m/s
        'wind_dir_2min': ('register', 204, 0.1), # 0-3599
        'wind_speed_10min': ('register', 205, 0.1), # 0-500 m/s
        'wind_dir_10min': ('register', 206, 0.1), # 0-3599
        'wind_gust_speed': ('register', 207, 0.1), # 0-500 m/s
        'wind_gust_dir': ('register', 208, 0.1), # 0-3599
        'tph_status': ('register', 220), # -1 to 3; -1=none
        'temperature': ('register', 221, 0.1), # -400-1250 C
        'humidity': ('register', 222, 0.1), # %
        'pressure': ('register', 223, 0.1), # mbar
        'pressure_trend': ('register', 224), # -2, -1, 0, 1, 2
        # why is there a second temperature at 225?
        'rain_day_total': ('register', 242), # daily count
        'rain_rate': ('register', 243, 0.1), # -400-1250 count/hour
        }

    CHARGER_STATUS = {
        0: 'Off',
        1: 'Fast', # current-limited
        2: 'Fast Top', # voltage-limited
        3: 'Float Charge' } # low voltage charge

    def __init__(self, port, address, baud_rate):
        minimalmodbus.BAUDRATE = baud_rate
        minimalmodbus.Instrument.__init__(self, port, address)

    def __enter__(self):
        return self

    def __exit__(self, _, value, traceback):
        pass

    def get_system_parameters(self):
        data = dict()
        for x in self.SYSTEM_PARAMETERS:
            data[x] = self.get_parameter(x)
        return data

    def get_current(self):
        data = dict()
        for x in self.SENSORS:
            func = self.SENSORS[x][0]
            reg = self.SENSORS[x][1]
            mult = self.SENSORS[x][2] if len(self.SENSORS[x]) > 2 else 1.0
            try:
                data[x] = self.get_sensor(x, func, reg, mult)
            except IOError, e:
                logerr("sensor %s fail: %s" % (x, e))
        if data.get('wind_status') == -1:
            data['wind_speed'] = None
        if data.get('tph_status') == -1:
            data['temperature'] = None
        return data

    def get_sensor(self, label, func, reg, mult):
        v = getattr(self, 'read_%s' % func)(reg) * mult
        logdbg("%s: %s" % (label, v))
        return v

    def get_parameter(self, label):
        v = getattr(self, 'get_%s' % label)()
        logdbg("%s: %s" % (label, v))
        return v

    def get_product_id(self):
        # 16-bits
        # 0x03YY
        return self.read_register(100, signed=True)

    def get_firmware_version(self):
        # 16-bits
        return self.read_register(101, signed=False)

    def get_serial_number(self):
        # 32-bits
        return self.read_long(102, signed=False)

    def get_time(self):
        # 32-bits
        # HHMMSS - bcd encoded
        return "%06d" % self.read_long(104, signed=False)

    def get_date(self):
        # 32-bits
        # YYMMDD - bcd encoded
        return "%06d" % self.read_long(106, signed=False)

    def get_epoch(self):
        # station is gmtime
        ds = self.get_date()
        logdbg("date: %s" % ds)
        ts = self.get_time()
        logdbg("time: %s" % ts)
        return calendar.timegm(time.strptime("20%s.%s" % (ds, ts), "%Y%m%d.%H%M%S"))

    def set_epoch(self, ts=None):
        if ts is None:
            ts = int(time.time() + 0.5)
        tstr = time.gmtime(ts)
        v = (tstr.tm_year - 2000) * 10000 + tstr.tm_mon * 100 + tstr.tm_mday
        logdbg("set_epoch: date: %s" % v)
        self.write_long(106, v, signed=False)
        v = tstr.tm_hour * 10000 + tstr.tm_min * 100 + tstr.tm_sec
        logdbg("set_epoch: time: %s" % v)
        self.write_long(104, v, signed=False)

    def get_battery_voltage(self):
        # 16-bits
        # 0-50000 * 0.001
        return self.read_register(108, 3)

    def get_solar_charge_voltage(self):
        # 16-bits
        # 0-50000 * 0.001
        return self.read_register(109, 3)

    def get_charger_status(self):
        # 16-bits
        # 0=off, 1=fast, 2=fasttop, 3=floatcharge
        return self.read_register(110)


if __name__ == '__main__':
    import optparse

    usage = """%prog [options] [--debug] [--help]"""

    def main():
        syslog.openlog('wee_cm1', syslog.LOG_PID | syslog.LOG_CONS)
        parser = optparse.OptionParser(usage=usage)
        parser.add_option('--version', dest='version', action='store_true',
                          help='display driver version')
        parser.add_option('--debug', dest='debug', action='store_true',
                          help='display diagnostic information while running')
        parser.add_option('--port', dest='port', metavar='PORT',
                          help='serial port to which the station is connected',
                          default=CM1Station.DEFAULT_PORT)
        parser.add_option('--address', dest='address', metavar='ADDRESS',
                          help='modbus slave address', type=int,
                          default=CM1Station.DEFAULT_ADDRESS)
        parser.add_option('--baud-rate', dest='baud_rate', metavar='BAUD_RATE',
                          help='modbus slave baud rate', type=int,
                          default=CM1Station.DEFAULT_BAUD_RATE)
        parser.add_option('--set-time', dest='settime', action='store_true',
                          help='set station time to computer time')
        (options, _) = parser.parse_args()

        if options.version:
            print "cm1 driver version %s" % DRIVER_VERSION
            exit(1)

        if options.debug is not None:
            syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_DEBUG))
        else:
            syslog.setlogmask(syslog.LOG_UPTO(syslog.LOG_INFO))

        station = CM1Station(options.port, options.address, options.baud_rate)
        if options.settime:
            station.set_epoch()
        else:
            data = station.get_system_parameters()
            print "system parameters: ", data
            data = station.get_current()
            print "current values: ", data

    main()
