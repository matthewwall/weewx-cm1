#!/usr/bin/env python
# Copyright 2016 Matthew Wall
# Distributed under the terms of the GNU Public License (GPLv3)

"""Driver for collecting data from Dyacon weather station using the CM1
weather tation control module.

Thanks to Eugene at Dyacon for full support in the development of this driver.

This implementation uses the Modbus-RTU interface described in the Dyacon
reference 57-6032-DOC-Manual-CM-1.pdf (2014).

This driver requires the minimalmodbus python module, which in turn depends on
the pyserial (pure python) module.

pip install minimalmodbus

The CM1 has two communication interfaces: a USB port for configuration, and
a serial port for reading data (Modbus-RTU slave over RS-485).

The CM1 has a data logger with capacity of 49,152 records, with logging
intervals of 1, 2, 5, 10, 15, 20, 30, and 60 minutes.

The CM1 emits the following Modbus errors:
  01 - illegal function
  02 - illegal address
  03 - illegal data value
  04 - device failure
"""

import minimalmodbus
import struct
import syslog
import time

import weewx
import weewx.drivers
from weewx.wxformulas import calculate_rain


DRIVER_NAME = 'CM1'
DRIVER_VERSION = '0.5'


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


def loader(config_dict, _):
    return CM1Driver(**config_dict[DRIVER_NAME])

def confeditor_loader():
    return CM1ConfEditor()


class CM1ConfEditor(weewx.drivers.AbstractConfEditor):
    @property
    def default_stanza(self):
        return """
[CM1]
    # This section is for Dyacon weather stations using the CM1.

    # Which model of weather station is this
    model = MS-120

    # RS485 (modbus) serial port
    port = /dev/ttyUSB0

    # How often to poll the device, in seconds
    poll_interval = 10

    # The driver to use
    driver = user.cm1
"""

    def prompt_for_settings(self):
        print "Specify the serial port on which the station is connected, for"
        print "example /dev/ttyUSB0 or /dev/ttyS0 or /dev/tty.usbserial"
        port = self._prompt('port', '/dev/ttyUSB0')
        return {'port': port}


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
        'wetbulb': 'wetbulb',
        'extraTemp1': 'analog_1',
        'extraTemp2': 'analog_2',
        'lightning_disturber_count': 'lightning_disturber_count',
        'lightning_strike_count': 'lightning_strike_count',
        'lightning_noise_count': 'lightning_noise_count',
        'lightning_distance': 'lightning_distance',
        'lightning_energy': 'lightning_energy',
        'solar_voltage': 'solar_voltage',
        'battery_voltage': 'battery_voltage',
        'charger_status': 'charger_status',
        'tph_status': 'tph_status',
        'lightning_status': 'lightning_status',
        'wind_status': 'wind_status',
    }

    def __init__(self, **stn_dict):
        loginf('driver version is %s' % DRIVER_VERSION)
        self.model = stn_dict.get('model', 'MS-120')
        loginf("model is %s" % self.model)
        port = stn_dict.get('port', CM1.DEFAULT_PORT)
        loginf("port is %s" % port)
        address = int(stn_dict.get('address', CM1.DEFAULT_ADDRESS))
        loginf("address is %s" % address)
        baud_rate = int(stn_dict.get('baud_rate', CM1.DEFAULT_BAUD_RATE))
        timeout = int(stn_dict.get('timeout', CM1.DEFAULT_TIMEOUT))
        self.poll_interval = int(stn_dict.get('poll_interval', 10))
        loginf("poll interval is %s" % self.poll_interval)
        self.bucket_size = float(stn_dict.get('bucket_size', 0.2)) # mm
        loginf("bucket size is %s mm" % self.bucket_size)
        self.sensor_map = dict(CM1Driver.DEFAULT_MAP)
        if 'sensor_map' in stn_dict:
            self.sensor_map.update(stn_dict['sensor_map'])
        loginf("sensor map: %s" % self.sensor_map)
        self.max_tries = int(stn_dict.get('max_tries', 6))
        self.retry_wait = int(stn_dict.get('retry_wait', 5))
        self.last_rain = None
        self.station = CM1(port, address, baud_rate, timeout)
        params = self._get_with_retries('get_system_parameters')
        for x in CM1.SYSTEM_PARAMETERS:
            loginf("%s: %s" % (x, params[x]))

    @property
    def hardware_name(self):
        return self.model

    def closePort(self):
