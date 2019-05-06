"""
monobit.hex - read and write .hex and files

(c) 2019 Rob Hagemans
licence: https://opensource.org/licenses/MIT
"""

import os
import logging
import string

from .base import (
    Glyph, Font, Typeface, ensure_stream,
    clean_comment, split_global_comment, write_comments
)


@Typeface.loads('hex', encoding='utf-8-sig')
def load(infile):
    """Load font from a .hex file."""
    with ensure_stream(infile, 'r', encoding='utf-8-sig') as instream:
        glyphs = {}
        comments = {}
        key = None
        current_comment = []
        for line in instream:
            line = line.rstrip('\r\n')
            if not line:
                # preserve empty lines if they separate comments
                if current_comment and current_comment[-1] != '':
                    current_comment.append('')
                continue
            if line[0] not in string.hexdigits:
                current_comment.append(line)
                continue
            if key is None:
                global_comment, current_comment = split_global_comment(current_comment)
                comments[None] = clean_comment(global_comment)
            # parse code line
            key, value = line.split(':', 1)
            value = value.strip()
            # may be on one of next lines
            while not value:
                value = instream.readline.strip()
            if (set(value) | set(key)) - set(string.hexdigits):
                raise ValueError('Keys and values must be hexadecimal.')
            key = int(key, 16)
            if len(value) == 32:
                width, height = 8, 16
            elif len(value) == 64:
                width, height = 16, 16
            else:
                raise ValueError('Hex strings must be 32 or 64 characters long.')
            glyphs[key] = Glyph.from_hex(value, width)
            comments[key] = clean_comment(current_comment)
            current_comment = []
        # preserve any comment at end of file
        comments[key].extend(clean_comment(current_comment))
    return Typeface([Font(glyphs, comments)])


@Typeface.saves('hex', encoding='utf-8')
def save(typeface, outfile):
    """Write fonts to a .hex file."""
    if len(typeface._fonts) > 1:
        raise ValueError('Saving multiple fonts to .hex or not possible')
    with ensure_stream(outfile, 'w') as outstream:
        font = typeface._fonts[0]
        write_comments(outstream, font._comments, None, comm_char='#')
        for ordinal, char in font._glyphs.items():
            write_comments(outstream, font._comments, ordinal, comm_char='#')
            if isinstance(ordinal, int):
                outstream.write('{:04x}:'.format(ordinal))
            else:
                raise ValueError('Font has non-integer keys')
            if char.height != 16 or char.width not in (8, 16):
                raise ValueError('Hex format only supports 8x16 or 16x16 glyphs.')
            outstream.write(char.as_hex().upper())
            outstream.write('\n')
    return typeface
