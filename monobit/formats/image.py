"""
monobit.formats.image - fonts stored in image files

(c) 2019--2023 Rob Hagemans
licence: https://opensource.org/licenses/MIT
"""

import logging
from collections import Counter
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None

from ..basetypes import Coord, RGB
from ..binary import ceildiv
from ..storage import loaders, savers
from ..magic import FileFormatError
from ..font import Font
from ..glyph import Glyph
from ..chart import chart, grid_traverser


DEFAULT_IMAGE_FORMAT = 'png'


# available background policies
# -----------------------------
#
# most-common       use colour most commonly found in payload cells
# least-common      use colour least commonly found in payload cells
# brightest         use brightest colour, by sum of RGB values
# darkest           use darkest colour, by sum of RGB values
# top-left          use colour of top-left pixel in first cell


if Image:
    @loaders.register(
        name='image',
        patterns=(
            '*.png', '*.bmp', '*.gif', '*.tif', '*.tiff',
            '*.ppm', '*.pgm', '*.pbm', '*.pnm', '*.webp',
            '*.pcx', '*.tga', '*.jpg', '*.jpeg',
        ),
        magic=(
            # PNG
            b'\x89PNG\r\n\x1a\n',
            # BMP
            #b'BM',   # -- clash with bmfont b'BMF'
            # GIF
            b'GIF87a', b'GIF89a',
            # TIFF
            b'\x4D\x4D\x00\x2A', b'\x49\x49\x2A\x00'
            # PNM
            b'P1', b'P2', b'P3',
            # WebP
            b'RIFF',
            # PCX
            b'\n\x00', b'\n\x02', b'\n\x03', b'\n\x04', b'\n\x05',
            # JPEG
            b'\xFF\xD8\xFF',
        ),
    )
    def load_image(
            infile,
            cell:Coord=Coord(8, 8),
            margin:Coord=Coord(0, 0),
            padding:Coord=Coord(0, 0),
            scale:Coord=Coord(1, 1),
            table_size:Coord=Coord(0, 0),
            count:int=0,
            background:str='most-common',
            first_codepoint:int=0,
            order:str='row-major',
            direction:Coord=Coord(1, -1),
        ):
        """
        Extract character-cell font from image.

        cell: size X,Y of character cell (default: 8x8)
        margin: number of pixels in X,Y direction around glyph chart (default: 0x0)
        padding: number of pixels in X,Y direction between glyph (default: 0x0)
        scale: number of pixels in X,Y direction per glyph bit (default: 1x1)
        table_size: number of glyphs in X, Y direction. 0 or negative means as much as fits on the axis (default).
        count: maximum number of glyphs to extract (within constraints of table_size). 0 or negative means extract all (default).
        background: determine background from "most-common" (default), "least-common", "brightest", "darkest", "top-left" colour
        first_codepoint: codepoint value assigned to first glyph (default: 0)
        order: start with "r" for row-major order (default), "c" for column-major order
        direction: X, Y direction where +1, -1 (default) means left-to-right, top-to-bottom
        """
        # work out image geometry
        step_x = cell.x * scale.x + padding.x
        step_y = cell.y * scale.y + padding.y
        # maximum number of cells that fits
        img = Image.open(infile)
        img = img.convert('RGB')
        ncells_x, ncells_y = table_size
        if ncells_x <= 0:
            ncells_x = (img.width - margin.x) // step_x
        if ncells_y <= 0:
            ncells_y = (img.height - margin.y) // step_y
        traverse = grid_traverser(ncells_x, ncells_y, order, direction)
        # extract sub-images
        crops = tuple(
            img.crop((
                margin.x + _col*step_x,
                img.height - (margin.y + _row*step_y + cell.y * scale.y),
                margin.x + _col*step_x + cell.x * scale.x,
                img.height - (margin.y + _row*step_y),
            ))
            for _row, _col in traverse
        )
        if not crops:
            logging.error('Image too small; no characters found.')
            return Font()
        if count > 0:
            crops = crops[:count]
        # scale
        crops = tuple(_crop.resize(cell) for _crop in crops)
        # get border/padding colour
        if margin.x or margin.y:
            border = img.getpixel((0, 0))
        elif padding.x:
            border = img.getpixel((cell.x, 0))
        elif padding.y:
            border = img.getpixel((0, cell.y))
        else:
            # can't determine border colour without padding or margin
            border = None
        # clip off border colour from cells
        crops = tuple(_crop_border(_crop, border) for _crop in crops)
        # get pixels
        paper, ink = _identify_colours(crops, background)
        # convert to glyphs, set codepoints
        glyphs = tuple(
            Glyph.from_vector(
                tuple(_crop.getdata()), stride=_crop.width, _0=paper, _1=ink,
                codepoint=_index,
            )
            for _index, _crop in enumerate(crops, first_codepoint)
        )
        return Font(glyphs)


    def _identify_colours(crops, background):
        """Identify paper and ink colours from cells."""
        # check that cells are monochrome
        crops = tuple(tuple(_crop.getdata()) for _crop in crops)
        colourset = set.union(*(set(_data) for _data in crops))
        if len(colourset) > 2:
            raise FileFormatError(
                f'More than two colours ({len(colourset)}) found in image. '
                'Colour, greyscale and antialiased glyphs are not supported. '
            )
        colourfreq = Counter(_c for _data in crops for _c in _data)
        brightness = sorted((sum(_v for _v in _c), _c) for _c in colourset)
        if background == 'most-common':
            # most common colour in image assumed to be background colour
            paper, _ = colourfreq.most_common(1)[0]
        elif background == 'least-common':
            # least common colour in image assumed to be background colour
            paper, _ = colourfreq.most_common()[-1]
        elif background == 'brightest':
            # brightest colour assumed to be background
            _, paper = brightness[-1]
        elif background == 'darkest':
            # darkest colour assumed to be background
            _, paper = brightness[0]
        elif background == 'top-left':
            # top-left pixel of first char assumed to be background colour
            paper = crops[0][0]
        # 2 colour image - not-paper means ink
        ink = (colourset - {paper}).pop()
        return paper, ink


    def _crop_border(image, border):
        """Remove border area from image."""
        while image.width:
            right_colours = image.crop((
                image.width-1, 0, image.width, image.height
            )).getcolors()
            if len(right_colours) == 1 and right_colours[0][1] == border:
                image = image.crop((0, 0, image.width-1, image.height))
            else:
                break
        return image


    @savers.register(linked=load_image)
    def save_image(
            fonts, outfile, *,
            image_format:str='',
            columns:int=32,
            margin:Coord=Coord(0, 0),
            padding:Coord=Coord(0, 0),
            scale:Coord=Coord(1, 1),
            order:str='row-major',
            direction:Coord=Coord(1, -1),
            border:RGB=(32, 32, 32), paper:RGB=(0, 0, 0), ink:RGB=(255, 255, 255),
            codepoint_range:Coord=None,
        ):
        """
        Export character-cell font to image.

        image_format: image file format (default: png)
        columns: number of columns in glyph chart (default: 32)
        margin: number of pixels in X,Y direction around glyph chart (default: 0x0)
        padding: number of pixels in X,Y direction between glyph (default: 0x0)
        scale: number of pixels in X,Y direction per glyph bit (default: 1x1)
        order: start with "r" for row-major order (default), "c" for column-major order
        direction: X, Y direction where +1, -1 (default) means left-to-right, top-to-bottom
        paper: background colour R,G,B 0--255 (default: 0,0,0)
        ink: foreground colour R,G,B 0--255 (default: 255,255,255)
        border: border colour R,G,B 0--255 (default 32,32,32)
        codepoint_range: first and last codepoint to include (includes bounds and undefined codepoints; default: False)
        """
        if len(fonts) > 1:
            raise FileFormatError('Can only save one font to image file.')
        font = fonts[0]
        if codepoint_range:
            # make contiguous
            glyphs = tuple(
                font.get_glyph(_codepoint, missing='empty')
                for _codepoint in range(codepoint_range[0], codepoint_range[1]+1)
            )
            font = font.modify(glyphs)
        font = font.equalise_horizontal()
        font = font.stretch(*scale)
        img = (
            chart(font, columns, margin, padding, order, direction)
            .as_image(border=border, paper=paper, ink=ink)
        )
        try:
            img.save(outfile, format=image_format or Path(outfile).suffix[1:])
        except (KeyError, ValueError, TypeError):
            img.save(outfile, format=DEFAULT_IMAGE_FORMAT)
