# -*- coding: utf-8 -*-

from setuptools import find_packages
from setuptools import setup

import fastentrypoints

dependencies = ["click"]

config = {
    "version": "0.1",
    "name": "portagetool",
    "url": "https://github.com/jakeogh/portagetool",
    "license": "ISC",
    "author": "Justin Keogh",
    "author_email": "github.com@v6y.net",
    "description": "Common functions for portage",
    "long_description": __doc__,
    "packages": find_packages(exclude=["tests"]),
    "package_data": {"portagetool": ["py.typed"]},
    "include_package_data": True,
    "zip_safe": False,
    "platforms": "any",
    "install_requires": dependencies,
    "scripts": ["io-niceness.sh"],
    "entry_points": {
        "console_scripts": [
            "portagetool=portagetool.portagetool:cli",
            "emerge_keep=portagetool.portagetool:emerge_keepwork",
        ],
    },
}

setup(**config)
