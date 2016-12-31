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

doc issues:
- 14.4.4 - spurious row 225?
- 14.4.8 - 259 should be 290
- 14.4.8 - 0-3 system status does not match table of status values
- 14.4.8 - units of energy?  32767 is not a long
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
        'pressure': 'pressure',
        'outTemp': 'temperature',
        'outHumidity': 'humidity',
        'windSpeed': 'wind_speed',
        'windDir': 'wind_dir',
        'windGust': 'wind_gust_speed',
        'windGustDir': 'wind_gust_dir',
        'rainRate': 'rain_rate',
        'heatindex': 'heatindex',
        'windchill': 'windchill',
        'dewpoint': 'dewpoint',
        'wetbulb': 'wetbulb'}

    def __init__(self, **stn_dict):
        self.model = stn_dict.get('model', 'MS-120')
        loginf("model is %s" % self.model)
        port = stn_dict.get('port', CM1.DEFAULT_PORT)
        address = int(stn_dict.get('address', CM1.DEFAULT_ADDRESS))
        loginf("address is %s" % address)
        baud_rate = int(stn_dict.get('baud_rate', CM1.DEFAULT_BAUD))
        self.poll_interval = int(stn_dict.get('poll_interval', 10))
        loginf("poll interval is %s" % self.poll_interval)
        self.sensor_map = stn_dict.get('sensor_map', CM1Driver.DEFAULT_MAP)
        loginf("sensor map: %s" % self.sensor_map)
        self.max_tries = int(stn_dict.get('max_tries', 3))
        self.retry_wait = int(stn_dict.get('retry_wait', 2))
        self.station = CM1(port, address, baud_rate)
        params = self.station.get_system_parameters()
        for x in CM1.SYSTEM_PARAMETERS:
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

    def setTime(self):
        self.station.set_epoch()

    def getTime(self):
        return self.station.get_epoch()
        

