"""
monobit.formats.raw - raw binary font files

(c) 2019--2022 Rob Hagemans
licence: https://opensource.org/licenses/MIT
"""

import logging

from ..binary import ceildiv, bytes_to_bits
from ..storage import loaders, savers
from ..font import Font
from ..glyph import Glyph
from ..raster import Raster
from ..streams import FileFormatError
from ..basetypes import Coord


@loaders.register('bin', 'rom', 'raw', name='binary')
def load_binary(
        instream, where=None, *,
        cell:Coord=(8, 8), count:int=-1, offset:int=0, padding:int=0,
        align:str='left', strike_count:int=1, strike_bytes:int=-1,
        first_codepoint:int=0
    ):
    """
    Load character-cell font from binary bitmap.

    cell: size X,Y of character cell (default: 8x8)
    offset: number of bytes in file before bitmap starts (default: 0)
    padding: number of bytes between encoded glyph rows (default: 0)
    count: number of glyphs to extract (<= 0 means all; default: all)
    strike_count: number of glyphs in glyph row (<=0 for all; default: 1)
    strike_bytes: strike width in bytes (<=0 means as many as needed to fit the glyphs; default: as needed)
    align: alignment of strike row ('left' for most-, 'right' for least-significant; 'bit' for bit-aligned; default: 'left')
    first_codepoint: first code point in bitmap (default: 0)
    """
    width, height = cell
    # get through the offset
    # we don't assume instream is seekable - it may be sys.stdin
    instream.read(offset)
    return load_bitmap(
        instream, width, height, count, padding, align, strike_count, strike_bytes, first_codepoint
    )

def save_bitmap(
        outstream, font, *,
        strike_count:int=1, align:str='left', padding:int=0,
    ):
    """
    Save character-cell fonts to binary bitmap.

    strike_count: number of glyphs in glyph row (<=0 for all; default: 1)
    align: alignment of strike row ('left' for most-, 'right' for least-significant; 'bit' for bit-aligned; default: 'left')
    padding: number of bytes between encoded glyph rows (default: 0)
    """
    for font in fonts:
        save_bitmap(outstream, font)


###############################################################################
# raw 8x14 format
# CHET .814 - http://fileformats.archiveteam.org/wiki/CHET_font

@loaders.register('814', name='chet')
def load_pcr(instream, where=None):
    """Load a raw 8x14 font."""
    return load_binary(instream, where, cell=(8, 14), count=256)


###############################################################################
# raw 8x8 format
# https://www.seasip.info/Unix/PSF/Amstrad/UDG/index.html

@loaders.register('64c', 'udg', name='8x8')
def load_8x8(instream, where=None):
    """Load a raw 8x8 font."""
    return load_binary(instream, where, cell=(8, 8), count=256)

# https://www.seasip.info/Unix/PSF/Amstrad/Genecar/index.html
# GENECAR included three fonts in a format it calls .CAR. This is basically a
# raw dump of the font, but using a 16×16 character cell rather than the usual 16×8.
@loaders.register('car', name='16x16')
def load_16x16(instream, where=None):
    """Load a raw 16x16 font."""
    return load_binary(instream, where, cell=(16, 16))


###############################################################################
# raw 8xN format with height in suffix
# guess we won't have them less than 4 or greater than 31

from pathlib import PurePath

_F_SUFFIXES = tuple(f'f{_height:02}' for _height in range(4, 32))

@loaders.register(*_F_SUFFIXES, name='8xn')
def load_8xn(instream, where=None):
    """Load a raw 8x14 font."""
    suffix = PurePath(instream.name).suffix
    try:
        height = int(suffix[2:])
    except ValueError:
        height=8
    return load_binary(instream, where, cell=(8, height))


###############################################################################
# raw formats we can't easily recognise from suffix or magic

# degas elite .fnt, 8x16x128, + flags, 2050 bytes https://temlib.org/AtariForumWiki/index.php/DEGAS_Elite_Font_file_format
# warp 9 .fnt, 8x16x256 + flags, 4098 bytes https://temlib.org/AtariForumWiki/index.php/Warp9_Font_file_format
# however not all have the extra word

# Harlekin III .fnt - "Raw font data line by line, 8x8 (2048 bytes) or 8x16 (4096 bytes) only."
# https://temlib.org/AtariForumWiki/index.php/Fonts
# i.e. this is a wide-strike format, load width -strike-count=-1


