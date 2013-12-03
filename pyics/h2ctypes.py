"""A generator of ctypes wrappers for C libraries.
"""


from collections import namedtuple
import ctypes
try:
    from ctypes import wintypes
except ValueError:
    class wintypes:
        """Standard types defined by :file:`Windows.h`.
        """
        BYTE = ctypes.c_ubyte
        DWORD = ctypes.c_uint32
        ULONG =  ctypes.c_uint32
        WORD = ctypes.c_ushort
from enum import IntEnum
import functools
import inspect
import re


C_TYPES = {"_Bool": ctypes.c_bool,
           "char": ctypes.c_char, # also ctypes.c_byte
           "wchar_t": ctypes.c_wchar,
           "unsigned char": ctypes.c_ubyte,
           "short": ctypes.c_short,
           "unsigned short": ctypes.c_ushort,
           "int": ctypes.c_int,
           "unsigned int": ctypes.c_uint,
           "long": ctypes.c_long,
           "unsigned long": ctypes.c_ulong,
           "long long": ctypes.c_longlong,
           "unsigned long long": ctypes.c_ulonglong,
           "size_t": ctypes.c_size_t,
           "ssize_t": ctypes.c_ssize_t,
           "float": ctypes.c_float,
           "double": ctypes.c_double,
           "long double": ctypes.c_longdouble,
           "char*": ctypes.c_char_p,
           "wchar_t*": ctypes.c_wchar_p,
           "void*": ctypes.c_void_p,
           "int32_t": ctypes.c_int32,
           "uint32_t": ctypes.c_uint32,
           "int64_t": ctypes.c_int64,
           "uint64_t": ctypes.c_uint64,
           "BYTE": wintypes.BYTE,
           "DWORD": wintypes.DWORD,
           "ULONG": wintypes.ULONG,
           "WORD": wintypes.WORD}


class CIntEnum(IntEnum):
    def from_param(self):
        return ctypes.c_int(int(self))

    @staticmethod
    def as_ctype():
        return ctypes.c_int


class CUIntEnum(IntEnum):
    def from_param(self):
        return ctypes.c_uint(int(self))

    @staticmethod
    def as_ctype():
        return ctypes.c_uint


def as_ctype(type):
    """Unwraps an IntEnum type into a C type.
    """
    return getattr(type, "as_ctype", lambda: type)()


class ParseError(Exception):
    """Raised by unparseable constructs.
    """


class Parse(namedtuple("_Parse", "constants enums structs fundecls")):
    """The result of the parsing of a C header.
    """

    def export_for_pydoc(self, module_globals):
        """Export a parse to a module's global dict.
        """
        module_all = module_globals.setdefault("__all__", [])
        for k, v in sorted(self.constants.items()):
            module_globals[k] = v
            module_all.append(k)
        for k, v in sorted(self.enums.items()):
            module_globals[k] = v
            module_all.append(k)
        for fname, (argtypes, argtuple, restype) in sorted(
            self.fundecls.items()):
            prototype = "def {}{}: pass".format(
                fname, inspect.formatargspec(argtuple._fields))
            d = {}
            exec(prototype, globals(), d)
            func = d[fname]
            for arg, argtype in zip(argtuple._fields, argtypes):
                func.__annotations__[arg] = argtype
            func.__annotations__["return"] = restype
            module_globals[fname] = func
            module_all.append(fname)


