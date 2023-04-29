"""
monobit.formats.mac.nfnt - Mac FONT/NFNT fonts

(c) 2019--2023 Rob Hagemans
licence: https://opensource.org/licenses/MIT

NFNT writer based on the Apple IIgs writer
(c) 2023 Kelvin Sherlock
licence: https://opensource.org/licenses/MIT
"""

import logging
from itertools import chain, accumulate

from ...binary import bytes_to_bits
from ...struct import bitfield, big_endian as be, little_endian as le
from ...font import Font
from ...glyph import Glyph, KernTable
from ...magic import FileFormatError
from ...labels import Char
from ...encoding import charmaps
from ...raster import Raster


##############################################################################
# NFNT/FONT resource

# the Font Type Element
# https://developer.apple.com/library/archive/documentation/mac/Text/Text-251.html#MARKER-9-442
def font_type_struct(base):
    return base.Struct(
        # 15    Reserved. Should be set to 0.
        reserved_15=bitfield('uint16', 1),
        # 14    This bit is set to 1 if the font is not to be expanded to match the screen depth. The
        #       font is for color Macintosh computers only if this bit is set to 1. This is for some
        #       fonts, such as Kanji, which are too large for synthetic fonts to be effective or
        #       meaningful, or bitmapped fonts that are larger than 50 points.
        dont_expand_to_match_screen_depth=bitfield('uint16', 1),
        # 13    This bit is set to 1 if the font describes a fixed-width font, and is set to 0 if the
        #       font describes a proportional font. The Font Manager does not check the setting of this bit.
        fixed_width=bitfield('uint16', 1),
        # 12    Reserved. Should be set to 1.
        reserved_12=bitfield('uint16', 1),
        # 10-11 Reserved. Should be set to 0.
        reserved_10_11=bitfield('uint16', 2),
        # 9     This bit is set to 1 if the font contains colors other than black. This font is for
        #       color Macintosh computers only if this bit is set to 1.
        has_colors=bitfield('uint16', 1),
        # 8     This bit is set to 1 if the font is a synthetic font, created dynamically from the
        #       available font resources in response to a certain color and screen depth combination.
        #       The font is for color Macintosh computers only if this bit is set to 1.
        synthetic=bitfield('uint16', 1),
        # 7     This bit is set to 1 if the font has a font color table ('fctb') resource. The font
        #       is for color Macintosh computers only if this bit is set to 1.
        has_fctb=bitfield('uint16', 1),
        # 4-6   Reserved. Should be set to 0.
        reserved_4_6=bitfield('uint16', 3),
        # 2-3   These two bits define the depth of the font. Each of the four possible values indicates
        #       the number of bits (and therefore, the number of colors) used to represent each pixel
        #       in the glyph images.
        #       Value    Font depth    Number of colors
        #           0    1-bit    1
        #           1    2-bit    4
        #           2    4-bit    16
        #           3    8-bit    256
        #       Normally the font depth is 0 and the glyphs are specified as monochrome images. If
        #       bit 7 of this field is set to 1, a resource of type 'fctb' with the same ID as the font
        #       can optionally be provided to assign RGB colors to specific pixel values.
        #
        # If this font resource is a member of a font family, the settings of bits 8 and 9 of the
        # fontStyle field in this font's association table entry should be the same as the settings of
        # bits 2 and 3 in the fontType field. For more information, see "The Font Association Table"
        # on page 4-89.
        depth=bitfield('uint16', 2),
        # 1    This bit is set to 1 if the font resource contains a glyph-width table.
        has_width_table=bitfield('uint16', 1),
        # 0 This bit is set to 1 if the font resource contains an image height table.
        has_height_table=bitfield('uint16', 1),
    )

# the header of the NFNT is a FontRec
# https://developer.apple.com/library/archive/documentation/mac/Text/Text-214.html
def nfnt_header_struct(base):
    return base.Struct(
        #    {font type}
        fontType=font_type_struct(base),
        #    {character code of first glyph}
        firstChar='uint16',
        #    {character code of last glyph}
        lastChar='uint16',
        #    {maximum glyph width}
        widMax='uint16',
        #    {maximum glyph kern}
        kernMax='int16',
        #    {negative of descent}
        nDescent='int16',
        #    {width of font rectangle}
        fRectWidth='uint16',
        #    {height of font rectangle}
        fRectHeight='uint16',
        #    {offset to width/offset table}
        owTLoc='uint16',
        #    {maximum ascent measurement}
        ascent='uint16',
        #    {maximum descent measurement}
        descent='uint16',
        #    {leading measurement}
        leading='uint16',
        #    {row width of bit image in 16-bit wds}
        rowWords='uint16',
        # followed by:
        # bit image table
        # bitmap location table
        # width offset table
        # glyph-width table
        # image height table
    )


