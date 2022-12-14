"""
monobit.formats.daisydot - Daisy Dot II/III NLQ format

(c) 2022 Rob Hagemans
licence: https://opensource.org/licenses/MIT
"""

import logging

from ..struct import big_endian as be
from ..storage import loaders, savers
from ..font import Font
from ..glyph import Glyph
from ..raster import Raster
from ..streams import FileFormatError
from ..binary import bytes_to_bits


_DD2_MAGIC = b'DAISY-DOT NLQ FONT\x9b'
_DD3_MAGIC = b'3\x9b'

_DD_RANGE = tuple(_c for _c in range(32, 125) if _c not in (96, 123))


@loaders.register('nlq', name='daisy', magic=(_DD2_MAGIC, _DD3_MAGIC))
def load_daisy(instream, where=None):
    """Load font from fontx file."""
    props, glyphs = _read_daisy(instream)
    # logging.info('daisy properties:')
    # for line in str(props).splitlines():
    #     logging.info('    ' + line)
    return Font(glyphs, **props)


################################################################################
# daisy-dot II and III binary formats

# https://archive.org/stream/daisydotiiii/Daisy%20Dot%20III_djvu.txt

_DD3_FINAL = be.Struct(
    height='uint8',
    underline='uint8',
    space_width='uint8',
)

def _read_daisy(instream):
    """Read daisy-dot binary file and return glyphs."""
    data = instream.read()
    if data.startswith(_DD2_MAGIC):
        return _parse_daisy2(data)
    elif data.startswith(_DD3_MAGIC):
        return _parse_daisy3(data)
    raise FileFormatError(
        'Not a Daisy-Dot file: magic does not match either version'
    )

def _parse_daisy2(data):
    """Read daisy-dot II binary file and return glyphs."""
    ofs = len(_DD2_MAGIC)
    glyphs = []
    for cp in _DD_RANGE:
        width = data[ofs]
        if width < 1 or width > 19:
            logging.warning('Glyph width outside of allowed values, continuing')
        pass0 = bytes_to_bits(data[ofs+1:ofs+width+1])
        pass1 = bytes_to_bits(data[ofs+width+1:ofs+2*width+1])
        bits = tuple(_b for _pair in zip(pass0, pass1) for _b in _pair)
        glyphs.append(
            Glyph.from_vector(bits, stride=16, codepoint=cp)
            .transpose(adjust_metrics=False)
        )
        # separated by a \x9b
        ofs += 2*width + 2
    props = dict(
        right_bearing=1,
        line_height=20,
        source_format='Daisy-Dot II'
    )
    return props, glyphs


def _parse_daisy3(data):
    """Read daisy-dot III binary file and return glyphs."""
    ofs = len(_DD3_MAGIC)
    glyphs = []
    # dd3 does not store space glyph
    for cp in _DD_RANGE[1:]:
        double, width = divmod(data[ofs], 64)
        ofs += 1
        if width < 1 or width > 32:
            logging.warning('Glyph width outside of allowed values, continuing')
        double = bool(double)
        passes = [
            bytes_to_bits(data[ofs:ofs+width]),
            bytes_to_bits(data[ofs+width:ofs+2*width])
        ]
        bits = tuple(_b for _tup in zip(*passes) for _b in _tup)
        matrix = Raster.from_vector(bits, stride=16).transpose().as_matrix()
        ofs += 2*width
        if double:
            passes = [
                bytes_to_bits(data[ofs:ofs+width]),
                bytes_to_bits(data[ofs+width:ofs+2*width])
            ]
            ofs += 2*width
            bits = tuple(_b for _tup in zip(*passes) for _b in _tup)
            matrix += (
                Raster.from_vector(bits, stride=16).transpose().as_matrix()
            )
        glyphs.append(Glyph(matrix, codepoint=cp))
        # in dd3, not separated by a \x9b
    dd3_props = _DD3_FINAL.from_bytes(data, ofs)
    # extend non-doubled glyphs
    height = max(_g.height for _g in glyphs)
    glyphs = [
        _g.expand(bottom=height-_g.height, adjust_metrics=False)
        for _g in glyphs
    ]
    # create space glyph
    space = Glyph.blank(
        width=dd3_props.space_width, height=height, codepoint=0x20,
    )
    glyphs = [space, *glyphs]
    # metrics
    pixel_size = dd3_props.height+1
    # we're using the underline as an indicator of where the baseline is
    descent = dd3_props.height-dd3_props.underline+2
    props = dict(
        right_bearing=1,
        source_format='Daisy-Dot III',
        # > Each DD3 font can be up to 32 rows high. However, If a font you are
        # > designing Is smaller than that, DD3 allows you to specify the actual
        # > height of the character so line spacing within the main printing
        # > program will match the size of the characters. The height marker can
        # > range from the second row (referred to as row 1) to the last row (row
        # > 31).
        shift_up=pixel_size-height-descent,
        ascent=pixel_size-descent,
        descent=descent,
        underline_descent=1,
        # > In Daisy-Dot III, line spacing is the vertical space, measured in units
        # > of 1/72", from the bottom of one line to the top of the next. Note that
        # > this is different from line spacing's typical definition, the space from
        # > the top of one line to the top of the next. The default line spacing is
        # > 4.
        line_height=pixel_size+4,
    )
    return props, glyphs