###############################################################################
# OPTIKS PCR - near-raw format
# http://fileformats.archiveteam.org/wiki/PCR_font
# http://cd.textfiles.com/simtel/simtel20/MSDOS/GRAPHICS/OKF220.ZIP
# OKF220.ZIP → OKFONTS.ZIP → FONTS.DOC - Has an overview of the format.
# > I have added 11 bytes to the head of the file
# > so that OPTIKS can identify it as a font file. The header has
# > a recognition pattern, OPTIKS version number and the size of
# > the font file.

from ..struct import little_endian as le

_PCR_HEADER = le.Struct(
    magic='7s',
    # maybe it's a be uint16 of the file size, followed by the same size as le
    # anyway same difference
    height='uint8',
    zero='uint8',
    bytesize='uint16',
)

@loaders.register('pcr', name='pcr', magic=(b'KPG\1\2\x20\1', b'KPG\1\1\x20\1'))
def load_pcr(instream, where=None):
    """Load an OPTIKS .PCR font."""
    header = _PCR_HEADER.read_from(instream)
    font = load_binary(instream, where, cell=(8, header.height), count=256)
    font = font.modify(source_format='Optiks PCR')
    return font



###############################################################################
# REXXCOM Font Mania
# raw bitmap with DOS .COM header
# http://fileformats.archiveteam.org/wiki/Font_Mania_(REXXCOM)

from ..struct import little_endian as le

# guessed by inspecion, with reference to Intel 8086 opcodes
_FM_HEADER = le.Struct(
    # JMP SHORT opcode 0xEB
    jmp='uint8',
    # signed jump target - 0x4b or 0x4e
    code_offset='int8',
    bitmap_offset='uint16',
    bitmap_size='uint16',
    # seems to be always 0x2000 le, i.e. b'\0x20'.
    nul_space='2s',
    version_string='62s',
    # 'FONT MANIA, VERSION 1.0 \r\n COPYRIGHT (C) REXXCOM SYSTEMS, 1991'
    # 'FONT MANIA, VERSION 2.0 \r\n COPYRIGHT (C) REXXCOM SYSTEMS, 1991'
    # 'FONT MANIA, VERSION 2.2 \r\n COPYRIGHT (C) 1992  REXXCOM SYSTEMS'
)

