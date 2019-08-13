# installer for dyacon cm1 driver
# Copyright 2016 Matthew Wall
# Distributed under the terms of the GNU Public License (GPLv3)

from setup import ExtensionInstaller

def loader():
    return CM1Installer()

class CM1Installer(ExtensionInstaller):
    def __init__(self):
        super(CM1Installer, self).__init__(
            version="0.4",
            name='cm1',
            description='Collect data from Dyacon weather station using CM1',
            author="Matthew Wall",
            author_email="mwall@users.sourceforge.net",
            files=[('bin/user', ['bin/user/cm1.py'])]
            )