class CM1(minimalmodbus.Instrument):
    DEFAULT_PORT = '/dev/ttyUSB0'
    DEFAULT_ADDRESS = 1
    DEFAULT_BAUD_RATE = 19200

    SYSTEM_PARAMETERS = ['serial_number', 'product_id', 'firmware_version',
                         'date', 'time', 'battery_voltage', 'solar_voltage',
                         'charger_status']

    CHARGER_STATUS = {
        0: 'Off',
        1: 'Fast', # current-limited
        2: 'Fast Top', # voltage-limited
        3: 'Float Charge' } # low voltage charge

    def __init__(self, port, address, baud_rate):
        minimalmodbus.BAUDRATE = baud_rate
        minimalmodbus.Instrument.__init__(self, port, address)
        loginf("port: %s" % self.serial.port)
        loginf("serial settings: %s:%s:%s:%s" % (
            self.serial.baudrate, self.serial.bytesize,
            self.serial.parity, self.serial.stopbits))
        
    def __enter__(self):
        return self

    def __exit__(self, _, value, traceback):
        pass

    @staticmethod
    def _to_signed(x, bits=16):
        # assumes two's complement enoding of signed integer
        if (x & (1 << (bits - 1))) != 0:
            x = x - (1 << bits)
        return x

    @staticmethod
    def _to_long(a, b):
        return (a << 16) + b

    @staticmethod
    def _to_float(a, b):
        return unpack('f', packe('>HH', a, b))[0]

    @staticmethod
    def _to_calculated(x):
        if x == -999:
            return None
        return x * 0.1

    def get_system_parameters(self):
        data = dict()
        x = self.read_registers(100, 11)
        data['product_id'] = CM1._to_signed(x[0])
        data['firmware_version'] = x[1]
        data['serial_number'] = CM1._to_long(x[2], x[3])
        data['time'] = CM1._to_long(x[4], x[5])
        data['date'] = CM1._to_long(x[6], x[7])
        data['battery_voltage'] = x[8] * 0.001
        data['solar_voltage'] = x[9] * 0.001
        data['charger_status'] = x[10]
        return data

    def get_current(self):
        data = dict()
        x = self.read_registers(108, 3)
        data.update(CM1._decode_power(x))
        x = self.read_registers(200, 92)
        data.update(CM1._decode_wind(x[0:9]))
        data.update(CM1._decode_tph(x[20:26]))
        data.update(CM1._decode_rain(x[42:44]))
        data.update(CM1._decode_analog(x[44:48]))
        data.update(CM1._decode_calculated(x[40:42]+x[48:50]))
        data.update(CM1._decode_lightning(x[80:92]))
        return data

    def get_epoch(self):
        # station is gmtime
        x = self.read_registers(104, 4)
        ds = (x[2] << 16) + x[3]
        ts = (x[0] << 16) + x[1]
        dt = "20%06d.%06d" % (ds, ts)
        logdbg("date.time: %s" % dt)
        return calendar.timegm(time.strptime(dt, "%Y%m%d.%H%M%S"))

    def set_epoch(self, epoch=None):
        if epoch is None:
            epoch = int(time.time() + 0.5)
        tstr = time.gmtime(epoch)
        ds = (tstr.tm_year - 2000) * 10000 + tstr.tm_mon * 100 + tstr.tm_mday
        dlo = ds % 0x10000
        dhi = (ds - dlo) >> 16
        ts = tstr.tm_hour * 10000 + tstr.tm_min * 100 + tstr.tm_sec
        tlo = ts % 0x10000
        thi = (ts - tlo) >> 16
        buf = [thi, tlo, dhi, dlo]
        logdbg("set_epoch: date.time: %s.%s (%s)" % (ds, ts, buf))
        self.write_registers(104, buf)

    def get_time(self):
        # 32-bits
        # HHMMSS - bcd encoded
        return "%06d" % self.read_long(104)

    def get_date(self):
        # 32-bits
        # YYMMDD - bcd encoded
        return "%06d" % self.read_long(106)

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

    @staticmethod
    def _decode_power(x):
        data = dict()
        data['battery_voltage'] = x[0] * 0.001
        data['solar_voltage'] = x[1] * 0.001
        data['charger_status'] = x[2]
        return data

    def get_wind(self):
        # all values are 16-bit signed integers with 0.1 multiplier
        x = self.read_registers(200, 9)
        return CM1._decode_wind(x)

    @staticmethod
    def _decode_wind(x):
        data = dict()
        data['wind_status'] = x[0]
        if data['wind_status'] == -1:
            pass # no sensor attached
        elif data['wind_status'] == 0:
            data['wind_speed'] = x[1] * 0.1 # m/s
            data['wind_dir'] = x[2] * 0.1 # compass degree
            data['wind_speed_2m'] = x[3] * 0.1
            data['wind_dir_2m'] = x[4] * 0.1
            data['wind_speed_10m'] = x[5] * 0.1
            data['wind_dir_10m'] = x[6] * 0.1
            data['wind_gust_speed'] = x[7] * 0.1
            data['wind_gust_dir'] = x[8] * 0.1
        else:
            data['wind_speed'] = None
            data['wind_dir'] = None
            data['wind_speed_2m'] = None
            data['wind_dir_2m'] = None
            data['wind_speed_10m'] = None
            data['wind_dir_10m'] = None
            data['wind_gust_speed'] = None
            data['wind_gust_dir'] = None
        return data

    def get_tph(self):
        # all values are 16-bit signed integers with 0.1 multiplier
        # register 225 is ignored
        x = self.read_registers(220, 6)
        return CM1._decode_tph(x)

    @staticmethod
    def _decode_tph(x):
        data = dict()
        data['tph_status'] = x[0]
        if data['tph_status'] == -1:
            pass # no sensor attached
        else:
            if data['tph_status'] & 0x01 == 0x01:
                data['temperature'] = None
                data['humidity'] = None
            else:
                data['temperature'] = x[1] * 0.1
                data['humidity'] = x[2] * 0.1
            if data['tph_status'] & 0x02 == 0x02:
                data['pressure'] = None
                data['pressure_trend'] = None
            else:
                data['pressure'] = x[3] * 0.1
                data['pressure_trend'] = x[4]
        return data

    def get_rain(self):
        x = self.read_registers(242, 2)
        return CM1._decode_rain(x)

    @staticmethod
    def _decode_rain(x, multiplier=1.0):
        # multiplier converts to mm
        data = dict()
        data['rain_day_total'] = x[0] * multiplier
        data['rain_rate'] = x[1] * multiplier
        return data

    def get_analog(self):
        x = self.read_registers(244, 4)
        return CM1._decode_analog(x)

    @staticmethod
    def _decode_analog(x):
        data = dict()
        data['analog_1'] = CM1._to_float(x[0], x[1])
        data['analog_2'] = CM1._to_float(x[0], x[1])
        return data

    def get_calculated(self):
        x = self.read_registers(240, 2)
        y = self.read_registers(248, 2)
        return CM1._decode_calculated(x+y)

    @staticmethod
    def _decode_calculated(x):
        data = dict()
        data['heatindex'] = CM1._to_calculated(x[0])
        data['windchill'] = CM1._to_calculated(x[1])
        data['dewpoint'] = CM1._to_calculated(x[2])
        data['wetbulb'] = CM1._to_calculated(x[3])
        return data

    def get_lightning(self):
        x = self.read_registers(280, 12)
        return CM1._decode_lightning(x)

    @staticmethod
    def _decode_lightning(x):
        data = dict()
        data['lightning_status'] = x[0] # 0-3
        if data['lightning_status'] == 0x0080:
            data['lightning_strike_count'] = None
            data['lightning_noise_count'] = None
            data['lightning_disturber_count'] = None
            data['lightning_distance'] = None
            data['lightning_energy'] = None
            data['lightning_strike_count_10m'] = None
            data['lightning_strike_count_30m'] = None
            data['lightning_strike_count_60m'] = None
            data['lightning_noise_count_60m'] = None
            data['lightning_disturber_count_60m'] = None
        else:
            data['lightning_strike_count'] = x[1]
            data['lightning_noise_count'] = x[2]
            data['lightning_disturber_count'] = x[3]
            data['lightning_distance'] = x[4] # 0-40 km; 63=out-of-range
            data['lightning_energy'] = CM1._to_long(x[5], x[6])
            data['lightning_strike_count_10m'] = x[7]
            data['lightning_strike_count_30m'] = x[8]
            data['lightning_strike_count_60m'] = x[9]
            data['lightning_noise_count_60m'] = x[10]
            data['lightning_disturber_count_60m'] = x[11]
        return data


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
                          default=CM1.DEFAULT_PORT)
        parser.add_option('--address', dest='address', metavar='ADDRESS',
                          help='modbus slave address', type=int,
                          default=CM1.DEFAULT_ADDRESS)
        parser.add_option('--baud-rate', dest='baud_rate', metavar='BAUD_RATE',
                          help='modbus slave baud rate', type=int,
                          default=CM1.DEFAULT_BAUD_RATE)
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

        station = CM1(options.port, options.address, options.baud_rate)
        if options.settime:
            station.set_epoch()
            exit(0)

#        print station.read_register(200, functioncode=3, signed=True)
#        print station.get_epoch()

        data = station.get_system_parameters()
        print "system parameters: ", data
        data = station.get_current()
        print "current values: ", data

    main()