# the version string would be a much better signature, but we need an offset
@loaders.register(
    #'com',
    name='mania', magic=(b'\xEB\x4D', b'\xEB\x4E')
)
def load_mania(instream, where=None):
    """Load a REXXCOM Font Mania font."""
    header = _FM_HEADER.read_from(instream)
    logging.debug('Version string %r', header.version_string.decode('latin-1'))
    font = load_binary(
        instream, where,
        offset=header.bitmap_offset - header.size,
        cell=(8, header.bitmap_size//256),
        count=256
    )
    font = font.modify(source_format='DOS loader (REXXCOM Font Mania)')
    return font


###############################################################################
# psftools PSF2AMS font loader
# raw bitmap with Z80 CP/M loader, prefixed with a DOS stub, 512-bytes offset
# https://github.com/ZXSpectrumVault/john-elliot/blob/master/psftools/tools/psf2ams.c
# /* Offsets in PSFCOM:
#  * 0000-000E  Initial code
#  * 000F-002D  Signature
#  * 002E-002F  Length of font, bytes (2k or 4k)
#  * 0030-0031  Address of font */

#_PSFCOM_STUB = bytes.fromhex('eb04 ebc3 ???? b409 ba32 01cd 21cd 20')
_PSFCOM_SIG08 = b'\rFont converted with PSF2AMS\r\n\032'
_PSFCOM_SIG16 = b'\rFont Converted with PSF2AMS\r\n\032'
_PSFCOM_HEADER = le.Struct(
    code='15s',
    sig='31s',
    bitmap_size='uint16',
    # apparently the offset to the space char, but 0-31 are defined before that
    # so this is the offset - 0x100 ?
    address='uint16',
)

@loaders.register(
    #'com',
    name='psfcom',
    magic=(b'\xeb\x04\xeb\xc3',)
)
def load_psfcom(instream, where=None):
    """Load a PSFCOM font."""
    header = _PSFCOM_HEADER.read_from(instream)
    logging.debug('Version string %r', header.sig.decode('latin-1'))
    if header.sig == _PSFCOM_SIG16:
        height = 16
    else:
        height = 8
    font = load_binary(
        instream, where,
        offset=header.address - header.size - 0x100,
        cell=(8, height),
    )
    font = font.modify(
        source_format='Amstrad/Spectrum CP/M loader (PSFCOM)',
        encoding='amstrad-cpm-plus',
    )
    font = font.label()
    return font


###############################################################################
###############################################################################
# bitmap reader

def load_bitmap(
        instream, width, height, count=-1, padding=0, align='left',
        strike_count=1, strike_bytes=-1, first_codepoint=0,
    ):
    """Load fixed-width font from bitmap."""
    data, count, cells_per_row, bytes_per_row, nrows = _extract_data_and_geometry(
        instream, width, height, count, padding, strike_count, strike_bytes,
    )
    cells = _extract_cells(
        data, width, height, align, cells_per_row, bytes_per_row, nrows
    )
    # reduce to given count, if exceeded
    cells = cells[:count]
    # assign codepoints
    glyphs = tuple(
        Glyph(_cell, codepoint=_index)
        for _index, _cell in enumerate(cells, first_codepoint)
    )
    return Font(glyphs)


def _extract_data_and_geometry(
        instream, width, height, count=-1, padding=0,
        strike_count=1, strike_bytes=-1,
    ):
    """Determine geometry from defaults and data size."""
    data = None
    # determine byte-width of the bitmap strike rows
    if strike_bytes <= 0:
        if strike_count <= 0:
            data = instream.read()
            strike_bytes = len(data) // height
        else:
            strike_bytes = ceildiv(strike_count*width, 8)
    else:
        strike_count = -1
    # deteermine number of cells per strike row
    if strike_count <= 0:
        strike_count = (strike_bytes * 8) // width
    # determine bytes per strike row
    row_bytes = strike_bytes*height + padding
    # determine number of strike rows
    if count is None or count <= 0:
        if not data:
            data = instream.read()
        # get number of chars in extract
        nrows = ceildiv(len(data), row_bytes)
        count = nrows * strike_count
    else:
        nrows = ceildiv(count, strike_count)
        if not data:
            data = instream.read(nrows * row_bytes)
    # we may exceed the length of the rom because we use ceildiv, pad with nulls
    data = data.ljust(nrows * row_bytes, b'\0')
    if nrows == 0 or row_bytes == 0:
        return Font()
    return data, count, strike_count, row_bytes, nrows


def _extract_cells(
        data, width, height, align, cells_per_row, bytes_per_row, nrows
    ):
    """Extract glyphs from bitmap strike with given geometry."""
    # extract one strike row at a time
    # note that the strikes may not be immediately contiguous if there's padding
    glyphrows = (
        Raster.from_bytes(
            data[_i*bytes_per_row : (_i+1)*bytes_per_row],
            width*cells_per_row, height,
            align=align
        )
        for _i in range(nrows)
    )
    # clip out glyphs
    cells = tuple(
        _glyphrow.crop(
            left=_i*width,
            right=_glyphrow.width - (_i+1)*width
        )
        for _glyphrow in glyphrows
        for _i in range(cells_per_row)
    )
    return cells


###############################################################################
###############################################################################
# bitmap writer

def save_bitmap(
        outstream, font, *,
        strike_count:int=1, align:str='left', padding:int=0,
    ):
    """
    Save character-cell font to binary bitmap.

    strike_count: number of glyphs in glyph row (<=0 for all; default: 1)
    align: alignment of strike row ('left' for most-, 'right' for least-significant; 'bit' for bit-aligned; default: 'left')
    padding: number of bytes between encoded glyph rows (default: 0)
    """
    if font.spacing != 'character-cell':
        raise FileFormatError(
            'This format only supports character-cell fonts.'
        )
    # TODO: normalise
    # get pixel rasters
    rasters = (_g.pixels for _g in font_glyphs)
    # contruct rows (itertools.grouper recipe)
    args = [iter(_g)] * strike_count
    grouped = zip_longest(*args, fillvalue=Glyph())
    glyphrows = (
        Raster.concatenate(*_row)
        for _row in grouped
    )
    for glyphrow in glyphrows:
        outstream.write(glyphrow.as_bytes(align=align))
        outstream.write(b'\0' * padding)
