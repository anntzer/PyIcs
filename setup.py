#!/usr/bin/env python
from distutils.core import setup
import sys

setup(
    name="PyIcs",
    version="0.1.0",
    packages=["pyics"],
    license="LICENSE.txt",
    long_description=open("README.md").read(),
    requires=[] if sys.version_info >= (3, 4) else ["enum (==0.9.19)"]
)