# location table entry
def loc_entry_struct(base):
    return base.Struct(
        offset='uint16',
    )


# width/offset table entry
# Width/offset table. For every glyph in the font, this table contains a word with the glyph offset
# in the high-order byte and the glyph's width, in integer form, in the low-order byte. The value of
# the offset, when added to the maximum kerning  value for the font, determines the horizontal
# distance from the glyph origin to the left edge of the bit image of the glyph, in pixels. If this
# sum is negative, the glyph origin  is to the right of the glyph image's left edge, meaning the
# glyph kerns to the left.  If the sum is positive, the origin is to the left of the image's left
# edge. If the sum equals zero, the glyph origin corresponds with the left edge of the bit image.
# Missing glyphs are represented by a word value of -1. The last word of this table is also -1,
# representing the end.
def wo_entry_struct(base):
    return base.Struct(
        offset='uint8',
        width='uint8',
    )

# glyph width table entry
# > Glyph-width table. For every glyph in the font, this table contains a word
# > that specifies the glyph's fixed-point glyph width at the given point size
# > and font style, in pixels. The Font Manager gives precedence to the values
# > in this table over those in the font family glyph-width table. There is an
# > unsigned integer in the high-order byte and a fractional part in the
# > low-order byte. This table is optional.
def width_entry_struct(base):
    return base.Struct(
        # divide by 256
        width='uint16',
    )

# height table entry
# Image height table. For every glyph in the font, this table contains a word that specifies the
# image height of the glyph, in pixels. The image height is the height of the glyph image and is
# less than or equal to the font height. QuickDraw uses the image height for improved character
# plotting, because it only draws the visible part of the glyph. The high-order byte of the word is
# the offset from the top of the font rectangle of the first non-blank (or nonwhite) row in the
# glyph, and the low-order byte is the number of rows that must be drawn. The Font Manager creates
# this table.
def height_entry_struct(base):
    return base.Struct(
        offset='uint8',
        height='uint8',
    )


