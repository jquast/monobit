"""
monobit.windows - read and write windows font (.fon and .fnt) files

based on Simon Tatham's dewinfont; see MIT-style licence below.
changes (c) 2019 Rob Hagemans and released under the same licence.

dewinfont is copyright 2001,2017 Simon Tatham. All rights reserved.

Permission is hereby granted, free of charge, to any person
obtaining a copy of this software and associated documentation files
(the "Software"), to deal in the Software without restriction,
including without limitation the rights to use, copy, modify, merge,
publish, distribute, sublicense, and/or sell copies of the Software,
and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import sys
import string
import struct
import logging
from types import SimpleNamespace

from .base import VERSION, Glyph, Font, ensure_stream, bytes_to_bits, ceildiv

 # https://docs.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/0d0b32ac-a836-4bd2-a112-b6000a1b4fc9
 # typedef  enum
 # {
 #   ANSI_CHARSET = 0x00000000,
 #   DEFAULT_CHARSET = 0x00000001,
 #   SYMBOL_CHARSET = 0x00000002,
 #   MAC_CHARSET = 0x0000004D,
 #   SHIFTJIS_CHARSET = 0x00000080,
 #   HANGUL_CHARSET = 0x00000081,
 #   JOHAB_CHARSET = 0x00000082,
 #   GB2312_CHARSET = 0x00000086,
 #   CHINESEBIG5_CHARSET = 0x00000088,
 #   GREEK_CHARSET = 0x000000A1,
 #   TURKISH_CHARSET = 0x000000A2,
 #   VIETNAMESE_CHARSET = 0x000000A3,
 #   HEBREW_CHARSET = 0x000000B1,
 #   ARABIC_CHARSET = 0x000000B2,
 #   BALTIC_CHARSET = 0x000000BA,
 #   RUSSIAN_CHARSET = 0x000000CC,
 #   THAI_CHARSET = 0x000000DE,
 #   EASTEUROPE_CHARSET = 0x000000EE,
 #   OEM_CHARSET = 0x000000FF
 # } CharacterSet;




bytestruct = struct.Struct("B")
wordstruct = struct.Struct("<H")
dwordstruct = struct.Struct("<L")

def frombyte(s):
    return bytestruct.unpack_from(s, 0)[0]
def fromword(s):
    return wordstruct.unpack_from(s, 0)[0]
def fromdword(s):
    return dwordstruct.unpack_from(s, 0)[0]

def asciz(s):
    for length in range(len(s)):
        if frombyte(s[length:length+1]) == 0:
            break
    return s[:length].decode("ASCII")

class char(SimpleNamespace):
    pass

def dofnt(fnt):
    """Create an internal font description from a .FNT-shaped string."""
    properties = {}
    version = fromword(fnt[0:])
    ftype = fromword(fnt[0x42:])
    if ftype & 1:
        raise ValueError('This font is a vector font')
    off_facename = fromdword(fnt[0x69:])
    if off_facename < 0 or off_facename > len(fnt):
        raise ValueError('Face name not contained within font data')
    properties = {
        'source-format': 'WindowsFont [0x{:04x}]'.format(version),
        'name': asciz(fnt[off_facename:]),
        'copyright': asciz(fnt[6:66]),
        'points': fromword(fnt[0x44:]),
        'ascent': fromword(fnt[0x4A:]),
    }
    height = fromword(fnt[0x58:])
    properties['size'] = height
    properties['slant'] = 'italic' if frombyte(fnt[0x50:]) else 'roman'
    deco = []
    if frombyte(fnt[0x51:]):
        deco.append('underline')
    if frombyte(fnt[0x52:]):
        deco.append('strikethrough')
    if deco:
        properties['decoration'] = ' '.join(deco)
    properties['_WEIGHT'] = fromword(fnt[0x53:])
    properties['_CHARSET'] = frombyte(fnt[0x55:])
    # Read the char table.
    if version == 0x200:
        ctstart = 0x76
        ctsize = 4
    else:
        ctstart = 0x94
        ctsize = 6
    maxwidth = 0
    glyphs = {}
    firstchar = frombyte(fnt[0x5F:])
    lastchar = frombyte(fnt[0x60:])
    for i in range(firstchar, lastchar+1):
        entry = ctstart + ctsize * (i-firstchar)
        width = fromword(fnt[entry:])
        if not width:
            continue
        if ctsize == 4:
            off = fromword(fnt[entry+2:])
        else:
            off = fromdword(fnt[entry+2:])
        rows = []
        bytewidth = ceildiv(width, 8)
        for j in range(height):
            rowbytes = []
            for k in range(bytewidth):
                bytepos = off + k * height + j
                rowbytes.append(frombyte(fnt[bytepos:]))
            rows.append(bytes_to_bits(rowbytes, width))
        if rows:
            glyphs[i] = Glyph(tuple(rows))
    return Font(glyphs, comments={}, properties=properties)

def nefon(fon, neoff):
    "Finish splitting up a NE-format FON file."
    ret = []
    # Find the resource table.
    rtable = fromword(fon[neoff + 0x24:])
    rtable = rtable + neoff
    # Read the shift count out of the resource table.
    shift = fromword(fon[rtable:])
    # Now loop over the rest of the resource table.
    p = rtable+2
    while 1:
        rtype = fromword(fon[p:])
        if rtype == 0:
            break  # end of resource table
        count = fromword(fon[p+2:])
        p = p + 8  # type, count, 4 bytes reserved
        for i in range(count):
            start = fromword(fon[p:]) << shift
            size = fromword(fon[p+2:]) << shift
            if start < 0 or size < 0 or start+size > len(fon):
                raise ValueError('Resource overruns file boundaries')
            if rtype == 0x8008: # this is an actual font
                try:
                    font = dofnt(fon[start:start+size])
                except Exception as e:
                    raise ValueError('Failed to read font resource at {:x}: {}'.format(start, e))
                ret = ret + [font]
            p = p + 12 # start, size, flags, name/id, 4 bytes reserved
    return ret

def pefon(fon, peoff):
    "Finish splitting up a PE-format FON file."
    dirtables=[]
    dataentries=[]
    def gotoffset(off,dirtables=dirtables,dataentries=dataentries):
        if off & 0x80000000:
            off = off &~ 0x80000000
            dirtables.append(off)
        else:
            dataentries.append(off)
    def dodirtable(rsrc, off, rtype, gotoffset=gotoffset):
        number = fromword(rsrc[off+12:]) + fromword(rsrc[off+14:])
        for i in range(number):
            entry = off + 16 + 8*i
            thetype = fromdword(rsrc[entry:])
            theoff = fromdword(rsrc[entry+4:])
            if rtype == -1 or rtype == thetype:
                gotoffset(theoff)

    # We could try finding the Resource Table entry in the Optional
    # Header, but it talks about RVAs instead of file offsets, so
    # it's probably easiest just to go straight to the section table.
    # So let's find the size of the Optional Header, which we can
    # then skip over to find the section table.
    secentries = fromword(fon[peoff+0x06:])
    sectable = peoff + 0x18 + fromword(fon[peoff+0x14:])
    for i in range(secentries):
        secentry = sectable + i * 0x28
        secname = asciz(fon[secentry:secentry+8])
        secrva = fromdword(fon[secentry+0x0C:])
        secsize = fromdword(fon[secentry+0x10:])
        secptr = fromdword(fon[secentry+0x14:])
        if secname == ".rsrc":
            break
    if secname != ".rsrc":
        raise ValueError('Unable to locate resource section')
    # Now we've found the resource section, let's throw away the rest.
    rsrc = fon[secptr:secptr+secsize]

    # Now the fun begins. To start with, we must find the initial
    # Resource Directory Table and look up type 0x08 (font) in it.
    # If it yields another Resource Directory Table, we stick the
    # address of that on a list. If it gives a Data Entry, we put
    # that in another list.
    dodirtable(rsrc, 0, 0x08)
    # Now process Resource Directory Tables until no more remain
    # in the list. For each of these tables, we accept _all_ entries
    # in it, and if they point to subtables we stick the subtables in
    # the list, and if they point to Data Entries we put those in
    # the other list.
    while len(dirtables) > 0:
        table = dirtables[0]
        del dirtables[0]
        dodirtable(rsrc, table, -1) # accept all entries
    # Now we should be left with Resource Data Entries. Each of these
    # describes a font.
    ret = []
    for off in dataentries:
        rva = fromdword(rsrc[off:])
        start = rva - secrva
        size = fromdword(rsrc[off+4:])
        try:
            font = dofnt(rsrc[start:start+size])
        except Exception as e:
            raise ValueError('Failed to read font resource at {:x}: {}'.format(start, e))
        ret = ret + [font]
    return ret

def dofon(fon):
    "Split a .FON up into .FNTs and pass each to dofnt."
    # Check the MZ header.
    if fon[0:2] != b'MZ':
        raise ValueError('MZ signature not found')
    # Find the NE header.
    neoff = fromdword(fon[0x3C:])
    if fon[neoff:neoff+2] == b'NE':
        return nefon(fon, neoff)
    elif fon[neoff:neoff+4] == b'PE\0\0':
        return pefon(fon, neoff)
    else:
        raise ValueError('NE or PE signature not found')

def isfon(data):
    """Determine if a file is a .FON (True) or a .FNT (False) format font."""
    return data[0:2] == b'MZ'


@Font.loads('fnt', 'fon', encoding=None)
def load(infile):
    """Load a Windows .FON or .FNT file."""
    with ensure_stream(infile, 'rb') as instream:
        data = instream.read()
    if isfon(data):
        print('fon')
        fonts = dofon(data)
    else:
        print('fnt')
        fonts = [dofnt(data)]
    if len(fonts) > 1:
        raise ValueError("More than one font in file; not yet supported")
    return fonts[0]
