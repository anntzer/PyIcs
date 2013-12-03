"""A Pythonic, ctypes-based wrapper for libics.
"""


from collections import namedtuple
from ctypes import (
    byref, c_double, c_int, c_size_t, c_uint, c_void_p, create_string_buffer)
import os

import numpy as np

from .api import *


__all__ = ["ICS"]


_ics_np_types = [
    (Ics_DataType.Ics_uint8, np.dtype(np.uint8)),
    (Ics_DataType.Ics_sint8, np.dtype(np.int8)),
    (Ics_DataType.Ics_uint16, np.dtype(np.uint16)),
    (Ics_DataType.Ics_sint16, np.dtype(np.int16)),
    (Ics_DataType.Ics_uint32, np.dtype(np.uint32)),
    (Ics_DataType.Ics_sint32, np.dtype(np.int32)),
    (Ics_DataType.Ics_real32, np.dtype(np.float32)),
    (Ics_DataType.Ics_real64, np.dtype(np.float64)),
    (Ics_DataType.Ics_complex32, np.dtype(np.complex64)),
    (Ics_DataType.Ics_complex64, np.dtype(np.complex128))]
_as_np_type = dict(_ics_np_types)
_as_ics_type = dict((np, ics) for ics, np in _ics_np_types)


def _new_token():
    return create_string_buffer(b" " * ICS_STRLEN_TOKEN)


def _new_string():
    return create_string_buffer(b" " * ICS_LINE_LENGTH)


ImelUnits = namedtuple("ImelUnits", "origin scale units")
Parameter = namedtuple("Parameter", "order label origin scale units")
Channel = namedtuple(
    "Channel", "excitation emission pinhole_radius photon_count")
Sensor = namedtuple("Sensor", "model type na lens_ri medium_ri")