#        self.station.serial.close()
        self.station = None

    def genLoopPackets(self):
        while True:
            data = self._get_with_retries('get_current')
            logdbg("raw data: %s" % data)
            pkt = dict()
            pkt['dateTime'] = int(time.time() + 0.5)
            pkt['usUnits'] = weewx.METRICWX
            for k in self.sensor_map:
                if self.sensor_map[k] in data:
                    pkt[k] = data[self.sensor_map[k]]
            if 'rain_day_total' in data:
                pkt['rain'] = calculate_rain(
                    data['rain_day_total'], self.last_rain)
                if pkt['rain'] is not None:
                    pkt['rain'] *= self.bucket_size
                self.last_rain = data['rain_day_total']
            if 'rainRate' in pkt and pkt['rainRate'] is not None:
                pkt['rainRate'] *= self.bucket_size
            yield pkt
            if self.poll_interval:
                time.sleep(self.poll_interval)

#    def setTime(self):
#        self.station.set_clock()

#    def getTime(self):
#        return self.station.get_clock()

    def _get_with_retries(self, method):
        for n in range(self.max_tries):
            try:
                return getattr(self.station, method)()
            except (IOError, ValueError, TypeError), e:
                loginf("failed attempt %s of %s: %s" %
                       (n + 1, self.max_tries, e))
                time.sleep(self.retry_wait)
        else:
            raise weewx.WeeWxIOError("%s: max tries %s exceeded" %
                                     (method, self.max_tries))


class CM1(minimalmodbus.Instrument):
    DEFAULT_PORT = '/dev/ttyUSB0'
    DEFAULT_ADDRESS = 1
    DEFAULT_BAUD_RATE = 19200
    DEFAULT_TIMEOUT = 6.0 # seconds

    SYSTEM_PARAMETERS = ['serial_number', 'product_id', 'firmware_version',
                         'date', 'time', 'battery_voltage', 'solar_voltage',
                         'charger_status']

    CHARGER_STATUS = {
        0: 'Off',
        1: 'Fast', # current-limited
        2: 'Fast Top', # voltage-limited
        3: 'Float Charge' } # low voltage charge

    def __init__(self, port, address, baud_rate, timeout):
#        minimalmodbus.BAUDRATE = baud_rate
#        minimalmodbus.TIMEOUT = timeout
        minimalmodbus.Instrument.__init__(self, port, address)
        self.serial.baudrate = baud_rate
        self.serial.timeout = timeout
        loginf("port: %s" % self.serial.port)
        loginf("serial settings: %s:%s:%s:%s" % (
            self.serial.baudrate, self.serial.bytesize,
            self.serial.parity, self.serial.stopbits))
#        self.address = address

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
        f = struct.unpack('f', struct.pack('>HH', a, b))[0]
