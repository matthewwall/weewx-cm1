# installer for dyacon cm1 driver
# Copyright 2016 Matthew Wall

from setup import ExtensionInstaller

def loader():
    return CM1Installer()

class CM1Installer(ExtensionInstaller):
    def __init__(self):
        super(CM1Installer, self).__init__(
            version="0.1",
            name='cm1',
            description='Collect data from Dyacon weather station using CM1',
            author="Matthew Wall",
            author_email="mwall@users.sourceforge.net",
            files=[('bin/user', ['bin/user/cm1.py'])]
            )