class ICS:
    """A reader/writer class for ICS files.

    ICS objects can be used as context managers.  Note that libics actually
    writes the data to the file only when the file is closed!

    Attributes:
    -----------
    data: ndarray
        The contents of the file (partial reads are not supported).
        The ndarray's dtype and shape reflect the layout given in the ICS file.
    significant_bits: int
    coordinate_system: string
        Can be set with `set_coordinate_system`.
    imel_units: ImelUnits namedtuple (origin: float, scale: float, units: string)
        Can be set with `set_imel_units`.
    parameters: list of (order: string, label: string,
                         origin: float, scale: float, units: float) namedtuple
        Can be set with `set_parameters`.
    history: list of (string, string) pairs.
        Can be set with `set_history`.
    channels: list of Channel namedtuples.
        Can be set with `set_channels`.
    sensor: Sensor namedtuple.
        Can be set with `set_sensor`.
    """

    def _init(self, path, mode):
        """Common initialization method to both constructors.
        """
        self.mode = mode
        self._ip = c_void_p()
        dll.IcsOpen(byref(self._ip), os.fsencode(path), mode.encode("ascii"))
        self.closed = False

    def __init__(self, path, mode="r"):
        """Open an ICS file for read ("r") or update ("rw").

        The "f" suffix avoids forcing the name suffix to ".ics".  To open files
        for writing, use the `ICS.writing` constructor.
        """
        if mode.startswith("w"):
            raise ValueError("Use ICS.writing for writing")
        self._init(path, mode)
        self._layout = layout = dll.IcsGetLayout(
            self._ip, c_uint(), c_int(), (c_size_t * ICS_MAXDIM)())
        dtype = _as_np_type[Ics_DataType(layout.dt)]
        self.data = np.empty(
            layout.dims[:layout.ndims], dtype=dtype, order="F")
        dll.IcsGetData(self._ip,
                       self.data.ctypes._as_parameter_,
                       self.data.size * dtype.itemsize)
        self.significant_bits = self._get_significant_bits()
        self.coordinate_system = self._get_coordinate_system()
        self.imel_units = self._get_imel_units()
        self.parameters = self._get_parameters()
        self.history = self._get_history()
        self.channels = self._get_channels()
        self.sensor = self._get_sensor()

    @classmethod
    def writing(cls, path, data_or_source, data_template=None, *,
                version=2, compression=0, nbits=None):
        """Write a numpy array or a path to a source file in a new ICS file.

        If `data_or_source` is a numpy array, later modifications to the array
        will be reflected into the file as long as the file isn't closed!

        If `data_or_source` is a string (a path to a binary file),
        `data_template` should be a numpy array whose dtype and shape will be
        used.  Non-zero offsets are not allowed.

        Use the `version` keyword argument to set the ICS version used.

        Use the `compression` keyword argument to set the compression level.
        A zero level uses uncompressed mode.  The "compress" mode is not
        supported.

        Use the `nbits` keyword argument to set the number of significant bits.
        """
        self = object.__new__(cls)
        if isinstance(data_or_source, np.ndarray):
            self._set_data = array = np.asfortranarray(data_or_source)
        elif isinstance(data_or_source, (str, bytes)):
            source = data_or_source
            array = data_template
        else:
            raise TypeError(
                "data_or_source should be a numpy array or a (byte)string")
        layout_args = (_as_ics_type[array.dtype],
                       len(array.shape),
                       array.ctypes.shape_as(c_size_t))
        self._init(path, "w" + str(version))
        dll.IcsSetLayout(self._ip, *layout_args)
        if isinstance(data_or_source, np.ndarray):
            dll.IcsSetData(self._ip,
                           array.ctypes._as_parameter_,
                           array.size * array.dtype.itemsize)
        elif isinstance(data_or_source, (str, bytes)):
            dll.IcsSetSource(self._ip, os.fsencode(source), 0)
        dll.IcsSetCompression(
            self._ip,
            Ics_Compression.IcsCompr_gzip if compression
            else Ics_Compression.IcsCompr_uncompressed,
            compression)
        if nbits is not None:
            dll.IcsSetSignificantBits(self._ip, nbits)
            self.significant_bits = nbits
        return self

    def close(self):
        """Close a file, writing down the new data and metadata.
        """
        self.closed = True
        dll.IcsClose(self._ip)

    def __del__(self):
        if not getattr(self, "closed", True):
            self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, tb):
        if not getattr(self, "closed", True):
            self.close()

    def dump(self):
        """Dump an ICS file structure to sys.__stdout__.
        """
        dll.IcsPrintIcs(self._ip)

    def _get_significant_bits(self):
        return dll.IcsGetSignificantBits(self._ip, c_size_t()).nbits

    def _get_coordinate_system(self):
        return (dll.IcsGetCoordinateSystem(self._ip, _new_token()).coord.
                decode("ascii"))

    def set_coordinate_system(self, system):
        """Set the coordinate system.
        """
        dll.IcsSetCoordinateSystem(self._ip, system.encode("ascii"))
        self.coordinate_system = system

    def _get_imel_units(self):
        _, origin, scale, units = dll.IcsGetImelUnits(
            self._ip, c_double(), c_double(), _new_token())
        return ImelUnits(
            origin=origin, scale=scale, units=units.decode("ascii"))

    def set_imel_units(self, imel_units):
        """Set the imel units from an (origin, scale, units) triplet.
        """
        dll.IcsSetImelUnits(
            self._ip,
            *imel_units._replace(units=imel_units.units.encode("ascii")))
        self.imel_units = imel_units

    def _get_parameters(self):
        parameters = []
        for dim in range(self._layout.ndims):
            _, _, order, label = dll.IcsGetOrder(
                self._ip, dim, _new_token(), _new_token())
            _, _, origin, scale, units = dll.IcsGetPosition(
                self._ip, dim, c_double(), c_double(), _new_token())
            parameters.append(Parameter(
                order.decode("ascii"), label.decode("ascii"),
                origin, scale, units.decode("ascii")))
        return parameters

    def set_parameters(self, parameters):
        """Set the parameters' order, labels, origins, scales and units.
        """
        for dim, (order, label, origin, scale, units) in enumerate(parameters):
            dll.IcsSetOrder(
                self._ip, dim, order.encode("ascii"), label.encode("ascii"))
            dll.IcsSetPosition(
                self._ip, dim, origin, scale, units.encode("ascii"))
        self.parameters = parameters

    def _get_history(self):
        _, n_history_strings = dll.IcsGetNumHistoryStrings(self._ip, c_int())
        kvs = []
        if not n_history_strings:
            return kvs
        _, k, v, _ = dll.IcsGetHistoryKeyValue(
            self._ip, _new_token(), _new_string(),
            Ics_HistoryWhich.IcsWhich_First)
        kvs.append((k.decode("ascii"), v.decode("ascii")))
        for _ in range(n_history_strings - 1):
            _, k, v, _ = dll.IcsGetHistoryKeyValue(
                self._ip, _new_token(), _new_string(),
                Ics_HistoryWhich.IcsWhich_Next)
            kvs.append((k.decode("ascii"), v.decode("ascii")))
        return kvs

    def set_history(self, history):
        """Set the history.
        """
        dll.IcsDeleteHistory(self._ip, b"")
        for k, v in history:
            dll.IcsAddHistoryString(
                self._ip, k.encode("ascii"), v.encode("ascii"))
        self.history = history

    def _get_channels(self):
        return [Channel(
            excitation=dll.IcsGetSensorExcitationWavelength(self._ip, channel),
            emission=dll.IcsGetSensorEmissionWavelength(self._ip, channel),
            pinhole_radius=dll.IcsGetSensorPinholeRadius(self._ip, channel),
            photon_count=dll.IcsGetSensorPhotonCount(self._ip, channel))
            for channel in range(dll.IcsGetSensorChannels(self._ip))]

    def set_channels(self, channels):
        """Set the channels.
        """
        dll.IcsEnableWriteSensor(self._ip, 1)
        dll.IcsSetSensorChannels(self._ip, len(channels))
        for channel, (exc, em, pr, pc) in self.channels:
            dll.IcsSetSensorExcitationWavelength(self._ip, channel, exc)
            dll.IcsSetSensorEmissionWavelength(self._ip, channel, em)
            dll.IcsSetSensorPinholeRadius(self._ip, channel, pr)
            dll.IcsSetSensorPhotonCount(self._ip, channel, pc)
        self.channels = channels

    def _get_sensor(self):
        return Sensor(
            model=dll.IcsGetSensorModel(self._ip).decode("ascii"),
            type=dll.IcsGetSensorType(self._ip).decode("ascii"),
            na=dll.IcsGetSensorNumAperture(self._ip),
            lens_ri=dll.IcsGetSensorLensRI(self._ip),
            medium_ri=dll.IcsGetSensorMediumRI(self._ip))

    def set_sensor(self, sensor):
        """Set the sensor.
        """
        dll.IcsEnableWriteSensor(self._ip, 1)
        model, type, na, lens_ri, medium_ri = sensor
        dll.IcsSetSensorModel(self._ip, model.encode("ascii"))
        dll.IcsSetSensorType(self._ip, type.encode("ascii"))
        dll.IcsSetSensorNumAperture(self._ip, na)
        dll.IcsSetSensorLensRI(self._ip, lens_ri)
        dll.IcsSetSensorMediumRI(self._ip, medium_ri)
        self.sensor = sensor