class Parser:
    """A stateful C header parser.

    An instance of the parser keeps tracks of the ``#defines``, whether of
    constants or of types (no other preprocessor macro is handled).
    """

    def __init__(self, *fnames, compiler="gcc"):
        self.types = C_TYPES
        self.constants = {}
        lines = []
        for fname in fnames:
            with open(fname) as f:
                lines.extend(line.split("//")[0] for line in f)
                self.header = re.sub(
                    r"/\*.*?\*/", "", "".join(lines), flags=re.DOTALL)
        if compiler not in ("gcc", "msvc"):
            raise ValueError("Unknown compiler")
        self.compiler = compiler

    def parse(self):
        """Parse the header file.

        Four mappings are returned in a single namespace object: constants,
        enum typedefs, struct typedefs and function declarations.

        Constants are mapped onto their value, with ``#define``'s with no value
        mapped to None.  Structs are mapped onto ctypes structs.  Functions
        are mapped onto ``((type, ...), namedtuple, restype)`` triplets, where
        each namedtuple's fields are the names of the arguments.

        Definitions that include unknown types are silently ignored.
        """
        return Parse(constants=self.parse_defines(),
                     enums=self.parse_enums(),
                     structs=self.parse_structs(),
                     fundecls=self.parse_functions())

    def parse_decl(self, decl):
        """Parse a type name as a :mod:`ctypes` type and identifier pair.
        """
        array_match = re.search(r"\[(.+?)\]$", decl)
        if array_match:
            decl = decl[:array_match.start()]
            array_size = eval(array_match.group(1), {}, dict(self.constants))
        else:
            array_size = None
        ident_match = re.search(r"\w+$", decl)
        if not ident_match:
            raise ParseError
        ident = ident_match.group()
        type_s = decl[:ident_match.start()]
        pointed_to = type_s.rstrip("* ")
        n_stars = type_s[len(pointed_to):].count("*")
        pointed_to = " ".join(el for el in pointed_to.split() if el != "const")
        if pointed_to in ("char", "wchar_t", "void") and n_stars >= 1:
            pointed_to += "*"
            n_stars -= 1
        try:
            ctype = self.types[pointed_to]
        except KeyError:
            raise ParseError
        if n_stars:
            ctype = as_ctype(ctype)
        for _ in range(n_stars):
            ctype = ctypes.POINTER(ctype)
        if array_size is not None:
            ctype = ctype * array_size
        return ctype, ident

    def parse_defines(self):
        """Parse ``#define``'s of constants and of types.
        """
        for line in self.header.splitlines():
            if line.lower().startswith("#define"):
                _, line = line.strip().split(None, 1) # remove #define
                if " " in line:
                    symbol, value = line.split(None, 1)
                    if value.isdigit():
                        value = int(value)
                    elif value.startswith("0x"):
                        value = int(value, 16)
                    elif value in self.types:
                        self.types[symbol] = self.types[value]
                else:
                    symbol = line
                    value = ""
                self.constants[symbol] = value
        return self.constants

    def parse_enums(self):
        """Parse ``typedef enum``'s.
        """
        # Notes on enum types
        #
        # GCC:
        #
        # Normally, the type is unsigned int if there are no negative values in
        # the enumeration, otherwise int. If -fshort-enums is specified, then
        # if there are negative values it is the first of signed char, short
        # and int that can represent all the values, otherwise it is the first
        # of unsigned char, unsigned short and unsigned int that can represent
        # all the values.
        #
        # On some targets, -fshort-enums is the default; this is determined by
        # the ABI.
        #
        # MSVC:
        #
        # A variable declared as enum is an int [32-bit].
        enums = {}
        entry_re = re.compile(r"\s*(\w+)\s*(?:=\s*(\w+)\s*)?")
        for entries, enumname in re.findall(
            r"typedef\s+enum\s+\w*\s*{([^}]*)}\s*(\w+)\s*;", self.header,
            re.DOTALL):
            if self.compiler == "msvc":
                underlying_type = ctypes.c_int
            elif self.compiler == "gcc":
                underlying_type = ctypes.c_uint
            values = []
            for entry in entries.split(","):
                name, value = re.match(entry_re, entry).groups()
                value = eval(value) if value is not None else (
                    values[-1][1] + 1 if values else 0)
                if value < 0:
                    underlying_type = ctypes.c_int
                values.append((name, value))
            enum_type = {ctypes.c_int: CIntEnum,
                         ctypes.c_uint: CUIntEnum}[underlying_type]
            self.types[enumname] = enums[enumname] = enum_type(enumname, values)
        return enums

    def parse_structs(self):
        """Parse ``typedef struct``'s.
        """
        structs = {}
        for fields, structname in re.findall(
            r"typedef\s+struct\s+\w*\s*{([^}]*)}\s*(\w+)\s*;", self.header,
            re.DOTALL):
            fieldtypes = []
            fieldnames = []
            for field in fields.split(";"):
                field = field.strip()
                if not field:
                    continue
                fieldtype, fieldname = self.parse_decl(field)
                fieldtypes.append(fieldtype)
                fieldnames.append(fieldname)
            struct = type(
                str(structname),
                (ctypes.Structure,),
                {"_fields_": list(zip(fieldnames, map(as_ctype, fieldtypes)))})
            struct.__doc__ = "\n".join(
                "{0}: {1}".format(field, type.__name__)
                for field, type in zip(fieldnames, fieldtypes))
            self.types[structname] = structs[structname] = struct
        return structs

    def parse_functions(self):
        """Parse function declarations
        """
        fundecls = {}
        for prefix, fname, proto in re.findall(
            r"^(.+?\s+)?(\w+)\s*\(([\w\*\s,]+)\);", self.header, re.MULTILINE):
            prefix = " ".join(self.constants.get(word, word)
                              for word in prefix.split()).strip()
            if prefix == "void":
                restype = None
            else:
                restype, _ = self.parse_decl(prefix + " _")
                assert _ == "_"
            argtypes = []
            argnames = []
            for argspec in proto.split(","):
                argspec = argspec.strip()
                if argspec == "void":
                    continue
                argtype, argname = self.parse_decl(argspec)
                argtypes.append(argtype)
                argnames.append(argname)
            fundecls[fname] = argtypes, namedtuple("args", argnames), restype
        return fundecls


