"""
monobit.cpi - read and write .cpi font files

(c) 2019 Rob Hagemans
licence: https://opensource.org/licenses/MIT
"""

import os
import logging

from .base import Glyph, Font, Typeface, ceildiv, friendlystruct, VERSION
from .raw import parse_aligned


_CPI_HEADER = friendlystruct(
    'le',
    id0='byte',
    id='7s',
    reserved='8s',
    pnum='short',
    ptyp='byte',
    fih_offset='long',
)
_FONT_INFO_HEADER = friendlystruct(
    'le',
    num_codepages='short',
)
_CODEPAGE_ENTRY_HEADER = friendlystruct(
    'le',
    cpeh_size='short',
    next_cpeh_offset='long',
    device_type='short',
    device_name='8s',
    codepage='short',
    reserved='6s',
    cpih_offset='long',
)
# device types
_DT_SCREEN = 1
_DT_PRINTER = 2
# early printer devices that may erroneously have a device_type of 1
#_PRINTERS = ('4201', '4208', '5202', '1050')

# version for CP resource
_CP_FONT = 1
_CP_DRFONT = 2

_CODEPAGE_INFO_HEADER = friendlystruct(
    'le',
    version='short',
    num_fonts='short',
    size='short',
)
_PRINTER_FONT_HEADER = friendlystruct(
    'le',
    printer_type='short',
    escape_length='short',
)
_SCREEN_FONT_HEADER = friendlystruct(
    'le',
    height='byte',
    width='byte',
    yaspect='byte',
    xaspect='byte',
    num_chars='short',
)

# DRDOS Extended Font File Header
def drdos_ext_header(num_fonts_per_codepage=0):
    return friendlystruct(
        'le',
        num_fonts_per_codepage='byte',
        font_cellsize=friendlystruct.uint8 * num_fonts_per_codepage,
        dfd_offset=friendlystruct.uint32 * num_fonts_per_codepage,
    )
# DRFONT character index table
_CHARACTER_INDEX_TABLE = friendlystruct(
    'le',
    FontIndex=friendlystruct.int16 * 256,
)


@Typeface.loads('cpi', encoding=None)
def load(instream):
    """Load fonts from CPI file."""
    data = instream.read()
    fonts = _parse_cpi(data)
    for font in fonts:
        font._properties['source-name'] = os.path.basename(instream.name)
    return Typeface(fonts)

@Typeface.saves('cpi', encoding=None)
def save(typeface, outstream):
    """Save fonts to CPI file."""
    return typeface


def _parse_cpi(data):
    """Parse CPI data."""
    cpi_header = _CPI_HEADER.from_bytes(data)
    logging.info(cpi_header.id)
    if cpi_header.id0 == 0xff and cpi_header.id == b'FONT   ':
        return _parse_font(data)
    if cpi_header.id0 == 0xff and cpi_header.id == b'FONT.NT':
        return _parse_font(data, nt=True)
    if cpi_header.id0 == 0x7f and cpi_header.id == b'DRFONT ':
        return _parse_font(data, dr=True)
    raise ValueError('Unrecognised CPI signature. Not a valid CPI file.')

def _parse_font(data, nt=False, dr=False):
    """Parse CPI data in FONT, FONT.NT or DRFONT format."""
    cpi_header = _CPI_HEADER.from_bytes(data)
    if dr:
        # read the extended DRFONT header - determine size first
        drdos_effh = drdos_ext_header().from_bytes(data, _CPI_HEADER.size)
        drdos_effh = drdos_ext_header(drdos_effh.num_fonts_per_codepage).from_bytes(
            data, _CPI_HEADER.size
        )
    else:
        drdos_effh = None
    fih = _FONT_INFO_HEADER.from_bytes(data, cpi_header.fih_offset)
    cpeh_offset = cpi_header.fih_offset + _FONT_INFO_HEADER.size
    # run through the linked list and parse fonts
    fonts = []
    for cp in range(fih.num_codepages):
        font, cpeh_offset = _parse_cp(data, cpeh_offset, nt=nt, drdos_effh=drdos_effh)
        fonts.append(font)
    return fonts

def _parse_cp(data, cpeh_offset, drdos_effh=None, nt=False):
    """Parse a .CP codepage."""
    cpeh = _CODEPAGE_ENTRY_HEADER.from_bytes(data, cpeh_offset)
    if nt:
        # fix relative offsets in FONT.NT
        cpeh.cpih_offset += cpeh_offset
        cpeh.next_cpeh_offset += cpeh_offset
        fmt_id = 'Windows NT'
    elif drdos_effh:
        fmt_id = 'DR-DOS'
    else:
        fmt_id = 'MS-DOS'
    cpih = _CODEPAGE_INFO_HEADER.from_bytes(data, cpeh.cpih_offset)
    # offset to the first font header
    fh_offset = cpeh.cpih_offset + _CODEPAGE_INFO_HEADER.size
    # handle Toshiba fonts
    if cpih.version == 0:
        cpih.version = _CP_FONT
    # printer CPs have one font only
    if cpeh.device_type == _DT_PRINTER:
        cpih.num_fonts = 1
        # TODO: parse printer font
        props = {}
        cells = []
    else:
        # char table offset for drfont
        if cpih.version ==_CP_DRFONT:
            cit_offset = fh_offset + cpih.num_fonts * _SCREEN_FONT_HEADER.size
        for cp_index in range(cpih.num_fonts):
            fh = _SCREEN_FONT_HEADER.from_bytes(data, fh_offset)
            # extract font properties
            props = {
                'encoding': 'cp{}'.format(cpeh.codepage),
                'device': cpeh.device_name.strip().decode('ascii', 'replace'),
                'size': '{} {}'.format(fh.width, fh.height),
                'converter': 'monobit v{}'.format(VERSION),
                'source-format': 'CPI ({})'.format(fmt_id),
            }
            # apparently never used
            if fh.xaspect or fh.yaspect:
                # not clear how this would be interpreted...
                props['cpi.xaspect'] = str(fh.xaspect)
                props['cpi.yaspect'] = str(fh.yaspect)
            # get the bitmap
            if cpih.version == _CP_FONT:
                # bitmaps follow font header
                bm_offset = fh_offset + _SCREEN_FONT_HEADER.size
                cells = parse_aligned(data, fh.width, fh.height, fh.num_chars, bm_offset)
                fh_offset = bm_offset + fh.num_chars * fh.height * ceildiv(fh.width, 8)
            else:
                # DRFONT bitmaps
                cells = []
                cit = _CHARACTER_INDEX_TABLE.from_bytes(data, cit_offset)
                for ord, fi in zip(range(fh.num_chars), cit.FontIndex):
                    bm_offs_char = (
                        fi * drdos_effh.font_cellsize[cp_index] + drdos_effh.dfd_offset[cp_index]
                    )
                    cells.append(Glyph.from_bytes(
                        data[bm_offs_char : bm_offs_char+drdos_effh.font_cellsize[cp_index]],
                        fh.width
                    ))
                fh_offset += _SCREEN_FONT_HEADER.size
    font = Font(cells, properties=props)
    return font, cpeh.next_cpeh_offset
