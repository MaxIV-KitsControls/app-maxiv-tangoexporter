#!/usr/bin/env python

from setuptools import setup

setup(
    name="python-tangoexporter",
    version="0.0.5",
    description="Prometheus exporter for TANGO device servers.",
    author="Johan Forsberg",
    author_email="johan.forsberg@maxlab.lu.se",
    license="GPLv3",
    url="http://www.maxlab.lu.se",
    packages=['tango_exporter'],
    entry_points={
        'console_scripts': [
            'tango_exporter = tango_exporter:main'
        ]
    }
)