def deref(obj):
    """Cast a ctypes object or byref into a Python object.
    """
    try:
        return obj._obj.value # byref
    except AttributeError:
        try:
            return obj.value # plain ctypes
        except AttributeError:
            return obj # plain python


class DLLError(Exception):
    """Raised when a DLL function returns a non-success exit code.
    """

    def __init__(self, code):
        self.code = code


class DLL:
    """A wrapper for a `ctypes` DLL object.
    """

    def __init__(self, dll, parse, success_code):
        self._dll = dll
        self._fundecls = parse.fundecls
        for fname in parse.fundecls:
            self._set_success_codes(fname, [success_code])

    def _set_success_codes(self, fname, success_codes):
        """Add a method with specific success codes.
        """
        func = getattr(self._dll, fname)
        argtypes, func.argtuple_t, restype = self._fundecls[fname]
        argtypes = [argtype
            if not (isinstance(argtype, type(ctypes.POINTER(ctypes.c_int))) and
                    argtype._type_.__module__ != "ctypes") # remove struct (nested) pointers
            else ctypes.c_voidp for argtype in argtypes]
        func.argtypes = argtypes
        try:
            success_code_type, = set(type(code) for code in success_codes)
        except ValueError:
            raise AssertionError("Success code of different types")
        if success_code_type == restype:
            func.success_codes = success_codes
            func.errcheck = errcheck
        else:
            func.restype = restype
        setattr(self, fname, func)

    def _prohibit(self, fname):
        """Hide a DLL function.
        """
        @functools.wraps(getattr(cls, fname))
        def prohibited(*args, **kwargs):
            raise AttributeError(
                "{} is not a public function of the DLL".format(fname))
        setattr(self, fname, prohibited)


def errcheck(retcode, func, args):
    """Return all (deref'ed) arguments on success, raise exception on failure.
    """
    if retcode in func.success_codes:
        return func.argtuple_t(*[deref(arg) for arg in args])
    else:
        raise DLLError(type(func.success_codes[0])(retcode))