def _extract_nfnt(data, offset, endian='big', owt_loc_high=0, font_type=None):
    """Read a MacOS NFNT or FONT resource."""
    # create struct types; IIgs NFNTs are little-endian
    base = {'b': be, 'l': le}[endian[:1].lower()]
    NFNTHeader = nfnt_header_struct(base)
    LocEntry = loc_entry_struct(base)
    WOEntry = wo_entry_struct(base)
    WidthEntry = width_entry_struct(base)
    HeightEntry = height_entry_struct(base)
    # font type override (for IIgs)
    if font_type is not None:
        data = font_type + data[2:]
    # this is not in the header documentation but is is mentioned here:
    # https://www.kreativekorp.com/swdownload/lisa/AppleLisaFontFormat.pdf
    compressed = data[offset+1] & 0x80
    if compressed:
        data = _uncompress_nfnt(data, offset)
        offset = 0
    fontrec = NFNTHeader.from_bytes(data, offset)
    if not (fontrec.rowWords and fontrec.widMax and fontrec.fRectWidth and fontrec.fRectHeight):
        logging.debug('Empty FONT/NFNT resource.')
        return dict(glyphs=(), fontrec=fontrec)
    if fontrec.fontType.depth or fontrec.fontType.has_fctb:
        raise FileFormatError('Anti-aliased or colour fonts not supported.')
    # read char tables & bitmaps
    # table offsets
    strike_offset = offset + NFNTHeader.size
    loc_offset = offset + NFNTHeader.size + fontrec.fRectHeight * fontrec.rowWords * 2
    # bitmap strike
    strike = data[strike_offset:loc_offset]
    # location table
    # number of chars: coded chars plus missing symbol
    n_chars = fontrec.lastChar - fontrec.firstChar + 2
    # loc table should have one extra entry to be able to determine widths
    loc_table = LocEntry.array(n_chars+1).from_bytes(data, loc_offset)
    # width offset table
    # the high word of the table's offset (in words) is either:
    # - stored in a separate header (for IIgs)
    # - provided in the repurposed positive nDescent field (dfont)
    # https://developer.apple.com/library/archive/documentation/mac/Text/Text-252.html
    if fontrec.nDescent > 0:
        owt_loc_high = fontrec.nDescent
    wo_offset = (fontrec.owTLoc + (owt_loc_high << 16)) * 2
    # owtTLoc is offset "from itself" to table
    wo_table = WOEntry.array(n_chars).from_bytes(data, offset + 16 + wo_offset)
    # scalable width table
    width_offset = wo_offset + WOEntry.size * n_chars
    if fontrec.fontType.has_width_table:
        width_table = WidthEntry.array(n_chars).from_bytes(data, width_offset)
    # image height table: this can be deduced from the bitmaps
    # https://developer.apple.com/library/archive/documentation/mac/Text/Text-250.html#MARKER-9-414
    # > The Font Manager creates this table.
    if fontrec.fontType.has_height_table:
        height_offset = width_offset
        if fontrec.fontType.has_width_table:
            height_offset += WidthEntry.size * n_chars
        height_table = HeightEntry.array(n_chars).from_bytes(data, height_offset)
    # parse bitmap strike
    bitmap_strike = bytes_to_bits(strike)
    rows = [
        bitmap_strike[_offs:_offs+fontrec.rowWords*16]
        for _offs in range(0, len(bitmap_strike), fontrec.rowWords*16)
    ]
    # if the font was compressed, we need to XOR the bitmap rows
    if compressed:
        xoredrows = rows
        rows = [xoredrows[0]]
        for row in xoredrows[1:]:
            rows.append(tuple(_r ^ _p for _r, _p in zip(row, rows[-1])))
    # extract width from width/offset table
    # (do we need to consider the width table, if defined?)
    locs = [_loc.offset for _loc in loc_table]
    glyphs = [
        Glyph([_row[_offs:_next] for _row in rows])
        for _offs, _next in zip(locs[:-1], locs[1:])
    ]
    # add glyph metrics
    # scalable-width table
    if fontrec.fontType.has_width_table:
        glyphs = tuple(
            # fixed-point value, unsigned integer in the high-order byte
            # and a fractional part in the low-order byte
            _glyph.modify(scalable_width=f'{_we.width / 256:.2f}')
            for _glyph, _we in zip(glyphs, width_table)
        )
    # image-height table
    # > The Font Manager creates this table.
    # this appears to mean any stored contents may well be meaningless
    #
    # if fontrec.fontType.has_height_table:
    #     glyphs = tuple(
    #         _glyph.modify(image_height=_he.height, top_offset=_he.offset)
    #         for _glyph, _he in zip(glyphs, height_table)
    #     )
    # width & offset
    glyphs = tuple(
        _glyph.modify(wo_offset=_wo.offset, wo_width=_wo.width)
        for _glyph, _wo in zip(glyphs, wo_table)
    )
    return dict(
        glyphs=glyphs,
        fontrec=fontrec,
    )


# https://www.kreativekorp.com/swdownload/lisa/AppleLisaFontFormat.pdf
_COMPRESSED_HEADER = be.Struct(
    type='uint16',
    compressedLength='uint32',
    decompressedLength='uint32',
)

def _uncompress_nfnt(data, offset):
    """Decompress a compressed FONT/NFNT resource."""
    header = _COMPRESSED_HEADER.from_bytes(data, offset)
    offset += _COMPRESSED_HEADER.size
    payload = data[offset:offset+header.compressedLength]
    iter = reversed(payload)
    output = bytearray()
    for byte in iter:
        for bit in reversed(bytes_to_bits(bytes((byte,)))):
            if bit:
                output.append(0)
            else:
                try:
                    output.append(next(iter))
                except StopIteration:
                    break
    # bitmap rows still need to be XORed afterwards
    return bytes((data[0], data[1] ^ 0x80)) + bytes(reversed(output))


