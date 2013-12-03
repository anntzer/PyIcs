"""The libics test suite, translated for py.test.

test_strides and test_strides2 were not translated as the corresponding
functions are not implemented.
"""


import os
import shutil
from tempfile import TemporaryDirectory

import numpy as np
import pytest

from pyics import ICS


@pytest.fixture(scope="module") # tmpdir won't work here
def datadir():
    datadir = TemporaryDirectory()
    for fname in os.listdir("test/data"):
        shutil.copy2(os.path.join("test/data", fname), datadir.name)
    return lambda path: os.path.join(datadir.name, path)


def assert_equal(x, y):
    __tracebackhide__ = True
    try:
        np.testing.assert_equal(x, y)
    except AssertionError as e:
        pytest.fail(e)


def test_ics1(datadir):
    with ICS(datadir("testim.ics")) as ics:
        data = ics.data
    ICS.writing(datadir("result_v1.ics"), data, version=1).close()
    with ICS(datadir("result_v1.ics")) as ics:
        assert_equal(ics.data, data)
    with open(datadir("testim.ics")) as f1, open(datadir("result_v1.ics")) as f2:
        assert [line1 == line2 or "filename" in line1 or "filename" in line2
                for line1, line2 in zip(f1, f2)]


def test_ics2a(datadir):
    with ICS(datadir("testim.ics")) as ics:
        data = ics.data
    ICS.writing(datadir("result_v2a.ics"),
                datadir("testim.ids"), data, version=2).close()
    with ICS(datadir("result_v2a.ics")) as ics:
        assert_equal(ics.data, data)


def test_ics2b(datadir):
    with ICS(datadir("testim.ics")) as ics:
        data = ics.data
    ICS.writing(datadir("result_v2b.ics"), data, version=2).close()
    with ICS(datadir("result_v2b.ics")) as ics:
        assert_equal(ics.data, data)


def test_compress(datadir):
    with ICS(datadir("testim.ics")) as i1, ICS(datadir("testim_c.ics")) as i2:
        assert_equal(i1.data, i2.data)


def test_gzip(datadir):
    with ICS(datadir("testim.ics")) as ics:
        data = ics.data
    ICS.writing(datadir("result_v2z.ics"),
                data, version=2, compression=6).close()
    with ICS(datadir("result_v2z.ics")) as ics:
        assert_equal(ics.data, data)


@pytest.mark.parametrize("fname", ["result_v1.ics", "result_v2a.ics",
                                   "result_v2b.ics", "result_v2z.ics"])
def test_metadata(datadir, fname):
    with ICS(datadir(fname), "rw") as ics:
        data = ics.data
        parameters = ics.parameters
        parameters[0] = parameters[0][:2] + (1834, 0.02, "millimeter")
        parameters[1] = parameters[1][:2] + (-653, .014, "millimiter")
        ics.set_parameters(parameters)
        history = ics.history
        history.append(("test", "Adding history line"))
        ics.set_history(history)
    with ICS(datadir(fname), "r") as ics:
        assert_equal(ics.data, data)


def test_history(datadir):
    history = [("sequence1", "this is some data"),
               ("sequence2", "this is some more data"),
               ("sequence3", "this is some other stuff")]
    with ICS(datadir("result_v1.ics"), "rw") as ics:
        ics.set_history(history)
        assert ics.history == history
