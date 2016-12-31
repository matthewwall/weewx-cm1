weewx-cm1

This is a driver for weewx that collects data from Dyacon weather stations
using the Dyacon CM-1 control module.


===============================================================================
Pre-requisites

- weewx

sudo apt-get install weewx

- the minimalmodbus python packet

sudo pip install minimalmodbus


===============================================================================
Installation

1) download the driver

wget -O weewx-cm1.zip https://github.com/matthewwall/weewx-cm1/archive/master.zip

2) install the driver

wee_extension --install weewx-cm1.zip

3) configure the driver

wee_config --reconfigure

4) start weewx

sudo /etc/init.d/weewx start


===============================================================================
Configuration options

There are a few options to configure the Modbus parameters.  Use the sensor_map
to specify additional sensors.

[CM1]
    driver = user.cm1
    port = /dev/ttyUSB
    [[sensor_map]]
        pressure = pressure
        outTemp = temperature
        outHumidity = humidity
        rainRate = rain_rate
        windSpeed = wind_speed
        windDir = wind_dir
        windGust = wind_gust_speed
        windGustDir = wind_gust_dir
        heatindex = heatindex
        windchill = windchill
        dewpoint = dewpoint
        wetbulb = wetbulb
        # the following are optional and are not part of the default map
        extraTemp1 = analog_1
        soilTemp1 = analog_2
        lightning_count = lightning_strike_count
        lightning_distance = lightning_distance