def _convert_nfnt(properties, glyphs, fontrec):
    """Convert mac glyph metrics to monobit glyph metrics."""
    # the 'width' in the width/offset table is the pen advance
    # while the 'offset' is the (positive) offset after applying the
    # (positive or negative) 'kernMax' global offset
    #
    # since
    #   (glyph) advance_width == left_bearing + width + right_bearing
    # after this transformation we should have
    #   (glyph) advance_width == wo.width
    # which means
    #   (total) advance_width == wo.width - kernMax
    # since
    #   (total) advance_width == (font) left_bearing + glyph.advance_width + (font) right_bearing
    # and (font) left_bearing = -kernMax
    # we need to adjust for kernMax on both left and right bearings - it is an
    # offset only, not a tightening of the advance width
    if not glyphs:
        return Font()
    glyphs = tuple(
        _glyph.modify(
            left_bearing=_glyph.wo_offset + fontrec.kernMax,
            right_bearing=(
                _glyph.wo_width - _glyph.width
                - (_glyph.wo_offset + fontrec.kernMax)
            )
        )
        if _glyph.wo_width != 0xff and _glyph.wo_offset != 0xff else _glyph
        for _glyph in glyphs
    )
    # codepoint labels
    labelled = [
        _glyph.modify(codepoint=(_codepoint,))
        for _codepoint, _glyph in enumerate(glyphs[:-1], start=fontrec.firstChar)
    ]
    # last glyph is the "missing" glyph
    labelled.append(glyphs[-1].modify(tag='missing'))
    # drop undefined glyphs & their labels, so long as they're empty
    glyphs = tuple(
        _glyph for _glyph in labelled
        if (_glyph.wo_width != 0xff and _glyph.wo_offset != 0xff) or (_glyph.width and _glyph.height)
    )
    # drop mac glyph metrics
    # keep scalable_width
    glyphs = tuple(_glyph.drop('wo_offset', 'wo_width') for _glyph in glyphs)
    # store kerning table
    if properties.get('kerning-table', None):
        kern_table = sorted(
            (
                _entry.kernFirst, _entry.kernSecond,
                _entry.kernWidth * properties['point_size'] / 2**12
            )
            for _entry in properties['kerning-table']
        )
        glyphs = tuple(
            _glyph.modify(right_kerning=KernTable({
                _right: f'{_width:.2f}'
                for _left, _right, _width in kern_table
                if _glyph.codepoint and _left == int(_glyph.codepoint)
            }))
            for _glyph in glyphs
        )
    # store glyph-name encoding table
    if properties.get('encoding-table', None):
        tag_table = {
            _entry[:1]: _entry[1:].decode('mac-roman')
            for _entry in properties['encoding-table']
        }
        glyphs = tuple(
            _glyph.modify(tag=tag_table.get(_glyph.codepoint, ''))
            for _glyph in glyphs
        )
    # store properties
    properties.update({
        # not overridable; also seems incorrect for system fonts
        #'spacing': 'monospace' if fontrec.fontType.fixed_width else 'proportional',
        'default_char': 'missing',
        'ascent': fontrec.ascent,
        'descent': fontrec.descent,
        'line_height': fontrec.ascent + fontrec.descent + fontrec.leading,
        'shift_up': -fontrec.descent,
        # remove the kerning table and encoding table now stored in glyphs
        'kerning_table': None,
        'encoding_table': None,
        'source_format': 'NFNT',
    })
    return Font(glyphs, **properties)



###############################################################################
# NFNT writer


def _subset(font):
    """Subset to glyphs storable in NFNT and append default glyph."""
    font = font.label(codepoint_from=font.encoding)
    if font.encoding in ('mac-roman', 'mac-symbol', 'raw', '', None):
        labels = tuple(range(0, 256))
    elif font.encoding == 'ascii':
        labels = tuple(range(0, 128))
    else:
        font = font.label()
        labels = tuple(Char(_c) for _c in charmaps['mac-roman'].mapping.values())
    subfont = font.subset(labels=labels)
    if not subfont.glyphs:
        raise FileFormatError('No suitable characters for NFNT font')
    glyphs = [*subfont.glyphs, font.get_default_glyph()]
    font = font.modify(glyphs, encoding=None)
    return font


def _normalize_glyph(g, ink_bounds):
    """
    Trim the horizontal to glyph's ink bounds
    and expand the vertical to font's ink bounds
    in preparation for generating the font strike data
    """
    if not g:
        return None
    # shrink to fit
    g = g.reduce()
    return g.expand(
        bottom=g.shift_up - ink_bounds.bottom,
        top=ink_bounds.top-g.height-g.shift_up
    )


