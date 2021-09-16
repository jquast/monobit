"""
monobit.formats - loader and saver plugin registry

(c) 2019 Rob Hagemans
licence: https://opensource.org/licenses/MIT
"""

import gzip
import io
import sys
import logging
from pathlib import Path


def open_stream(file, mode, binary, *, on=None):
    """Ensure file is a stream of the right type, open or wrap if necessary."""
    # path is a path-like object
    # mode is 'r' or 'w'
    # binary is a boolean; open as binary if true, as text if false
    # on: container to open any new stream on
    mode = mode[:1]
    if not file and not on:
        # nameless stream on filesystem -> stdio
        file = stdio_stream(mode, binary=True)
    elif isinstance(file, (str, bytes, Path)):
        # if a path is provided, open a (binary) stream
        if not on:
            file = io.open(file, mode + 'b')
        else:
            file = on.open_binary(file, mode)
    # wrap compression/decompression if needed
    file = open_compressed_stream(file)
    # override gzip's mode values which are numeric
    if mode == 'r' and not file.readable():
        raise ValueError('Expected readable stream, got writable.')
    if mode == 'w' and not file.writable():
        raise ValueError('Expected writable stream, got readable.')
    # check text/binary
    # a text format can be read from/written to a binary stream with a wrapper
    # but vice versa can't be done
    if not is_binary(file) and binary:
        raise ValueError('Expected binary stream, got text stream.')
    if is_binary(file) and not binary:
        file = make_textstream(file)
    return file

def make_textstream(file, *, encoding=None):
    """Wrap binary stream to create text stream."""
    encoding = 'utf-8-sig' if file.readable() else 'utf-8'
    return io.TextIOWrapper(file, encoding=encoding)

def stdio_stream(mode, binary):
    """Get standard stream for given mode and text/binary type."""
    if mode == 'w':
        if binary:
            return sys.stdout.buffer
        return sys.stdout
    if binary:
        return sys.stdin.buffer
    return sys.stdin

def is_binary(instream):
    """Check if readable stream is binary."""
    if instream.readable():
        # read 0 bytes - the return type will tell us if this is a text or binary stream
        return isinstance(instream.read(0), bytes)
    # write empty bytes - error if text stream
    try:
        instream.write(b'')
    except TypeError:
        return False
    return True


###################################################################################################
# magic byte sequences

def has_magic(instream, magic):
    """Check if a binary stream matches the given signature."""
    try:
        return instream.peek(len(magic)).startswith(magic)
    except EnvironmentError:
        # e.g. write-only stream
        return False

class MagicRegistry:
    """Registry of file types and their magic sequences."""

    def __init__(self):
        """Set up registry."""
        self._magic = {}
        self._suffixes = {}

    def register(self, suffix, magic):
        """Decorator to register class that handles file type."""
        def decorator(klass):
            if suffix:
                self._suffixes[suffix.lower()] = klass
            if magic:
                self._magic[magic] = klass
            return klass
        return decorator

    def get(self, suffix):
        """Get type from suffix."""
        return self._suffixes.get(suffix.lower(), None)

    def identify(self, file):
        """Identify a type from magic sequence on input file."""
        if not file or isinstance(file, (str, bytes, Path)):
            # only use context manager if string provided
            # if we got an open stream we should not close it
            with open_stream(file, 'r', binary=True) as stream:
                return self.identify(stream)
        # can't read magic on write-only file
        if not file.readable():
            return None
        for magic, klass in self._magic.items():
            if has_magic(file, magic):
                return klass

        return None


###################################################################################################
# compression helpers

_compressors = MagicRegistry()
_compressors.register('.gz', b'\x1f\x8b')(gzip)


def open_compressed_stream(file):
    """Identify and wrap compressed streams."""
    compressor = _compressors.identify(file)
    if not compressor:
        try:
            suffix = Path(file.name).suffix
        except AttributeError:
            suffix = ''
        compressor = _compressors.get(suffix)
    if compressor:
        file = compressor.open(file, file.mode[:1] + 'b')
    return file
