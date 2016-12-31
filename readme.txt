weewx-cm1

This is a driver for weewx that collects data from Dyacon weather stations
using the Modbus CM-1 control module.

Installation

0) install weewx (see the weewx user guide)

1) download the driver

wget -O weewx-cm1.zip https://github.com/matthewwall/weewx-cm1/archive/master.zip

2) install the driver

wee_extension --install weewx-cm1.zip

3) configure the driver

wee_config --reconfigure

4) start weewx

sudo /etc/init.d/weewx start