def _normalize_metrics(font):
    """Calculate metrics for NFNT format."""
    # reduce to ink bounds horizontally, font ink bounds vertically
    glyphs = tuple(_normalize_glyph(_g, font.ink_bounds) for _g in font.glyphs)
    # calculate kerning. only negative kerning is handled
    kern = min(_g.left_bearing for _g in glyphs)
    kern = max(0, -kern)
    # add apple metrics to glyphs
    glyphs = tuple(
        _g.modify(wo_offset=_g.left_bearing+kern, wo_width=_g.advance_width)
        for _g in glyphs
    )
    # check that glyph widths and offsets fit
    if any(_g.wo_width >= 255 for _g in glyphs):
        raise FileFormatError('NFNT character width must be < 255')
    if any(_g.wo_offset >= 255 for _g in glyphs):
        raise FileFormatError('NFNT character offset must be < 255')
    font = font.modify(glyphs)
    return font, kern


def _create_nfnt(font, endian, ndescent_is_high):
    """Create FONT/NFNT resource."""
    # fontType is ignored
    # glyph-width table and image-height table not included
    base = {'b': be, 'l': le}[endian[:1].lower()]
    NFNTHeader = nfnt_header_struct(base)
    FontType = NFNTHeader.element_types['fontType']
    LocEntry = loc_entry_struct(base)
    WOEntry = wo_entry_struct(base)
    # subset the font. we need a font structure to calculate ink bounds
    font = _subset(font)
    font, kern = _normalize_metrics(font)
    # build the font-strike data
    strike_raster = Raster.concatenate(*(_g.pixels for _g in font.glyphs))
    # word-align strike
    strike_raster = strike_raster.expand(right=16-(strike_raster.width%16))
    font_strike = strike_raster.as_bytes()
    # get contiguous glyph list
    glyphs = font.glyphs
    first_char = int(glyphs[0].codepoint)
    last_char = int(glyphs[-2].codepoint)
    empty = Glyph(wo_offset=255, wo_width=255)
    glyph_table = [
        font.get_glyph(codepoint=_code, missing=empty)
        for _code in range(first_char, last_char+1)
    ]
    missing = glyphs[-1]
    glyph_table.append(missing)
    # build the width-offset table
    wo_table = b''.join(
        # glyph.wo_width and .wo_offset set in normalise_metrics
        bytes(WOEntry(width=_g.wo_width, offset=_g.wo_offset))
        # empty entry needed at the end.
        for _g in chain(glyph_table, [empty])
    )
    # build the location table
    loc_table = b''.join(
        bytes(LocEntry(offset=_offset))
        for _offset in accumulate((_g.width for _g in glyph_table), initial=0)
    )
    # owTLoc is the offset from the field itself
    # the remaining size of the header including owTLoc is 5 words
    owt_loc = (len(font_strike) + len(loc_table) + 10) >> 1
    # generate NFNT header
    fontrec = NFNTHeader(
        # this seems to be always 0x9000, 0xb000
        # even if docs say reserved_15 should be 0
        # we don't provide a scalable width or height tables
        fontType=FontType(
            reserved_15=1, reserved_12=1,
            fixed_width=font.spacing in ('monospace', 'character-cell'),
        ),
        firstChar=first_char,
        lastChar=last_char,
        widMax=max(_g.advance_width for _g in glyphs),
        kernMax=-kern,
        nDescent=font.ink_bounds.bottom,
        # font rectangle == font bounding box
        #max(_g.width + _g.left_bearing + kern for _g in glyphs),
        fRectWidth=font.bounding_box.x,
        fRectHeight=font.bounding_box.y,
        # word offset to width/offset table
        owTLoc=owt_loc & 0xffff,
        # docs define fRectHeight = ascent + descent
        # and generally suggest ascent and descent equal ink bounds
        # that's also monobit's *default* ascent & descent but is overridable
        ascent=font.ink_bounds.top,
        descent=-font.ink_bounds.bottom,
        # define leading in terms of bounding box, not pixel-height
        leading=font.line_height - font.bounding_box.y,
        rowWords=strike_raster.width // 16,
    )
    owt_loc_high = owt_loc >> 16
    if ndescent_is_high and owt_loc_high:
        fontrec.nDescent = owt_loc_high
    logging.debug('NFNT header: %s', fontrec)
    data = b''.join((
        bytes(fontrec),
        font_strike,
        loc_table,
        wo_table
    ))
    # fbr = max width from origin (including whitespace) and right kerned pixels
    # for IIgs header
    fbr_extent = max(
        _g.width + _g.left_bearing + max(_g.right_bearing, 0)
        for _g in glyphs
    )
    return data, owt_loc_high, fbr_extent