"""The libics API.
"""


from ctypes import CDLL
from .h2ctypes import Parser, DLL


__all__ = ["dll"]


parse = Parser("/usr/include/libics.h",
               "/usr/include/libics_sensor.h",
               "/usr/include/libics_test.h").parse()
parse.export_for_pydoc(globals())
dll = DLL(CDLL("libics.so"), parse, Ics_Error.IcsErr_Ok)
