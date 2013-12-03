PyIcs: a Pythonic, ctypes-based wrapper for libics
==================================================

PyIcs wraps libics, the reference implementation of for the ICS (Image
Cytometry Standard) file format.  Note that libics is *not* included!  The
libics headers are also needed.

The main entry point is the `pyics.ICS` class.  Currently, the path of the
headers is hard-coded.  Moreover, because PyIcs uses the `ctypes.CDLL` class,
the package is Linux-only.  However, it should be easy to "fix" this for
Windows.

PyIcs requires Python3.2+, although small changes could make it compatible with
Python2 as well.  But note that pylibics, another wrapper for libics, already
works with Python2.6.