#        loginf("to_float: a=%04x b=%04x f=%s" % (a, b, f))
        return f

    @staticmethod
    def _to_calculated(x):
        x = CM1._to_signed(x)
        if x == -9990:
            return None
        return x * 0.1

    def _read_registers(self, reg, cnt):
        return self.read_registers(reg, cnt)

    def _read_register(self, reg, places=0):
        return self.read_register(reg, places)

    def _read_long(self, reg):
        return self.read_long(reg)

    def get_system_parameters(self):
        data = dict()
        x = self._read_registers(100, 11)
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
        x = self._read_registers(108, 3)
        data.update(CM1._decode_power(x))
        x = self._read_registers(200, 92)
        data.update(CM1._decode_wind(x[0:9]))
        data.update(CM1._decode_tph(x[20:26]))
        data.update(CM1._decode_rain(x[42:44]))
        data.update(CM1._decode_analog(x[44:46], 1))
        data.update(CM1._decode_analog(x[46:48], 2))
        data.update(CM1._decode_calculated(x[40:42]+x[48:50]))
        data.update(CM1._decode_lightning(x[80:92]))
        return data

    def get_clock(self):
        # station is in local time, so convert from local time to epoch
        x = self._read_registers(104, 4)
        ds = (x[2] << 16) + x[3]
        ts = (x[0] << 16) + x[1]
        x = time.mktime(time.strptime("20%06d.%06d" % (ds, ts),
                                      "%Y%m%d.%H%M%S"))
        logdbg("get_clock: date.time: %s.%s (%s)" % (ds, ts, x))
        return x

    def set_clock(self, epoch=None):
        # station is in local time, so convert from epoch to local time
        if epoch is None:
            epoch = int(time.time() + 0.5)
        tstr = time.localtime(epoch)
        ds = (tstr.tm_year - 2000) * 10000 + tstr.tm_mon * 100 + tstr.tm_mday
        dlo = ds % 0x10000
        dhi = (ds - dlo) >> 16
        ts = tstr.tm_hour * 10000 + tstr.tm_min * 100 + tstr.tm_sec
        tlo = ts % 0x10000
        thi = (ts - tlo) >> 16
        buf = [thi, tlo, dhi, dlo]
        logdbg("set_clock: date.time: %06d.%06d (%s)" % (ds, ts, epoch))
        self.write_registers(104, buf)

    def get_time(self):
        # 32-bits
        # HHMMSS - bcd encoded
        return "%06d" % self._read_long(104)

    def get_date(self):
        # 32-bits
        # YYMMDD - bcd encoded
        return "%06d" % self._read_long(106)

    def get_battery_voltage(self):
        # 16-bits
        # 0-50000 * 0.001
        return self._read_register(108, 3)

    def get_solar_charge_voltage(self):
        # 16-bits
        # 0-50000 * 0.001
        return self._read_register(109, 3)

    def get_charger_status(self):
        # 16-bits
        # 0=off, 1=fast, 2=fasttop, 3=floatcharge
        return self._read_register(110)

    @staticmethod
    def _decode_power(x):
        data = dict()
        data['battery_voltage'] = x[0] * 0.001
        data['solar_voltage'] = x[1] * 0.001
        data['charger_status'] = x[2]
        return data

    def get_wind(self):
        # all values are 16-bit signed integers with 0.1 multiplier
        x = self._read_registers(200, 9)
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
        x = self._read_registers(220, 6)
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
                data['temperature_p'] = None
            else:
                data['pressure'] = x[3] * 0.1
                data['pressure_trend'] = x[4]
                data['temperature_p'] = x[5] * 0.1
        return data

    def get_rain(self):
        x = self._read_registers(242, 2)
        return CM1._decode_rain(x)

    @staticmethod
    def _decode_rain(x):
        # multiplier converts to mm
        data = dict()
        data['rain_day_total'] = x[0]
        data['rain_rate'] = x[1]
        return data

    def get_analog_1(self):
        x = self._read_registers(244, 2)
        return CM1._decode_analog(x, 1)

    def get_analog_2(self):
        x = self._read_registers(246, 2)
        return CM1._decode_analog(x, 2)

    @staticmethod
    def _decode_analog(x, label=1):
        data = dict()
        data['analog_%s' % label] = CM1._to_float(x[0], x[1])
        return data

    def get_calculated(self):
        x = self._read_registers(240, 2)
        y = self._read_registers(248, 2)
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
        x = self._read_registers(280, 12)
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
        parser.add_option('--timeout', dest='timeout', metavar='TIMEOUT',
                          help='modbus timeout, in seconds', type=int,
                          default=CM1.DEFAULT_TIMEOUT)
        parser.add_option('--get-time', dest='gettime', action='store_true',
                          help='get station time')
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

        if False:
            test_mmb(options.port, options.address, options.baud_rate,
                     options.timeout, options.debug)
        if False:
            test_mbtk(options.port, options.address, options.baud_rate,
                      options.timeout, options.debug)
        if True:
            test_CM1(options.port, options.address, options.baud_rate,
                     options.timeout, options.debug,
                     options.gettime, options.settime)

    def test_CM1(port, address, baud_rate, timeout, debug, gettime, settime):
        station = CM1(port, address, baud_rate, timeout)
        station.debug = debug
        if gettime:
            print "epoch:", station.get_clock()
            print "date:", station.get_date()
            print "time:", station.get_time()
            exit(0)
        if settime:
            print "epoch before:", station.get_clock()
            station.set_clock()
            print "epoch after:", station.get_clock()
            print "date:", station.get_date()
            print "time:", station.get_time()
            exit(0)
        data = station.get_system_parameters()
        print "system parameters: ", data
        data = station.get_current()
        print "current values: ", data

    def test_mmb(port, address, baud_rate, timeout, debug):
        print "\n\nminimalmodbus"
        import minimalmodbus
        instrument = minimalmodbus.Instrument(port, address)
        instrument.serial.baudrate = baud_rate
        instrument.serial.timeout = timeout
        instrument.debug = debug
        print instrument.read_register(100, 1)
        print instrument.read_registers(100, 11)
        print instrument.read_register(200, 1)
        print instrument.read_registers(200, 92)

    def test_mbtk(port, address, baud_rate, timeout, debug):
        print "\n\nmodbus-tk"
        import modbus_tk
        import modbus_tk.defines as cst
        from modbus_tk import modbus_rtu
        import serial
        if debug:
            logger = modbus_tk.utils.create_logger("console")
        master = modbus_rtu.RtuMaster(
            serial.Serial(port=port, baudrate=baud_rate,
                          bytesize=8, parity='N', stopbits=1))
        master.set_timeout(timeout)
        if debug:
            master.set_verbose(True)
        print master.execute(address, cst.READ_HOLDING_REGISTERS, 100, 1)
        print master.execute(address, cst.READ_HOLDING_REGISTERS, 100, 11)
        print master.execute(address, cst.READ_HOLDING_REGISTERS, 200, 1)
        print master.execute(address, cst.READ_HOLDING_REGISTERS, 200, 92)

    main()
