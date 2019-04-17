#!/usr/bin/env python3
"""
Extract monospace bitmap font from raw binary and output as hexdraw text file
(c) 2019 Rob Hagemans, licence: https://opensource.org/licenses/MIT
"""

import sys
import argparse

import monobit

# parse command line
parser = argparse.ArgumentParser()
parser.add_argument('infile', nargs='?', type=argparse.FileType('rb'), default=sys.stdin.buffer)
parser.add_argument('outfile', nargs='?', type=argparse.FileType('w'), default=sys.stdout)
# dimensions of cell, in pixels
parser.add_argument(
    '-y', '--height', default=8, type=int,
    help='pixel height of the character cell'
)
parser.add_argument(
    '-x', '--width', default=8, type=int,
    help='pixel width of the character cell'
)
parser.add_argument(
    '-n', '--number', nargs=1, default=None, type=lambda _s: int(_s, 0),
    help='number of characters to extract'
)
parser.add_argument(
    '--offset', default=0, type=lambda _s: int(_s, 0),
    help='bytes offset into binary'
)
parser.add_argument(
    '--padding', default=0, type=int,
    help='number of scanlines between characters to discard'
)
parser.add_argument(
    '--clip-x', default=0, type=int,
    help='number of pixels on the left of character to discard'
)
parser.add_argument(
    '--mirror', action='store_true', default=False,
    help='reverse bits horizontally'
)
parser.add_argument(
    '--invert', action='store_true', default=False,
    help='invert foreground and background'
)
parser.add_argument(
    '--first', default=0, type=lambda _s: int(_s, 0),
    help='code point of first glyph in image'
)
args = parser.parse_args()


font = monobit.raw.load(
    args.infile, cell=(args.width, args.height), n_chars=args.number,
    offset=args.offset, padding=args.padding, clip=args.clip_x, mirror=args.mirror,
    invert=args.invert, first=args.first,
)
monobit.hexdraw.save(font, args.outfile)
